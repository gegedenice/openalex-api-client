"""Raw work records -> tidy pandas tables. Pure functions, no network. Needs the `[tables]` extra."""

import gzip
import json
import logging
from pathlib import Path

import pandas as pd

from .query import short_id

logger = logging.getLogger(__name__)

__all__ = ["works_tables", "reconstruct_abstract", "short_id", "write_parquet", "iter_cached_works"]

LIST_AUTHORS_CAP = 100  # authorships kept per work in list results

COLUMNS = {
    "works": [
        "work_id", "doi", "title", "abstract", "has_abstract", "publication_date", "publication_year",
        "type", "language", "cited_by_count", "fwci", "is_retracted", "oa_status", "is_oa",
        "source_id", "source_name", "primary_topic_id", "primary_topic", "subfield_id", "subfield",
        "field_id", "field", "domain_id", "domain", "n_authors", "authors_truncated", "updated_date",
    ],
    "authorships": [
        "work_id", "author_position_idx", "author_id", "author_name", "is_corresponding",
        "institution_id", "institution_name", "institution_ror", "institution_country",
        "institution_type", "institution_lineage", "is_anchor",
    ],
    "topics": ["work_id", "rank", "topic_id", "topic", "score", "subfield_id", "field_id", "domain_id"],
    "counts_by_year": ["work_id", "year", "cited_by_count"],
    "sdgs": ["work_id", "sdg_id", "sdg", "score"],
    "funders": ["work_id", "funder_id", "funder", "award_id"],
}

DTYPES = {
    "works": {
        "publication_year": "Int64", "cited_by_count": "Int64", "n_authors": "Int64", "fwci": "Float64",
        "has_abstract": "boolean", "is_retracted": "boolean", "is_oa": "boolean", "authors_truncated": "boolean",
    },
    "authorships": {"author_position_idx": "Int64", "is_corresponding": "boolean", "is_anchor": "boolean"},
    "topics": {"rank": "Int64", "score": "Float64"},
    "counts_by_year": {"year": "Int64", "cited_by_count": "Int64"},
    "sdgs": {"score": "Float64"},
    "funders": {},
}


