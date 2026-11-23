"""
All SQL queries required by the project brief (7 + 7 + 6 = 20).

Each query is plain, portable SQL (works on MySQL, PostgreSQL and SQLite) and
uses named bind parameters (``:country`` ...) so user input is never pasted
into the SQL text (no SQL injection).

Note on the ``rank`` column: RANK is a reserved word in MySQL 8, so every
query refers to it with a table alias (``r.rank``), which MySQL always accepts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

# "Current week" = the most recent (year, week) snapshot stored in the database.
LATEST_SNAPSHOT = """r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings
                WHERE year = (SELECT MAX(year) FROM competitor_rankings))"""


@dataclass(frozen=True)
class Query:
    qid: str
    group: str
    title: str
    sql: str
    explanation: str
    params: dict = field(default_factory=dict)  # default values for the :named parameters


QUERIES: list[Query] = [
    # ------------------------------------------------------------------ Competitions
    Query(
        "C1", "Competitions", "List all competitions along with their category name",
        """SELECT c.competition_id, c.competition_name, c.type, c.gender, cat.category_name
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
ORDER BY cat.category_name, c.competition_name""",
        "INNER JOIN of competitions to categories through the category_id foreign key.",
    ),
    Query(
        "C2", "Competitions", "Count the number of competitions in each category",
        """SELECT cat.category_name, COUNT(c.competition_id) AS competition_count
FROM categories cat
LEFT JOIN competitions c ON c.category_id = cat.category_id
GROUP BY cat.category_id, cat.category_name
ORDER BY competition_count DESC""",
        "LEFT JOIN + GROUP BY so categories with zero competitions would still appear.",
    ),
    Query(
        "C3", "Competitions", "Find all competitions of type 'doubles'",
        """SELECT c.competition_id, c.competition_name, c.gender, cat.category_name
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
WHERE c.type = 'doubles'
ORDER BY cat.category_name, c.competition_name""",
        "Simple filter on the type column (served by idx_competitions_type).",
    ),
    Query(
        "C4", "Competitions", "Get competitions that belong to a specific category (e.g. ITF Men)",
        """SELECT c.competition_id, c.competition_name, c.type, c.gender
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
WHERE cat.category_name = :category_name
ORDER BY c.competition_name""",
        "Parameterised: change :category_name to any category (ATP, WTA, Challenger, ITF Women ...).",
        {"category_name": "ITF Men"},
    ),
    Query(
        "C5", "Competitions", "Identify parent competitions and their sub-competitions",
        """SELECT p.competition_id   AS parent_competition_id,
       p.competition_name AS parent_competition,
       ch.competition_id   AS sub_competition_id,
       ch.competition_name AS sub_competition,
       ch.type             AS sub_competition_type
FROM competitions p
JOIN competitions ch ON ch.parent_id = p.competition_id
ORDER BY p.competition_name, ch.competition_name""",
        "Self-join: the child's parent_id points at the parent's competition_id (e.g. ATP Vienna -> Singles / Doubles).",
    ),
    Query(
        "C6", "Competitions", "Analyze the distribution of competition types by category",
        """SELECT cat.category_name, c.type, COUNT(*) AS competition_count
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
GROUP BY cat.category_name, c.type
ORDER BY cat.category_name, competition_count DESC""",
        "Two-column GROUP BY gives a category x type cross-tab in long format.",
    ),
    Query(
        "C7", "Competitions", "List all competitions with no parent (top-level competitions)",
        """SELECT c.competition_id, c.competition_name, c.type, c.gender, cat.category_name
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
WHERE c.parent_id IS NULL
ORDER BY cat.category_name, c.competition_name""",
        "IS NULL (not = NULL) is required to test for a missing parent.",
    ),
    # ------------------------------------------------------------------ Venues
    Query(
        "V1", "Venues", "List all venues along with their associated complex name",
        """SELECT v.venue_id, v.venue_name, v.city_name, v.country_name, cx.complex_name
FROM venues v
JOIN complexes cx ON cx.complex_id = v.complex_id
ORDER BY cx.complex_name, v.venue_name""",
        "INNER JOIN of venues to complexes through complex_id.",
    ),
    Query(
        "V2", "Venues", "Count the number of venues in each complex",
        """SELECT cx.complex_name, COUNT(v.venue_id) AS venue_count
FROM complexes cx
LEFT JOIN venues v ON v.complex_id = cx.complex_id
GROUP BY cx.complex_id, cx.complex_name
ORDER BY venue_count DESC, cx.complex_name""",
        "GROUP BY complex with COUNT of its venues.",
    ),
    Query(
        "V3", "Venues", "Get details of venues in a specific country (e.g. Chile)",
        """SELECT v.venue_id, v.venue_name, v.city_name, v.country_name, v.country_code, v.timezone
FROM venues v
WHERE v.country_name = :country_name
ORDER BY v.city_name, v.venue_name""",
        "Parameterised on :country_name (served by idx_venues_country).",
        {"country_name": "Chile"},
    ),
    Query(
        "V4", "Venues", "Identify all venues and their timezones",
        """SELECT v.venue_name, v.city_name, v.country_name, v.timezone
