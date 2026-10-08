"""Senate Democrats floor page (democrats.senate.gov/floor) parser.

The page publishes structured entries:
- "Schedule for ..." posts: pro forma sessions and return dates
- "Wrap Up for ..." posts: roll call vote results with tallies

Example vote line:
  "Motion to invoke cloture on the motion to proceed to Cal. #548 H.R.7008,
   Stop Insider Trading Act; not agreed to: 53-47."

Parsed into: {action, calendar_no, measure, title, result, tally}
"""

from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional

# "09.30.2026" date prefixes on feed entries
_ENTRY_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")

# "Wrap Up for Wednesday, September 30, 2026" / "Schedule for Pro Forma Sessions and Monday November 9, 2026"
_WRAPUP_TITLE_RE = re.compile(r"Wrap Up for\s+(.+?)(?=\s+Roll Call Votes|\s*$)", re.I)
_SCHEDULE_TITLE_RE = re.compile(r"Schedule for\s+(.+?)(?=\s+The Senate|\s*$)", re.I)

# Vote result: "...; not agreed to: 53-47." / "...; agreed to: 53-47." / "...; confirmed: 47-41." / "...; invoked: 74-25."
_VOTE_RE = re.compile(
    r"(Motion to invoke cloture on the motion to proceed to|"
    r"Motion to invoke cloture on|"
    r"Confirmation of|"
    r"Motion to proceed to|"
    r"Passage of|"
    r"Adoption of)"
    r"\s+([^;]*?)"
    r";\s*(not agreed to|agreed to|confirmed|not confirmed|passed|failed|rejected|adopted|invoked)\s*:\s*(\d{1,3}\s*-\s*\d{1,3})",
    re.I,
)

# "Cal. #548 H.R.7008" / "Executive Calendar #912"
_CAL_NO_RE = re.compile(r"(?:Cal\.|Calendar)\s*#\s*(\d+)", re.I)
_MEASURE_RE = re.compile(r"\b((?:H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.)\s*\d+)\b")


def _parse_entry_date(text: str) -> Optional[date]:
    m = _ENTRY_DATE_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def parse_vote_results(text: str) -> List[Dict]:
    """Extract roll call vote results from wrap-up text."""
    results = []
    # Find the Roll Call Votes section
    start = text.find("Roll Call Votes")
    if start < 0:
        return results
    # End at Legislative Business or end of text
    end = text.find("Legislative Business", start)
    section = text[start:end] if end > 0 else text[start:]
    for m in _VOTE_RE.finditer(section):
        action_raw, detail, result, tally = m.group(1), m.group(2), m.group(3), m.group(4)
        detail = re.sub(r"\s+", " ", detail).strip(" ,")
        cal_m = _CAL_NO_RE.search(detail)
        measure_m = _MEASURE_RE.search(detail)
        # Title is what's left after removing cal # and measure
        title = detail
        if cal_m:
            title = title.replace(cal_m.group(0), "")
        if measure_m:
            title = title.replace(measure_m.group(0), "")
        title = re.sub(r"\s+", " ", title).strip(" ,-–")
        # Nominations: "Executive Calendar #912 Keith Sonderling, of Florida, to be ..."
        nominee_m = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}),\s+of\s+[A-Z][a-z]+,\s+to be\s+(.+?)(?:;|$)", detail)
        label = title
        if nominee_m and not measure_m:
            label = f"{nominee_m.group(1)} — {nominee_m.group(2).strip()}"
        results.append({
            "action": _normalize_action(action_raw),
            "calendar_no": cal_m.group(1) if cal_m else "",
            "measure": measure_m.group(1).replace(" ", "") if measure_m else "",
            "title": label,
            "result": result.lower(),
            "tally": re.sub(r"\s+", "", tally),
            "passed": result.lower() in {"agreed to", "confirmed", "passed", "adopted", "invoked"},
        })
    return results


def _normalize_action(action_raw: str) -> str:
    a = action_raw.lower()
    if "invoke cloture on the motion to proceed" in a:
        return "cloture on motion to proceed"
    if "invoke cloture" in a:
        return "cloture"
    if "confirmation" in a:
        return "confirmation"
    if "motion to proceed" in a:
        return "motion to proceed"
    if "passage" in a:
        return "passage"
    if "adoption" in a:
        return "adoption"
    return action_raw


def parse_floor_entries(feed_text: str) -> List[Dict]:
    """Split the floor feed into dated entries with titles."""
    entries = []
    # Entries start with MM.DD.YYYY date prefixes
    parts = _ENTRY_DATE_RE.split(feed_text)
    # parts[0] is preamble; then groups of (MM, DD, YYYY, body)
    for i in range(1, len(parts), 4):
        if i + 3 >= len(parts):
            break
        try:
            entry_date = date(int(parts[i + 2]), int(parts[i]), int(parts[i + 1]))
        except ValueError:
            continue
        body = parts[i + 3].strip()
        # Title is up to the first sentence or 120 chars
        title_end = body.find(".")
        title = body[:title_end].strip() if 0 < title_end < 150 else body[:120].strip()
        entry_type = "wrap_up" if "wrap up for" in title.lower() else (
            "schedule" if "schedule for" in title.lower() else "other")
        entries.append({
            "date": entry_date.isoformat(),
            "title": re.sub(r"\s+", " ", title),
            "type": entry_type,
            "body": body[:3000],
        })
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def latest_wrap_up_votes(feed_text: str, max_entries: int = 3) -> List[Dict]:
    """Get vote results from the most recent wrap-up entries."""
    votes = []
    for entry in parse_floor_entries(feed_text):
        if entry["type"] != "wrap_up":
            continue
        for v in parse_vote_results(entry["body"]):
            v["vote_date"] = entry["date"]
            votes.append(v)
        if len(votes) >= max_entries * 5:  # ~5 votes per wrap-up
            break
    return votes[:max_entries * 5]
