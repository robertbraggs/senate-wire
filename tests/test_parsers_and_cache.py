from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from app.main import (
    classify_floor,
    parse_forward_floor_schedule,
    split_ebb_events,
    parse_ebb_structured_fields,
    classify_ebb,
    split_floor_events,
)
from app.parser import parse_events
from app.source_cache import get_source_snapshot, upsert_source_failure, upsert_source_success

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_floor_schedule_parsing_from_saved_html():
    soup = BeautifulSoup(fixture_text("floor_schedule.html"), "html.parser")
    parsed = parse_forward_floor_schedule(soup.get_text(" "), today=date(2026, 5, 6))

    assert parsed["next_convening"]["date"] == "2026-05-11"
    assert parsed["vote_block"]["time_label"] == "approx. 5:30 p.m."
    assert len(parsed["expected_votes"]) >= 2
    assert any("cloture" in vote.lower() for vote in parsed["expected_votes"])


def test_ebb_event_parsing_from_saved_html():
    soup = BeautifulSoup(fixture_text("ebb.html"), "html.parser")
    raw_text = soup.get_text(" ")
    raw_events = split_ebb_events(raw_text)

    assert raw_events
    structured = parse_ebb_structured_fields(raw_text)
    classified = classify_ebb(raw_text)
    assert structured["title"] == "Senate Leadership Press Conference"
    assert classified["location"] == "S-325"
    assert classified["urgency"] == "move now"


def test_vote_and_cloture_floor_event_parsing():
    events = split_floor_events(fixture_text("floor_events.txt"))
    classes = [classify_floor(event) for event in events]

    assert any(item["title"] == "Roll Call Vote" for item in classes)
    assert any(item["title"] in {"Cloture Vote", "Cloture Invoked"} for item in classes)


def test_procedural_parser_detects_roll_call_and_cloture():
    parsed = parse_events(fixture_text("floor_events.txt"))
    event_types = {event["type"] for event in parsed["timeline"]}

    assert "vote_result" in event_types
    assert "cloture_passed" in event_types or "cloture_vote" in event_types
    assert any("will vote" in item.lower() for item in parsed["future"])


def test_source_failure_preserves_last_successful_snapshot():
    source_name = "pytest_fallback_source"
    upsert_source_success(source_name, {"text": "known-good payload", "url": "fixture://success"})
    upsert_source_failure(source_name, "temporary upstream failure")

    snapshot = get_source_snapshot(source_name)
    assert snapshot is not None
    assert snapshot["status"] == "error"
    assert snapshot["stale"] is True
    assert snapshot["payload"]["text"] == "known-good payload"
    assert "temporary upstream failure" in snapshot["error_message"]

def test_expired_pro_forma_windows_disappear_and_future_vote_promotes():
    sample = """Other than pro formas on Monday, May 4 at 6:45 a.m. and Thursday, May 7 at 10:00 a.m. the Senate will next convene at 3:00 p.m. on Monday, May 11th.
At approximately 5:30pm, 2 roll call votes expected.
Adoption of Calendar #5, S.Res.690, authorizing en bloc consideration in Executive Session of 49 nominations.
Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."""

    parsed = parse_forward_floor_schedule(sample, today=date(2026, 5, 7), now=datetime(2026, 5, 7, 10, 45))

    assert parsed["pro_formas"] == []
    assert any(window["window_type"] == "pro_forma" for window in parsed["expired_windows"])
    assert parsed["next_actionable_window"]["window_type"] == "next_convening"
    assert parsed["next_convening"]["timing_state"] == "UPCOMING"
    assert parsed["vote_block"]["timing_state"] == "UPCOMING"
    assert parsed["expected_votes"]

def test_expired_vote_block_stops_influencing_operational_schedule():
    sample = """The Senate will next convene at 3:00 p.m. on Monday, May 11th.
At approximately 5:30pm, 2 roll call votes expected.
Adoption of Calendar #5, S.Res.690, authorizing en bloc consideration in Executive Session of 49 nominations.
Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."""

    parsed = parse_forward_floor_schedule(sample, today=date(2026, 5, 11), now=datetime(2026, 5, 11, 20, 0))

    assert parsed["next_convening"] == {}
    assert parsed["vote_block"] == {}
    assert parsed["expected_votes"] == []
    assert {window["window_type"] for window in parsed["expired_windows"]} >= {"next_convening", "vote_block"}
    assert parsed["active_windows"] == []
    assert parsed["upcoming_windows"] == []


def test_schedule_window_state_transitions_from_upcoming_to_active_to_expired():
    sample = "The Senate will next convene at 3:00 p.m. on Monday, May 11th."

    upcoming = parse_forward_floor_schedule(sample, today=date(2026, 5, 11), now=datetime(2026, 5, 11, 14, 0))
    active = parse_forward_floor_schedule(sample, today=date(2026, 5, 11), now=datetime(2026, 5, 11, 15, 30))
    expired = parse_forward_floor_schedule(sample, today=date(2026, 5, 11), now=datetime(2026, 5, 11, 17, 0))

    assert upcoming["next_convening"]["timing_state"] == "UPCOMING"
    assert active["next_convening"]["timing_state"] == "ACTIVE"
    assert expired["next_convening"] == {}
    assert expired["expired_windows"][0]["timing_state"] == "EXPIRED"
