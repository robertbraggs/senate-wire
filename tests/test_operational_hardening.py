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


def make_test_jolt_item(raw="Sen. Thune filed cloture on the nomination."):
    return main.JoltItem(
        source="pytest",
        raw=raw,
        date_label="Today",
        time_label="5:30 p.m.",
        sort_datetime="2026-05-06T17:30:00",
        category="Floor Action",
        title="Floor action",
        urgency="monitor",
        status="upcoming",
        confidence="high",
        quality="confirmed",
        location="Senate floor",
        building="Capitol",
        measure="S. 1",
        takeaway="Procedural action.",
        where_to_be="Senate floor",
        movement_cue="Watch floor.",
        who_to_watch="Leadership",
        coverage_note="Monitor.",
        staff_note="Monitor.",
        gallery_note="Monitor.",
        senators_detected=[],
        coverage_target="floor",
        press_availability="",
        best_window="",
        event_type="floor_action",
        committee=None,
        url="fixture://event",
        topic="procedure",
        procedure_interpretation=main.classify_event_text(raw),
    )


def test_events_payload_preserves_existing_keys_and_adds_interpretation(monkeypatch):
    monkeypatch.setattr(main, "get_all_items", lambda: [make_test_jolt_item()])

    payload = main.events_endpoint()
    item = payload["items"][0]

    assert payload["app"] == main.APP_NAME
    assert payload["view"] == "reporter"
    assert "raw" in item
    assert "title" in item
    assert "procedure_interpretation" in item
    assert item["procedure_interpretation"]["status_code"] == "CLOTURE_FILED"


def test_summary_payload_preserves_existing_keys_and_adds_interpretations(monkeypatch):
    monkeypatch.setattr(main, "get_all_items", lambda: [make_test_jolt_item()])

    payload = main.summary_endpoint()

    assert payload["app"] == main.APP_NAME
    assert "total" in payload
    assert "votes" in payload
    assert "procedure_interpretations" in payload
    assert payload["procedure_interpretations"][0]["status_label"] == "Cloture filed"


def make_activity_item(title, sort_datetime, category="Earlier Floor Activity", status="historical"):
    return main.JoltItem(
        source="pytest",
        raw=title,
        date_label="fixture",
        time_label="12:00 p.m.",
        sort_datetime=sort_datetime,
        category=category,
        title=title,
        urgency="monitor",
        status=status,
        confidence="high",
        quality="confirmed",
        location="Senate floor",
        building="Capitol",
        measure=None,
        takeaway="Activity update.",
        where_to_be="Senate floor",
        movement_cue="Monitor.",
        who_to_watch="Leadership",
        coverage_note="Monitor.",
        staff_note="Monitor.",
        gallery_note="Monitor.",
        senators_detected=[],
        coverage_target="floor",
        press_availability="",
        best_window="",
        event_type="floor_action",
        committee=None,
        url="fixture://activity",
        topic="floor",
    )


def test_today_item_appears_in_recent_activity():
    now = datetime(2026, 5, 6, 15, 0)
    today_item = make_activity_item("Morning business began", "2026-05-06T10:00:00")

    current, prior = main.recent_activity_buckets([today_item], now)

    assert today_item in current
    assert prior == []


def test_upcoming_scheduled_item_appears_in_recent_activity():
    now = datetime(2026, 5, 6, 15, 0)
    upcoming_item = make_activity_item("Senate will convene tomorrow", "2026-05-07T10:00:00", category="Schedule", status="upcoming")

    current, prior = main.recent_activity_buckets([upcoming_item], now)

    assert upcoming_item in current
    assert prior == []


def test_previous_day_item_is_excluded_from_recent_activity():
    now = datetime(2026, 5, 6, 15, 0)
    previous_item = make_activity_item("Senate adjourned", "2026-05-05T18:00:00")

    current, _prior = main.recent_activity_buckets([previous_item], now)

    assert previous_item not in current


