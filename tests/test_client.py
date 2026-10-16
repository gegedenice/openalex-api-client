import logging

import pytest
import requests

from openalex_api_client import BudgetExhausted, HTTPError, OpenAlex, OpenAlexError, PaginationError
from openalex_api_client.query import filter_to_string, parse_url

from conftest import FakeResponse, group_page, page

SECRET = "sk-very-secret-key-123"


def rows(n, start=0):
    return [{"id": f"W{i}"} for i in range(start, start + n)]


# 1. cursor iteration ---------------------------------------------------------------


def test_cursor_iteration_stops_at_null_cursor(make_client):
    oa, session, _ = make_client([page(rows(3), "c1", 7), page(rows(3, 3), "c2", 7), page(rows(1, 6), None, 7)])
    results = oa.list("works", filter="type:article")
    assert [r["id"] for r in results] == [f"W{i}" for i in range(7)]
    assert [c["params"]["cursor"] for c in session.calls] == ["*", "c1", "c2"]
    assert all(c["params"]["per_page"] == 100 for c in session.calls)
    assert session.calls[0]["url"] == "https://api.openalex.org/works"


def test_cursor_loop_raises(make_client):
    oa, _, _ = make_client([page(rows(1), "c1"), page(rows(1, 1), "c1"), page(rows(1, 2), "c1")])
    with pytest.raises(PaginationError):
        oa.list("works")


def test_count_change_warns_or_raises(make_client, caplog):
    oa, _, _ = make_client([page(rows(1), "c1", 10), page(rows(1, 1), None, 11)])
    with caplog.at_level(logging.WARNING):
        assert len(oa.list("works")) == 2
    assert "meta.count changed" in caplog.text
    oa, _, _ = make_client([page(rows(1), "c1", 10), page(rows(1, 1), None, 11)])
    with pytest.raises(PaginationError):
        oa.list("works", strict=True)


# 2. max_results ----------------------------------------------------------------------


def test_max_results_truncates_exactly(make_client):
    oa, session, _ = make_client([page(rows(3), "c1"), page(rows(3, 3), "c2"), page(rows(3, 6), None)])
    results = oa.list("works", max_results=4)
    assert len(results) == 4
    assert len(session.calls) == 2  # third page never requested


# 3. retries --------------------------------------------------------------------------


def test_retry_after_then_success(make_client):
    oa, session, sleeps = make_client(
        [FakeResponse(429, {"error": "slow down"}, {"Retry-After": "1"}), FakeResponse(200, {"id": "W1"})]
    )
    assert oa.get("works", "W1") == {"id": "W1"}
    assert sleeps == [1]
    assert len(session.calls) == 2


def test_five_503_raise_http_error(make_client):
    oa, session, sleeps = make_client([FakeResponse(503, {"error": "down"}) for _ in range(5)], max_retries=4)
    with pytest.raises(HTTPError) as info:
        oa.get("works", "W1")
    assert info.value.status == 503
    assert len(session.calls) == 5
    assert len(sleeps) == 4


def test_budget_exhausted_without_retry(make_client):
    headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "3600"}
    oa, session, sleeps = make_client([FakeResponse(429, {"error": "budget"}, headers), FakeResponse(200, {})])
    with pytest.raises(BudgetExhausted) as info:
        oa.get("works", "W1")
    assert "3600" in str(info.value)
    assert len(session.calls) == 1
    assert sleeps == []


def test_connection_errors_are_retried_then_raised(make_client):
    oa, session, _ = make_client([requests.ConnectionError("boom")] * 3, max_retries=2)
    with pytest.raises(OpenAlexError):
        oa.count("works")
    assert len(session.calls) == 3


def test_usage_from_headers(make_client):
    headers = {"X-RateLimit-Limit": "100000", "X-RateLimit-Remaining": "99990",
               "X-RateLimit-Credits-Used": "1", "X-RateLimit-Reset": "500"}
    oa, _, _ = make_client([FakeResponse(200, {"meta": {"count": 5}}, headers)] * 2)
    oa.count("works")
    oa.count("works")
    assert oa.usage.limit == 100000
    assert oa.usage.remaining == 99990
    assert oa.usage.credits_used_total == 2
    assert oa.usage.reset_seconds == 500


# 4. the key never leaks ---------------------------------------------------------------


