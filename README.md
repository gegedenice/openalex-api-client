# openalex-api-client

A small, generic, dependable Python client for the [OpenAlex](https://openalex.org) REST API,
plus helpers that turn work records into tidy tables.

- one generic API for every entity (`works`, `authors`, `institutions`, `sources`, `topics`,
  `subfields`, `fields`, `domains`, `publishers`, `funders`, `keywords`, …);
- cursor paging everywhere (no 10,000-result limit), `group_by` with all groups, `sample`;
- retries with backoff on 429/5xx and network errors, a stop on an exhausted daily budget,
  throttling (10 requests/s by default);
- an optional page cache that lets a long harvest resume where it stopped;
- the API key is never logged and never appears in error messages or `repr`;
- tidy pandas tables (`works`, `authorships`, `topics`, `counts_by_year`, `sdgs`, `funders`).

The core depends on `requests` only. The tables need the `[tables]` extra (pandas + pyarrow).

## Installation

```bash
pip install "openalex-api-client @ git+https://github.com/gegedenice/openalex-api-client"
pip install "openalex-api-client[tables] @ git+https://github.com/gegedenice/openalex-api-client"
```

Python ≥ 3.10.

## Quick start

```python
from openalex_api_client import OpenAlex, short_id

oa = OpenAlex()        # key read from the OPENALEX_API_KEY environment variable (or anonymous)

oa.get("works", "W2741809807")
oa.get("works", "https://doi.org/10.7717/peerj.4375")          # DOI, ROR, ORCID… accepted as IDs
oa.count("works", filter="publication_year:2020,is_oa:true")
for work in oa.iter("works", filter="publication_year:2020", select="id,title", max_results=500):
    ...
oa.group_by("works", "authorships.countries", filter={"publication_year": 2020})
oa.sample("works", n=500, seed=42, filter="type:article")
oa.usage   # Usage(limit, remaining, credits_used_total, reset_seconds) from the last headers
```

## Acceptance examples

```python
from openalex_api_client import OpenAlex, short_id
oa = OpenAlex()                                   # key read from OPENALEX_API_KEY

# Research Signal Radar universe — pasted URL
oa.count_url("https://api.openalex.org/works?filter=authorships.institutions.lineage:I4210166444,"
             "type:article,publication_year:2020-2025,is_retracted:false")   # 47,848 in Oct 2026 (77,831 for 2016–2025)

# IRD study — partner countries of IRD articles linked to SDG 14, 2021–2025 (dict form)
ird = {"authorships.institutions.lineage": "I4210166444", "type": "article", "is_retracted": "false"}
oa.group_by("works", "authorships.countries",
            filter={**ird, "publication_year": "2021-2025", "sustainable_development_goals.id": "sdgs/14"})

# IRD study — OA status by field
for field in oa.list("fields"):
    oa.group_by("works", "open_access.oa_status",
                filter={**ird, "publication_year": "2021-2025", "primary_topic.field.id": short_id(field["id"])})

# The same kind of question in OQL, and the translation tool
oa.oql("works where year is (2023) group by type")
oa.translate("https://api.openalex.org/works?filter=authorships.institutions.lineage:I4210166444")
```

Exact filter values such as the SDG ID format are to be checked against the live API
(`oa.translate` helps).

## Three ways to ask — no query builder

**(a) Paste a URL.** Build the query on openalex.org or in the browser, copy the URL, paste it.
`api.openalex.org` and `openalex.org` web URLs are both accepted; `api_key`, `page`, `cursor` and
`mailto` are removed and everything else is kept unchanged.

```python
url = ("https://api.openalex.org/works?filter=authorships.institutions.lineage:I4210166444,"
       "type:article,publication_year:2020-2025,is_retracted:false&select=id,title")
oa.list_url(url)                  # all results (cursor paging added automatically)
oa.count_url(url)                 # meta.count only
oa.iter_url(url, max_results=500)
```

A URL with `group_by` returns the groups.

**(b) A classic filter, as a string or a dict.** Values are written exactly as in the OpenAlex
docs (`2020-2025`, `!FR`, `>10`, `KH|VN`).

```python
IRD = "authorships.institutions.lineage:I4210166444,type:article,publication_year:2020-2025,is_retracted:false"
oa.count("works", filter=IRD)

ird = {"authorships.institutions.lineage": "I4210166444", "type": "article",
       "publication_year": "2020-2025", "is_retracted": "false"}
oa.group_by("works", "authorships.countries", filter={**ird, "publication_year": "2021-2025"})
```

The dict form has only two conveniences: a list becomes an OR (`["KH", "VN"]` → `KH|VN`) and
Python `True`/`False`/`int` become `true`/`false`/`"10"` (`None` values are skipped). A list longer
than 100 values raises `ValueError` (OpenAlex limit). A string filter is sent unchanged.

**(c) OQL**, OpenAlex's text query language ([help.openalex.org/api/oql](https://help.openalex.org/api/oql/)).

```python
oa.oql("works where institution is (I4210166444) and type is (article) "
       "and year >= (2020) and year <= (2025)", select="id,title", max_results=None)
oa.oql("works where year is (2020) group by type")   # returns the groups
oa.translate("works where year is (2020)")            # {"oql", "oqo", "classic_url", "valid", "errors"}
oa.translate("https://api.openalex.org/works?filter=publication_year:2020")   # URL -> OQL
```

Queries are sent as `POST /` with paging, `select` and `sort` as sibling keys of `oql`.
OpenAlex says OQL "is in active development": use it for exploration, keep production
harvests on classic filters.

## API reference

```python
OpenAlex(api_key=None, base_url="https://api.openalex.org", timeout=30, max_retries=6,
         user_agent="openalex-api-client/1.0", cache_dir=None, max_rps=10)
```

| Method | Returns |
|---|---|
| `get(entity, id, select=None)` | one record |
| `count(entity, filter=None, search=None)` | `meta.count` |
| `iter(entity, filter=None, search=None, select=None, sort=None, per_page=100, max_results=None, checkpoint=None, strict=False, **params)` | iterator of records (cursor paging) |
| `list(entity, …same…)` | list of records |
| `group_by(entity, field, filter=None, search=None)` | `[{"key", "key_display_name", "count"}]`, all groups; the unknown group has `key=None` |
| `sample(entity, n=500, seed=42, filter=None, …)` | `n` random records (n ≤ 10,000) |
| `iter_url(url)`, `list_url(url)`, `count_url(url)` | as above, from a pasted URL |
| `iter_oql(query)`, `oql(query)`, `translate(text)` | OQL results / groups / translation |
| `usage` | `Usage(limit, remaining, credits_used_total, reset_seconds)` |

`filter` is a string or a dict; `select` and `sort` a string or a list. Extra keyword arguments
are passed as query parameters. Every method returns plain dicts and lists.

`iter` stops when `next_cursor` is null or at `max_results`. It raises `PaginationError` on a
cursor loop. If `meta.count` changes during iteration it logs a warning, or raises with
`strict=True`.

### Errors

All inherit from `OpenAlexError`:

- `HTTPError(status, url, body_excerpt, validation)` — a non-retryable error, or a retryable one
  after the last retry. `validation` carries the API's error message (e.g. an OQL syntax error).
- `BudgetExhausted` — HTTP 429 with `X-RateLimit-Remaining: 0`; raised at once, with the reset time.
- `PaginationError` — cursor loop, count change in strict mode, or checkpoint mismatch.

URLs in messages and logs never contain the API key.

### Retries and throttling

Retried: 429, 500, 502, 503, 504, connection errors and timeouts, up to `max_retries` times.
The delay is `Retry-After` when present, else `min(60, 1.5**attempt) + uniform(0, 1)` seconds.
Requests are spaced to stay under `max_rps` (default 10/s; OpenAlex allows 100/s).

### Page cache and resume

```python
oa = OpenAlex(cache_dir="data/cache")
for work in oa.iter("works", filter=IRD, checkpoint="ird-2016-2025"):
    ...
```

Each page is written to `data/cache/ird-2016-2025/page-00001.json.gz` with the request
parameters (without the key) and the cursor that produced it. Running the same `iter` again
replays the cached pages, then continues from the last `next_cursor`. If the parameters differ
from those in `params.json`, `PaginationError` is raised instead of mixing two harvests.

## Tidy tables

```python
from openalex_api_client.tidy import works_tables, write_parquet, reconstruct_abstract, short_id

tables = works_tables(works, root_institution="I4210166444")   # root optional
tables = works_tables("data/cache/ird-2016-2025")              # or re-tidy cached pages offline
write_parquet(tables, "data/tables")
```

| Table | One row per | Columns |
|---|---|---|
| `works` | work | `work_id`, `doi`, `title`, `abstract`, `has_abstract`, `publication_date`, `publication_year`, `type`, `language`, `cited_by_count`, `fwci`, `is_retracted`, `oa_status`, `is_oa`, `source_id`, `source_name`, `primary_topic_id`, `primary_topic`, `subfield_id`, `subfield`, `field_id`, `field`, `domain_id`, `domain`, `n_authors`, `authors_truncated`, `updated_date` |
| `authorships` | work × author position × institution (an author with no institution gets one row with null institution) | `work_id`, `author_position_idx` (0-based), `author_id`, `author_name`, `is_corresponding`, `institution_id`, `institution_name`, `institution_ror`, `institution_country`, `institution_type`, `institution_lineage` (list), `is_anchor` (root ∈ lineage; null without `root_institution`) |
| `topics` | work × topic (up to 3) | `work_id`, `rank` (1 = primary), `topic_id`, `topic`, `score`, `subfield_id`, `field_id`, `domain_id` |
| `counts_by_year` | work × year with ≥ 1 citation | `work_id`, `year`, `cited_by_count` |
| `sdgs` | work × SDG | `work_id`, `sdg_id`, `sdg`, `score` |
| `funders` | work × funder/award | `work_id`, `funder_id`, `funder`, `award_id` |

- IDs are in short form (`W123`, `I456`, `T789`, `A…`; `1105` for subfields). DOIs are bare (`10.…`).
- `reconstruct_abstract()` returns `None` when there is no abstract.
- Missing nested objects give nulls; a malformed record is skipped with a warning naming its ID.
- `funders` reads the older `grants` list and the newer `awards` + `funders` lists.

## Logging

The package uses module loggers only (`logging.getLogger("openalex_api_client…")`) and never
configures logging. Progress is logged at INFO every 50 pages; requests at DEBUG.

## Migrating from 0.x

`OpenAlexClient` (`get_work`, `list_works`, `list_all_works`, …) is kept for one version as a
thin wrapper over `OpenAlex`, emitting `DeprecationWarning`. `digest=True` is available there only.
Differences: `list_all_*` uses cursor paging (no 10,000 limit) and errors are raised instead of
silently returning partial results or `0`. Use `tidy.works_tables` instead of digests.

## Checked against the live API (October 2026)

- `group_by` follows cursors, and `:include_unknown` keeps the unknown group (the client appends it
  unless the field already has a `:` suffix): confirmed.
- `POST /query` takes a JSON body with one of `oql`, `oqo` or `oxurl` (a relative URL such as
  `/works?filter=publication_year:2020`). It answers with `oql` (normalized, e.g. `get works where
  published in 2020`), `oqo`, `oxurl` and `validation: {valid, errors, warnings}`. `translate` sends
  pasted URLs as `oxurl` and maps the answer to `classic_url` (base URL + `oxurl`), `valid` and
  `errors`. Errors come back as `{"valid": false, "errors": [{"type", "message", "location"}]}`;
  their messages are surfaced in `HTTPError.validation`.
- `authorships.institutions.lineage` has no known OQL equivalent: `institution is (…)` may match the
  exact institution only. Harvests that need child units stay on classic filters.

Still assumed:

- `select` accepts root-level fields only.
- The truncated-author-list flag in list results is `is_authors_truncated`
  (read into `works.authors_truncated`). A work with 33 authors had no such key, which is
  expected if the flag only appears on works with more than 100 authors; not yet seen on one.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

No test uses the network: a fake session is injected with `OpenAlex(session=...)`.

## License

MIT
