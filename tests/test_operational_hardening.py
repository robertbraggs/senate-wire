from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

import app.main as main
from app.refresher import SourceConfig, SourceRefreshManager, default_source_configs
from app.source_cache import get_source_snapshot, upsert_source_failure, upsert_source_success


class SequencedRefreshManager(SourceRefreshManager):
    def __init__(self, outcomes):
        super().__init__([SourceConfig("pytest_source", "https://example.test/source", 60, 1.0)])
        self.outcomes = list(outcomes)
        self.calls = 0
        self.disabled = False
        self.backoff_seconds = 0

    async def _fetch_once(self, source):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def refresh_congress_bill_enrichment(self, force: bool = False) -> None:
        return None


def run(coro):
    return asyncio.run(coro)


def test_refresher_startup_shutdown_lifecycle(monkeypatch):
    monkeypatch.setenv("SOURCE_REFRESH_ON_STARTUP", "false")
    manager = SequencedRefreshManager([{"text": "ok"}])

    async def scenario():
        await manager.start()
        assert manager._task is not None
        assert not manager._task.done()
        await manager.stop()
        assert manager._task is None

    run(scenario())


def test_retry_and_backoff_behavior(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    manager = SequencedRefreshManager([
        RuntimeError("temporary failure"),
        RuntimeError("temporary failure"),
        {"text": "eventual success"},
    ])
    manager.retries = 2
    manager.backoff_seconds = 2

    payload = run(manager._fetch_with_retries(manager.sources[0]))

    assert payload["text"] == "eventual success"
    assert manager.calls == 3
    assert sleeps == [2, 4]


def test_circuit_breaker_opens_and_resets():
    manager = SequencedRefreshManager([
        RuntimeError("api_key=SECRETKEY upstream failure"),
        RuntimeError("api_key=SECRETKEY upstream failure"),
        {"text": "recovered"},
    ])
    manager.retries = 0
    manager.failure_threshold = 2
    manager.circuit_reset_seconds = 60
    source = manager.sources[0]

    async def scenario():
        await manager.refresh_source(source)
        await manager.refresh_source(source)
        assert manager._circuit_open_until[source.name] > datetime.utcnow()
        await manager.refresh_source(source)
        assert manager.calls == 2
        manager._circuit_open_until[source.name] = datetime.utcnow() - timedelta(seconds=1)
        await manager.refresh_source(source)
        assert manager.calls == 3
        assert source.name not in manager._circuit_open_until

    run(scenario())


def test_stale_cache_fallback_and_sanitized_error_storage():
    source_name = "pytest_secret_fallback"
    upsert_source_success(source_name, {"text": "known good", "url": "https://api.example.test/items?api_key=SECRETKEY"})
    upsert_source_failure(source_name, "https://api.example.test/items?api_key=SECRETKEY failed")

    snapshot = get_source_snapshot(source_name)

    assert snapshot["status"] == "error"
    assert snapshot["stale"] is True
    assert snapshot["payload"]["text"] == "known good"
    assert "SECRETKEY" not in json.dumps(snapshot)
    assert "[redacted]" in json.dumps(snapshot)


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_protected_debug_endpoints_require_admin_token(monkeypatch):
    monkeypatch.setattr(main, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

    with pytest.raises(main.HTTPException) as raw_error:
        main.debug_raw(FakeRequest())
    with pytest.raises(main.HTTPException) as alerts_error:
        main.debug_alerts(FakeRequest())

    assert raw_error.value.status_code == 401
    assert alerts_error.value.status_code == 401
    assert main.debug_alerts(FakeRequest({"authorization": "Bearer test-admin-token"}))


def test_public_routes_do_not_perform_live_http(monkeypatch):
    def fail_live_http(*args, **kwargs):
        raise AssertionError("public route attempted live HTTP")

    monkeypatch.setattr(main, "fetch_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(main, "CONGRESS_API_KEY", "fake-key")
    monkeypatch.setattr("requests.get", fail_live_http)

    assert main.summary_endpoint()["app"] == main.APP_NAME
    assert main.health()["status"] == "ok"
    assert main.events_endpoint()["app"] == main.APP_NAME


def test_public_endpoints_do_not_leak_secrets(monkeypatch):
    monkeypatch.setenv("CONGRESS_API_KEY", "SECRETKEY")
    monkeypatch.setattr(main, "CONGRESS_API_KEY", "SECRETKEY")
    upsert_source_success("congress_committee_meetings", {"url": "https://api.congress.gov/v3/foo?api_key=SECRETKEY", "text": "{}"})
    upsert_source_failure("pytest_public_secret", "request failed for https://api.example.test/?api_key=SECRETKEY")

    for payload in (main.summary_endpoint(), main.health()):
        body = json.dumps(payload, default=str)
        assert "SECRETKEY" not in body
        assert "api_key=SECRETKEY" not in body


def test_congress_bill_metadata_uses_cached_enrichment(monkeypatch):
    monkeypatch.setattr(main, "CONGRESS_API_KEY", "fake-key")
    monkeypatch.setattr(main, "current_congress", lambda: 119)
    bill_source = main.congress_api_source_name("/bill/119/s/123")
    actions_source = main.congress_api_source_name("/bill/119/s/123/actions")
    summaries_source = main.congress_api_source_name("/bill/119/s/123/summaries")
    upsert_source_success(bill_source, {"text": json.dumps({"bill": {
        "title": "Test Bill Title",
        "latestAction": {"text": "Latest cached action", "actionDate": "2026-05-01"},
        "policyArea": {"name": "Government Operations"},
        "sponsors": [{"fullName": "Sen. Example"}],
        "url": "https://api.congress.gov/v3/bill/119/s/123?api_key=fake-key",
    }})})
    upsert_source_success(actions_source, {"text": json.dumps({"actions": [{"text": "Cached action list entry"}]})})
    upsert_source_success(summaries_source, {"text": json.dumps({"summaries": [{"text": "<p>Cached summary text.</p>"}]})})

    cached_text = get_source_snapshot(bill_source)["payload"].get("text")
    assert json.loads(cached_text)["bill"]["title"] == "Test Bill Title"
    assert main.congress_api_get("/bill/119/s/123").get("bill", {}).get("title") == "Test Bill Title"
    info = main.fetch_congress_bill_info("S. 123")

    assert info["congress_bill_title"] == "Test Bill Title"
    assert info["congress_latest_action"] == "Cached action list entry"
    assert info["congress_policy_area"] == "Government Operations"
    assert info["congress_sponsors"] == "Sen. Example"
    assert info["congress_summary"] == "Cached summary text."
    assert "fake-key" not in info["congress_url"]


def test_congress_api_key_not_embedded_in_default_source_urls(monkeypatch):
    monkeypatch.setenv("CONGRESS_API_KEY", "SECRETKEY")
    configs = default_source_configs()
    serialized = json.dumps([config.__dict__ for config in configs])

    assert "api_key=SECRETKEY" not in serialized
    assert any(config.name == "congress_committee_meetings" and config.params.get("api_key") == "SECRETKEY" for config in configs)
