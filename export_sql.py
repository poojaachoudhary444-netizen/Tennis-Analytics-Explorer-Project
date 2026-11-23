"""
Generate the SQL deliverables from the single source of truth (db.py + queries.py):

    sql/schema_mysql.sql        CREATE TABLE / INDEX statements for MySQL
    sql/schema_postgresql.sql   same for PostgreSQL
    sql/sql_queries.sql         all 20 analysis queries with comments (the "SQL queries document")

Run from the project root:   python scripts/export_sql.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import export_ddl  # noqa: E402
from queries import GROUPS, QUERIES, render_sql  # noqa: E402

SQL_DIR = ROOT / "sql"
SQL_DIR.mkdir(exist_ok=True)

for dialect in ("mysql", "postgresql"):
    (SQL_DIR / f"schema_{dialect}.sql").write_text(export_ddl(dialect), encoding="utf-8")

lines = [
    "-- =====================================================================",
    "-- Game Analytics: Unlocking Tennis Data with SportRadar API",
    "-- SQL analysis queries (20) - works on MySQL, PostgreSQL and SQLite",
    "-- Tables: categories, competitions, complexes, venues, competitors, competitor_rankings",
    "-- Note: 'rank' is a reserved word in MySQL 8, so it is always written r.rank",
    "-- =====================================================================",
    "",
]
titles = {"Competitions": "1) COMPETITIONS DATA", "Venues": "2) COMPLEXES & VENUES DATA", "Rankings": "3) DOUBLES COMPETITOR RANKINGS DATA"}
for group in GROUPS:
    lines += ["", "-- ---------------------------------------------------------------------", f"-- {titles[group]}", "-- ---------------------------------------------------------------------", ""]
    for query in (q for q in QUERIES if q.group == group):
        lines.append(f"-- {query.qid}. {query.title}")
        lines.append(f"-- {query.explanation}")
        lines.append(render_sql(query).rstrip() + ";")
        lines.append("")
(SQL_DIR / "sql_queries.sql").write_text("\n".join(lines), encoding="utf-8")
print("Wrote:", ", ".join(p.name for p in sorted(SQL_DIR.glob("*.sql"))))
