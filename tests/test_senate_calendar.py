"""Tests for the Senate Calendar of Business integration.

House rule: no live internet in tests. The calendar PDF fetch is stubbed;
parsing is tested against fixture text in the real calendar's format.
"""

from datetime import date

import pytest

from app.senate_calendar import (
    calendar_url_for,
    dated_vote_events,
    extract_uc_section,
    latest_calendar_url,
    parse_uc_agreements,
    summarize_for_dashboard,
)

FIXTURE_TOC = """CALENDAR OF BUSINESS
(UNANIMOUS CONSENT AGREEMENTS ON P. 2)
PREPARED UNDER THE DIRECTION OF JACKIE BARBER,
"""

FIXTURE_SECTION = """H.R. 2347 (ORDER NO. 453)
1.\u2014Ordered, That on Monday, November 9, 2026, upon the conclusion of Morning
Business, the Senate resume consideration of the motion to proceed to H.R. 2347, an
Act to amend the Internal Revenue Code of 1986; provided, that the cloture motion
with respect to the motion to proceed ripen at 5:30 p.m. (Sept. 30, 2026.)
H.R. 3633 (ORDER NO. 423)
2.\u2014Ordered, That with respect to the cloture motion with respect to the motion to
proceed to H.R. 3633, an Act to provide for a system of regulation, the
mandatory quorum call under Rule XXII be waived. (Sept. 15, 2026.)
"""

FIXTURE_FULL = FIXTURE_TOC + "\nUNANIMOUS CONSENT AGREEMENTS\n" + FIXTURE_SECTION + "\x0c3\n\n2026\n"


def test_calendar_url_format():
    url = calendar_url_for(119, date(2026, 10, 9))
    assert url == "https://www.govinfo.gov/content/pkg/CCAL-119scal-2026-10-09/pdf/CCAL-119scal-2026-10-09.pdf"


def test_latest_calendar_url_walks_back():
    seen = []

    def head_fn(url):
        seen.append(url)
        return "2026-10-09" in url  # only the 9th exists

    result = latest_calendar_url(119, today=date(2026, 10, 12), lookback_days=5, head_fn=head_fn)
    assert result is not None
    url, cal_date = result
    assert cal_date == "2026-10-09"
    assert "2026-10-09" in url
    # walked back from the 12th through the 10th
    assert any("2026-10-12" in u for u in seen)
    assert any("2026-10-10" in u for u in seen)


def test_latest_calendar_url_none_when_missing():
    result = latest_calendar_url(119, today=date(2026, 10, 12), lookback_days=2, head_fn=lambda url: False)
    assert result is None


def test_extract_uc_section_skips_toc_reference():
    section = extract_uc_section(FIXTURE_FULL)
    assert "H.R. 2347 (ORDER NO. 453)" in section
    assert "PREPARED UNDER THE DIRECTION" not in section
    assert "\x0c" not in section


def test_extract_uc_section_empty_when_missing():
    assert extract_uc_section("no calendar here") == ""


def test_parse_uc_agreements():
    agreements = parse_uc_agreements(FIXTURE_SECTION)
    assert len(agreements) == 2
    first = agreements[0]
    assert first["measure"] == "H.R. 2347"
    assert first["order_no"] == "453"
    assert first["action"] == "cloture vote"
    assert first["time_labels"] == ["5:30 p.m."]
    assert first["operative_dates"][0]["date"] == "2026-11-09"
    assert first["agreement_date"] == "2026-09-30"
    second = agreements[1]
    assert second["measure"] == "H.R. 3633"
    assert second["operative_dates"] == []


def test_dated_vote_events_never_manufacture_today():
    """The core truth guarantee: a Nov 9 vote is not 'today' on Oct 7."""
    agreements = parse_uc_agreements(FIXTURE_SECTION)
    events = dated_vote_events(agreements, today=date(2026, 10, 7))
    assert len(events) == 1
    assert events[0]["event_date"] == "2026-11-09"
    assert events[0]["is_today"] is False
    assert events[0]["time_label"] == "5:30 p.m."


def test_dated_vote_events_today_when_matching():
    agreements = parse_uc_agreements(FIXTURE_SECTION)
    events = dated_vote_events(agreements, today=date(2026, 11, 9))
    assert len(events) == 1
    assert events[0]["is_today"] is True


def test_dated_vote_events_drop_past_dates():
    agreements = parse_uc_agreements(FIXTURE_SECTION)
    events = dated_vote_events(agreements, today=date(2026, 11, 10))
    assert events == []


def test_summarize_for_dashboard():
    agreements = parse_uc_agreements(FIXTURE_SECTION)
    events = dated_vote_events(agreements, today=date(2026, 10, 7))
    summary = summarize_for_dashboard(events, agreements)
    assert summary["next_vote"]["measure"] == "H.R. 2347"
    assert summary["order_count"] == 2
    assert len(summary["orders"]) == 2


def test_floor_watch_renders_calendar_orders():
    import app.main as main
    schedule_context = {
        "calendar_orders": {
            "next_vote": {
                "measure": "H.R. 2347",
                "order_no": "453",
                "action": "cloture vote",
                "event_date": "2026-11-09",
                "event_weekday": "Monday",
                "time_label": "5:30 p.m.",
                "is_today": False,
                "summary": "H.R. 2347: cloture vote at 5:30 p.m.",
            },
            "orders": [
                {"measure": "H.R. 3633", "order_no": "423", "action": "motion to proceed",
                 "when": "", "text": "quorum waived"},
            ],
            "order_count": 2,
        }
    }
    html = main.render_floor_watch([], schedule_context, date(2026, 10, 7))
    assert "SENATE FLOOR" in html
    assert "Next scheduled vote" in html
    assert "H.R. 2347" in html
    assert "Monday, November 9" in html
    assert "5:30 p.m." in html
    assert "H.R. 3633" in html
    # No phantom "today" language for a future vote
    assert "Expected today" not in html


def test_calendar_vote_block_uses_true_date(monkeypatch):
    """A same-day calendar vote becomes the vote block with the real date."""
    import app.main as main
    from app.senate_calendar import dated_vote_events, parse_uc_agreements, summarize_for_dashboard

    agreements = parse_uc_agreements(FIXTURE_SECTION)
    events = dated_vote_events(agreements, today=date(2026, 11, 9))
    summary = summarize_for_dashboard(events, agreements)
    monkeypatch.setattr(main, "_calendar_orders_context", lambda: summary)
    monkeypatch.setattr(main, "fetch_forward_schedule_sources", lambda: {
        "loaded_sources": [], "texts": [], "errors": {},
    })
    monkeypatch.setattr(main, "et_today", lambda: date(2026, 11, 9))
    debug = main.build_forward_schedule_context()
    ctx = debug["schedule_context"]
    assert ctx["floorStatus"] == "expected_today"
    assert ctx["vote_block"]["date_label"] == "2026-11-09"
    assert ctx["vote_block"]["measure"] == "H.R. 2347"
    assert ctx["vote_block_time_source"] == "senate_calendar"
