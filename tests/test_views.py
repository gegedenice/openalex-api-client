import pytest

from openalex_api_client import VIEWS, hydrate, reconstruct_abstract, views
from openalex_api_client.views import resolve_fields

from conftest import FakeResponse, page

INDEX = {"Hello": [0], "world": [1, 3], "again": [2]}


def test_resolve_full_record_when_nothing_asked():
    assert resolve_fields("works") == (None, (), ())
    # a full record already carries the inverted index: nothing added, nothing dropped
    assert resolve_fields("works", hydrate=True) == (None, ("abstract",), ())


def test_views_union_with_select_keeps_order_and_id():
    select, _, drop = resolve_fields("works", select="doi, title", view=["oa", "funding"])
    fields = select.split(",")
    assert fields[0] == "id" and fields.count("id") == 1
    assert fields == list(dict.fromkeys(VIEWS["works"]["oa"] + VIEWS["works"]["funding"] + ["doi", "title"]))
    assert drop == ()


def test_hydrate_adds_and_then_drops_its_dependency():
    select, hydrators, drop = resolve_fields("works", view="core", hydrate="abstract")
    assert select.endswith(",abstract_inverted_index")
    assert hydrators == ("abstract",) and drop == ("abstract_inverted_index",)


def test_explicitly_asked_dependency_is_kept():
    _, _, drop = resolve_fields("works", select=["abstract_inverted_index"], hydrate=True)
    assert drop == ()


def test_unknown_names_raise():
    with pytest.raises(ValueError, match="unknown view"):
        resolve_fields("works", view="nope")
    with pytest.raises(ValueError, match="unknown hydrate"):
        resolve_fields("works", hydrate="nope")
    with pytest.raises(ValueError, match="no views defined"):
        resolve_fields("authors", view="core")


def test_views_returns_a_copy():
    v = views("works")
    v["oa"].append("x")
    assert "x" not in VIEWS["works"]["oa"]


def test_reconstruct_abstract():
    assert reconstruct_abstract(INDEX) == "Hello world again world"
    assert reconstruct_abstract(None) is None and reconstruct_abstract({}) is None


def test_hydrate_function_on_cached_record():
    rec = {"id": "W1", "abstract_inverted_index": INDEX, "_derived": {"other": 1}}
    out = hydrate(rec, drop=["abstract_inverted_index"])
    assert out == {"id": "W1", "_derived": {"other": 1, "abstract": "Hello world again world"}}
    assert hydrate({"id": "W2"})["_derived"] == {"abstract": None}


def test_get_with_view_and_hydrate(make_client):
    body = {"id": "https://openalex.org/W1", "open_access": {"is_oa": True}, "abstract_inverted_index": INDEX}
    oa, session, _ = make_client([FakeResponse(body=body)])
    work = oa.get("works", "W1", view="oa", hydrate=True)
    sent = session.calls[0]["params"]["select"].split(",")
    assert sent[0] == "id" and "open_access" in sent and sent[-1] == "abstract_inverted_index"
    assert "abstract_inverted_index" not in work
    assert work["_derived"]["abstract"] == "Hello world again world"


def test_get_without_options_is_unchanged(make_client):
    body = {"id": "W1", "abstract_inverted_index": INDEX}
    oa, session, _ = make_client([FakeResponse(body=dict(body))])
    assert oa.get("works", "W1") == body
    assert "select" not in session.calls[0]["params"]


def test_list_hydrates_each_result(make_client):
    results = [{"id": "W1", "abstract_inverted_index": INDEX}, {"id": "W2", "abstract_inverted_index": None}]
    oa, session, _ = make_client([page(results, None, count=2)])
    works = oa.list("works", view="core", hydrate="abstract")
    assert [w["_derived"]["abstract"] for w in works] == ["Hello world again world", None]
    assert all("abstract_inverted_index" not in w for w in works)


def test_oql_group_by_is_not_hydrated(make_client):
    groups = {"meta": {"count": 1, "next_cursor": None}, "group_by": [{"key": "2020", "count": 3}]}
    oa, _, _ = make_client([FakeResponse(body=groups)])
    out = oa.oql("get works where year > 2019; group by year", hydrate=True)
    assert "_derived" not in out[0]
