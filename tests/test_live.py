"""Live checks against api.openalex.org. Run with: OPENALEX_LIVE=1 pytest tests/test_live.py"""

import os

import pytest

from openalex_api_client import OpenAlex, views

pytestmark = pytest.mark.skipif(not os.environ.get("OPENALEX_LIVE"), reason="set OPENALEX_LIVE=1")

WORK = "W2741809807"


@pytest.mark.parametrize("name", sorted(views("works")))
def test_every_work_view_is_accepted(name):
    # A field OpenAlex does not know makes the request fail with HTTP 400.
    work = OpenAlex().get("works", WORK, view=name)
    assert work["id"].endswith(WORK)


def test_hydrated_abstract_live():
    work = OpenAlex().get("works", WORK, view="core", hydrate=True)
    assert work["_derived"]["abstract"].startswith("Despite growing interest")
    assert "abstract_inverted_index" not in work