def test_previous_day_item_is_not_shown_as_context_without_current_relevance():
    now = datetime(2026, 5, 6, 15, 0)
    previous_item = make_activity_item("Senate adjourned", "2026-05-05T18:00:00")

    current, prior = main.recent_activity_buckets([previous_item], now)

    assert current == []
    assert prior == []


def test_unresolved_prior_procedure_can_be_shown_as_material_carryover():
    now = datetime(2026, 5, 6, 15, 0)
    carryover_item = make_activity_item("Cloture filed on nomination", "2026-05-05T18:00:00")
    carryover_item.action_line = "Cloture filed on the nomination."

    current, prior = main.recent_activity_buckets([carryover_item], now)
    rendered = main.render_material_context_section(prior, "reporter")

    assert current == []
    assert prior == [carryover_item]
    assert "Floor Timing Carryover" in rendered
    assert "may affect the next coverage window" in rendered


def test_empty_current_state_message_uses_operational_language():
    rendered = main.section("Current Coverage Signals", [], "reporter", collapsed=True)

    assert "0 Current Coverage Signals" in rendered
    assert "No current coverage signals." in rendered
    assert "Earlier item. Keep for context only." not in rendered


def test_operational_copy_generation_uses_coverage_window_language():
    rendered = main.render_key_votes_section([], {"schedule_context": {"vote_block": {"date_label": "Monday, May 11", "time_label": "approx. 5:30 p.m."}}}, "reporter")
    outlook = main.coverage_outlook([], {})
    news_empty = main.empty_message("News Events & Stakeouts")

    assert "Next expected vote window" in rendered
    assert "No scheduled press events detected." in outlook
    assert "No scheduled press events detected." in news_empty


def test_current_signal_empty_state_uses_noncontradictory_operational_language():
    rendered = main.section("Current Coverage Signals", [], "reporter", collapsed=True)

    assert "No current coverage signals." in rendered
    assert "No current Senate floor movement." not in rendered


def test_empty_collapsed_sections_can_be_suppressed_for_clean_zero_state():
    rendered = main.section("Current Coverage Signals", [], "reporter", collapsed=True, hide_empty=True)

    assert "hidden" in rendered
    assert "No current coverage signals." not in rendered


def test_visible_coverage_signal_count_matches_rendered_items():
    schedule_context = {
        "vote_block": {"date": "2026-05-11", "date_label": "Monday, May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."],
    }

    signals = main.build_coverage_signal_items({}, schedule_context)
    rendered = main.section("Current Coverage Signals", signals, "reporter", collapsed=True, hide_empty=True)

    assert len(signals) == 2
    assert rendered.count('<article class="card">') == len(signals)
    assert "2 Upcoming Coverage Signals" in rendered
    assert "Upcoming vote window scheduled for Monday, May 11" in rendered
    assert "Cloture vote window listed" in rendered


def test_coverage_signal_section_hidden_when_no_signals_exist():
    rendered = main.section(
        "Current Coverage Signals",
        main.build_coverage_signal_items({}, {}),
        "reporter",
        collapsed=True,
        hide_empty=True,
    )

    assert rendered == '<div hidden data-refresh-key="current-coverage-signals"></div>'
    assert "Current Coverage Signals (1)" not in rendered


def test_upcoming_signal_label_avoids_current_floor_contradiction():
    schedule_context = {
        "next_convening": {"date": "2026-05-11", "date_label": "Monday, May 11", "time_label": "3:00 p.m."}
    }

    signals = main.build_coverage_signal_items({}, schedule_context)
    rendered_section = main.section("Current Coverage Signals", signals, "reporter", collapsed=True)
    rendered_summary = main.render_signal_summary(
        [item.title for item in signals], 0, main.coverage_signal_scope(signals)
    )

    assert "1 Upcoming Coverage Signal" in rendered_section
    assert "1</b>Upcoming Coverage Signal" in rendered_summary
    assert "Scheduled floor convening window listed for Monday, May 11" in rendered_section
    assert "No current Senate floor movement" not in rendered_section + rendered_summary
    assert "No active Senate floor" not in rendered_section + rendered_summary


