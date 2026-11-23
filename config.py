"""
Central configuration for the Tennis Analytics project.

Values are read from environment variables (or a local ``.env`` file).
Nothing secret is ever hard-coded - copy ``.env.example`` to ``.env`` and
fill in your own SportRadar API key and database URL.
"""

import os
from pathlib import Path

try:  # python-dotenv is optional; env vars work without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent

# --- SportRadar API ---------------------------------------------------------
SPORTRADAR_API_KEY = os.getenv("SPORTRADAR_API_KEY", "")
SPORTRADAR_ACCESS_LEVEL = os.getenv("SPORTRADAR_ACCESS_LEVEL", "trial")  # trial | production
SPORTRADAR_LANGUAGE = os.getenv("SPORTRADAR_LANGUAGE", "en")
SPORTRADAR_BASE_URL = os.getenv("SPORTRADAR_BASE_URL", "https://api.sportradar.com/tennis")  # overridable for tests

# Trial keys are limited to 1 request/second, so we wait a little longer.
API_MIN_INTERVAL_SECONDS = float(os.getenv("API_MIN_INTERVAL_SECONDS", "1.2"))
API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "5"))
API_TIMEOUT_SECONDS = int(os.getenv("API_TIMEOUT_SECONDS", "30"))

# --- Database ---------------------------------------------------------------
# MySQL      : mysql+pymysql://user:password@localhost:3306/tennis_db
# PostgreSQL : postgresql+psycopg2://user:password@localhost:5432/tennis_db
# SQLite     : sqlite:///tennis.db   (default - zero setup, good for demos)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'tennis.db'}")

# --- Files ------------------------------------------------------------------
RAW_DATA_DIR = BASE_DIR / "data" / "raw"
RAW_FILES = {
    "competitions": RAW_DATA_DIR / "competitions.json",
    "complexes": RAW_DATA_DIR / "complexes.json",
    "doubles_rankings": RAW_DATA_DIR / "doubles_rankings.json",
}
