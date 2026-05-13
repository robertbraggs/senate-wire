from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from app import main
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


def test_radio_tv_hearing_source_creates_committee_item(monkeypatch):
    html = """
    <html><body>
    Event Date: May 11, 2026 Event Time: 10:00 a.m. Location: SD-226
    Title: Judiciary Committee Hearing Description: Hearing on judicial nominations. Chamber: Senate
    </body></html>
    """

    def fake_fetch(url, timeout=15):
        assert "radiotv.senate.gov" in url
        return html

    monkeypatch.setattr("app.main.fetch_url", fake_fetch)
    items = __import__("app.main", fromlist=["fetch_radio_tv_gallery_items"]).fetch_radio_tv_gallery_items()

    assert len(items) == 1
    item = items[0]
    assert item.category == "Committee Meetings & Hearings"
    assert item.source == "Radio-TV Gallery"
    assert item.location == "SD-226"
    assert item.time_label == "10:00 a.m."
    assert "Judiciary" in (item.committee or item.title)


def test_radio_tv_isolated_time_does_not_create_hearing(monkeypatch):
    html = """
    <html><body>
    Other than pro formas on Monday, May 4 at 6:45 a.m. the Senate will next convene later.
    Senate Radio-TV Gallery office information and archive links. Location: S-325.
    </body></html>
    """

    monkeypatch.setattr("app.main.fetch_url", lambda url, timeout=15: html)

    assert main.fetch_radio_tv_gallery_items() == []


def test_radio_tv_committee_listing_has_structured_committee_card(monkeypatch):
    html = """
    <html><body>
    Event Date: May 12, 2026 Event Time: 2:30 p.m. Location: SD-106
    Title: Senate Committee on Foreign Relations Hearing
    Description: Hearing on nomination of ambassadors. Chamber: Senate
    </body></html>
    """

    monkeypatch.setattr("app.main.fetch_url", lambda url, timeout=15: html)
    items = main.fetch_radio_tv_gallery_items()

    assert len(items) == 1
    assert items[0].category == "Committee Meetings & Hearings"
    assert items[0].section_target == "committee"
    assert "Foreign Relations" in (items[0].committee or items[0].title)
    assert "nomination of ambassadors" in (items[0].topic or items[0].takeaway)


def test_committee_signal_links_to_committee_not_floor_window():
    hearing = main.JoltItem(
        source="Radio-TV Gallery", raw="Judiciary hearing on nominations", date_label="May 11", time_label="10:00 a.m.",
        sort_datetime="2026-05-11T10:00:00", category="Committee Meetings & Hearings", title="Judiciary: Nominations",
        urgency="scheduled", status="confirmed", confidence="medium", quality="committee context with event topic",
        location="SD-226", building="Dirksen", measure=None, takeaway="Judicial nominations", where_to_be="SD-226",
        movement_cue="Arrive before start", who_to_watch="Judiciary", coverage_note="Committee room logistics",
        staff_note="", gallery_note="", senators_detected=[], coverage_target="committee", press_availability="Medium",
        best_window="committee room / public access areas", event_type="Hearing", committee="Judiciary", url="https://www.radiotv.senate.gov/", topic="Judicial nominations",
        section_target="committee",
    )
    main.enrich_public_fields(hearing)

    groups = main.grouped([hearing])
    signals = main.build_coverage_signal_items(groups, {}, datetime(2026, 5, 11, 9, 0))

    assert groups["Committee Meetings & Hearings"] == [hearing]
    assert not groups["Floor Action"]
    assert len(signals) == 1
    assert signals[0].section_target == "committee"
    assert signals[0].url == hearing.url


def test_bad_fallback_labels_are_suppressed_from_public_groups():
    item = main.parse_floor_item("Floor Update: Senators continued routine business.", date(2026, 5, 11))

    groups = main.grouped([item])

    assert item.title == "Floor Update"
    assert all(item not in values for values in groups.values())