def test_api_key_never_leaks(make_client, caplog, monkeypatch):
    error_body = {"error": f"bad request for https://api.openalex.org/works?api_key={SECRET}"}
    responses = [
        FakeResponse(503, {}),
        FakeResponse(400, error_body),
        requests.ConnectionError(f"failed https://api.openalex.org/works?api_key={SECRET}"),
        requests.ConnectionError(f"failed https://api.openalex.org/works?api_key={SECRET}"),
    ]
    oa, session, _ = make_client(responses, api_key=SECRET, max_retries=1)
    assert SECRET not in repr(oa)
    messages = []
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(HTTPError) as info:
            oa.list("works", filter="type:article")
        messages.append(str(info.value))
        messages.append(info.value.url)
        with pytest.raises(OpenAlexError) as info:
            oa.count("works")
        messages.append(str(info.value))
        assert info.value.__cause__ is None and info.value.__context__ is not None
    assert session.calls[0]["params"]["api_key"] == SECRET  # it is sent...
    for text in messages + [r.getMessage() for r in caplog.records]:
        assert SECRET not in text  # ...but never shown
    monkeypatch.setenv("OPENALEX_API_KEY", SECRET)
    assert OpenAlex().api_key == SECRET
    assert SECRET not in repr(OpenAlex())


# 5. filters, URLs, OQL ---------------------------------------------------------------


IRD = "authorships.institutions.lineage:I4210166444,type:article,publication_year:2020-2025,is_retracted:false"


def test_filter_string_unchanged_and_dict_conversion(make_client):
    assert filter_to_string(IRD) == IRD
    ird = {"authorships.institutions.lineage": "I4210166444", "type": "article",
           "publication_year": "2020-2025", "is_retracted": False}
    assert filter_to_string(ird) == IRD
    assert filter_to_string({"authorships.countries": ["KH", "VN"], "cited_by_count": ">10", "x": 3, "y": None}) == (
        "authorships.countries:KH|VN,cited_by_count:>10,x:3"
    )
    with pytest.raises(ValueError):
        filter_to_string({"ids.openalex": [f"W{i}" for i in range(101)]})
    oa, session, _ = make_client([FakeResponse(200, {"meta": {"count": 47851}})])
    assert oa.count("works", filter=ird) == 47851
    assert session.calls[0]["params"]["filter"] == IRD


def test_api_and_web_urls_give_same_request(make_client):
    api = f"https://api.openalex.org/works?filter={IRD}&select=id,title&page=3&api_key=abc&mailto=a@b.c&cursor=xyz"
    web = f"https://openalex.org/works?filter={IRD}&select=id,title&page=2"
    assert parse_url(api) == parse_url(web) == ("/works", {"filter": IRD, "select": "id,title"})
    with pytest.raises(ValueError):
        parse_url("https://example.org/works")

    oa, session, _ = make_client([page(rows(2), None), page(rows(2), None)])
    assert oa.list_url(api) == oa.list_url(web)
    first, second = (c["params"] for c in session.calls)
    assert first == second
    assert first == {"filter": IRD, "select": "id,title", "per_page": 100, "cursor": "*"}

    oa, session, _ = make_client([FakeResponse(200, {"meta": {"count": 47851}})])
    assert oa.count_url(api) == 47851
    assert session.calls[0]["params"] == {"filter": IRD, "select": "id,title", "per_page": 1}


def test_oql_post_body_has_paging_siblings(make_client):
    oa, session, _ = make_client([page(rows(2), "c1"), page(rows(1, 2), None)])
    query = "works where year is (2020)"
    assert len(oa.oql(query, select="id,title")) == 3
    first, second = session.calls
    assert first["method"] == "POST" and first["url"] == "https://api.openalex.org/"
    assert first["json"] == {"oql": query, "per_page": 100, "select": "id,title", "cursor": "*"}
    assert second["json"]["cursor"] == "c1" and second["json"]["oql"] == query


def test_oql_group_by_returns_groups(make_client):
    groups = [{"key": "article", "key_display_name": "article", "count": 10},
              {"key": "unknown", "key_display_name": "unknown", "count": 1}]
    oa, _, _ = make_client([group_page(groups, None)])
    result = oa.oql("works where year is (2020) group by type")
    assert result == [{"key": "article", "key_display_name": "article", "count": 10},
                      {"key": None, "key_display_name": "unknown", "count": 1}]


def test_oql_400_surfaces_validation(make_client):
    body = {"error": "Invalid query", "validation": {"errors": ["Unknown field 'colour'"]}}
    oa, _, _ = make_client([FakeResponse(400, body), FakeResponse(400, body)])
    with pytest.raises(HTTPError) as info:
        oa.oql("works where colour is (red)")
    assert "Unknown field 'colour'" in str(info.value)
    translated = oa.translate("works where colour is (red)")
    assert translated["valid"] is False and "Unknown field" in translated["errors"][0]


