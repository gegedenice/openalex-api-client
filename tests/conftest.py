import json

import pytest

from openalex_api_client import OpenAlex


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    """Replays a list of FakeResponse (or exceptions) and records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": dict(params or {}), "json": json})
        if not self.responses:
            raise AssertionError("unexpected request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def page(results, next_cursor, count=None):
    meta = {"count": count, "next_cursor": next_cursor}
    return FakeResponse(body={"meta": meta, "results": results})


def group_page(groups, next_cursor, count=None):
    return FakeResponse(body={"meta": {"count": count, "next_cursor": next_cursor}, "group_by": groups})


@pytest.fixture
def make_client(tmp_path):
    """make_client(responses, **kwargs) -> (OpenAlex, FakeSession, sleeps)."""

    def factory(responses, **kwargs):
        session = FakeSession(responses)
        kwargs.setdefault("api_key", None)
        kwargs.setdefault("max_rps", None)
        oa = OpenAlex(session=session, **kwargs)
        sleeps = []
        oa._sleep = sleeps.append
        return oa, session, sleeps

    return factory