def test_convening_countdown_alert_timing():
    context = {"schedule_context": {"next_convening": {"date": "2026-05-11", "time_label": "3:00 p.m."}}}

    far = main.build_alert_signals([], context, datetime(2026, 5, 11, 10, 22))
    inside = main.build_alert_signals([], context, datetime(2026, 5, 11, 14, 15))
    after = main.build_alert_signals([], context, datetime(2026, 5, 11, 15, 5))
    missing = main.build_alert_signals([], {"schedule_context": {}}, datetime(2026, 5, 11, 10, 22))

    assert far[0]["title"] == "Senate convenes later today at 3:00 p.m."
    assert far[0]["body"] != "Convening is inside the next hour."
    assert inside[0]["body"] == "Convening is inside the next hour."
    assert after == []
    assert missing == []


def test_signal_count_matches_visible_valid_signals_only():
    valid = main.JoltItem(
        source="Congress.gov API", raw="HELP hearing on health policy", date_label="May 11", time_label="10:00 a.m.",
        sort_datetime="2026-05-11T10:00:00", category="Committee Meetings & Hearings", title="HELP: Health policy",
        urgency="scheduled", status="confirmed", confidence="high", quality="official", location="SD-430", building="Dirksen",
        measure=None, takeaway="Health policy oversight", where_to_be="SD-430", movement_cue="Arrive before start",
        who_to_watch="HELP", coverage_note="Committee logistics", staff_note="", gallery_note="", senators_detected=[],
        coverage_target="committee", press_availability="Medium", best_window="committee room / public access areas", event_type="Hearing",
        committee="HELP", url="https://www.congress.gov/committee-meetings", topic="Health policy oversight", section_target="committee",
    )
    weak = main.parse_floor_item("Floor Update: Routine floor update at 11:30 a.m. Monitor source before moving.", date(2026, 5, 11))
    main.enrich_public_fields(valid)

    groups = main.grouped([valid, weak])
    signals = main.build_coverage_signal_items(groups, {}, datetime(2026, 5, 11, 9, 0))
    rendered = main.section("Current Coverage Signals", signals, "reporter", collapsed=True, hide_empty=True)

    assert len(signals) == 1
    assert rendered.count('<article class="card">') == len(signals)
    assert f"{len(signals)} Upcoming Coverage" in rendered


def test_known_expected_vote_block_is_preserved_from_expected_vote_list():
    sample = """
    The Senate will next convene at 3:00 p.m. on Monday, May 11, 2026.
    At approximately 5:30 p.m., 2 roll call votes expected.
    Expected votes:
    1. Adoption of Executive Calendar #5, S.Res.690, authorizing en bloc consideration in Executive Session of 49 nominations.
    2. Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination.
    Floor Update: Senators continued routine business.
    """

    parsed = parse_forward_floor_schedule(sample, today=date(2026, 5, 6))

    assert parsed["vote_block"]["time_label"] == "approx. 5:30 p.m."
    assert len(parsed["expected_votes"]) >= 2
    assert any("S.Res.690" in vote for vote in parsed["expected_votes"])
    assert any("Warsh" in vote for vote in parsed["expected_votes"])


def test_generic_floor_update_cannot_overwrite_specific_schedule_data(monkeypatch):
    specific = {
        "key": "senate_dems_schedule",
        "url": "fixture://specific",
        "text": "The Senate will next convene at 3:00 p.m. on Monday, May 11, 2026. At approximately 5:30 p.m., 2 roll call votes expected. Adoption of Executive Calendar #5, S.Res.690. Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination.",
    }
    generic = {
        "key": "radio_tv",
        "url": "fixture://generic",
        "text": "Floor Update. Routine floor update at 11:30 a.m. Monitor source before moving.",
    }

    monkeypatch.setattr("app.main.fetch_forward_schedule_sources", lambda: {"loaded_sources": [], "texts": [generic, specific], "errors": {}})
    parsed = __import__("app.main", fromlist=["build_forward_schedule_context"]).build_forward_schedule_context()["schedule_context"]

    vote_block = parsed.get("vote_block") or next(window for window in parsed["expired_windows"] if window["window_type"] == "vote_block")
    assert vote_block["time_label"] == "approx. 5:30 p.m."
    assert "11:30" not in vote_block["time_label"]
    assert parsed["parsed_expected_vote_count"] == 2