def test_quick_link_accordions_default_collapsed():
    rendered = main.render_quick_link_groups()

    assert "<details class='link-group' open" not in rendered
    assert rendered.count("data-accordion-key=") == len(main.QUICK_LINK_GROUPS)


def test_coverage_signal_reasons_explain_non_floor_signal_count():
    schedule_context = {
        "vote_block": {"date": "2026-05-11", "date_label": "Monday, May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."],
    }

    reasons = main.coverage_signal_reasons({}, schedule_context)
    rendered = main.render_signal_summary(reasons, 0)

    assert len(reasons) == 2
    assert "Upcoming vote window scheduled for Monday, May 11" in rendered
    assert "Cloture vote window listed" in rendered
    assert rendered.count("<li>") == len(reasons)
    assert "No active Senate floor" not in rendered


def test_empty_floor_remarks_section_is_hidden_when_no_substantive_remarks():
    filler = make_activity_item("Sen. Example spoke about local sports.", "2026-05-06T12:00:00", category="Remarks")
    filler.senators_detected = ["Example"]
    filler.topic = "sports"

    remarks = main.build_floor_remarks([filler])
    rendered = main.section("Floor Remarks", remarks, "reporter", collapsed=True, hide_empty=True)

    assert remarks == []
    assert rendered == '<div hidden data-refresh-key="floor-remarks"></div>'


def test_substantive_floor_remarks_render_when_procedural_or_leadership_related():
    leadership = make_activity_item("Leader remarks on the floor schedule.", "2026-05-06T12:00:00", category="Remarks")
    leadership.senators_detected = ["John Thune"]
    leadership.topic = "schedule"
    cloture = make_activity_item("Sen. Example spoke about cloture on the nomination.", "2026-05-06T13:00:00", category="Remarks")
    cloture.senators_detected = ["Example"]
    cloture.topic = "cloture"

    remarks = main.build_floor_remarks([leadership, cloture])
    rendered = main.section("Floor Remarks", remarks, "reporter", collapsed=True, hide_empty=True)

    assert len(remarks) == 2
    assert "Floor Remarks (2)" in rendered
    assert "John Thune" in rendered
    assert "Example" in rendered


def test_operational_language_avoids_directive_vote_block_copy():
    schedule_context = {
        "vote_block": {"date_label": "Monday, May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."],
    }

    signals = main.build_coverage_signal_items({}, schedule_context)
    actions = main.top_actions([], {"schedule_context": schedule_context})
    rendered = main.section("Current Coverage Signals", signals, "reporter", collapsed=True)

    combined = " ".join(actions) + rendered
    assert "Next major floor coverage window is the announced vote sequence" in " ".join(actions)
    assert "Coverage focus:" in " ".join(actions)
    assert "Prepare for" not in combined
    assert "pre-position" not in combined


def test_homepage_status_expires_completed_pro_forma_without_hiding_future_vote_window():
    now = datetime(2026, 5, 7, 13, 0)
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."],
    }, now)

    signals = main.build_coverage_signal_items({}, schedule_context, now)
    status = main.homepage_operational_status(schedule_context, signals, now)

    assert schedule_context["pro_formas"] == []
    assert any(window["window_type"] == "pro_forma" for window in schedule_context["expired_windows"])
    assert status["status"] == "No active Senate floor proceedings"
    assert status["state"] == "UPCOMING_SESSION"
    assert "announced vote sequence" in status["timing"]
    assert "May 11" in status["timing"]
    assert "5:30" in status["timing"]
    assert schedule_context["expected_votes"]


def test_homepage_status_reports_completed_pro_forma_as_no_active_floor_when_no_future_activity():
    now = datetime(2026, 5, 7, 13, 0)
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
    }, now)

    status = main.homepage_operational_status(schedule_context, [], now)

    assert status["state"] == "COMPLETED_SESSION"
    assert status["status"] == "No active Senate floor proceedings"
    assert status["timing"] == "No active floor coverage window"
    assert "completed a brief pro forma session earlier today" in status["why"]
    assert "Pro forma period" not in status["status"]


