"""
ETL: transform nested SportRadar JSON into flat relational rows and load them.

Every ``parse_*`` function is pure (no network, no database) so it is easy to
unit-test. Each returns the cleaned rows together with a :class:`ParseStats`
object that records how many records were received, kept, skipped, or had a
missing value replaced by a default - this is the audit trail behind the
"data extraction accuracy" requirement.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from db import (
    Category,
    Competition,
    Competitor,
    CompetitorRanking,
    Complex,
    PipelineRun,
    Venue,
)

logger = logging.getLogger(__name__)

UNKNOWN_TEXT = "Unknown"
UNKNOWN_CODE = "UNK"


@dataclass
class ParseStats:
    """Audit information for one parsed dataset."""

    name: str
    received: int = 0
    kept: int = 0
    skipped: int = 0
    duplicates: int = 0
    defaulted: Counter = field(default_factory=Counter)  # column -> times a default was used
    truncated: int = 0

    def summary(self) -> str:
        defaults = ", ".join(f"{k}={v}" for k, v in self.defaulted.items()) or "none"
        return (
            f"{self.name}: received={self.received} kept={self.kept} skipped={self.skipped} "
            f"duplicates={self.duplicates} truncated={self.truncated} defaults used: {defaults}"
        )


def _clip(value: str, length: int, stats: ParseStats) -> str:
    """Trim a string to the VARCHAR length defined in the schema."""
    value = str(value).strip()
    if len(value) > length:
        stats.truncated += 1
        return value[:length]
    return value


def _code(value: Any) -> str | None:
    """Normalise an ISO-style country code to exactly 3 upper-case letters (or None)."""
    if not value:
        return None
    return str(value).strip().upper()[:3] or None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1) Competitions  ->  categories + competitions
# ---------------------------------------------------------------------------
def parse_competitions(payload: dict[str, Any]) -> tuple[list[dict], list[dict], ParseStats]:
    stats = ParseStats("competitions")
    categories: dict[str, dict] = {}
    competitions: dict[str, dict] = {}

    for item in payload.get("competitions", []) or []:
        stats.received += 1
        competition_id = item.get("id")
        name = item.get("name")
        category = item.get("category") or {}
        category_id, category_name = category.get("id"), category.get("name")

        if not (competition_id and name and category_id and category_name):
            stats.skipped += 1
            logger.debug("Skipping competition with missing key fields: %s", item)
            continue
        if competition_id in competitions:
            stats.duplicates += 1
            continue

        competition_type = item.get("type")
        gender = item.get("gender")
        if not competition_type:
            stats.defaulted["type"] += 1
            competition_type = "unknown"
        if not gender:
            stats.defaulted["gender"] += 1
            gender = "unknown"

        categories.setdefault(
            category_id, {"category_id": category_id, "category_name": _clip(category_name, 100, stats)}
        )
        competitions[competition_id] = {
            "competition_id": competition_id,
            "competition_name": _clip(name, 100, stats),
            "parent_id": item.get("parent_id") or None,
            "type": _clip(competition_type, 20, stats),
            "gender": _clip(gender, 10, stats),
            "category_id": category_id,
        }
        stats.kept += 1

    return list(categories.values()), list(competitions.values()), stats


# ---------------------------------------------------------------------------
# 2) Complexes  ->  complexes + venues
# ---------------------------------------------------------------------------
def parse_complexes(payload: dict[str, Any]) -> tuple[list[dict], list[dict], ParseStats]:
    stats = ParseStats("complexes/venues")
    complexes: dict[str, dict] = {}
    venues: dict[str, dict] = {}

    for item in payload.get("complexes", []) or []:
        stats.received += 1
        complex_id, complex_name = item.get("id"), item.get("name")
        if not (complex_id and complex_name):
            stats.skipped += 1
            continue
        if complex_id in complexes:
            stats.duplicates += 1
            continue
        complexes[complex_id] = {"complex_id": complex_id, "complex_name": _clip(complex_name, 100, stats)}

        for venue in item.get("venues", []) or []:
            venue_id, venue_name = venue.get("id"), venue.get("name")
            if not (venue_id and venue_name):
                stats.skipped += 1
                continue
            if venue_id in venues:
                stats.duplicates += 1
                continue

            row = {
                "venue_id": venue_id,
                "venue_name": _clip(venue_name, 100, stats),
                "city_name": venue.get("city_name"),
                "country_name": venue.get("country_name"),
                "country_code": _code(venue.get("country_code")),
                "timezone": venue.get("timezone"),
                "complex_id": complex_id,
            }
            # NOT NULL columns - replace a missing value with an explicit placeholder
            for column, placeholder in (
                ("city_name", UNKNOWN_TEXT),
                ("country_name", UNKNOWN_TEXT),
                ("country_code", UNKNOWN_CODE),
                ("timezone", UNKNOWN_TEXT),
            ):
                if not row[column]:
                    stats.defaulted[column] += 1
                    row[column] = placeholder
            row["city_name"] = _clip(row["city_name"], 100, stats)
            row["country_name"] = _clip(row["country_name"], 100, stats)
            row["timezone"] = _clip(row["timezone"], 100, stats)
            venues[venue_id] = row
            stats.kept += 1

    return list(complexes.values()), list(venues.values()), stats


# ---------------------------------------------------------------------------
# 3) Doubles rankings  ->  competitors + competitor_rankings
# ---------------------------------------------------------------------------
def parse_doubles_rankings(payload: dict[str, Any]) -> tuple[list[dict], list[dict], ParseStats]:
    stats = ParseStats("doubles rankings")
    competitors: dict[str, dict] = {}
    rankings: list[dict] = []
    seen_snapshot_rows: set[tuple] = set()

    for ranking in payload.get("rankings", []) or []:
        ranking_type = _clip(ranking.get("name") or UNKNOWN_TEXT, 20, stats)
        year, week = _to_int(ranking.get("year")), _to_int(ranking.get("week"))
        gender = _clip(ranking.get("gender") or "unknown", 10, stats)
        if year is None or week is None:
            logger.warning("Ranking list '%s' has no year/week - skipped.", ranking_type)
            stats.skipped += len(ranking.get("competitor_rankings", []) or [])
            continue

        for entry in ranking.get("competitor_rankings", []) or []:
            stats.received += 1
            competitor = entry.get("competitor") or {}
            competitor_id, name = competitor.get("id"), competitor.get("name")
            rank, points = _to_int(entry.get("rank")), _to_int(entry.get("points"))

            if not (competitor_id and name) or rank is None or points is None:
                stats.skipped += 1
                continue

            snapshot_key = (competitor_id, ranking_type, year, week, gender)
            if snapshot_key in seen_snapshot_rows:
                stats.duplicates += 1
                continue
            seen_snapshot_rows.add(snapshot_key)

            movement = _to_int(entry.get("movement"))
            if movement is None:
                stats.defaulted["movement"] += 1
                movement = 0
            played = _to_int(entry.get("competitions_played"))
            if played is None:
                stats.defaulted["competitions_played"] += 1
                played = 0

            if competitor_id not in competitors:
                country = competitor.get("country")
                code = _code(competitor.get("country_code"))
                abbreviation = competitor.get("abbreviation")
                if not country:
                    stats.defaulted["country"] += 1
                    country = UNKNOWN_TEXT
                if not code:
                    stats.defaulted["country_code"] += 1
                    code = UNKNOWN_CODE
                if not abbreviation:
                    stats.defaulted["abbreviation"] += 1
                    abbreviation = "".join(ch for ch in name if ch.isalpha())[:3].upper() or "UNK"
                competitors[competitor_id] = {
                    "competitor_id": competitor_id,
                    "name": _clip(name, 100, stats),
                    "country": _clip(country, 100, stats),
                    "country_code": code,
                    "abbreviation": _clip(abbreviation, 10, stats),
                }

            rankings.append(
                {
                    "rank": rank,
                    "movement": movement,
                    "points": points,
                    "competitions_played": played,
                    "competitor_id": competitor_id,
                    "ranking_type": ranking_type,
                    "year": year,
                    "week": week,
                    "gender": gender,
                }
            )
            stats.kept += 1

    return list(competitors.values()), rankings, stats


# ---------------------------------------------------------------------------
# Raw JSON helpers (so the pipeline can be re-run offline)
# ---------------------------------------------------------------------------
def save_raw(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved raw JSON -> %s", path)


def load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Raw data file not found: {path}. Run the pipeline with --source api first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_competition_data(engine: Engine, categories: list[dict], competitions: list[dict]) -> None:
    with Session(engine) as session, session.begin():
        for row in categories:
            session.merge(Category(**row))
        session.flush()
        for row in competitions:
            session.merge(Competition(**row))
    logger.info("Loaded %d categories and %d competitions.", len(categories), len(competitions))


def load_venue_data(engine: Engine, complexes: list[dict], venues: list[dict]) -> None:
    with Session(engine) as session, session.begin():
        for row in complexes:
            session.merge(Complex(**row))
        session.flush()
        for row in venues:
            session.merge(Venue(**row))
    logger.info("Loaded %d complexes and %d venues.", len(complexes), len(venues))


def load_ranking_data(engine: Engine, competitors: list[dict], rankings: list[dict]) -> None:
    """Upsert competitors and replace any ranking snapshot that is being re-loaded."""
    snapshots = {(r["ranking_type"], r["year"], r["week"], r["gender"]) for r in rankings}
    with Session(engine) as session, session.begin():
        for row in competitors:
            session.merge(Competitor(**row))
        session.flush()
        for ranking_type, year, week, gender in snapshots:  # idempotent re-runs
            session.execute(
                delete(CompetitorRanking).where(
                    CompetitorRanking.ranking_type == ranking_type,
                    CompetitorRanking.year == year,
                    CompetitorRanking.week == week,
                    CompetitorRanking.gender == gender,
                )
            )
        session.flush()
        session.add_all(CompetitorRanking(**row) for row in rankings)
    logger.info("Loaded %d competitors and %d ranking rows.", len(competitors), len(rankings))


def record_pipeline_run(engine: Engine, source: str, notes: str = "") -> None:
    with Session(engine) as session, session.begin():
        session.add(PipelineRun(source=source, run_at=datetime.utcnow(), notes=notes[:500]))


# ---------------------------------------------------------------------------
# Validation  (data extraction accuracy)
# ---------------------------------------------------------------------------
def validate_database(engine: Engine) -> dict[str, Any]:
    """Row counts plus referential-integrity checks. Returns a dict of results."""
    results: dict[str, Any] = {"counts": {}, "issues": []}
    with Session(engine) as session:
        for model in (Category, Competition, Complex, Venue, Competitor, CompetitorRanking):
            results["counts"][model.__tablename__] = session.scalar(select(func.count()).select_from(model))

        orphan_competitions = session.scalar(
            select(func.count())
            .select_from(Competition)
            .outerjoin(Category, Competition.category_id == Category.category_id)
            .where(Category.category_id.is_(None))
        )
        orphan_venues = session.scalar(
            select(func.count())
            .select_from(Venue)
            .outerjoin(Complex, Venue.complex_id == Complex.complex_id)
            .where(Complex.complex_id.is_(None))
        )
        orphan_rankings = session.scalar(
            select(func.count())
            .select_from(CompetitorRanking)
            .outerjoin(Competitor, CompetitorRanking.competitor_id == Competitor.competitor_id)
            .where(Competitor.competitor_id.is_(None))
        )
        for label, value in (
            ("competitions without a category", orphan_competitions),
            ("venues without a complex", orphan_venues),
            ("rankings without a competitor", orphan_rankings),
        ):
            if value:
                results["issues"].append(f"{value} {label}")
    return results
