"""Derived fields computed locally from a raw record: no network, no pandas.

Derived values are written under the record's `_derived` key, never over an OpenAlex field.
"""

__all__ = ["HYDRATORS", "DEFAULT_HYDRATE", "reconstruct_abstract", "hydrate", "resolve_hydrate"]


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


# name -> (top-level fields it reads, function record -> value)
HYDRATORS = {
    "abstract": (("abstract_inverted_index",), lambda r: reconstruct_abstract(r.get("abstract_inverted_index"))),
}

DEFAULT_HYDRATE = ("abstract",)


def resolve_hydrate(value):
    """`None`/`False` -> (), `True` -> the default set, a name or a list of names -> a tuple."""
    if value is None or value is False:
        return ()
    if value is True:
        return DEFAULT_HYDRATE
    names = [value] if isinstance(value, str) else list(value)
    unknown = [n for n in names if n not in HYDRATORS]
    if unknown:
        raise ValueError(f"unknown hydrate {unknown}; available: {sorted(HYDRATORS)}")
    return tuple(dict.fromkeys(names))


def hydrate(record, names=True, drop=()):
    """Add `record["_derived"][name]` for each hydrator, then remove the `drop` keys.

    Works on any raw record, e.g. one read back from cached pages. The record is changed in place
    and returned.
    """
    if not isinstance(record, dict):
        return record
    names = resolve_hydrate(names)
    if names:
        derived = record.get("_derived")
        derived = dict(derived) if isinstance(derived, dict) else {}
        for name in names:
            derived[name] = HYDRATORS[name][1](record)
        record["_derived"] = derived
    for key in drop:
        record.pop(key, None)
    return record