def test_homepage_status_state_machine_active_upcoming_completed_low_activity():
    active = main.apply_schedule_window_lifecycle({
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
    }, datetime(2026, 5, 11, 15, 30))
    upcoming = main.apply_schedule_window_lifecycle({
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
    }, datetime(2026, 5, 11, 14, 0))
    completed = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
    }, datetime(2026, 5, 7, 11, 0))

    assert main.homepage_operational_status(active, [], datetime(2026, 5, 11, 15, 30))["state"] == "ACTIVE_SESSION"
    assert main.homepage_operational_status(upcoming, [], datetime(2026, 5, 11, 14, 0))["state"] == "UPCOMING_SESSION"
    assert main.homepage_operational_status(completed, [], datetime(2026, 5, 7, 11, 0))["state"] == "COMPLETED_SESSION"
    assert main.homepage_operational_status({}, [], datetime(2026, 5, 7, 13, 0))["state"] == "LOW_ACTIVITY_PERIOD"


def test_refresh_script_patches_sections_and_preserves_scroll_and_accordions():
    script = (main.BASE_DIR / "static" / "app.js").read_text()

    assert "patchMainContent(nextMain, currentMain, state)" in script
    assert "accordionState(root)" in script
    assert "restoreAccordionState(currentMain, openState)" in script
    assert "restoreScrollIfStable(state)" in script
    assert "window.scrollTo({ left: state.x, top: state.y, behavior: \"auto\" })" in script
    assert "currentMain.innerHTML = nextMain.innerHTML" not in script
    assert "document.createElement(\"div\")" in script
    assert "placeholder.dataset.refreshKey" in script
    assert "patchElementInPlace(currentNode, nextNode)" in script
    assert "document.body.innerHTML" not in script

def test_expired_schedule_signals_do_not_count_or_render():
    schedule_context = main.apply_schedule_window_lifecycle({
        "vote_block": {"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."},
        "expected_votes": ["Motion to invoke cloture on Example nomination."],
        "expected_votes_final": ["Motion to invoke cloture on Example nomination."],
    }, datetime(2026, 5, 7, 13, 0))

    signals = main.build_coverage_signal_items({}, schedule_context, datetime(2026, 5, 7, 13, 0))
    rendered = main.section("Current Coverage Signals", signals, "reporter", collapsed=True, hide_empty=True)

    assert signals == []
    assert rendered == '<div hidden data-refresh-key="current-coverage-signals"></div>'


def test_next_expected_floor_action_omits_expired_pro_forma_and_promotes_vote_window():
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."],
        "source_label": "Public schedule source",
    }, datetime(2026, 5, 7, 10, 45))

    rendered = main.render_next_expected_floor_action(None, {"schedule_context": schedule_context})

    assert "May 7 · 10:00 a.m." not in rendered
    assert "Senate next convenes:</strong> May 11 · 3:00 p.m." in rendered
    assert "Next expected floor vote window:</strong> May 11 · approx. 5:30 p.m." in rendered
    assert "Warsh" in rendered


def test_homepage_logistics_card_hides_expired_pro_forma_section_after_window_passes():
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Example nomination."],
    }, datetime(2026, 5, 7, 13, 0))

    rendered = main.render_next_expected_floor_action(None, {"schedule_context": schedule_context})

    assert "Pro forma sessions" not in rendered
    assert "None announced" not in rendered
    assert "May 7 · 10:00 a.m." not in rendered
    assert "Senate next convenes:</strong> May 11 · 3:00 p.m." in rendered
    assert "Next expected floor vote window:</strong> May 11 · approx. 5:30 p.m." in rendered