def _valid_text(value):
    """OpenAlex text can hold lone UTF-16 surrogates (e.g. a half math symbol), which pyarrow
    cannot encode. Replace them with U+FFFD; valid strings are returned unchanged."""
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def reconstruct_abstract(inverted_index):
    """Rebuild an abstract from OpenAlex's `abstract_inverted_index`; `None` when absent."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return None
    positions = {}
    for word, indexes in inverted_index.items():
        for index in indexes or []:
            positions[index] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def _bare_doi(doi):
    if not doi:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            return doi[len(prefix):]
    return doi


def _get(obj, *path):
    """Nested `.get` that tolerates missing or null objects."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def iter_cached_works(path):
    """Yield works from cached pages (`*.json.gz`): a file, or a directory searched recursively.

    Accepts the client's checkpoint pages and raw API pages (`{"results": [...]}`).
    """
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.rglob("*.json.gz"))
    for file in files:
        with gzip.open(file, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        page = data.get("response", data) if isinstance(data, dict) else {}
        yield from page.get("results") or []


def _work_rows(work, root):
    work_id = short_id(work["id"])
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    primary = work.get("primary_topic") or {}
    source = _get(work, "primary_location", "source") or {}
    authorships = work.get("authorships") or []
    # List results cut authorships at 100 without any flag (checked October 2026: a work with
    # 2,467 authors came back with 100). A list of 100 or more is therefore marked as possibly
    # truncated, so the caller can re-read it with a (free) singleton get.
    authors_count = work.get("authors_count")
    n_authors = authors_count if isinstance(authors_count, int) else len(authorships)
    truncated = work.get("is_authors_truncated")
    if truncated is None:
        if isinstance(authors_count, int):
            truncated = authors_count > len(authorships)
        else:
            truncated = len(authorships) >= LIST_AUTHORS_CAP

    rows = {name: [] for name in COLUMNS}
    rows["works"].append({
        "work_id": work_id,
        "doi": _bare_doi(work.get("doi")),
        "title": work.get("title") or work.get("display_name"),
        "abstract": abstract,
        "has_abstract": abstract is not None,
        "publication_date": work.get("publication_date"),
        "publication_year": work.get("publication_year"),
        "type": work.get("type"),
        "language": work.get("language"),
        "cited_by_count": work.get("cited_by_count"),
        "fwci": work.get("fwci"),
        "is_retracted": work.get("is_retracted"),
        "oa_status": _get(work, "open_access", "oa_status"),
        "is_oa": _get(work, "open_access", "is_oa"),
        "source_id": short_id(source.get("id")),
        "source_name": source.get("display_name"),
        "primary_topic_id": short_id(primary.get("id")),
        "primary_topic": primary.get("display_name"),
        "subfield_id": short_id(_get(primary, "subfield", "id")),
        "subfield": _get(primary, "subfield", "display_name"),
        "field_id": short_id(_get(primary, "field", "id")),
        "field": _get(primary, "field", "display_name"),
        "domain_id": short_id(_get(primary, "domain", "id")),
        "domain": _get(primary, "domain", "display_name"),
        "n_authors": n_authors,
        "authors_truncated": bool(truncated) if truncated is not None else None,
        "updated_date": work.get("updated_date"),
    })

    root = short_id(root) if root else None
    for idx, authorship in enumerate(authorships):
        author = authorship.get("author") or {}
        base = {
            "work_id": work_id,
            "author_position_idx": idx,
            "author_id": short_id(author.get("id")),
            "author_name": author.get("display_name") or authorship.get("raw_author_name"),
            "is_corresponding": authorship.get("is_corresponding"),
        }
        institutions = [i for i in (authorship.get("institutions") or []) if isinstance(i, dict)]
        if not institutions:
            rows["authorships"].append({**base, **dict.fromkeys(COLUMNS["authorships"][5:])})
            continue
        for inst in institutions:
            inst_id = short_id(inst.get("id"))
            lineage = [short_id(x) for x in (inst.get("lineage") or ([inst["id"]] if inst.get("id") else []))]
            rows["authorships"].append({
                **base,
                "institution_id": inst_id,
                "institution_name": inst.get("display_name"),
                "institution_ror": inst.get("ror"),
                "institution_country": inst.get("country_code"),
                "institution_type": inst.get("type"),
                "institution_lineage": lineage,
                "is_anchor": (root in lineage) if root else None,
            })

    for rank, topic in enumerate(work.get("topics") or [], start=1):
        rows["topics"].append({
            "work_id": work_id,
            "rank": rank,
            "topic_id": short_id(topic.get("id")),
            "topic": topic.get("display_name"),
            "score": topic.get("score"),
            "subfield_id": short_id(_get(topic, "subfield", "id")),
            "field_id": short_id(_get(topic, "field", "id")),
            "domain_id": short_id(_get(topic, "domain", "id")),
        })

    for entry in work.get("counts_by_year") or []:
        if (entry.get("cited_by_count") or 0) >= 1:
            rows["counts_by_year"].append(
                {"work_id": work_id, "year": entry.get("year"), "cited_by_count": entry["cited_by_count"]}
            )

    for sdg in work.get("sustainable_development_goals") or []:
        rows["sdgs"].append({
            "work_id": work_id,
            "sdg_id": short_id(sdg.get("id")),
            "sdg": sdg.get("display_name"),
            "score": sdg.get("score"),
        })

    # Older records carry `grants`; newer ones `awards` + `funders`.
    funded = set()
    for grant in work.get("grants") or []:
        funder_id = short_id(grant.get("funder"))
        funded.add(funder_id)
        rows["funders"].append({
            "work_id": work_id, "funder_id": funder_id,
            "funder": grant.get("funder_display_name"), "award_id": grant.get("award_id"),
        })
    for award in work.get("awards") or []:
        funder_id = short_id(award.get("funder_id"))
        funded.add(funder_id)
        rows["funders"].append({
            "work_id": work_id, "funder_id": funder_id,
            "funder": award.get("funder_display_name"), "award_id": award.get("funder_award_id"),
        })
    for funder in work.get("funders") or []:
        funder_id = short_id(funder.get("id"))
        if funder_id not in funded:
            rows["funders"].append({
                "work_id": work_id, "funder_id": funder_id,
                "funder": funder.get("display_name"), "award_id": None,
            })
    return rows


def works_tables(works, root_institution=None):
    """Tidy tables from raw work dicts, or from a path to cached `*.json.gz` pages.

    Returns a dict of DataFrames: works, authorships, topics, counts_by_year, sdgs, funders.
    With `root_institution`, `authorships.is_anchor` is True where the root is in the lineage.
    """
    if isinstance(works, (str, Path)):
        works = iter_cached_works(works)
    rows = {name: [] for name in COLUMNS}
    for work in works:
        work_id = work.get("id") if isinstance(work, dict) else None
        try:
            if not work_id:
                raise ValueError("record has no id")
            work_rows = _work_rows(work, root_institution)
        except Exception as exc:  # a malformed record never stops the whole table
            logger.warning("skipping malformed work %s: %s", work_id, exc)
            continue
        for name, items in work_rows.items():
            rows[name].extend({k: _valid_text(v) for k, v in item.items()} for item in items)
    return {
        name: pd.DataFrame(rows[name], columns=COLUMNS[name]).astype(DTYPES[name])
        for name in COLUMNS
    }


def write_parquet(tables, directory):
    """Write each table to `directory/<name>.parquet`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_parquet(directory / f"{name}.parquet", index=False)
