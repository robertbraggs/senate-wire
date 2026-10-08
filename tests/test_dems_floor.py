"""Tests for the Senate Democrats floor feed parser. No live internet."""

from app.dems_floor import latest_wrap_up_votes, parse_floor_entries, parse_vote_results

FEED = """
09.30.2026 Schedule for Pro Forma Sessions and Monday November 9, 2026
The Senate stands adjourned for Pro Forma sessions only with no business conducted.
09.30.2026 Wrap Up for Wednesday, September 30, 2026 Roll Call Votes
Motion to invoke cloture on the motion to proceed to Cal. #548 H.R.7008, Stop Insider Trading Act; not agreed to: 53-47.
Motion to invoke cloture on Executive Calendar #912 Keith Sonderling, of Florida, to be Secretary of Labor; agreed to: 53-47.
Confirmation of Executive Calendar #912 Keith Sonderling, of Florida, to be Secretary of Labor; confirmed: 47-41.
Legislative Business Passed the following bills:
09.29.2026 Wrap Up for Tuesday, September 29, 2026 Roll Call Votes
Motion to invoke cloture on the motion to proceed to Cal. #684, H.R.9340, Ratepayer Protection Act; not agreed to: 57-43.
"""


def test_parse_floor_entries():
    entries = parse_floor_entries(FEED)
    assert len(entries) == 3
    assert entries[0]["date"] == "2026-09-30"
    assert entries[0]["type"] == "schedule"
    assert entries[1]["type"] == "wrap_up"


def test_parse_vote_results():
    # parse_vote_results handles a single wrap-up section (first one in FEED)
    votes = parse_vote_results(FEED)
    assert len(votes) == 3
    first = votes[0]
    assert first["action"] == "cloture on motion to proceed"
    assert first["measure"] == "H.R.7008"
    assert first["calendar_no"] == "548"
    assert first["result"] == "not agreed to"
    assert first["tally"] == "53-47"
    assert first["passed"] is False


def test_parse_nomination_votes():
    votes = parse_vote_results(FEED)
    cloture = votes[1]
    assert cloture["action"] == "cloture"
    assert cloture["passed"] is True
    assert "Sonderling" in cloture["title"]
    conf = votes[2]
    assert conf["action"] == "confirmation"
    assert conf["result"] == "confirmed"
    assert conf["tally"] == "47-41"


def test_latest_wrap_up_votes():
    votes = latest_wrap_up_votes(FEED, max_entries=2)
    assert len(votes) == 4
    assert all(v["vote_date"] == "2026-09-30" for v in votes[:3])
    assert votes[3]["vote_date"] == "2026-09-29"


def test_parse_vote_results_empty():
    assert parse_vote_results("no votes here") == []
    assert parse_floor_entries("nothing dated") == []


def test_render_recent_votes():
    import app.main as main

    html = main.render_recent_votes()
    # No cached source in test env -> empty string, no crash
    assert html == ""