def test_homepage_logistics_card_does_not_render_none_announced_pro_forma_section():
    schedule_context = {
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Example nomination."],
    }

    rendered = main.render_next_expected_floor_action(None, {"schedule_context": schedule_context})

    assert "Pro forma sessions" not in rendered
    assert "None announced" not in rendered
    assert "The Senate is scheduled to return after any pro forma sessions" not in rendered
    assert "The announced vote sequence is the next clear floor staffing checkpoint." in rendered


def test_homepage_logistics_card_renders_upcoming_pro_forma_when_relevant():
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "2:00 p.m."}],
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
    }, datetime(2026, 5, 7, 12, 0))

    rendered = main.render_next_expected_floor_action(None, {"schedule_context": schedule_context})

    assert "Pro forma sessions" in rendered
    assert "May 7 · 2:00 p.m." in rendered
    assert "pro forma sequence" in rendered.lower()


def test_homepage_logistics_card_promotes_vote_copy_when_pro_forma_suppressed():
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Example nomination."],
    }, datetime(2026, 5, 7, 13, 0))

    rendered = main.render_next_expected_floor_action(None, {"schedule_context": schedule_context})

    assert "Pro forma sessions" not in rendered
    assert "Logistics note:</strong> The announced vote sequence is the next clear floor staffing checkpoint." in rendered
    assert "Coverage timing:</strong> Next major floor coverage window is the announced vote sequence." in rendered


def test_homepage_logistics_card_structure_preserved_when_pro_forma_suppressed():
    schedule_context = main.apply_schedule_window_lifecycle({
        "pro_formas": [{"date": "2026-05-07", "date_label": "May 7", "time_label": "10:00 a.m."}],
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
        "expected_votes": ["Motion to invoke cloture on Example nomination."],
    }, datetime(2026, 5, 7, 13, 0))

    rendered = main.render_next_expected_floor_action(None, {"schedule_context": schedule_context})

    assert "<div class='card'>" in rendered
    assert "<div class='logistics'>" in rendered
    assert "Senate next convenes:</strong>" in rendered
    assert "Next expected floor vote window:</strong>" in rendered
    assert "Expected votes:</strong><ol>" in rendered
    assert "Logistics note:</strong>" in rendered
    assert "Coverage timing:</strong>" in rendered


def test_refresh_script_defers_passive_updates_while_scrolling():
    script = (main.BASE_DIR / "static" / "app.js").read_text()

    assert "const SCROLL_IDLE_MS = 700" in script
    assert 'window.addEventListener("scroll", markScrolling, { passive: true })' in script
    assert "pendingRefresh = true" in script
    assert "pendingRefreshText = text" in script
    assert "refresh fetch deferred due to scrolling" in script
    assert "if (!manual && scrolling)" in script


def test_refresh_script_preserves_scroll_only_without_user_scroll():
    script = (main.BASE_DIR / "static" / "app.js").read_text()

    restore_body = script.split("function restoreScrollIfStable(state)", 1)[1].split("function markScrolling", 1)[0]
    assert "scrollVersion !== state.scrollVersion" in restore_body
    assert "scroll restore skipped" in restore_body
    assert 'window.scrollTo({ left: state.x, top: state.y, behavior: "auto" })' in restore_body
    assert "scrollTo(0" not in script
    assert "scrollIntoView" not in script


def test_refresh_script_keeps_accordions_mounted_and_does_not_force_focus():
    script = (main.BASE_DIR / "static" / "app.js").read_text()
    patch_body = script.split("function patchDetailsInPlace", 1)[1].split("function patchElementInPlace", 1)[0]

    assert "const wasOpen = currentDetails.open" in patch_body
    assert "currentDetails.open = wasOpen" in patch_body
    assert "currentDetails.replaceWith" not in patch_body
    assert ".focus(" not in script
    assert "activeElementId" in script


def test_header_timestamp_has_stable_width_to_avoid_reflow():
    main_source = (main.BASE_DIR / "app" / "main.py").read_text()

    assert ".last-updated {{ display: inline-block; min-width: 170px;" in main_source
    assert "font-variant-numeric: tabular-nums" in main_source
