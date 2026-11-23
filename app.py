"""
Tennis Analytics Explorer - Streamlit app
=========================================
Interactive dashboards on top of the SQL database filled from the SportRadar
Tennis API (competitions, complexes/venues, doubles rankings).

Run:  streamlit run app.py
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text

import config
from db import get_engine
from queries import GROUPS, QUERIES, QUERY_BY_ID, render_sql, run_query

st.set_page_config(page_title="Tennis Analytics Explorer", page_icon="🎾", layout="wide")

PAGE_SIZES = [10, 25, 50, 100]
LATEST = """r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings WHERE year = (SELECT MAX(year) FROM competitor_rankings))"""


# ---------------------------------------------------------------------------
# Small compatibility / UI helpers
# ---------------------------------------------------------------------------
def show_df(df: pd.DataFrame, **kwargs) -> None:
    """st.dataframe that works on old and new Streamlit versions."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except Exception:  # older Streamlit
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def show_chart(chart: alt.Chart) -> None:
    try:
        st.altair_chart(chart, width="stretch")
    except Exception:  # older Streamlit
        st.altair_chart(chart, use_container_width=True)


def hbar(df: pd.DataFrame, label: str, value: str, title: str = "", color: str = "#2e7d32", height: int | None = None):
    """Horizontal bar chart, sorted by value."""
    return (
        alt.Chart(df)
        .mark_bar(color=color, cornerRadiusEnd=3)
        .encode(
            x=alt.X(f"{value}:Q", title=None),
            y=alt.Y(f"{label}:N", sort="-x", title=None),
            tooltip=[label, value],
        )
        .properties(title=title, height=height or max(180, 26 * len(df)))
    )


