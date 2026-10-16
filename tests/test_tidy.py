import gzip
import json
import logging

import pandas as pd
import pytest

from openalex_api_client.tidy import reconstruct_abstract, short_id, works_tables, write_parquet

ROOT = "https://openalex.org/I4210166444"


def topic(i, score):
    return {
        "id": f"https://openalex.org/T{i}", "display_name": f"Topic {i}", "score": score,
        "subfield": {"id": "https://openalex.org/subfields/1105", "display_name": "Ecology"},
        "field": {"id": "https://openalex.org/fields/11", "display_name": "Agricultural Sciences"},
        "domain": {"id": "https://openalex.org/domains/1", "display_name": "Life Sciences"},
    }


WORKS = [
    {   # three topics, anchor + non-anchor institutions, SDG, grant
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/abc", "title": "First",
        "abstract_inverted_index": {"Rice": [0], "grows": [1], "fast": [2]},
        "publication_date": "2021-03-04", "publication_year": 2021, "type": "article", "language": "en",
        "cited_by_count": 5, "fwci": 1.2, "is_retracted": False,
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "primary_location": {"source": {"id": "https://openalex.org/S9", "display_name": "J"}},
        "primary_topic": topic(1, 0.9), "topics": [topic(1, 0.9), topic(2, 0.5), topic(3, 0.1)],
        "authorships": [
            {"author": {"id": "https://openalex.org/A1", "display_name": "Ana"}, "is_corresponding": True,
             "institutions": [
                 {"id": "https://openalex.org/I77", "display_name": "IRD unit", "ror": "https://ror.org/x",
                  "country_code": "FR", "type": "facility",
                  "lineage": ["https://openalex.org/I77", ROOT]},
                 {"id": "https://openalex.org/I88", "display_name": "Univ", "country_code": "SN",
                  "type": "education", "lineage": ["https://openalex.org/I88"]},
             ]},
        ],
        "is_authors_truncated": False,
        "counts_by_year": [{"year": 2023, "cited_by_count": 3}, {"year": 2022, "cited_by_count": 0},
                           {"year": 2021, "cited_by_count": 2}],
        "sustainable_development_goals": [
            {"id": "https://metadata.un.org/sdg/2", "display_name": "Zero hunger", "score": 0.7}],
        "grants": [{"funder": "https://openalex.org/F1", "funder_display_name": "ANR", "award_id": "ANR-1"}],
        "updated_date": "2026-10-01T00:00:00",
    },
    {   # no abstract; one author without institution; awards + funders schema
        "id": "https://openalex.org/W2", "title": "Second", "publication_year": 2022,
        "abstract_inverted_index": None,
        "authorships": [
            {"author": {"id": "https://openalex.org/A2", "display_name": "Bo"}, "institutions": []},
            {"author": {"id": "https://openalex.org/A3", "display_name": "Cy"},
             "institutions": [{"id": ROOT, "display_name": "IRD", "lineage": [ROOT]}]},
        ],
        "awards": [{"funder_id": "https://openalex.org/F2", "funder_display_name": "EU", "funder_award_id": "H2020"}],
        "funders": [{"id": "https://openalex.org/F2", "display_name": "EU"},
                    {"id": "https://openalex.org/F3", "display_name": "AFD"}],
    },
    {   # minimal record: every nested object missing
        "id": "https://openalex.org/W3", "primary_location": None, "primary_topic": None,
        "open_access": None, "authorships": None,
    },
]


def test_works_tables_row_counts_and_nulls(caplog):
    with caplog.at_level(logging.WARNING):
        tables = works_tables(WORKS + [{"title": "no id"}, "garbage"], root_institution=ROOT)
    assert "skipping malformed work" in caplog.text

    works = tables["works"].set_index("work_id")
    assert list(works.index) == ["W1", "W2", "W3"]
    assert works.loc["W1", "doi"] == "10.1/abc"
    assert works.loc["W1", "abstract"] == "Rice grows fast"
    assert bool(works.loc["W1", "has_abstract"]) and not bool(works.loc["W2", "has_abstract"])
    assert pd.isna(works.loc["W2", "abstract"])
    assert works.loc["W1", "subfield_id"] == "1105" and works.loc["W1", "source_id"] == "S9"
    assert works.loc["W1", "n_authors"] == 1 and works.loc["W2", "n_authors"] == 2
    assert works.loc["W3", "n_authors"] == 0
    assert pd.isna(works.loc["W3", "primary_topic_id"]) and pd.isna(works.loc["W3", "oa_status"])

    auth = tables["authorships"]
    assert len(auth) == 4  # W1: 1 author x 2 institutions; W2: 2 authors x 1 row
    no_inst = auth[(auth.work_id == "W2") & (auth.author_id == "A2")]
    assert len(no_inst) == 1 and no_inst.institution_id.isna().all() and no_inst.is_anchor.isna().all()
    anchors = dict(zip(auth.institution_id, auth.is_anchor))
    assert anchors["I77"] == True and anchors["I88"] == False and anchors["I4210166444"] == True  # noqa: E712
    assert auth.loc[auth.institution_id == "I77", "institution_lineage"].iloc[0] == ["I77", "I4210166444"]
    assert list(auth[auth.work_id == "W2"].author_position_idx) == [0, 1]

    assert list(tables["topics"]["rank"]) == [1, 2, 3]
    assert list(tables["topics"].topic_id) == ["T1", "T2", "T3"]
    assert len(tables["counts_by_year"]) == 2  # the zero year is dropped
    assert list(tables["sdgs"].sdg_id) == ["2"]
    funders = tables["funders"]
    assert list(zip(funders.work_id, funders.funder_id)) == [("W1", "F1"), ("W2", "F2"), ("W2", "F3")]
    assert list(funders.award_id[:2]) == ["ANR-1", "H2020"] and pd.isna(funders.award_id[2])


def test_is_anchor_null_without_root():
    auth = works_tables(WORKS)["authorships"]
    assert auth.is_anchor.isna().all()


def test_empty_input_keeps_columns():
    tables = works_tables([])
    assert all(frame.empty for frame in tables.values())
    assert "work_id" in tables["works"].columns


def test_works_tables_from_cached_pages_and_parquet(tmp_path):
    cache = tmp_path / "cache" / "ird"
    cache.mkdir(parents=True)
    with gzip.open(cache / "page-00001.json.gz", "wt") as fh:
        json.dump({"params": {}, "cursor": "*", "response": {"meta": {}, "results": WORKS[:2]}}, fh)
    with gzip.open(cache / "page-00002.json.gz", "wt") as fh:
        json.dump({"meta": {}, "results": WORKS[2:]}, fh)  # raw API page
    tables = works_tables(tmp_path / "cache", root_institution="I4210166444")
    assert len(tables["works"]) == 3
    write_parquet(tables, tmp_path / "out")
    back = pd.read_parquet(tmp_path / "out" / "authorships.parquet")
    assert len(back) == 4


def test_reconstruct_abstract_round_trip():
    text = "the cat saw the other cat"
    index = {}
    for position, word in enumerate(text.split()):
        index.setdefault(word, []).append(position)
    assert reconstruct_abstract(index) == text
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


@pytest.mark.parametrize("value,expected", [
    ("https://openalex.org/W123", "W123"), ("W123", "W123"), (None, None),
    ("https://openalex.org/subfields/1105", "1105"), ("https://metadata.un.org/sdg/14", "14"),
])
def test_short_id(value, expected):
    assert short_id(value) == expected
