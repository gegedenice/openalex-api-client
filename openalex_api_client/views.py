"""Named views: aliases for groups of top-level fields, sent to OpenAlex as `select`.

OpenAlex `select` only takes top-level fields, so a view trims the response block by block,
not inside a block (`authorships` comes back whole).
"""

from .derive import HYDRATORS, resolve_hydrate

__all__ = ["VIEWS", "views", "resolve_fields"]

# Field names were checked against the client's own parsers and the live API (October 2026);
# `tests/test_live.py` re-checks every view (OPENALEX_LIVE=1).
VIEWS = {
    "works": {
        "core": ["id", "doi", "title", "display_name", "publication_year", "publication_date", "type", "language"],
        "ids": ["id", "doi", "ids"],
        "oa": [
            "id", "open_access", "best_oa_location", "primary_location", "locations", "locations_count",
            "apc_list", "apc_paid", "has_fulltext",
        ],
        "affiliations": [
            "id", "authorships", "corresponding_author_ids", "corresponding_institution_ids",
            "institutions_distinct_count", "countries_distinct_count",
        ],
        "classification": ["id", "primary_topic", "topics", "keywords", "sustainable_development_goals"],
        "impact": ["id", "cited_by_count", "counts_by_year", "fwci", "citation_normalized_percentile"],
        "references": ["id", "referenced_works_count", "referenced_works", "related_works"],
        "funding": ["id", "grants", "awards", "funders"],
        "biblio": ["id", "primary_location", "biblio"],
        "record": ["id", "is_retracted", "created_date", "updated_date"],
    },
}


def views(entity="works"):
    """The views defined for an entity: `{name: [fields]}` (a copy)."""
    entity = entity.strip("/")
    if entity not in VIEWS:
        raise ValueError(f"no views defined for {entity!r}; entities with views: {sorted(VIEWS)}")
    return {name: list(fields) for name, fields in VIEWS[entity].items()}


def _split(select):
    if select is None:
        return []
    if isinstance(select, str):
        return [f.strip() for f in select.split(",") if f.strip()]
    return [str(f).strip() for f in select if str(f).strip()]


def resolve_fields(entity, select=None, view=None, hydrate=None):
    """Combine `select`, `view` and `hydrate` into what to send and what to do afterwards.

    Returns `(select, hydrators, drop)`:
    - `select`: the comma-joined field list, or `None` for the full record;
    - `hydrators`: tuple of hydrator names to apply;
    - `drop`: fields added only because a hydrator needs them, removed from the result.
    """
    hydrators = resolve_hydrate(hydrate)
    names = [view] if isinstance(view, str) else list(view or [])
    asked = []
    if names:
        available = views(entity)
        unknown = [n for n in names if n not in available]
        if unknown:
            raise ValueError(f"unknown view {unknown} for {entity!r}; available: {sorted(available)}")
        asked = ["id"]
        for name in names:
            asked += available[name]
    asked += _split(select)
    if not asked:  # full record: everything a hydrator needs is already there
        return None, hydrators, ()
    asked = list(dict.fromkeys(asked))
    needed = [f for name in hydrators for f in HYDRATORS[name][0] if f not in asked]
    needed = list(dict.fromkeys(needed))
    return ",".join(asked + needed), hydrators, tuple(needed)
