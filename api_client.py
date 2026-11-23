"""
SportRadar Tennis API (v3) client.

Handles the things that usually go wrong when calling a rate-limited REST API:
  * Authentication through the ``x-api-key`` header (key never appears in URLs/logs)
  * Throttling - trial keys allow 1 request per second
  * Retries with exponential back-off on HTTP 429 (rate limit) and 5xx errors,
    honouring the ``Retry-After`` header when the server sends one
  * Clear, specific exceptions for bad keys / wrong endpoints / network failures
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


class SportradarAPIError(Exception):
    """Raised when the API cannot be reached or returns an unrecoverable error."""


class SportradarClient:
    """Small wrapper around the Tennis v3 REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        access_level: str | None = None,
        language: str | None = None,
        min_interval: float | None = None,
        max_retries: int | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = api_key or config.SPORTRADAR_API_KEY
        if not self.api_key:
            raise SportradarAPIError(
                "No API key found. Set SPORTRADAR_API_KEY in your .env file "
                "(get a free trial key at https://console.sportradar.com/signup)."
            )
        self.access_level = access_level or config.SPORTRADAR_ACCESS_LEVEL
        self.language = language or config.SPORTRADAR_LANGUAGE
        self.min_interval = config.API_MIN_INTERVAL_SECONDS if min_interval is None else min_interval
        self.max_retries = config.API_MAX_RETRIES if max_retries is None else max_retries
        self.timeout = config.API_TIMEOUT_SECONDS if timeout is None else timeout
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({"accept": "application/json", "x-api-key": self.api_key})

    # ------------------------------------------------------------------
    def _url(self, feed: str) -> str:
        return f"{config.SPORTRADAR_BASE_URL}/{self.access_level}/v3/{self.language}/{feed}.json"

    def _throttle(self) -> None:
        """Sleep just long enough to stay under the per-second request limit."""
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, feed: str) -> dict[str, Any]:
        url = self._url(feed)
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning("Network problem on %s (attempt %d/%d): %s", feed, attempt, self.max_retries, exc)
                time.sleep(2**attempt)
                continue

            status = response.status_code
            if status == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SportradarAPIError(f"'{feed}' returned invalid JSON: {exc}") from exc

            if status in (401, 403):
                raise SportradarAPIError(
                    f"HTTP {status}: the API key was rejected for '{feed}'. "
                    "Check SPORTRADAR_API_KEY and that your key has Tennis v3 access."
                )
            if status == 404:
                raise SportradarAPIError(f"HTTP 404: endpoint '{feed}' was not found ({url}).")

            if status == 429 or status >= 500:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                logger.warning("HTTP %d on %s (attempt %d/%d). Waiting %.0fs.", status, feed, attempt, self.max_retries, delay)
                time.sleep(delay)
                continue

            raise SportradarAPIError(f"Unexpected HTTP {status} for '{feed}': {response.text[:200]}")

        raise SportradarAPIError(f"Gave up on '{feed}' after {self.max_retries} attempts.")

    # ------------------------------------------------------------------
    # Endpoints used by this project
    # ------------------------------------------------------------------
    def get_competitions(self) -> dict[str, Any]:
        """GET /competitions.json - every competition with its category."""
        return self._get("competitions")

    def get_complexes(self) -> dict[str, Any]:
        """GET /complexes.json - sports complexes and their venues."""
        return self._get("complexes")

    def get_doubles_rankings(self) -> dict[str, Any]:
        """GET /double_competitors_rankings.json - top 500 ATP + WTA doubles rankings."""
        return self._get("double_competitors_rankings")
