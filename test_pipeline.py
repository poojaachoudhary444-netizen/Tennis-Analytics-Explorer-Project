"""Run with:  python -m pytest -q   (from the project root)"""

import re

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import etl
from db import Competitor, CompetitorRanking, create_schema, get_engine
from demo_data import generate_demo_payloads
from queries import QUERIES, run_query


@pytest.fixture(scope="module")
def payloads():
    return generate_demo_payloads()


@pytest.fixture()
def engine(tmp_path, payloads):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_schema(engine)
    cats, comps, _ = etl.parse_competitions(payloads["competitions"])
    etl.load_competition_data(engine, cats, comps)
    cxs, venues, _ = etl.parse_complexes(payloads["complexes"])
    etl.load_venue_data(engine, cxs, venues)
    people, ranks, _ = etl.parse_doubles_rankings(payloads["doubles_rankings"])
    etl.load_ranking_data(engine, people, ranks)
    return engine


# ------------------------------------------------------------------ parsers
def test_competitions_parser_skips_bad_rows_and_defaults_missing_fields():
    payload = {"competitions": [
        {"id": "a", "name": "Good", "type": "singles", "gender": "men", "category": {"id": "c1", "name": "ATP"}},
        {"id": "b", "name": "No category"},                                         # skipped
        {"id": "c", "name": "No gender/type", "category": {"id": "c1", "name": "ATP"}},  # defaults
        {"id": "a", "name": "Duplicate", "type": "singles", "gender": "men", "category": {"id": "c1", "name": "ATP"}},
        {"id": "d", "name": "X" * 150, "type": "doubles", "gender": "women", "category": {"id": "c2", "name": "WTA"}},
    ]}
    cats, comps, stats = etl.parse_competitions(payload)
    assert stats.received == 5 and stats.kept == 3 and stats.skipped == 1 and stats.duplicates == 1
    assert {c["category_id"] for c in cats} == {"c1", "c2"}
    row = next(c for c in comps if c["competition_id"] == "c")
    assert row["type"] == "unknown" and row["gender"] == "unknown" and row["parent_id"] is None
    assert len(next(c for c in comps if c["competition_id"] == "d")["competition_name"]) == 100
    assert stats.truncated == 1


def test_complexes_parser_fills_not_null_columns():
    payload = {"complexes": [{"id": "x", "name": "Nacional", "venues": [{"id": "v1", "name": "Court 1", "country_name": "Chile"}]}]}
    _, venues, stats = etl.parse_complexes(payload)
    assert venues[0]["country_code"] == "UNK" and venues[0]["timezone"] == "Unknown" and venues[0]["city_name"] == "Unknown"
    assert stats.defaulted["timezone"] == 1


def test_rankings_parser_handles_missing_movement_and_duplicates():
    entry = {"rank": 1, "points": 100, "competitor": {"id": "p1", "name": "Doe, Jane", "country": "Spain", "country_code": "esp"}}
    payload = {"rankings": [{"name": "WTA", "year": 2026, "week": 5, "gender": "women", "competitor_rankings": [entry, dict(entry)]}]}
    people, ranks, stats = etl.parse_doubles_rankings(payload)
    assert len(ranks) == 1 and stats.duplicates == 1
    assert ranks[0]["movement"] == 0 and ranks[0]["competitions_played"] == 0
    assert people[0]["country_code"] == "ESP" and people[0]["abbreviation"] == "DOE"


# ------------------------------------------------------------------ database
def test_loaded_data_is_consistent(engine):
    result = etl.validate_database(engine)
    assert result["issues"] == []
    assert all(count > 0 for count in result["counts"].values())


def test_pipeline_is_idempotent(engine, payloads):
    with Session(engine) as s:
        before = (s.scalar(select(func.count()).select_from(CompetitorRanking)), s.scalar(select(func.count()).select_from(Competitor)))
    people, ranks, _ = etl.parse_doubles_rankings(payloads["doubles_rankings"])
    etl.load_ranking_data(engine, people, ranks)  # load the same snapshot again
    with Session(engine) as s:
        after = (s.scalar(select(func.count()).select_from(CompetitorRanking)), s.scalar(select(func.count()).select_from(Competitor)))
    assert before == after


# ------------------------------------------------------------------ queries
@pytest.mark.parametrize("query", QUERIES, ids=[q.qid for q in QUERIES])
def test_every_query_runs_and_returns_rows(engine, query):
    df = run_query(engine, query.sql, query.params)
    assert len(df) > 0, f"{query.qid} returned no rows on demo data"


def test_there_are_twenty_queries():
    assert len(QUERIES) == 20


def test_rank_column_is_always_qualified_in_queries():
    """`rank` is reserved in MySQL 8 - it must only appear as r.rank / alias.rank."""
    for query in QUERIES:
        for match in re.finditer(r"(?<![\w.])rank(?!\w)", query.sql):
            pytest.fail(f"{query.qid}: unqualified 'rank' at position {match.start()}")
