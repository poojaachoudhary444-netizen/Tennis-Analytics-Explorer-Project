"""
Database layer: schema definition (SQLAlchemy ORM), engine factory and DDL export.

The schema follows the project brief exactly (table / column names, data types,
primary keys, foreign keys, NOT NULL rules) and works unchanged on MySQL,
PostgreSQL and SQLite.

Documented extensions beyond the brief (all additive, nothing removed):
  * competitor_rankings.ranking_type / year / week / gender - needed for the
    Year / Week / Gender filters shown in the sample UI, and so several weekly
    snapshots can be stored side by side.
  * UNIQUE(competitor_id, ranking_type, year, week, gender) - prevents duplicate
    ranking rows when the pipeline is re-run.
  * pipeline_runs - small audit table (where the data came from and when).
  * Indexes on every foreign key and common filter column (query performance).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable

import config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base class for all tables."""


# ---------------------------------------------------------------------------
# Competitions data
# ---------------------------------------------------------------------------
class Category(Base):
    __tablename__ = "categories"

    category_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)


class Competition(Base):
    __tablename__ = "competitions"

    competition_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    competition_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)
    category_id: Mapped[str] = mapped_column(String(50), ForeignKey("categories.category_id"))

    __table_args__ = (
        Index("idx_competitions_category", "category_id"),
        Index("idx_competitions_parent", "parent_id"),
        Index("idx_competitions_type", "type"),
        Index("idx_competitions_gender", "gender"),
    )


# ---------------------------------------------------------------------------
# Complexes & venues data
# ---------------------------------------------------------------------------
class Complex(Base):
    __tablename__ = "complexes"

    complex_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    complex_name: Mapped[str] = mapped_column(String(100), nullable=False)


class Venue(Base):
    __tablename__ = "venues"

    venue_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    venue_name: Mapped[str] = mapped_column(String(100), nullable=False)
    city_name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    complex_id: Mapped[str] = mapped_column(String(50), ForeignKey("complexes.complex_id"))

    __table_args__ = (
        Index("idx_venues_complex", "complex_id"),
        Index("idx_venues_country", "country_name"),
    )


# ---------------------------------------------------------------------------
# Doubles competitor rankings data
# ---------------------------------------------------------------------------
class Competitor(Base):
    __tablename__ = "competitors"

    competitor_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        Index("idx_competitors_country", "country"),
        Index("idx_competitors_name", "name"),
    )


class CompetitorRanking(Base):
    __tablename__ = "competitor_rankings"

    rank_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    movement: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    competitions_played: Mapped[int] = mapped_column(Integer, nullable=False)
    competitor_id: Mapped[str] = mapped_column(String(50), ForeignKey("competitors.competitor_id"))
    # --- documented extensions (see module docstring) ---
    ranking_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ATP / WTA
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        UniqueConstraint("competitor_id", "ranking_type", "year", "week", "gender", name="uq_ranking_snapshot"),
        Index("idx_rankings_competitor", "competitor_id"),
        Index("idx_rankings_snapshot", "year", "week", "gender"),
        Index("idx_rankings_rank", "rank"),
        Index("idx_rankings_points", "points"),
    )


# ---------------------------------------------------------------------------
# Audit table
# ---------------------------------------------------------------------------
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # api | json | demo
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------
def get_engine(url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine (SQLite foreign keys are switched on explicitly)."""
    url = url or config.DATABASE_URL
    engine = create_engine(url, pool_pre_ping=True, future=True)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_schema(engine: Engine) -> None:
    """Create all tables (no-op for tables that already exist)."""
    Base.metadata.create_all(engine)
    logger.info("Schema ready (%d tables).", len(Base.metadata.tables))


def drop_schema(engine: Engine) -> None:
    """Drop all tables - used by ``--reset``."""
    Base.metadata.drop_all(engine)
    logger.warning("All tables dropped.")


def export_ddl(dialect_name: str) -> str:
    """Return CREATE TABLE / CREATE INDEX statements for ``mysql`` or ``postgresql``."""
    dialects = {"mysql": mysql.dialect(), "postgresql": postgresql.dialect()}
    dialect = dialects[dialect_name]
    lines = [
        f"-- Tennis Analytics schema ({dialect_name})",
        "-- Generated from db.py - do not edit by hand; edit the models and re-run scripts/export_sql.py",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            lines.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        lines.append("")
    return "\n".join(lines)