def test_no_no_vote_block_copy_when_expected_votes_exist_without_vote_block():
    rendered = __import__("app.main", fromlist=["render_next_expected_floor_action"]).render_next_expected_floor_action(
        None,
        {"schedule_context": {"expected_votes": ["Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination."]}},
    )

    assert "Motion to invoke cloture" in rendered
    assert "No vote block announced" not in rendered
    assert "timing pending" in rendered


def test_daily_press_gallery_may_11_series_of_two_votes_source_truth():
    sample = """
    Monday, May 11, 2026
    The Senate will next convene at 3:00 p.m. on Monday, May 11, 2026.
    At 5:30 p.m. the Senate proceeds to a series of two votes:
    1. Adoption of S.Res.690 authorizing en bloc consideration in Executive Session of 49 nominations.
    2. Cloture on Kevin Warsh nomination.
    """

    parsed = parse_forward_floor_schedule(sample, today=date(2026, 5, 11))

    assert parsed["next_convening"]["time_label"] == "3:00 p.m."
    assert parsed["vote_block"]["time_label"] == "approx. 5:30 p.m."
    assert parsed["vote_block"]["roll_call_votes_expected"] == 2
    assert len(parsed["expected_votes"]) == 2
    assert any("S.Res.690" in vote and "en bloc" in vote for vote in parsed["expected_votes"])
    assert any("cloture" in vote.lower() and "Warsh" in vote for vote in parsed["expected_votes"])


def test_generic_no_vote_and_floor_update_suppressed_by_specific_daily_press(monkeypatch):
    specific = {
        "key": "daily_press",
        "url": "fixture://daily-press",
        "text": "The Senate will next convene at 3:00 p.m. on Monday, May 11, 2026. At 5:30 p.m. the Senate proceeds to a series of two votes: Adoption of S.Res.690 authorizing en bloc consideration in Executive Session of 49 nominations. Cloture on Kevin Warsh nomination.",
    }
    generic = {
        "key": "radio_tv",
        "url": "fixture://generic",
        "text": "Floor Update. No vote block announced. Routine floor update at 11:30 a.m.",
    }

    monkeypatch.setattr("app.main.fetch_forward_schedule_sources", lambda: {"loaded_sources": [], "texts": [generic, specific], "errors": {}})
    parsed = main.build_forward_schedule_context()["schedule_context"]

    assert parsed["source_name"] == "daily_press"
    vote_block = parsed.get("vote_block") or next(window for window in parsed["expired_windows"] if window["window_type"] == "vote_block")
    assert vote_block["time_label"] == "approx. 5:30 p.m."
    assert parsed["parsed_expected_vote_count"] == 2
    assert all("No vote block announced" not in vote for vote in parsed.get("expected_votes_final", []))
    assert parsed["suppressed_competing_sources"]


def test_generic_committee_listing_does_not_become_public_card_or_signal():
    generic = main.JoltItem(
        source="Congress.gov API", raw="Official Senate committee meeting listing", date_label=None, time_label=None,
        sort_datetime=None, category="Committee Meetings & Hearings", title="Senate Committee",
        urgency="scheduled", status="confirmed", confidence="high", quality="official", location=None, building=None,
        measure=None, takeaway="Official Senate committee meeting listing.", where_to_be="", movement_cue="",
        who_to_watch="Senate Committee", coverage_note="Official committee listing.", staff_note="", gallery_note="",
        senators_detected=[], coverage_target="committee", press_availability="Medium", best_window="committee room / public access areas",
        event_type="Hearing/Meeting", committee="Senate Committee", url="https://www.congress.gov/committee-meetings", topic="",
        section_target="committee",
    )

    groups = main.grouped([generic])
    signals = main.build_coverage_signal_items(groups, {}, datetime(2026, 5, 11, 9, 0))

    assert groups["Committee Meetings & Hearings"] == []
    assert signals == []


