"""The OpenAlex client: one generic API for every entity, cursor paging, retries, page cache."""

import gzip
import json
import logging
import math
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests

from .errors import BudgetExhausted, HTTPError, OpenAlexError, PaginationError
from .query import filter_to_string, join_fields, parse_url, short_id

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_PER_PAGE = 100
MAX_SAMPLE = 10_000
_GROUP_BY_RE = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)
_KEY_IN_TEXT_RE = re.compile(r"(api_key=)[^&\s'\"]+")


@dataclass
class Usage:
    """Budget information read from the X-RateLimit-* headers of the last response."""

    limit: float | None = None
    remaining: float | None = None
    credits_used_total: float = 0
    reset_seconds: float | None = None


def _header(headers, name):
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None


def _number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _normalize_group(group):
    key = group.get("key")
    if key in ("", "unknown"):
        key = None
    return {"key": key, "key_display_name": group.get("key_display_name"), "count": group.get("count")}


def _json_normalized(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


class _PageCache:
    """Pages of one harvest under `cache_dir/name/`, plus the params that produced them."""

    def __init__(self, directory, signature):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        signature = _json_normalized(signature)
        params_file = self.directory / "params.json"
        if params_file.exists():
            stored = json.loads(params_file.read_text(encoding="utf-8"))
            if stored != signature:
                raise PaginationError(
                    f"checkpoint {self.directory.name!r} was created with different params; "
                    f"use another checkpoint name or delete {self.directory}"
                )
        else:
            params_file.write_text(json.dumps(signature, indent=2, sort_keys=True), encoding="utf-8")
        self.signature = signature

    def pages(self):
        for path in sorted(self.directory.glob("page-*.json.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                yield json.load(fh)

    def write(self, number, cursor, response):
        path = self.directory / f"page-{number:05d}.json.gz"
        tmp = path.with_suffix(".tmp")
        entry = {"params": self.signature, "cursor": cursor, "response": response}
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(entry, fh)
        tmp.replace(path)  # atomic: an interrupted write never leaves a half page


class OpenAlex:
    """Client for the OpenAlex REST API.

    Every method takes an entity path (`works`, `authors`, `institutions`, `topics`,
    `subfields`, `sources`, ...) and returns plain dicts and lists.
    """

    def __init__(
        self,
        api_key=None,
        base_url="https://api.openalex.org",
        timeout=30,
        max_retries=6,
        user_agent="openalex-api-client/1.0",
        cache_dir=None,
        max_rps=10,
        session=None,
    ):
        self.api_key = api_key if api_key is not None else (os.environ.get("OPENALEX_API_KEY") or None)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_rps = max_rps
        self.session = session if session is not None else requests.Session()
        self.usage = Usage()
        self._headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",  # no Brotli
            "User-Agent": user_agent,
        }
        self._sleep = time.sleep
        self._last_request = 0.0

    def __repr__(self):
        key = "'***'" if self.api_key else None
        return f"OpenAlex(base_url={self.base_url!r}, api_key={key})"

    # ------------------------------------------------------------------ transport

    def _scrub(self, text):
        text = _KEY_IN_TEXT_RE.sub(r"\1***", str(text))
        if self.api_key:
            text = text.replace(self.api_key, "***")
        return text

    def _display_url(self, url, params):
        shown = {k: v for k, v in params.items() if k != "api_key"}
        return url + ("?" + urlencode(shown) if shown else "")

    def _throttle(self):
        if not self.max_rps:
            return
        wait = self._last_request + 1.0 / self.max_rps - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _backoff(self, attempt):
        return min(60, 1.5**attempt) + random.uniform(0, 1)

    def _update_usage(self, headers):
        limit = _number(_header(headers, "X-RateLimit-Limit"))
        remaining = _number(_header(headers, "X-RateLimit-Remaining"))
        used = _number(_header(headers, "X-RateLimit-Credits-Used"))
        reset = _number(_header(headers, "X-RateLimit-Reset"))
        if limit is not None:
            self.usage.limit = limit
        if remaining is not None:
            self.usage.remaining = remaining
        if used is not None:
            self.usage.credits_used_total += used
        if reset is not None:
            self.usage.reset_seconds = reset

    def _http_error(self, response, shown):
        text = self._scrub(getattr(response, "text", "") or "")
        validation = None
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            errors = body.get("errors") or (body.get("validation") or {}).get("errors")
            if isinstance(errors, list) and errors:
                # /query and OQL: {"valid": false, "errors": [{"type", "message", "location"}]}
                messages = [e.get("message", json.dumps(e)) if isinstance(e, dict) else str(e) for e in errors]
                validation = self._scrub("; ".join(messages))
            else:
                for key in ("validation", "message", "error"):
                    if body.get(key):
                        value = body[key]
                        validation = self._scrub(value if isinstance(value, str) else json.dumps(value))
                        break
        return HTTPError(response.status_code, shown, text[:500], validation)

    def _request(self, method, path, params=None, body=None):
        url = self.base_url + path
        params = {k: v for k, v in (params or {}).items() if v is not None}
        shown = self._display_url(url, params)
        send_params = dict(params)
        if self.api_key:
            send_params["api_key"] = self.api_key

        for attempt in range(self.max_retries + 1):
            self._throttle()
            logger.debug("%s %s", method, shown)
            try:
                response = self.session.request(
                    method, url, params=send_params, json=body, headers=self._headers, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.max_retries:
                    raise OpenAlexError(
                        f"{type(exc).__name__} for {shown} after {attempt + 1} attempts"
                    ) from None
                delay = self._backoff(attempt)
                logger.warning("%s for %s, retrying in %.1f s", type(exc).__name__, shown, delay)
                self._sleep(delay)
                continue

            self._update_usage(response.headers)
            status = response.status_code
            if status < 400:
                try:
                    return response.json()
                except ValueError:
                    raise OpenAlexError(f"invalid JSON in response to {shown}") from None
            if status == 429 and _number(_header(response.headers, "X-RateLimit-Remaining")) == 0:
                raise BudgetExhausted(self.usage.reset_seconds)
            if status in RETRY_STATUSES and attempt < self.max_retries:
                delay = _number(_header(response.headers, "Retry-After"))
                if delay is None:
                    delay = self._backoff(attempt)
                logger.warning("HTTP %s for %s, retrying in %.1f s", status, shown, delay)
                self._sleep(delay)
                continue
            raise self._http_error(response, shown)
        raise AssertionError("unreachable")

    # ------------------------------------------------------------------ paging

    def _paginate(self, fetch, signature, items_key, max_results=None, checkpoint=None, strict=False):
        """Follow cursors and yield items. `fetch(cursor)` returns one response page."""
        if max_results is not None and max_results <= 0:
            return
        cache = None
        if checkpoint:
            if self.cache_dir is None:
                raise ValueError("checkpoint requires OpenAlex(cache_dir=...)")
            cache = _PageCache(self.cache_dir / checkpoint, signature)

        def pages():
            cursor = "*"
            number = 0
            if cache:
                for entry in cache.pages():
                    number += 1
                    data = entry["response"]
                    yield entry["cursor"], data
                    cursor = (data.get("meta") or {}).get("next_cursor")
                    if cursor is None or not data.get(items_key):
                        return
                if number:
                    logger.info("checkpoint %r: replayed %d cached pages", checkpoint, number)
            while cursor:
                data = fetch(cursor)
                number += 1
                if cache:
                    cache.write(number, cursor, data)
                yield cursor, data
                cursor = (data.get("meta") or {}).get("next_cursor")
                if not data.get(items_key):
                    return

        seen = set()
        first_count = None
        warned = False
        yielded = 0
        for number, (cursor, data) in enumerate(pages(), start=1):
            if cursor in seen:
                raise PaginationError(f"cursor loop detected at page {number}")
            seen.add(cursor)
            count = (data.get("meta") or {}).get("count")
            if first_count is None:
                first_count = count
            elif count != first_count and not warned:
                message = f"meta.count changed during iteration ({first_count} -> {count})"
                if strict:
                    raise PaginationError(message)
                logger.warning(message)
                warned = True
            if number % 50 == 0:
                logger.info("page %d: %d items so far (meta.count=%s)", number, yielded, first_count)
            for item in data.get(items_key) or []:
                yield _normalize_group(item) if items_key == "group_by" else item
                yielded += 1
                if max_results is not None and yielded >= max_results:
                    return

    def _iter_get(self, path, params, max_results=None, checkpoint=None, strict=False):
        params = {k: v for k, v in params.items() if v is not None}
        per_page = int(params.get("per_page", MAX_PER_PAGE))
        if per_page > MAX_PER_PAGE:
            raise ValueError(f"per_page maximum is {MAX_PER_PAGE}")
        params["per_page"] = per_page
        items_key = "group_by" if "group_by" in params else "results"
        signature = {"method": "GET", "path": path, "params": params}

        def fetch(cursor):
            return self._request("GET", path, {**params, "cursor": cursor})

        return self._paginate(fetch, signature, items_key, max_results, checkpoint, strict)

    @staticmethod
    def _path(entity):
        return "/" + entity.strip("/")

    @staticmethod
    def _group_field(field):
        # Keep the unknown/null group (OpenAlex leaves it out unless asked).
        return field if ":" in field else f"{field}:include_unknown"

    # ------------------------------------------------------------------ public API

    def get(self, entity, id, select=None):
        """One record by ID. OpenAlex IDs, DOIs, ROR, ORCID... are accepted."""
        if str(id).startswith(("https://openalex.org/", "http://openalex.org/")):
            id = short_id(id)
        return self._request("GET", f"{self._path(entity)}/{id}", {"select": join_fields(select)})

    def count(self, entity, filter=None, search=None, **params):
        """`meta.count` for a query (one list call)."""
        data = self._request(
            "GET",
            self._path(entity),
            {**params, "filter": filter_to_string(filter), "search": search, "per_page": 1},
        )
        return int((data.get("meta") or {}).get("count") or 0)

    def iter(
        self,
        entity,
        filter=None,
        search=None,
        select=None,
        sort=None,
        per_page=100,
        max_results=None,
        checkpoint=None,
        strict=False,
        **params,
    ):
        """Iterate over all results with cursor paging.

        With `checkpoint="name"` (and `cache_dir` set), every page is cached and a rerun
        replays the cached pages, then resumes from the last cursor.
        """
        query = {
            **params,
            "filter": filter_to_string(filter),
            "search": search,
            "select": join_fields(select),
            "sort": join_fields(sort),
            "per_page": per_page,
        }
        return self._iter_get(self._path(entity), query, max_results, checkpoint, strict)

    def list(self, entity, **kwargs):
        """Same arguments as `iter`; returns a list."""
        return list(self.iter(entity, **kwargs))

    def group_by(self, entity, field, filter=None, search=None, **params):
        """All groups `[{"key", "key_display_name", "count"}]`, following cursors.

        The unknown/null group is kept with `key=None`.
        """
        query = {
            **params,
            "filter": filter_to_string(filter),
            "search": search,
            "group_by": self._group_field(field),
        }
        return list(self._iter_get(self._path(entity), query))

    def sample(self, entity, n=500, seed=42, filter=None, search=None, select=None, **params):
        """A random sample of `n` records (at most 10,000), reproducible with `seed`."""
        if n > MAX_SAMPLE:
            raise ValueError(f"sample maximum is {MAX_SAMPLE}")
        per_page = min(MAX_PER_PAGE, n)
        query = {
            **params,
            "filter": filter_to_string(filter),
            "search": search,
            "select": join_fields(select),
            "sample": n,
            "seed": seed,
            "per_page": per_page,
        }
        results = []
        for page in range(1, math.ceil(n / per_page) + 1):
            data = self._request("GET", self._path(entity), {**query, "page": page})
            batch = data.get("results") or []
            results.extend(batch)
            if not batch or len(results) >= n:
                break
        return results[:n]

    # -- pasted URLs

    def iter_url(self, url, max_results=None, checkpoint=None, strict=False):
        """Iterate over a pasted api.openalex.org / openalex.org URL (groups if it has group_by)."""
        path, params = parse_url(url)
        return self._iter_get(path, params, max_results, checkpoint, strict)

    def list_url(self, url, **kwargs):
        return list(self.iter_url(url, **kwargs))

    def count_url(self, url):
        path, params = parse_url(url)
        params.pop("group_by", None)
        data = self._request("GET", path, {**params, "per_page": 1})
        return int((data.get("meta") or {}).get("count") or 0)

    # -- OQL

    def iter_oql(self, query, select=None, sort=None, per_page=100, max_results=None, strict=False):
        """Iterate over an OQL query (POST /). Yields groups if the query has `group by`."""
        if per_page > MAX_PER_PAGE:
            raise ValueError(f"per_page maximum is {MAX_PER_PAGE}")
        body = {"oql": query, "per_page": per_page, "select": join_fields(select), "sort": join_fields(sort)}
        body = {k: v for k, v in body.items() if v is not None}
        items_key = "group_by" if _GROUP_BY_RE.search(query) else "results"

        def fetch(cursor):
            return self._request("POST", "/", body={**body, "cursor": cursor})

        return self._paginate(fetch, {"method": "POST", "body": body}, items_key, max_results, None, strict)

    def oql(self, query, **kwargs):
        """Run an OQL query; returns the results, or the groups for a `group by` query."""
        return list(self.iter_oql(query, **kwargs))

    def translate(self, text):
        """Translate and validate a classic URL or an OQL query via /query, without running it.

        Returns `{"oql", "oqo", "classic_url", "valid", "errors"}`.
        """
        if text.strip().lower().startswith(("http://", "https://")):
            path, params = parse_url(text)
            query = urlencode(params, safe=":,|!<>*/")
            body = {"oxurl": path + ("?" + query if query else "")}
        else:
            body = {"oql": text}
        keys = ("oql", "oqo", "classic_url", "valid", "errors")
        try:
            data = self._request("POST", "/query", body=body)
        except HTTPError as exc:
            if exc.status != 400:
                raise
            return {**dict.fromkeys(keys), "valid": False, "errors": [exc.validation or exc.body_excerpt]}
        validation = data.get("validation") or {}
        oxurl = data.get("oxurl")
        return {
            "oql": data.get("oql"),
            "oqo": data.get("oqo"),
            "classic_url": self.base_url + oxurl if oxurl else None,
            "valid": validation.get("valid"),
            "errors": validation.get("errors"),
        }