def test_translate_returns_known_keys(make_client):
    body = {"oql": "works where ...", "oqo": {}, "classic_url": "https://api.openalex.org/works?filter=x",
            "valid": True, "errors": [], "extra": 1}
    oa, session, _ = make_client([FakeResponse(200, body)])
    result = oa.translate("https://api.openalex.org/works?filter=x")
    assert set(result) == {"oql", "oqo", "classic_url", "valid", "errors"}
    assert session.calls[0]["url"].endswith("/query")


# 6. group_by -------------------------------------------------------------------------


def test_group_by_follows_cursors_and_keeps_null(make_client):
    oa, session, _ = make_client([
        group_page([{"key": "https://openalex.org/countries/FR", "key_display_name": "France", "count": 9}], "g1"),
        group_page([{"key": "unknown", "key_display_name": "unknown", "count": 2}], None),
    ])
    groups = oa.group_by("works", "authorships.countries", filter={"type": "article"})
    assert groups == [
        {"key": "https://openalex.org/countries/FR", "key_display_name": "France", "count": 9},
        {"key": None, "key_display_name": "unknown", "count": 2},
    ]
    assert session.calls[0]["params"]["group_by"] == "authorships.countries:include_unknown"
    assert [c["params"]["cursor"] for c in session.calls] == ["*", "g1"]


# 7. resume ---------------------------------------------------------------------------


def test_resume_from_checkpoint(make_client, tmp_path):
    pages = [page(rows(2), "c1"), page(rows(2, 2), "c2"), page(rows(2, 4), None)]
    oa, session, _ = make_client(
        [pages[0], pages[1], FakeResponse(400, {"error": "interrupted"})], cache_dir=tmp_path, max_retries=0
    )
    seen = []
    with pytest.raises(HTTPError):
        for work in oa.iter("works", filter="type:article", checkpoint="ird"):
            seen.append(work)
    assert len(seen) == 4
    assert sorted(p.name for p in (tmp_path / "ird").iterdir()) == [
        "page-00001.json.gz", "page-00002.json.gz", "params.json"
    ]

    oa, session, _ = make_client([pages[2]], cache_dir=tmp_path)
    results = oa.list("works", filter="type:article", checkpoint="ird")
    assert [r["id"] for r in results] == [f"W{i}" for i in range(6)]
    assert [c["params"]["cursor"] for c in session.calls] == ["c2"]  # only page 3 fetched

    oa, session, _ = make_client([], cache_dir=tmp_path)
    assert len(oa.list("works", filter="type:article", checkpoint="ird")) == 6  # all cached
    assert session.calls == []

    with pytest.raises(PaginationError):
        oa.list("works", filter="type:book", checkpoint="ird")


def test_checkpoint_requires_cache_dir(make_client):
    oa, _, _ = make_client([])
    with pytest.raises(ValueError):
        oa.list("works", checkpoint="x")


# misc ---------------------------------------------------------------------------------


def test_sample_uses_pages_and_seed(make_client):
    oa, session, _ = make_client([page(rows(100), None), page(rows(50, 100), None)])
    result = oa.sample("works", n=150, seed=7)
    assert len(result) == 150
    assert [c["params"]["page"] for c in session.calls] == [1, 2]
    assert session.calls[0]["params"]["sample"] == 150 and session.calls[0]["params"]["seed"] == 7
    with pytest.raises(ValueError):
        oa.sample("works", n=10_001)


def test_get_accepts_external_ids(make_client):
    oa, session, _ = make_client([FakeResponse(200, {}), FakeResponse(200, {})])
    oa.get("works", "https://doi.org/10.1234/x")
    oa.get("works", "https://openalex.org/W2741809807", select=["id", "title"])
    assert session.calls[0]["url"] == "https://api.openalex.org/works/https://doi.org/10.1234/x"
    assert session.calls[1]["url"] == "https://api.openalex.org/works/W2741809807"
    assert session.calls[1]["params"] == {"select": "id,title"}


def test_no_logging_config_at_import():
    import importlib

    import openalex_api_client

    root = logging.getLogger()
    before = list(root.handlers)
    importlib.reload(openalex_api_client)
    assert root.handlers == before


def test_legacy_wrapper_warns_and_uses_new_api(make_client):
    from openalex_api_client import OpenAlexClient

    with pytest.warns(DeprecationWarning):
        client = OpenAlexClient(api_key=SECRET, max_rps=None)
    client._oa.session = type(make_client([])[1])([page([{"id": "https://openalex.org/W1", "title": "T"}], None)])
    with pytest.warns(DeprecationWarning):
        works = client.list_all_works(digest=True, filter="type:article")
    assert works[0]["id"] == "https://openalex.org/W1"
    assert SECRET not in repr(client)
