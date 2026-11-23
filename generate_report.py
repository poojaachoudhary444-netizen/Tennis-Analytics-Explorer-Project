"""
Generate the project documentation (Word) straight from the database.

The insights section is computed from whatever data is currently loaded, so
run this AFTER loading real data (``python run_pipeline.py --source api``):

    python scripts/generate_report.py                     # -> docs/Project_Report.docx
    python scripts/generate_report.py --author "Pooja"

If the database holds DEMO data the report says so prominently on the first
page, so fake numbers can never be mistaken for real ones.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Pt, RGBColor  # noqa: E402

from db import Base, get_engine  # noqa: E402
from queries import GROUPS, QUERIES, render_sql, run_query  # noqa: E402

LATEST = """r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings WHERE year = (SELECT MAX(year) FROM competitor_rankings))"""


# ---------------------------------------------------------------------------
# python-docx helpers
# ---------------------------------------------------------------------------
def shade(paragraph_or_cell, fill: str) -> None:
    element = paragraph_or_cell._p.get_or_add_pPr() if hasattr(paragraph_or_cell, "_p") else paragraph_or_cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    element.append(shading)


def code_block(doc: Document, sql: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(6)
    shade(paragraph, "F2F2F2")
    for i, line in enumerate(sql.splitlines()):
        run = paragraph.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        if i < len(sql.splitlines()) - 1:
            run.add_break()


def table_from_df(doc: Document, df: pd.DataFrame, max_rows: int = 5, font_size: float = 8.5) -> None:
    if df.empty:
        doc.add_paragraph("(no rows)").italic = True
        return
    shown = df.head(max_rows)
    table = doc.add_table(rows=1, cols=len(shown.columns))
    table.style = "Light Grid Accent 1"
    for i, column in enumerate(shown.columns):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(column))
        run.bold = True
        run.font.size = Pt(font_size)
    for _, row in shown.iterrows():
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run("" if pd.isna(value) else str(value))
            run.font.size = Pt(font_size)
    doc.add_paragraph()


def simple_table(doc: Document, header: list[str], rows: list[list[str]], font_size: float = 9) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Light Grid Accent 1"
    for i, title in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(title)
        run.bold = True
        run.font.size = Pt(font_size)
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(value)).font.size = Pt(font_size)
    doc.add_paragraph()


def bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


# ---------------------------------------------------------------------------
# Insight computation
# ---------------------------------------------------------------------------
def compute_insights(engine) -> list[str]:
    def one(sql: str) -> pd.DataFrame:
        return run_query(engine, sql)

    insights: list[str] = []
    top_countries = one("SELECT country, COUNT(*) AS n FROM competitors GROUP BY country ORDER BY n DESC, country LIMIT 3")
    total_competitors = int(one("SELECT COUNT(*) AS n FROM competitors").iloc[0, 0])
    if len(top_countries):
        listing = ", ".join(f"{r.country} ({r.n})" for r in top_countries.itertuples())
        share = top_countries["n"].sum() / total_competitors * 100
        insights.append(f"Player representation is concentrated: the three largest countries - {listing} - account for "
                        f"{share:.0f}% of the {total_competitors:,} ranked doubles competitors.")

    leaders = one(f"SELECT c.name, c.country, r.ranking_type, r.points FROM competitor_rankings r JOIN competitors c ON c.competitor_id = r.competitor_id "
                  f"WHERE {LATEST} AND r.points = (SELECT MAX(r2.points) FROM competitor_rankings r2 WHERE r2.ranking_type = r.ranking_type "
                  f"AND r2.year = r.year AND r2.week = r.week) ORDER BY r.points DESC")
    for r in leaders.itertuples():
        insights.append(f"In the latest {r.ranking_type} doubles ranking the points leader is {r.name} ({r.country}) with {int(r.points):,} points.")

    movement = one(f"SELECT SUM(CASE WHEN r.movement = 0 THEN 1 ELSE 0 END) AS stable, SUM(CASE WHEN r.movement > 0 THEN 1 ELSE 0 END) AS up, "
                   f"SUM(CASE WHEN r.movement < 0 THEN 1 ELSE 0 END) AS down, COUNT(*) AS total FROM competitor_rankings r WHERE {LATEST}").iloc[0]
    if movement["total"]:
        insights.append(f"Rankings are fairly sticky week to week: {movement['stable'] / movement['total'] * 100:.0f}% of competitors kept the same rank, "
                        f"{movement['up'] / movement['total'] * 100:.0f}% moved up and {movement['down'] / movement['total'] * 100:.0f}% moved down.")

    played = one(f"SELECT AVG(r.competitions_played) AS avg_played, MAX(r.competitions_played) AS max_played FROM competitor_rankings r WHERE {LATEST}").iloc[0]
    if played["avg_played"] == played["avg_played"]:
        insights.append(f"A ranked doubles player has played {played['avg_played']:.1f} competitions on average in the ranking window "
                        f"(maximum {int(played['max_played'])}).")

    cats = one("SELECT cat.category_name, COUNT(*) AS n FROM competitions c JOIN categories cat ON cat.category_id = c.category_id "
               "GROUP BY cat.category_name ORDER BY n DESC")
    total_comps = int(cats["n"].sum()) if len(cats) else 0
    if total_comps:
        top = cats.iloc[0]
        insights.append(f"Competition structure: '{top['category_name']}' is the largest category with {int(top['n']):,} of {total_comps:,} competitions "
                        f"({top['n'] / total_comps * 100:.0f}%).")

    types = one("SELECT type, COUNT(*) AS n FROM competitions GROUP BY type ORDER BY n DESC")
    if len(types):
        mix = ", ".join(f"{r.type} {r.n / types['n'].sum() * 100:.0f}%" for r in types.head(3).itertuples())
        insights.append(f"Event type mix (top three): {mix}.")

    gender = one("SELECT gender, COUNT(*) AS n FROM competitions GROUP BY gender ORDER BY n DESC")
    if len(gender) > 1:
        insights.append("Gender split of competitions: " + ", ".join(f"{r.gender} {r.n / gender['n'].sum() * 100:.0f}%" for r in gender.itertuples()) + ".")

    parents = one("SELECT COUNT(*) AS n FROM competitions WHERE parent_id IS NULL").iloc[0, 0]
    if total_comps:
        insights.append(f"{int(parents):,} of {total_comps:,} competitions ({parents / total_comps * 100:.0f}%) are top-level (no parent); "
                        "the rest are sub-competitions such as singles/doubles draws of a tournament.")

    venues = one("SELECT v.country_name, COUNT(*) AS n FROM venues v GROUP BY v.country_name ORDER BY n DESC, v.country_name LIMIT 3")
    multi = one("SELECT COUNT(*) AS n FROM (SELECT complex_id FROM venues GROUP BY complex_id HAVING COUNT(*) > 1) t").iloc[0, 0]
    total_cx = one("SELECT COUNT(*) AS n FROM complexes").iloc[0, 0]
    if len(venues):
        insights.append("Venue footprint: " + ", ".join(f"{r.country_name} ({r.n})" for r in venues.itertuples())
                        + f" host the most venues; {int(multi):,} of {int(total_cx):,} complexes contain more than one venue.")
    return insights


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_report(author: str, output: Path) -> Path:
    engine = get_engine()
    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Pt(64)
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)

    source = run_query(engine, "SELECT source, run_at FROM pipeline_runs ORDER BY run_id DESC LIMIT 1")
    source_name = str(source.iloc[0]["source"]) if len(source) else "unknown"
    run_at = str(source.iloc[0]["run_at"])[:16] if len(source) else "-"
    is_demo = source_name == "demo"

    # ---- title page
    for _ in range(5):
        doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Game Analytics:\nUnlocking Tennis Data with SportRadar API")
    run.bold, run.font.size = True, Pt(26)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run("Project Documentation - workflow, schema design, challenges and insights").font.size = Pt(13)
    doc.add_paragraph()
    by = doc.add_paragraph()
    by.alignment = WD_ALIGN_PARAGRAPH.CENTER
    by_run = by.add_run(f"Prepared by: {author}")
    by_run.bold, by_run.font.size = True, Pt(15)
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Data source: {source_name} · loaded {run_at} UTC · report generated {datetime.now():%Y-%m-%d}").font.size = Pt(10)
    if is_demo:
        warn = doc.add_paragraph()
        warn.alignment = WD_ALIGN_PARAGRAPH.CENTER
        shade(warn, "FDE9E7")
        w = warn.add_run("DATA NOTE - SportRadar API access (trial key sign-up) was not available when this project was prepared, "
                         "so the database was filled with SIMULATED sample data in the exact JSON structure of the real API responses. "
                         "All numbers in this document are therefore illustrative. The pipeline is complete: running "
                         "python run_pipeline.py --source api --reset with a valid key replaces it with real data, and this report regenerates automatically.")
        w.bold, w.font.color.rgb, w.font.size = True, RGBColor(0xB7, 0x1C, 0x1C), Pt(11)
    doc.add_page_break()

    # ---- 1 overview
    doc.add_heading("1. Project overview", 1)
    doc.add_paragraph(
        "This project builds an end-to-end analytics solution on tennis data from the SportRadar API: JSON is extracted with Python, "
        "flattened into a normalised relational schema, stored in SQL, analysed with 20 SQL queries, and explored interactively in a Streamlit app."
    )
    doc.add_heading("Business use cases", 2)
    bullets(doc, [
        "Event exploration - navigate competition hierarchies (e.g. ATP Vienna -> singles / doubles draws).",
        "Trend analysis - distribution of events by type, gender and competition level.",
        "Performance insights - doubles competitor participation, points and rank movement.",
        "Decision support - help organisers and sports bodies allocate resources using venue and event data.",
    ])

    # ---- 2 workflow
    doc.add_heading("2. Workflow", 1)
    simple_table(doc, ["Step", "What happens", "Code"], [
        ["1. Extract", "Call three SportRadar endpoints with throttling, retries and error handling; save raw JSON.", "api_client.py"],
        ["2. Transform", "Flatten nested JSON into rows; fill/flag missing values, remove duplicates, trim to column lengths, log statistics.", "etl.py (parse_*)"],
        ["3. Load", "Create the schema and upsert rows in one transaction per dataset (idempotent re-runs).", "db.py, etl.py (load_*)"],
        ["4. Validate", "Row counts and referential-integrity checks (no orphan rows).", "etl.validate_database"],
        ["5. Analyse", "20 parameterised SQL queries (competitions, venues, rankings).", "queries.py, sql/sql_queries.sql"],
        ["6. Present", "Interactive Streamlit dashboard with filters, search, pagination and a live SQL explorer.", "app.py"],
    ])
    doc.add_heading("Data collection endpoints", 2)
    simple_table(doc, ["Endpoint (Tennis API v3)", "Tables filled"], [
        ["/competitions.json", "categories, competitions"],
        ["/complexes.json", "complexes, venues"],
        ["/double_competitors_rankings.json", "competitors, competitor_rankings"],
    ])

    # ---- 3 schema
    doc.add_heading("3. Database schema design", 1)
    doc.add_paragraph("The schema is normalised: each fact is stored once and tables are linked by primary / foreign keys.")
    for table in Base.metadata.sorted_tables:
        if table.name == "pipeline_runs":
            continue
        doc.add_heading(table.name, 3)
        rows = []
        for column in table.columns:
            constraint = []
            if column.primary_key:
                constraint.append("PRIMARY KEY" + (" AUTO_INCREMENT" if column.autoincrement is True or (column.name == "rank_id") else ""))
            if not column.nullable and not column.primary_key:
                constraint.append("NOT NULL")
            for fk in column.foreign_keys:
                constraint.append(f"FOREIGN KEY -> {fk.column.table.name}({fk.column.name})")
            rows.append([column.name, str(column.type), ", ".join(constraint) or "NULLABLE"])
        simple_table(doc, ["Column", "Type", "Constraints"], rows)
        if table.indexes:
            doc.add_paragraph("Indexes: " + ", ".join(sorted(i.name for i in table.indexes)))
    doc.add_heading("Design decisions", 2)
    bullets(doc, [
        "Lower-case table names - MySQL on Linux is case-sensitive, so one convention avoids surprises.",
        "competitions.parent_id has no foreign key: the API can reference a parent that is not in the feed, and a hard FK would reject those rows.",
        "Extension columns on competitor_rankings (ranking_type, year, week, gender) support the Year / Week / Gender filters and let several weekly snapshots coexist; a UNIQUE constraint prevents duplicate snapshot rows.",
        "Indexes on every foreign key and common filter column (category, type, gender, country, rank, points) keep the dashboard queries fast.",
        "pipeline_runs records where the data came from and when (used by the app to flag demo data).",
    ])

    # ---- 4 insights
    doc.add_heading("4. Insights from the data", 1)
    if is_demo:
        p = doc.add_paragraph()
        r = p.add_run("These insights are computed from simulated sample data and are illustrative only.")
        r.bold, r.font.color.rgb = True, RGBColor(0xB7, 0x1C, 0x1C)
    bullets(doc, compute_insights(engine))

    doc.add_heading("Data quality & extraction accuracy", 2)
    counts = {t.name: int(run_query(engine, f"SELECT COUNT(*) AS n FROM {t.name}").iloc[0, 0]) for t in Base.metadata.sorted_tables if t.name != "pipeline_runs"}
    simple_table(doc, ["Table", "Rows loaded"], [[k, f"{v:,}"] for k, v in counts.items()])
    orphans = run_query(engine, "SELECT (SELECT COUNT(*) FROM competitions c LEFT JOIN categories k ON k.category_id = c.category_id WHERE k.category_id IS NULL) AS competitions_without_category, "
                                "(SELECT COUNT(*) FROM venues v LEFT JOIN complexes x ON x.complex_id = v.complex_id WHERE x.complex_id IS NULL) AS venues_without_complex, "
                                "(SELECT COUNT(*) FROM competitor_rankings r LEFT JOIN competitors c ON c.competitor_id = r.competitor_id WHERE c.competitor_id IS NULL) AS rankings_without_competitor")
    doc.add_paragraph("Referential-integrity check (all should be 0): " + ", ".join(f"{k} = {int(v)}" for k, v in orphans.iloc[0].items()))

    # ---- 5 app
    doc.add_heading("5. Streamlit application", 1)
    simple_table(doc, ["Page", "What it offers"], [
        ["Homepage dashboard", "Total competitors, countries represented, highest points; charts by country, category, type and rank movement."],
        ["Search & filter competitors", "Name search; filters for year, week, gender, rank range, country and minimum points; server-side pagination; CSV export."],
        ["Competitor details", "Rank, movement, points, competitions played, country; ranking history and compatriots."],
        ["Country-wise analysis", "Competitors, average and total points per country with drill-down."],
        ["Leaderboards", "Top-ranked and highest-points tables per tour."],
        ["Competitions explorer", "Filter by category/type/gender, parent -> sub-competition hierarchy, distribution charts."],
        ["Venues & complexes", "Venues by country / complex, complexes with several venues, timezone chart."],
        ["SQL query explorer", "All 20 brief queries run live with safely bound parameters and CSV download."],
    ])
    doc.add_paragraph("Performance: results are cached for 5 minutes and tables are paginated in SQL (LIMIT/OFFSET) so only one page of rows is fetched at a time.")

    # ---- 6 challenges
    doc.add_heading("6. Challenges and how they were handled", 1)
    simple_table(doc, ["Challenge", "Solution"], [
        ["Nested JSON (complexes contain venues, rankings contain competitors)", "Dedicated parse_* functions flatten each level into its own table and de-duplicate by ID."],
        ["API rate limits (trial key: 1 request/second)", "Client-side throttling, retries with exponential back-off, Retry-After support; only 3 calls are needed."],
        ["Missing values vs NOT NULL columns", "Explicit, counted defaults ('Unknown', 'UNK', 0) and skipped rows are logged in a parse summary, so nothing is silently lost."],
        ["'rank' is a reserved word in MySQL 8", "Every query uses a table-qualified r.rank and aliases the output as competitor_rank; a unit test enforces this."],
        ["Re-running the pipeline created duplicates", "Upserts (merge) for dimensions; ranking snapshots are replaced; UNIQUE constraint on the snapshot key."],
        ["ATP and WTA points are not comparable", "Queries and charts split by tour / gender; the app warns when mixing them."],
        ["Large tables in the UI", "Server-side pagination, caching and SQL aggregation instead of loading everything into pandas."],
        ["Keeping the API key secret", "Key read from environment / .env (git-ignored) and sent in a header, never in the URL or logs."],
        ["User input in filters", "All filter values are bound parameters - no string concatenation, no SQL injection."],
    ])

    # ---- appendix
    doc.add_page_break()
    doc.add_heading("Appendix - SQL queries and sample output", 1)
    doc.add_paragraph("The same queries are in sql/sql_queries.sql (the document required for GitHub). Sample output shows the first rows.")
    for group in GROUPS:
        doc.add_heading({"Competitions": "A. Competitions", "Venues": "B. Complexes & venues", "Rankings": "C. Doubles competitor rankings"}[group], 2)
        for query in (q for q in QUERIES if q.group == group):
            doc.add_heading(f"{query.qid}. {query.title}", 3)
            code_block(doc, render_sql(query))
            df = run_query(engine, query.sql, query.params)
            doc.add_paragraph(f"Rows returned: {len(df):,} (showing {min(3, len(df))})")
            table_from_df(doc, df.iloc[:, :6], max_rows=3)

    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"Prepared by: {author}").font.size = Pt(9)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--author", default="Pooja")
    parser.add_argument("--output", default=str(ROOT / "docs" / "Project_Report.docx"))
    args = parser.parse_args()
    print("Report written to", build_report(args.author, Path(args.output)))