def vbar(df: pd.DataFrame, label: str, value: str, title: str = "", color: str = "#2e7d32"):
    return (
        alt.Chart(df)
        .mark_bar(color=color, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(x=alt.X(f"{label}:N", sort="-y", title=None), y=alt.Y(f"{value}:Q", title=None), tooltip=[label, value])
        .properties(title=title, height=300)
    )


def rk(df: pd.DataFrame) -> pd.DataFrame:
    """Show the SQL alias ``competitor_rank`` as a friendly ``rank`` column."""
    return df.rename(columns={"competitor_rank": "rank"})


def movement_label(value: int) -> str:
    if value > 0:
        return f"▲ {value}"
    if value < 0:
        return f"▼ {abs(value)}"
    return "＝ 0"


# ---------------------------------------------------------------------------
# Database access (cached)
# ---------------------------------------------------------------------------
def resolve_database_url() -> str:
    try:  # Streamlit Cloud secrets, if configured
        return st.secrets["DATABASE_URL"]
    except Exception:
        return config.DATABASE_URL


@st.cache_resource(show_spinner=False)
def get_db():
    return get_engine(resolve_database_url())


@st.cache_data(ttl=300, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a cached read-only query. ``params`` is a tuple of (name, value) pairs so it is hashable."""
    return run_query(get_db(), sql, dict(params))


def P(**kwargs) -> tuple:
    return tuple(sorted(kwargs.items()))


def ensure_database_ready() -> None:
    try:
        with get_db().connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM competitors")).scalar()
    except Exception as exc:
        st.error(
            "Could not read the database. Create it with `python run_pipeline.py --source api` "
            "(or `--source demo` to test with fake data), then reload this page."
        )
        st.caption(f"Technical detail: {exc}")
        st.stop()
    if not count:
        st.warning("The database is empty. Run `python run_pipeline.py --source api` first.")
        st.stop()


def data_source_info() -> tuple[str, str]:
    try:
        row = q("SELECT source, run_at FROM pipeline_runs ORDER BY run_id DESC LIMIT 1")
        if len(row):
            return str(row.iloc[0]["source"]), str(row.iloc[0]["run_at"])[:16]
    except Exception:
        pass
    return "unknown", "-"


def paged_table(count_sql: str, data_sql: str, params: dict, key: str, page_size: int) -> pd.DataFrame | None:
    """Server-side pagination: only one page of rows is ever fetched from the database."""
    total = int(q(count_sql, P(**params)).iloc[0, 0])
    pages = max(1, -(-total // page_size))
    left, right = st.columns([3, 1])
    left.caption(f"{total:,} matching rows")
    page = right.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=f"{key}_page") if pages > 1 else 1
    if total == 0:
        st.info("No rows match the current filters.")
        return None
    return q(f"{data_sql} LIMIT :_limit OFFSET :_offset", P(**params, _limit=page_size, _offset=(int(page) - 1) * page_size))


def download_button(df: pd.DataFrame, name: str) -> None:
    st.download_button("⬇️ Download this page as CSV", df.to_csv(index=False).encode("utf-8"), file_name=name, mime="text/csv")


# ---------------------------------------------------------------------------
# Ranking snapshot filters (Year / Week / Gender) used by several pages
# ---------------------------------------------------------------------------
def snapshot_filters(include_all_gender: bool = True) -> dict:
    snaps = q("SELECT DISTINCT year, week, gender, ranking_type FROM competitor_rankings ORDER BY year DESC, week DESC")
    years = sorted(snaps["year"].unique(), reverse=True)
    year = st.sidebar.selectbox("Year", years)
    weeks = sorted(snaps[snaps["year"] == year]["week"].unique(), reverse=True)
    week = st.sidebar.selectbox("Week", weeks)
    genders = sorted(snaps["gender"].unique())
    gender = st.sidebar.selectbox("Gender", (["All"] if include_all_gender else []) + genders)
    return {"year": int(year), "week": int(week), "gender": gender}


# ---------------------------------------------------------------------------
# PAGE 1 - Homepage dashboard
# ---------------------------------------------------------------------------
def page_home() -> None:
    st.title("🎾 Tennis Analytics Explorer")
    st.caption("Doubles rankings, competitions and venues - loaded from the SportRadar Tennis API into SQL.")

    totals = q(
        "SELECT (SELECT COUNT(*) FROM competitors) AS competitors, "
        "(SELECT COUNT(DISTINCT country) FROM competitors) AS countries, "
        "(SELECT COUNT(*) FROM competitions) AS competitions, (SELECT COUNT(*) FROM categories) AS categories, "
        "(SELECT COUNT(*) FROM complexes) AS complexes, (SELECT COUNT(*) FROM venues) AS venues"
    ).iloc[0]
    best = q(
        "SELECT c.name, c.country, r.points, r.ranking_type FROM competitor_rankings r "
        "JOIN competitors c ON c.competitor_id = r.competitor_id ORDER BY r.points DESC LIMIT 1"
    ).iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total competitors", f"{int(totals['competitors']):,}")
    c2.metric("Countries represented", f"{int(totals['countries']):,}")
    c3.metric("Highest points scored", f"{int(best['points']):,}", help=f"{best['name']} ({best['country']}) - {best['ranking_type']}")
    c4, c5, c6, c7 = st.columns(4)
    c4.metric("Competitions", f"{int(totals['competitions']):,}")
    c5.metric("Categories", f"{int(totals['categories']):,}")
    c6.metric("Complexes", f"{int(totals['complexes']):,}")
    c7.metric("Venues", f"{int(totals['venues']):,}")
    st.caption(f"Highest points: **{best['name']}** ({best['country']}, {best['ranking_type']}) with {int(best['points']):,} points.")

    st.divider()
    left, right = st.columns(2)
    with left:
        top_countries = q("SELECT country, COUNT(*) AS competitors FROM competitors GROUP BY country ORDER BY competitors DESC LIMIT 10")
        show_chart(hbar(top_countries, "country", "competitors", "Top 10 countries by number of competitors"))
    with right:
        cats = q(
            "SELECT cat.category_name AS category, COUNT(*) AS competitions FROM competitions c "
            "JOIN categories cat ON cat.category_id = c.category_id GROUP BY cat.category_name ORDER BY competitions DESC"
        )
        show_chart(hbar(cats, "category", "competitions", "Competitions by category", color="#1565c0"))

    left, right = st.columns(2)
    with left:
        types = q("SELECT type, COUNT(*) AS competitions FROM competitions GROUP BY type ORDER BY competitions DESC")
        show_chart(vbar(types, "type", "competitions", "Competitions by type", color="#ef6c00"))
    with right:
        moves = q(
            f"SELECT CASE WHEN r.movement > 0 THEN 'Moved up' WHEN r.movement < 0 THEN 'Moved down' ELSE 'Stable' END AS movement, "
            f"COUNT(*) AS competitors FROM competitor_rankings r WHERE {LATEST} GROUP BY 1"
        )
        show_chart(vbar(moves, "movement", "competitors", "Rank movement vs previous week (latest week)", color="#6a1b9a"))


# ---------------------------------------------------------------------------
# PAGE 2 - Search & filter competitors
# ---------------------------------------------------------------------------
def page_search() -> None:
    st.title("🔎 Search & Filter Competitors")
    st.sidebar.header("Filters")
    snap = snapshot_filters()

    bounds = q(
        "SELECT MIN(r.rank) AS lo, MAX(r.rank) AS hi, MAX(r.points) AS max_points FROM competitor_rankings r "
        "WHERE r.year = :year AND r.week = :week" + ("" if snap["gender"] == "All" else " AND r.gender = :gender"),
        P(year=snap["year"], week=snap["week"], **({} if snap["gender"] == "All" else {"gender": snap["gender"]})),
    ).iloc[0]
    lo, hi = int(bounds["lo"] or 1), int(bounds["hi"] or 1)
    rank_range = st.sidebar.slider("Rank range", lo, hi, (lo, min(hi, lo + 49)))
    min_points = st.sidebar.number_input("Minimum points", min_value=0, max_value=int(bounds["max_points"] or 0), value=0, step=50)
    countries = q("SELECT DISTINCT country FROM competitors ORDER BY country")["country"].tolist()
    chosen_countries = st.sidebar.multiselect("Country", countries)
    st.sidebar.header("Search Competitors")
    name = st.sidebar.text_input("Name contains")
    page_size = st.sidebar.selectbox("Rows per page", PAGE_SIZES, index=1)

    where = ["r.year = :year", "r.week = :week", "r.rank BETWEEN :rank_lo AND :rank_hi", "r.points >= :min_points"]
    params: dict = {"year": snap["year"], "week": snap["week"], "rank_lo": rank_range[0], "rank_hi": rank_range[1], "min_points": int(min_points)}
    if snap["gender"] != "All":
        where.append("r.gender = :gender")
        params["gender"] = snap["gender"]
    if name.strip():
        where.append("LOWER(c.name) LIKE :name")
        params["name"] = f"%{name.strip().lower()}%"
    if chosen_countries:
        placeholders = []
        for i, country in enumerate(chosen_countries):
            params[f"country_{i}"] = country
            placeholders.append(f":country_{i}")
        where.append(f"c.country IN ({', '.join(placeholders)})")

    base = "FROM competitor_rankings r JOIN competitors c ON c.competitor_id = r.competitor_id WHERE " + " AND ".join(where)
    df = paged_table(
        f"SELECT COUNT(*) {base}",
        "SELECT r.ranking_type AS tour, r.gender, r.rank AS competitor_rank, c.name, c.country, c.country_code, r.points, "
        f"r.movement, r.competitions_played {base} ORDER BY r.ranking_type, r.rank, r.points DESC",
        params, "search", page_size,
    )
    if df is not None:
        df = rk(df)
        df.insert(5, "trend", df["movement"].apply(movement_label))
        show_df(df.drop(columns=["movement"]))
        download_button(df, "competitors_filtered.csv")


# ---------------------------------------------------------------------------
# PAGE 3 - Competitor details viewer
# ---------------------------------------------------------------------------
def page_details() -> None:
    st.title("👤 Competitor Details Viewer")
    search = st.text_input("Type part of a name to search", placeholder="e.g. Kai")
    options = q(
        "SELECT competitor_id, name, country FROM competitors WHERE LOWER(name) LIKE :n ORDER BY name LIMIT 100",
        P(n=f"%{search.strip().lower()}%"),
    )
    if options.empty:
        st.info("No competitor matches that search.")
        return
    labels = {row.competitor_id: f"{row.name} - {row.country}" for row in options.itertuples()}
    chosen = st.selectbox("Select a competitor", list(labels), format_func=labels.get)

    history = q(
        "SELECT r.ranking_type, r.gender, r.year, r.week, r.rank AS competitor_rank, r.movement, r.points, r.competitions_played "
        "FROM competitor_rankings r WHERE r.competitor_id = :cid ORDER BY r.year DESC, r.week DESC",
        P(cid=chosen),
    )
    history = rk(history)
    person = q("SELECT * FROM competitors WHERE competitor_id = :cid", P(cid=chosen)).iloc[0]
    if history.empty:
        st.warning("This competitor has no ranking rows.")
        return
    now = history.iloc[0]

    st.subheader(f"{person['name']}  ·  {person['country']} ({person['country_code']})")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rank", int(now["rank"]), delta=int(now["movement"]) if now["movement"] else None, help="Delta = places moved since last week")
    c2.metric("Points", f"{int(now['points']):,}")
    c3.metric("Competitions played", int(now["competitions_played"]))
    c4.metric("Tour", f"{now['ranking_type']} ({now['gender']})")
    c5.metric("Abbreviation", person["abbreviation"])
    st.caption(f"Snapshot: year {int(now['year'])}, week {int(now['week'])}")

    if len(history) > 1:
        st.markdown("**Ranking history**")
        chart = alt.Chart(history.assign(period=history["year"].astype(str) + "-W" + history["week"].astype(str))).mark_line(point=True).encode(
            x="period:N", y=alt.Y("rank:Q", scale=alt.Scale(reverse=True), title="Rank (1 = best)"), tooltip=["period", "rank", "points"]
        )
        show_chart(chart.properties(height=260))
    show_df(history)

    st.markdown(f"**Other competitors from {person['country']}** (latest week)")
    mates = q(
        f"SELECT c.name, r.ranking_type AS tour, r.rank AS competitor_rank, r.points FROM competitor_rankings r "
        f"JOIN competitors c ON c.competitor_id = r.competitor_id WHERE c.country = :country AND c.competitor_id <> :cid AND {LATEST} "
        "ORDER BY r.points DESC LIMIT 10",
        P(country=person["country"], cid=chosen),
    )
    mates = rk(mates)
    show_df(mates) if len(mates) else st.caption("No other competitors from this country.")


# ---------------------------------------------------------------------------
# PAGE 4 - Country-wise analysis
# ---------------------------------------------------------------------------
def page_countries() -> None:
    st.title("🌍 Country-wise Analysis")
    st.sidebar.header("Filters")
    snap = snapshot_filters()
    min_competitors = st.sidebar.slider("Minimum competitors per country", 1, 20, 1)

    where, params = "r.year = :year AND r.week = :week", {"year": snap["year"], "week": snap["week"]}
    if snap["gender"] != "All":
        where += " AND r.gender = :gender"
        params["gender"] = snap["gender"]
    df = q(
        "SELECT c.country, COUNT(DISTINCT c.competitor_id) AS total_competitors, ROUND(AVG(r.points), 1) AS average_points, "
        "SUM(r.points) AS total_points, MIN(r.rank) AS best_rank FROM competitor_rankings r "
        f"JOIN competitors c ON c.competitor_id = r.competitor_id WHERE {where} GROUP BY c.country "
        "HAVING COUNT(DISTINCT c.competitor_id) >= :minimum ORDER BY total_competitors DESC, average_points DESC",
        P(**params, minimum=min_competitors),
    )
    if df.empty:
        st.info("No countries match the current filters.")
        return
    st.caption("Tip: choose a single gender in the sidebar - ATP and WTA points are on different scales, so mixing them skews averages.")
    left, right = st.columns(2)
    with left:
        show_chart(hbar(df.head(15), "country", "total_competitors", "Competitors per country (top 15)"))
    with right:
        show_chart(hbar(df.sort_values("average_points", ascending=False).head(15), "country", "average_points", "Average points per country (top 15)", color="#ef6c00"))
    show_df(df)

    st.subheader("Drill down into a country")
    country = st.selectbox("Country", df["country"].tolist())
    detail = q(
        "SELECT r.ranking_type AS tour, r.rank AS competitor_rank, c.name, r.points, r.competitions_played FROM competitor_rankings r "
        f"JOIN competitors c ON c.competitor_id = r.competitor_id WHERE {where} AND c.country = :country ORDER BY r.points DESC",
        P(**params, country=country),
    )
    show_df(rk(detail))


# ---------------------------------------------------------------------------
# PAGE 5 - Leaderboards
# ---------------------------------------------------------------------------
def page_leaderboards() -> None:
    st.title("🏆 Leaderboards")
    top_n = st.sidebar.slider("Show top N", 5, 50, 10, step=5)
    tours = q(f"SELECT DISTINCT r.ranking_type, r.gender FROM competitor_rankings r WHERE {LATEST} ORDER BY r.ranking_type")
    if tours.empty:
        st.info("No ranking data.")
        return
    tabs = st.tabs([f"{t.ranking_type} ({t.gender})" for t in tours.itertuples()])
    for tab, tour in zip(tabs, tours.itertuples()):
        with tab:
            params = P(tour=tour.ranking_type, gender=tour.gender, n=top_n)
            base = (
                "SELECT r.rank AS competitor_rank, c.name, c.country, r.points, r.movement, r.competitions_played "
                f"FROM competitor_rankings r JOIN competitors c ON c.competitor_id = r.competitor_id "
                f"WHERE {LATEST} AND r.ranking_type = :tour AND r.gender = :gender"
            )
            left, right = st.columns(2)
            with left:
                st.markdown(f"**Top {top_n} ranked competitors**")
                show_df(rk(q(f"{base} ORDER BY r.rank, r.points DESC LIMIT :n", params)))
            with right:
                st.markdown(f"**Top {top_n} by points**")
                by_points = rk(q(f"{base} ORDER BY r.points DESC, r.rank LIMIT :n", params))
                show_df(by_points)
            show_chart(hbar(by_points.head(10), "name", "points", "Points - top 10", color="#2e7d32"))


# ---------------------------------------------------------------------------
# PAGE 6 - Competitions explorer
# ---------------------------------------------------------------------------
def page_competitions() -> None:
    st.title("🏟️ Competitions Explorer")
    st.sidebar.header("Filters")
    cats = q("SELECT category_name FROM categories ORDER BY category_name")["category_name"].tolist()
    types = q("SELECT DISTINCT type FROM competitions ORDER BY type")["type"].tolist()
    genders = q("SELECT DISTINCT gender FROM competitions ORDER BY gender")["gender"].tolist()
    f_cats = st.sidebar.multiselect("Category (level)", cats)
    f_types = st.sidebar.multiselect("Competition type", types)
    f_genders = st.sidebar.multiselect("Gender", genders)
    f_name = st.sidebar.text_input("Name contains")
    top_only = st.sidebar.checkbox("Top-level competitions only (no parent)")
    page_size = st.sidebar.selectbox("Rows per page", PAGE_SIZES, index=1)

    where, params = ["1 = 1"], {}
    for column, values, prefix in (("cat.category_name", f_cats, "cat"), ("c.type", f_types, "typ"), ("c.gender", f_genders, "gen")):
        if values:
            names = []
            for i, v in enumerate(values):
                params[f"{prefix}_{i}"] = v
                names.append(f":{prefix}_{i}")
            where.append(f"{column} IN ({', '.join(names)})")
    if f_name.strip():
        where.append("LOWER(c.competition_name) LIKE :name")
        params["name"] = f"%{f_name.strip().lower()}%"
    if top_only:
        where.append("c.parent_id IS NULL")
    base = "FROM competitions c JOIN categories cat ON cat.category_id = c.category_id WHERE " + " AND ".join(where)

    tab_browse, tab_tree, tab_charts = st.tabs(["Browse", "Competition hierarchy", "Distribution charts"])
    with tab_browse:
        df = paged_table(
            f"SELECT COUNT(*) {base}",
            f"SELECT c.competition_id, c.competition_name, cat.category_name AS category, c.type, c.gender, c.parent_id {base} "
            "ORDER BY cat.category_name, c.competition_name",
            params, "comp", page_size,
        )
        if df is not None:
            show_df(df)
            download_button(df, "competitions_filtered.csv")

    with tab_tree:
        st.caption("Pick a parent competition (e.g. ATP Vienna) to see its singles / doubles sub-competitions.")
        parents = q(
            "SELECT p.competition_id, p.competition_name, COUNT(ch.competition_id) AS subs FROM competitions p "
            "JOIN competitions ch ON ch.parent_id = p.competition_id GROUP BY p.competition_id, p.competition_name "
            "ORDER BY p.competition_name"
        )
        if parents.empty:
            st.info("No parent/child relationships found in the data.")
        else:
            search = st.text_input("Filter parents", key="parent_search")
            if search.strip():
                parents = parents[parents["competition_name"].str.contains(search.strip(), case=False, regex=False)]
            if parents.empty:
                st.info("No parent competition matches that filter.")
            else:
                labels = {r.competition_id: f"{r.competition_name} ({r.subs} sub-competitions)" for r in parents.itertuples()}
                parent_id = st.selectbox("Parent competition", list(labels), format_func=labels.get)
                parent = q("SELECT c.competition_name, cat.category_name, c.type, c.gender FROM competitions c "
                           "JOIN categories cat ON cat.category_id = c.category_id WHERE c.competition_id = :pid", P(pid=parent_id)).iloc[0]
                st.markdown(f"**{parent['competition_name']}** · {parent['category_name']} · {parent['type']} · {parent['gender']}")
                subs = q("SELECT competition_id, competition_name, type, gender FROM competitions WHERE parent_id = :pid ORDER BY competition_name", P(pid=parent_id))
                show_df(subs)

    with tab_charts:
        dist = q(f"SELECT cat.category_name AS category, c.type, COUNT(*) AS competitions {base} GROUP BY cat.category_name, c.type", P(**params))
        if dist.empty:
            st.info("Nothing to chart for the current filters.")
        else:
            chart = alt.Chart(dist).mark_bar().encode(
                y=alt.Y("category:N", sort="-x", title=None), x=alt.X("competitions:Q", title="Competitions"),
                color=alt.Color("type:N", title="Type"), tooltip=["category", "type", "competitions"],
            ).properties(title="Competition types by category", height=max(220, 34 * dist["category"].nunique()))
            show_chart(chart)
            gender = q(f"SELECT c.gender, COUNT(*) AS competitions {base} GROUP BY c.gender", P(**params))
            show_chart(vbar(gender, "gender", "competitions", "Competitions by gender", color="#6a1b9a"))


# ---------------------------------------------------------------------------
# PAGE 7 - Venues & complexes
# ---------------------------------------------------------------------------
def page_venues() -> None:
    st.title("🏢 Venues & Complexes")
    st.sidebar.header("Filters")
    countries = q("SELECT DISTINCT country_name FROM venues ORDER BY country_name")["country_name"].tolist()
    f_countries = st.sidebar.multiselect("Country", countries)
    f_complex = st.sidebar.text_input("Complex name contains")
    page_size = st.sidebar.selectbox("Rows per page", PAGE_SIZES, index=1)

    where, params = ["1 = 1"], {}
    if f_countries:
        names = []
        for i, v in enumerate(f_countries):
            params[f"c_{i}"] = v
            names.append(f":c_{i}")
        where.append(f"v.country_name IN ({', '.join(names)})")
    if f_complex.strip():
        where.append("LOWER(cx.complex_name) LIKE :cx")
        params["cx"] = f"%{f_complex.strip().lower()}%"
    base = "FROM venues v JOIN complexes cx ON cx.complex_id = v.complex_id WHERE " + " AND ".join(where)

    k1, k2, k3 = st.columns(3)
    stats = q(f"SELECT COUNT(*) AS venues, COUNT(DISTINCT v.complex_id) AS complexes, COUNT(DISTINCT v.country_name) AS countries {base}", P(**params)).iloc[0]
    k1.metric("Venues", int(stats["venues"]))
    k2.metric("Complexes", int(stats["complexes"]))
    k3.metric("Countries", int(stats["countries"]))

    tab_venues, tab_complex, tab_charts = st.tabs(["Venues", "Complexes", "Charts"])
    with tab_venues:
        df = paged_table(
            f"SELECT COUNT(*) {base}",
            f"SELECT v.venue_name, cx.complex_name, v.city_name, v.country_name, v.country_code, v.timezone {base} "
            "ORDER BY v.country_name, v.city_name, v.venue_name",
            params, "venue", page_size,
        )
        if df is not None:
            show_df(df)
            download_button(df, "venues_filtered.csv")
    with tab_complex:
        multi_only = st.checkbox("Only complexes with more than one venue")
        having = "HAVING COUNT(v.venue_id) > 1" if multi_only else ""
        df = q(f"SELECT cx.complex_name, COUNT(v.venue_id) AS venue_count {base} GROUP BY cx.complex_id, cx.complex_name {having} "
               "ORDER BY venue_count DESC, cx.complex_name", P(**params))
        show_df(df) if len(df) else st.info("No complexes match.")
    with tab_charts:
        by_country = q(f"SELECT v.country_name AS country, COUNT(*) AS venues {base} GROUP BY v.country_name ORDER BY venues DESC LIMIT 15", P(**params))
        by_tz = q(f"SELECT v.timezone, COUNT(*) AS venues {base} GROUP BY v.timezone ORDER BY venues DESC LIMIT 15", P(**params))
        if by_country.empty:
            st.info("Nothing to chart.")
        else:
            left, right = st.columns(2)
            with left:
                show_chart(hbar(by_country, "country", "venues", "Venues per country (top 15)", color="#1565c0"))
            with right:
                show_chart(hbar(by_tz, "timezone", "venues", "Venues per timezone (top 15)", color="#ef6c00"))


# ---------------------------------------------------------------------------
# PAGE 8 - SQL query explorer
# ---------------------------------------------------------------------------
def page_sql() -> None:
    st.title("🧮 SQL Query Explorer")
    st.caption("All 20 analysis queries from the project brief, executed live against the database. Parameters are bound safely (no SQL injection).")
    group = st.radio("Dataset", GROUPS, horizontal=True)
    available = [qq for qq in QUERIES if qq.group == group]
    chosen_id = st.selectbox("Query", [qq.qid for qq in available], format_func=lambda i: f"{i} · {QUERY_BY_ID[i].title}")
    query = QUERY_BY_ID[chosen_id]
    st.info(query.explanation)

    values = {}
    if query.params:
        cols = st.columns(len(query.params))
        for col, (name, default) in zip(cols, query.params.items()):
            values[name] = col.text_input(f":{name}", value=default)
    with st.expander("Show SQL", expanded=True):
        st.code(render_sql(query, values), language="sql")

    try:
        df = q(query.sql, P(**values))
    except Exception as exc:
        st.error(f"The query failed: {exc}")
        return
    st.caption(f"{len(df):,} rows returned")
    if df.empty:
        st.info("The query ran but returned no rows (try a different parameter value).")
        return
    show_df(df.head(500))
    if len(df) > 500:
        st.caption("Showing the first 500 rows.")
    st.download_button("⬇️ Download result as CSV", df.to_csv(index=False).encode("utf-8"), file_name=f"{chosen_id}.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
PAGES = {
    "🏠 Homepage dashboard": page_home,
    "🔎 Search & filter competitors": page_search,
    "👤 Competitor details": page_details,
    "🌍 Country-wise analysis": page_countries,
    "🏆 Leaderboards": page_leaderboards,
    "🏟️ Competitions explorer": page_competitions,
    "🏢 Venues & complexes": page_venues,
    "🧮 SQL query explorer": page_sql,
}


def main() -> None:
    ensure_database_ready()
    st.sidebar.title("🎾 Tennis Analytics")
    page = st.sidebar.radio("Navigate", list(PAGES), label_visibility="collapsed")
    source, loaded_at = data_source_info()
    if source == "demo":
        st.warning("⚠️ **DEMO DATA** - the database holds fictional sample data, not real SportRadar data. "
                   "Run `python run_pipeline.py --source api --reset` with your API key to load the real data.")
    st.sidebar.caption(f"Data source: **{source}** · loaded {loaded_at} UTC")
    st.sidebar.divider()
    PAGES[page]()


main()
