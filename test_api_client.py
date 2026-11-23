"""API client behaviour (no network - HTTP responses are faked)."""

import pytest

import api_client
from api_client import SportradarAPIError, SportradarClient


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code, self._payload, self.headers, self.text = status, payload or {}, headers or {}, text

    def json(self):
        return self._payload


def make_client(monkeypatch, responses):
    monkeypatch.setattr(api_client.time, "sleep", lambda *_: None)  # no real waiting in tests
    client = SportradarClient(api_key="test-key", min_interval=0, max_retries=3)
    calls = iter(responses)
    monkeypatch.setattr(client._session, "get", lambda url, timeout: next(calls))
    return client


def test_missing_key_gives_clear_message(monkeypatch):
    monkeypatch.setattr(api_client.config, "SPORTRADAR_API_KEY", "")
    with pytest.raises(SportradarAPIError, match="No API key"):
        SportradarClient()


def test_key_is_sent_in_header_not_url():
    client = SportradarClient(api_key="secret-123")
    assert client._session.headers["x-api-key"] == "secret-123"
    assert "secret-123" not in client._url("competitions")


def test_retries_after_rate_limit_then_succeeds(monkeypatch):
    client = make_client(monkeypatch, [FakeResponse(429), FakeResponse(503), FakeResponse(200, {"competitions": []})])
    assert client.get_competitions() == {"competitions": []}


def test_gives_up_after_max_retries(monkeypatch):
    client = make_client(monkeypatch, [FakeResponse(429)] * 3)
    with pytest.raises(SportradarAPIError, match="Gave up"):
        client.get_complexes()


@pytest.mark.parametrize("status, message", [(401, "rejected"), (403, "rejected"), (404, "not found")])
def test_fatal_errors_fail_fast(monkeypatch, status, message):
    client = make_client(monkeypatch, [FakeResponse(status)])
    with pytest.raises(SportradarAPIError, match=message):
        client.get_doubles_rankings()


def test_endpoint_urls(monkeypatch):
    client = SportradarClient(api_key="k", access_level="trial", language="en")
    assert client._url("double_competitors_rankings").endswith("/tennis/trial/v3/en/double_competitors_rankings.json")
