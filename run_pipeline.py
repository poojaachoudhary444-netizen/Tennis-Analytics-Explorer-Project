"""
End-to-end data pipeline:  SportRadar API  ->  parse JSON  ->  SQL database.

Usage
-----
    python run_pipeline.py --source api            # real data (needs SPORTRADAR_API_KEY)
    python run_pipeline.py --source json           # re-load previously saved raw JSON (offline)
    python run_pipeline.py --source demo           # FAKE demo data, for testing the app only
    python run_pipeline.py --source api --reset    # drop all tables first, then reload

Each dataset (competitions, complexes, rankings) is processed independently, so
a failure in one endpoint never prevents the others from loading.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import config
import etl
from api_client import SportradarAPIError, SportradarClient
from db import create_schema, drop_schema, get_engine

LOG_DIR = Path(__file__).resolve().parent / "logs"


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8")],
    )


def get_payloads(source: str) -> dict[str, dict | Exception]:
    """Return raw JSON payloads per dataset (an Exception object if a dataset failed)."""
    payloads: dict[str, dict | Exception] = {}

    if source == "demo":
        from demo_data import generate_demo_payloads

        return dict(generate_demo_payloads())

    if source == "json":
        for name, path in config.RAW_FILES.items():
            try:
                payloads[name] = etl.load_raw(path)
            except (FileNotFoundError, ValueError) as exc:
                payloads[name] = exc
        return payloads

    # source == "api"
    client = SportradarClient()  # raises a clear error if no key is configured
    fetchers = {
        "competitions": client.get_competitions,
        "complexes": client.get_complexes,
        "doubles_rankings": client.get_doubles_rankings,
    }
    for name, fetch in fetchers.items():
        try:
            logging.info("Fetching %s ...", name)
            payloads[name] = fetch()
            etl.save_raw(config.RAW_FILES[name], payloads[name])
        except SportradarAPIError as exc:
            logging.error("Could not fetch %s: %s", name, exc)
            payloads[name] = exc
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Load SportRadar tennis data into SQL.")
    parser.add_argument("--source", choices=["api", "json", "demo"], default="api")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args()

    setup_logging()
    if args.source == "demo":
        logging.warning("*** DEMO MODE: loading FAKE data - do not submit this as real project data ***")

    engine = get_engine()
    logging.info("Database: %s", engine.url.render_as_string(hide_password=True))
    if args.reset:
        drop_schema(engine)
    create_schema(engine)

    try:
        payloads = get_payloads(args.source)
    except SportradarAPIError as exc:
        logging.error("%s", exc)
        return 2

    failures: list[str] = []
    stats_lines: list[str] = []

    def process(name, parse, load):
        payload = payloads.get(name)
        if isinstance(payload, Exception) or payload is None:
            failures.append(f"{name}: {payload}")
            return
        try:
            first, second, stats = parse(payload)
            load(engine, first, second)
            stats_lines.append(stats.summary())
        except Exception as exc:  # database / parsing problems must not hide the other datasets
            logging.exception("Failed to load %s", name)
            failures.append(f"{name}: {exc}")

    process("competitions", etl.parse_competitions, etl.load_competition_data)
    process("complexes", etl.parse_complexes, etl.load_venue_data)
    process("doubles_rankings", etl.parse_doubles_rankings, etl.load_ranking_data)

    result = etl.validate_database(engine)
    etl.record_pipeline_run(engine, args.source, notes="; ".join(failures) if failures else "ok")

    print("\n================ PIPELINE SUMMARY ================")
    for line in stats_lines:
        print(" *", line)
    print("\nRows in database:")
    for table, count in result["counts"].items():
        print(f"   {table:<22}{count:>8,}")
    for issue in result["issues"]:
        print(" ! integrity issue:", issue)
    if failures:
        print("\nDatasets that FAILED:")
        for failure in failures:
            print("  -", failure)
        return 1
    print("\nAll datasets loaded successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