def test_committee_item_renders_only_in_committee_section_not_floor_sections():
    hearing = main.JoltItem(
        source="Congress.gov API", raw="Judiciary hearing on judicial nominations", date_label="May 11", time_label="10:00 a.m.",
        sort_datetime="2026-05-11T10:00:00", category="Committee Meetings & Hearings", title="Judiciary: Judicial nominations",
        urgency="scheduled", status="confirmed", confidence="high", quality="official", location="SD-226", building="Dirksen",
        measure=None, takeaway="Judicial nominations", where_to_be="SD-226", movement_cue="Arrive before start",
        who_to_watch="Judiciary", coverage_note="Committee logistics", staff_note="", gallery_note="", senators_detected=[],
        coverage_target="committee", press_availability="Medium", best_window="committee room / public access areas", event_type="Hearing",
        committee="Judiciary", url="https://www.congress.gov/committee-meetings", topic="Judicial nominations", section_target="committee",
    )
    main.enrich_public_fields(hearing)

    groups = main.grouped([hearing])

    assert groups["Committee Meetings & Hearings"] == [hearing]
    assert groups["Floor Action"] == []
    assert groups["Schedule"] == []
    assert groups["Votes"] == []


def test_pre_convening_status_is_not_active_before_gavel():
    context = main.apply_schedule_window_lifecycle({
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
        "vote_block": {"date": "2026-05-11", "date_label": "May 11", "time_label": "approx. 5:30 p.m."},
    }, datetime(2026, 5, 11, 14, 0))

    status = main.homepage_operational_status(context, [], datetime(2026, 5, 11, 14, 0))

    assert status["state"] == "PRE_CONVENING"
    assert status["status"] == "Status: Senate not yet in session"
    assert status["location"] == "Floor / chamber area"
    assert status["timing"] == "Convenes 3:00 p.m.; vote block approx. 5:30 p.m."
    assert status["status"] != "Floor active"


def test_may_11_logistics_signals_preserve_convening_vote_block_and_individual_votes():
    sample = """
    The Senate will next convene at 3:00 p.m. on Monday, May 11, 2026.
    At approximately 5:30 p.m., 2 roll call votes expected.
    Expected votes:
    1. Adoption of Executive Calendar #5, S.Res.690, authorizing en bloc consideration in Executive Session of 49 nominations.
    2. Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination.
    """
    context = parse_forward_floor_schedule(sample, today=date(2026, 5, 11), now=datetime(2026, 5, 11, 14, 0))

    signals = main.build_coverage_signal_items({}, context, datetime(2026, 5, 11, 14, 0))
    rendered = main.section("Current Coverage Signals", signals, "reporter", collapsed=True, hide_empty=True)
    titles = [signal.title for signal in signals]

    assert len(signals) == 4
    assert rendered.count('<article class="card">') == len(signals)
    assert any(title == "Senate convenes — 3:00 p.m." for title in titles)
    assert any(title == "Vote block — approx. 5:30 p.m." for title in titles)
    assert any("Adoption" in title and "S.Res.690" in title for title in titles)
    assert any("Cloture" in title and "Warsh" in title for title in titles)
    assert [signal.signal_type for signal in signals].count("cloture_vote_window") == 1
    assert next(signal for signal in signals if signal.signal_type == "cloture_vote_window").signal_score == 90
    assert next(signal for signal in signals if signal.signal_type == "adoption_vote_window").signal_score == 70