FROM venues v
ORDER BY v.timezone, v.country_name, v.venue_name""",
        "Ordered by timezone so venues in the same zone sit together.",
    ),
    Query(
        "V5", "Venues", "Find complexes that have more than one venue",
        """SELECT cx.complex_name, COUNT(v.venue_id) AS venue_count
FROM complexes cx
JOIN venues v ON v.complex_id = cx.complex_id
GROUP BY cx.complex_id, cx.complex_name
HAVING COUNT(v.venue_id) > 1
ORDER BY venue_count DESC, cx.complex_name""",
        "HAVING filters on the aggregate (WHERE cannot, because it runs before grouping).",
    ),
    Query(
        "V6", "Venues", "List venues grouped by country",
        """SELECT v.country_name,
       COUNT(*) OVER (PARTITION BY v.country_name) AS venues_in_country,
       v.city_name, v.venue_name
FROM venues v
ORDER BY v.country_name, v.city_name, v.venue_name""",
        "A window function counts the venues per country while still listing every venue, grouped by country.",
    ),
    Query(
        "V7", "Venues", "Find all venues for a specific complex (e.g. Nacional)",
        """SELECT cx.complex_name, v.venue_name, v.city_name, v.country_name, v.timezone
FROM venues v
JOIN complexes cx ON cx.complex_id = v.complex_id
WHERE cx.complex_name = :complex_name
ORDER BY v.venue_name""",
        "Parameterised on :complex_name.",
        {"complex_name": "Nacional"},
    ),
    # ------------------------------------------------------------------ Rankings
    Query(
        "R1", "Rankings", "Get all competitors with their rank and points",
        """SELECT c.name, c.country, r.ranking_type, r.gender, r.year, r.week,
       r.rank AS competitor_rank, r.points, r.movement, r.competitions_played
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
ORDER BY r.ranking_type, r.year DESC, r.week DESC, r.rank""",
        "Join rankings to competitor details; every stored weekly snapshot is returned.",
    ),
    Query(
        "R2", "Rankings", "Find competitors ranked in the top 5",
        f"""SELECT c.name, c.country, r.ranking_type, r.rank AS competitor_rank, r.points
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE r.rank <= 5
  AND {LATEST_SNAPSHOT}
ORDER BY r.ranking_type, r.rank, c.name""",
        "Top 5 of the current (latest) week for each tour. Ties share a rank, so more than 5 rows can appear.",
    ),
    Query(
        "R3", "Rankings", "List competitors with no rank movement (stable rank)",
        f"""SELECT c.name, c.country, r.ranking_type, r.rank AS competitor_rank, r.points, r.movement
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE r.movement = 0
  AND {LATEST_SNAPSHOT}
ORDER BY r.ranking_type, r.rank""",
        "movement = 0 means the same rank as the previous week.",
    ),
    Query(
        "R4", "Rankings", "Get the total points of competitors from a specific country (e.g. Croatia)",
        f"""SELECT c.country, r.ranking_type,
       COUNT(*)        AS ranked_competitors,
       SUM(r.points)   AS total_points
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE c.country = :country
  AND {LATEST_SNAPSHOT}
GROUP BY c.country, r.ranking_type
ORDER BY total_points DESC""",
        "Parameterised on :country; totals are split by tour (ATP / WTA) because their points are not comparable.",
        {"country": "Croatia"},
    ),
    Query(
        "R5", "Rankings", "Count the number of competitors per country",
        """SELECT c.country, c.country_code, COUNT(*) AS competitor_count
FROM competitors c
GROUP BY c.country, c.country_code
ORDER BY competitor_count DESC, c.country""",
        "GROUP BY country over the competitors dimension table.",
    ),
    Query(
        "R6", "Rankings", "Find competitors with the highest points in the current week",
        f"""SELECT c.name, c.country, r.ranking_type, r.gender, r.rank AS competitor_rank, r.points
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE {LATEST_SNAPSHOT}
  AND r.points = (SELECT MAX(r2.points)
                  FROM competitor_rankings r2
                  WHERE r2.ranking_type = r.ranking_type
                    AND r2.year = r.year AND r2.week = r.week)
ORDER BY r.points DESC""",
        "Correlated sub-query returns the top points scorer of each tour in the latest week (ties included).",
    ),
]

QUERY_BY_ID = {q.qid: q for q in QUERIES}
GROUPS = ["Competitions", "Venues", "Rankings"]


def run_query(engine: Engine, sql: str, params: dict | None = None) -> pd.DataFrame:
    """Execute a (read-only) SELECT with bound parameters and return a DataFrame."""
    with engine.connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})


def render_sql(query: Query, params: dict | None = None) -> str:
    """Return the SQL with parameters substituted as literals (for documentation only)."""
    sql = query.sql
    for name, value in {**query.params, **(params or {})}.items():
        literal = "'" + str(value).replace("'", "''") + "'"
        sql = sql.replace(f":{name}", literal)
    return sql
