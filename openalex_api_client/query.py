"""Query helpers: filter dicts to strings, OpenAlex URLs to (path, params), short IDs."""

from urllib.parse import parse_qsl, urlsplit

MAX_OR_VALUES = 100

# Parameters dropped from pasted URLs: the client manages keys and paging itself.
DROPPED_URL_PARAMS = {"api_key", "page", "cursor", "mailto"}


def _format_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_OR_VALUES:
            raise ValueError(
                f"OpenAlex accepts at most {MAX_OR_VALUES} OR values per filter, got {len(value)}"
            )
        return "|".join(_format_value(v) for v in value)
    return str(value)


def filter_to_string(filter):
    """Return the OpenAlex `filter` parameter.

    A string is returned unchanged. A dict becomes `key:value,...`; a list value becomes
    an OR (`["KH", "VN"]` -> `KH|VN`), booleans become `true`/`false`, ints become strings,
    and `None` values are skipped.
    """
    if filter is None:
        return None
    if isinstance(filter, str):
        return filter
    if isinstance(filter, dict):
        parts = [f"{k}:{_format_value(v)}" for k, v in filter.items() if v is not None]
        return ",".join(parts) or None
    raise TypeError(f"filter must be a str or a dict, not {type(filter).__name__}")


def join_fields(value):
    """`select` / `sort` may be given as a string or a list of strings."""
    if value is None or isinstance(value, str):
        return value
    return ",".join(value)


def parse_url(url):
    """Split an api.openalex.org or openalex.org URL into (path, params).

    `api_key`, `page`, `cursor` and `mailto` are removed; every other parameter is kept as is.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host not in {"api.openalex.org", "openalex.org", "www.openalex.org"}:
        raise ValueError(f"not an OpenAlex URL: {parts.scheme}://{parts.netloc}{parts.path}")
    path = parts.path.rstrip("/") or "/"
    params = {
        k: v for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in DROPPED_URL_PARAMS
    }
    return path, params


def short_id(value):
    """Short form of an OpenAlex ID: `https://openalex.org/W123` -> `W123`.

    Works for any URL-style ID (`.../subfields/1105` -> `1105`, `.../sdg/14` -> `14`).
    Strings that are already short, and `None`, are returned unchanged.
    """
    if value is None:
        return None
    value = str(value).rstrip("/")
    if "/" in value:
        return value.rsplit("/", 1)[1]
    return value