def test_active_session_requires_trusted_floor_confirmation():
    context = main.apply_schedule_window_lifecycle({
        "next_convening": {"date": "2026-05-11", "date_label": "May 11", "time_label": "3:00 p.m."},
    }, datetime(2026, 5, 11, 15, 5))
    unconfirmed = main.homepage_operational_status(context, [], datetime(2026, 5, 11, 15, 5))

    confirmed_item = main.make_coverage_signal_item(
        "Senate convened and resumed consideration of S.Res.690.",
        "current",
        "floor_proceeding_underway",
        "Current",
        "Work the chamber area and watch vote timing.",
        "Official floor activity is underway.",
        source="Congressional Reporters",
    )
    confirmed_item.raw = "10:04 a.m. The Senate convened and resumed consideration of S.Res.690."
    confirmed = main.homepage_operational_status(context, [confirmed_item], datetime(2026, 5, 11, 15, 5))

    assert unconfirmed["state"] == "AWAITING_FLOOR_CONFIRMATION"
    assert unconfirmed["status"] != "Floor active"
    assert confirmed["state"] == "ACTIVE_SESSION"
    assert confirmed["status"] == "Floor active"
    assert confirmed["location"] == "Senate chamber / leadership area"


def test_radio_tv_hash_change_invalidates_floor_watch_and_forces_expected_today(monkeypatch):
    from app.source_cache import upsert_source_success

    upsert_source_success("radio_tv", {"text": "Senate inactive. No announced vote window."})
    radio_text = """
    Senate Floor Schedule
    Roll call votes expected
    At approximately 2:15 p.m., roll call votes expected.
    - Motion to invoke cloture on Executive Calendar #900 Jane Doe nomination.
    """
    upsert_source_success("radio_tv", {"text": radio_text})

    monkeypatch.setattr(main, "fetch_forward_schedule_sources", lambda: {
        "loaded_sources": [{"key": "radio_tv", "url": main.RADIO_TV_URL}],
        "texts": [{"key": "radio_tv", "url": main.RADIO_TV_URL, "text": radio_text}],
        "errors": {},
    })
    main.LAST_FORWARD_SCHEDULE_DEBUG = {"schedule_context": {"floorStatus": "inactive"}}

    debug = main.build_forward_schedule_context()
    parsed = debug["parsed_forward_schedule"]

    assert parsed["radioTvHashChanged"] is True
    assert parsed["floor_watch_cache_invalidated"] is True
    assert parsed["votesDetected"] is True
    assert parsed["floorStatus"] == "expected_today"
    assert parsed["floorStateBefore"] == "inactive"
    assert parsed["floorStateAfter"] == "expected_today"
    assert parsed["voteCount"] >= 1
    assert parsed["parsedVoteTimes"] == ["approx. 2:15 p.m."]
    assert parsed["vote_block"]["time_label"] == "approx. 2:15 p.m."

    status = main.homepage_operational_status(parsed, [], datetime.combine(date.today(), datetime.min.time()))
    assert status["floorStatus"] == "expected_today"
    assert status["state"] == "EXPECTED_TODAY"
    assert status["status"] != "Senate inactive"


def test_radio_tv_vote_detection_recomputes_from_latest_payload_without_prior_inactive(monkeypatch):
    radio_text = "Roll call votes expected at approximately 4:30 p.m."
    monkeypatch.setattr(main, "get_source_snapshot", lambda source_name: {
        "payload": {
            "text": radio_text,
            "content_hash": "latest",
            "previous_content_hash": "latest",
            "hash_changed": False,
        }
    } if source_name == "radio_tv" else None)
    monkeypatch.setattr(main, "fetch_forward_schedule_sources", lambda: {
        "loaded_sources": [{"key": "radio_tv", "url": main.RADIO_TV_URL}],
        "texts": [{"key": "radio_tv", "url": main.RADIO_TV_URL, "text": radio_text}],
        "errors": {},
    })
    main.LAST_FORWARD_SCHEDULE_DEBUG = {"schedule_context": {"floorStatus": "inactive"}}

    parsed = main.build_forward_schedule_context()["parsed_forward_schedule"]

    assert parsed["radioTvHashChanged"] is False
    assert parsed["votesDetected"] is True
    assert parsed["floorStatus"] == "expected_today"
    assert parsed["floorStateAfter"] == "expected_today"
    assert parsed["vote_block"]["time_label"] == "approx. 4:30 p.m."
