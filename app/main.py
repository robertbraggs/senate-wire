from dataclasses import dataclass, asdict
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Tuple, Any
import re
import html
import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from functools import lru_cache


APP_NAME = "The Senate JOLT"
CONGRESSIONAL_REPORTERS_URL = "https://www.dailypress.senate.gov/"
EBB_URL = "https://ebbs.senate.gov/"
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

app = FastAPI(title=APP_NAME, version="8.0.0")


COMMITTEE_SCHEDULE_URL = "https://www.congress.gov/committee-schedule/weekly/2026/04/27?q=%7B%22chamber%22%3A%22Senate%22%7D"
CONGRESS_API_BASE = "https://api.congress.gov/v3"
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

QUICK_LINKS = [
    ("Coverage Rules", "https://www.radiotv.senate.gov/gallery-members/coverage-rules/"),
    ("Coverage Locations", "https://www.radiotv.senate.gov/gallery-members/coverage-locations/"),
    ("Press Secretary Contacts", "https://www.radiotv.senate.gov/gallery-members/press-secretary-contacts/"),
    ("Committee Press Contacts", "https://www.radiotv.senate.gov/gallery-members/commitee-press-contacts/"),
    ("Senate Calendar", "https://www.radiotv.senate.gov/gallery-members/#senate-calendar"),
    ("Roll Call Votes", "https://www.senate.gov/legislative/votes_new.htm"),
    ("Executive Calendar", "https://www.senate.gov/legislative/LIS/executive_calendar/xcalv.pdf"),
    ("Committee Assignments", "https://www.senate.gov/general/committee_assignments/assignments.htm"),
    ("Rules & Procedure", "https://www.senate.gov/legislative/rules_procedure.htm"),
    ("Congressional Record", "https://www.congress.gov/congressional-record"),
    ("Congress.gov Committee Schedule", COMMITTEE_SCHEDULE_URL),
    ("EBB", EBB_URL),
]


SENATORS = [
    {"full": "John Thune", "last": "Thune", "party": "R", "state": "SD", "role": "Majority Leader", "coverage_target": "leadership"},
    {"full": "Chuck Schumer", "last": "Schumer", "party": "D", "state": "NY", "role": "Minority Leader", "coverage_target": "leadership"},
    {"full": "Mitch McConnell", "last": "McConnell", "party": "R", "state": "KY", "role": "Senator", "coverage_target": "leadership"},
    {"full": "Dick Durbin", "last": "Durbin", "party": "D", "state": "IL", "role": "Minority Whip", "coverage_target": "leadership"},
    {"full": "James Lankford", "last": "Lankford", "party": "R", "state": "OK", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Susan Collins", "last": "Collins", "party": "R", "state": "ME", "role": "Senator", "coverage_target": "committee"},
    {"full": "Lisa Murkowski", "last": "Murkowski", "party": "R", "state": "AK", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Rand Paul", "last": "Paul", "party": "R", "state": "KY", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Bernie Sanders", "last": "Sanders", "party": "I", "state": "VT", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Elizabeth Warren", "last": "Warren", "party": "D", "state": "MA", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Ted Cruz", "last": "Cruz", "party": "R", "state": "TX", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Amy Klobuchar", "last": "Klobuchar", "party": "D", "state": "MN", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Lindsey Graham", "last": "Graham", "party": "R", "state": "SC", "role": "Senator", "coverage_target": "committee"},
    {"full": "Cory Booker", "last": "Booker", "party": "D", "state": "NJ", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Mike Lee", "last": "Lee", "party": "R", "state": "UT", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Brian Schatz", "last": "Schatz", "party": "D", "state": "HI", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Alex Padilla", "last": "Padilla", "party": "D", "state": "CA", "role": "Senator", "coverage_target": "issue senator"},
    {"full": "Ron Wyden", "last": "Wyden", "party": "D", "state": "OR", "role": "Senator", "coverage_target": "committee"},
    {"full": "Chris Murphy", "last": "Murphy", "party": "D", "state": "CT", "role": "Senator", "coverage_target": "issue senator"},
]

SENATOR_MAP = {x["full"]: x for x in SENATORS}
for _s in SENATORS:
    _s["party_state"] = f"{_s['party']}-{_s['state']}"

MANUAL_GALLERY_NOTES = []
SEARCHABLE_LINK_LABELS = " ".join(name for name, _ in QUICK_LINKS).lower()


@dataclass
class JoltItem:
    source: str
    raw: str
    date_label: Optional[str]
    time_label: Optional[str]
    sort_datetime: Optional[str]
    category: str
    title: str
    urgency: str
    status: str
    confidence: str
    quality: str
    location: Optional[str]
    building: Optional[str]
    measure: Optional[str]
    takeaway: str
    where_to_be: str
    movement_cue: str
    who_to_watch: str
    coverage_note: str
    staff_note: str
    gallery_note: str
    senators_detected: List[str]
    coverage_target: Optional[str]
    press_availability: str
    best_window: str
    event_type: Optional[str]
    committee: Optional[str]
    url: Optional[str]
    topic: Optional[str]
    congress_bill_title: Optional[str] = None
    congress_latest_action: Optional[str] = None
    congress_policy_area: Optional[str] = None
    congress_sponsors: Optional[str] = None
    congress_url: Optional[str] = None
    congress_summary: Optional[str] = None
    congress_official_context: Optional[str] = None
    action_line: str = ""


SOURCE_STATUS = {
    "congressional_reporters": "not loaded",
    "ebb": "not loaded",
    "congress_api": "disabled: missing CONGRESS_API_KEY" if not CONGRESS_API_KEY else "loaded",
    "committee_schedule": "linked",
    "congressional_record": "linked/API available",
}


def clean(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def fetch_url(url: str, timeout: int = 20) -> str:
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 TheSenateJOLT/7.1"},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


def remove_noise(soup: BeautifulSoup) -> None:
    for selector in [
        "script", "style", "noscript", "nav", "header", "footer", "aside",
        ".menu", ".sidebar", ".widget", ".calendar", ".archive", ".pagination",
        ".search", ".site-header", ".site-footer",
    ]:
        for tag in soup.select(selector):
            tag.decompose()


def parse_date(line: str) -> Optional[date]:
    patterns = [
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})",
        r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, line)
        if not m:
            continue

        try:
            if len(m.groups()) == 4:
                return datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%B %d %Y").date()
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
        except ValueError:
            continue

    return None


def parse_time(line: str) -> Optional[time]:
    m = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?)\b",
        line,
        re.I,
    )
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    period = m.group(3).lower().replace(".", "")

    if period == "pm" and hour != 12:
        hour += 12
    if period == "am" and hour == 12:
        hour = 0

    try:
        return time(hour, minute)
    except ValueError:
        return None


def fmt_date(d: Optional[date]) -> Optional[str]:
    if not d:
        return None
    return d.strftime("%A, %B %d, %Y").replace(" 0", " ")


def fmt_time(t: Optional[time]) -> Optional[str]:
    if not t:
        return None
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'a.m.' if t.hour < 12 else 'p.m.'}"


def sort_dt(d: Optional[date], t: Optional[time]) -> Optional[str]:
    if d and t:
        return datetime.combine(d, t).isoformat()
    if d:
        return datetime.combine(d, time(23, 59)).isoformat()
    return None


def extract_measure(text: str) -> Optional[str]:
    m = re.search(
        r"\b((?:H\.R\.|S\.|S\.Res\.|S\. Res\.|S\.J\.Res\.|S\.J\. Res\.|H\.J\. Res\.|H\. Res\.)\s*\d+)",
        text,
        re.I,
    )
    return clean(m.group(1)) if m else None


def normalize_room(room: str) -> str:
    room = clean(room)
    room = re.sub(r"\bSD\s?(\d)", r"SD-\1", room, flags=re.I)
    room = re.sub(r"\bSH\s?(\d)", r"SH-\1", room, flags=re.I)
    room = re.sub(r"\bSR\s?(\d)", r"SR-\1", room, flags=re.I)

    if re.match(r"^(SD|SH|SR|S)-", room, re.I):
        return room.upper()

    if room.lower() == "ohio clock":
        return "Ohio Clock"

    return room


def infer_location(text: str) -> Optional[str]:
    patterns = [
        r"\bS-325\b",
        r"\bS-316\b",
        r"\b(?:SD|SH|SR)-?\s?\d+[A-Z]?\b",
        r"\bS-\d+[A-Z]?\b",
        r"\bDirksen\s+\d+[A-Z]?\b",
        r"\bHart\s+\d+[A-Z]?\b",
        r"\bRussell\s+\d+[A-Z]?\b",
        r"\bOhio Clock\b",
        r"\bSenate subway\b",
        r"\bSenate Radio-TV Gallery\b",
        r"\bCongressional Reporters Gallery\b",
        r"\bCapitol\s+[A-Z0-9-]+\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return normalize_room(clean(m.group(0)))

    return None


def infer_building(location: Optional[str]) -> Optional[str]:
    if not location:
        return None

    loc = location.upper()

    if loc.startswith("SD-") or "DIRKSEN" in loc:
        return "Dirksen Senate Office Building"
    if loc.startswith("SH-") or "HART" in loc:
        return "Hart Senate Office Building"
    if loc.startswith("SR-") or "RUSSELL" in loc:
        return "Russell Senate Office Building"
    if loc == "S-325":
        return "Senate Radio-TV Gallery"
    if loc == "S-316":
        return "Congressional Reporters Gallery"
    if loc.startswith("S-") or "CAPITOL" in loc:
        return "Capitol / Senate side"
    if "OHIO CLOCK" in loc:
        return "Ohio Clock corridor"
    if "SUBWAY" in loc:
        return "Senate subway routes"

    return None


def is_junk(text: str) -> bool:
    lower = text.lower()

    return (
        any(
            x in lower
            for x in [
                "skip to content",
                "search search",
                "radio-tv galleries",
                "senate floor archives",
                "u.s. senate press gallery phone",
                "previous page",
                "next page",
                "opens in a new tab",
            ]
        )
        or len(re.findall(r"\b\d{1,2}\b", text)) > 90
    )


def shorten(text: str, limit: int = 620) -> str:
    text = clean(text)
    if len(text) <= limit:
        return text
    return clean(text[:limit].rsplit(" ", 1)[0]) + "..."


def friendly_status(key: str) -> str:
    value = SOURCE_STATUS.get(key, "unknown")

    replacements = {
        "loaded: no event-like items parsed": "loaded; no scheduled media events parsed",
        "disabled: missing X_BEARER_TOKEN": "disabled",
    }

    return replacements.get(value, value)


def extract_congressional_reporters_text() -> str:
    try:
        soup = BeautifulSoup(fetch_url(CONGRESSIONAL_REPORTERS_URL), "html.parser")
        SOURCE_STATUS["congressional_reporters"] = "loaded"
    except Exception as exc:
        SOURCE_STATUS["congressional_reporters"] = f"error: {exc}"
        return ""

    remove_noise(soup)
    candidates = []

    for selector in [".entry-content", ".post-content", ".page-content", "article", "main"]:
        for block in soup.select(selector):
            text = clean(block.get_text(" "))
            if not text:
                continue

            score = (
                len(re.findall(r"\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.)", text, re.I)) * 5
                + text.lower().count("vote") * 4
                + text.lower().count("cloture") * 4
                - text.lower().count("previous page") * 50
                - text.lower().count("senate floor archives") * 50
            )
            candidates.append((score, text))

    text = max(candidates, key=lambda x: x[0])[1] if candidates else clean(soup.get_text(" "))

    for marker in [
        "« Previous Page", "Previous Page", "Senate Hearings & Meetings",
        "Follow Us", "RADIO-TV GALLERIES", "Senate Live Feed",
        "Senate Floor Archives", "U.S. Senate Press Gallery",
    ]:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]

    return clean(text)


def split_floor_events(text: str) -> List[str]:
    text = clean(text)
    if not text:
        return []

    text = re.sub(
        r"(?=(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        "\n",
        text,
    )
    text = re.sub(
        r"(?<!\d)(?=\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.))",
        "\n",
        text,
        flags=re.I,
    )

    events = []

    for piece in [clean(x) for x in text.split("\n") if clean(x)]:
        if len(piece) < 20 or is_junk(piece):
            continue
        if "vote" in piece.lower() and len(piece) < 80:
            continue
        events.append(shorten(piece, 760))

    seen = set()
    unique = []

    for event in events:
        key = event.lower()
        if key not in seen:
            seen.add(key)
            unique.append(event)

    return unique


def classify_floor(raw: str) -> Dict[str, str]:
    lower = raw.lower()

    if "now voting" in lower:
        title, category, urgency = "Vote Underway", "Votes", "move now"
        takeaway = "The Senate is actively voting."
        where = "Ohio Clock, chamber exits, Senate subway, or usual stakeout route."
        movement = "Move now if this vote is current; if historical, use only for context."
        watch = "Leadership, bill sponsors, opponents, affected-state Senators."
        coverage = "High-value hallway window. Be in position before Senators finish voting."
        staff = "Vote result determines immediate floor posture."
        gallery = "Expect member movement around chamber exits and subway routes."

    elif "by a vote of" in lower or "roll call vote" in lower:
        title, category, urgency = "Roll Call Vote", "Votes", "watch"
        takeaway = "The Senate recorded a vote."
        where = "Post-vote exits, Ohio Clock, stakeout positions, or Senator office routes."
        movement = "Good reaction window immediately after the vote."
        watch = "Sponsors, opponents, party leaders, swing votes, absences."
        coverage = "Good moment for reaction, especially if vote was close or procedural."
        staff = "Check vote margin, absences, and whether the question advanced."
        gallery = "Post-vote hallway movement may be brief; monitor quickly."

    elif "motion to invoke cloture" in lower:
        title, category, urgency = "Cloture Vote", "Votes", "move now"
        takeaway = "The Senate is voting or scheduled to vote on limiting debate."
        where = "Ohio Clock or chamber exits before the vote starts."
        movement = "Move before the vote window; cloture votes often shape the rest of the floor day."
        watch = "Leadership, bill managers, nominees’ home-state Senators, undecided Senators."
        coverage = "Cloture determines whether floor timing becomes more predictable."
        staff = "If invoked, the matter enters limited debate before disposition."
        gallery = "Treat as a major procedural timing vote."

    elif "invoked cloture" in lower:
        title, category, urgency = "Cloture Invoked", "Floor Action", "watch"
        takeaway = "Debate has been limited; the Senate is moving toward final action."
        where = "Monitor chamber exits and leadership routes after the vote."
        movement = "Watch for final vote timing and post-cloture agreement."
        watch = "Leadership, floor managers, opponents, nomination stakeholders."
        coverage = "Final vote timing may become clearer after this."
        staff = "Post-cloture time, amendments, and final disposition are next."
        gallery = "Flag likely next vote window once announced."

    elif "filed cloture" in lower or "file cloture" in lower:
        title, category, urgency = "Cloture Filed", "Floor Action", "watch"
        takeaway = "Leadership started the Rule XXII process."
        where = "No immediate movement required unless tied to leader remarks."
        movement = "Add to future vote watch list."
        watch = "Majority Leader, Minority Leader, bill managers."
        coverage = "This sets up a future vote and signals leadership’s floor plan."
        staff = "Track ripening time and any UC agreement that changes timing."
        gallery = "Add to vote watch list."

    elif "unanimous consent" in lower or "no objection" in lower or "objected" in lower:
        title, category, urgency = "Unanimous Consent", "Floor Action", "watch"
        takeaway = "The Senate acted, or attempted to act, by consent."
        where = "If objection occurred, watch the objecting Senator and requesting Senator."
        movement = "Potential hallway follow-up if a Senator objected or forced a negotiation."
        watch = "Requester, objector, leadership, affected committee members."
        coverage = "UC exchanges often reveal negotiations, objections, or quick passage."
        staff = "Terms of the agreement control next steps."
        gallery = "Potential hallway follow-up if objection is newsworthy."

    elif "passed by voice vote" in lower:
        title, category, urgency = "Passed by Voice Vote", "Floor Action", "watch"
        takeaway = "The Senate passed a measure without a recorded vote."
        where = "Watch bill sponsor or objectors if politically salient."
        movement = "No vote-window movement, but sponsor reaction may be useful."
        watch = "Sponsor, relevant committee leaders, affected-state Senators."
        coverage = "No roll call means no vote-window movement, but passage may still be newsworthy."
        staff = "Check whether House action, enrollment, or presidential action is next."
        gallery = "Good for quick alert rather than stakeout unless high-profile."

    elif "motion to discharge" in lower:
        title, category, urgency = "Discharge Motion", "Floor Action", "watch"
        takeaway = "A Senator is trying to bring a matter out of committee."
        where = "Watch sponsor, committee chair/ranking member, and leadership."
        movement = "Reaction window after vote or objection."
        watch = "Motion sponsor, committee leaders, party leadership."
        coverage = "Discharge fights can signal pressure on leadership or committees."
        staff = "If agreed to, matter may become available for floor action."
        gallery = "Monitor for post-vote reaction."

    elif "will convene" in lower or "senate convened" in lower or "next convene" in lower:
        title, category, urgency = "Senate Schedule", "Schedule", "scheduled"
        takeaway = "Sets convening time or expected floor schedule."
        where = "Plan arrival before leader remarks or first scheduled vote."
        movement = "Use this as the day’s first movement anchor."
        watch = "Leaders and Senators tied to scheduled business."
        coverage = "Use this to plan movement and staffing for the day."
        staff = "Schedule may be changed by UC or leadership announcement."
        gallery = "Baseline for next-day coverage planning."

    elif "adjourn" in lower:
        title, category, urgency = "Adjournment", "Schedule", "low"
        takeaway = "The Senate ended its sitting until the next session."
        where = "No floor stakeout unless Senators remain nearby."
        movement = "Coverage window has likely closed unless members remain in the building."
        watch = "Leadership if next schedule is unresolved."
        coverage = "Useful for planning the next coverage window."
        staff = "Floor action pauses until next convening."
        gallery = "Update schedule boards and next expected coverage time."

    elif "spoke on" in lower or "spoke about" in lower:
        title, category, urgency = "Floor Remarks", "Remarks", "low"
        takeaway = "A Senator made floor remarks."
        where = "No immediate location change unless remarks preview action."
        movement = "Monitor only if remarks are tied to a vote, objection, or announcement."
        watch = "Speaking Senator and Senators named in the issue area."
        coverage = "Useful for messaging; lower value for access unless tied to votes."
        staff = "Monitor whether remarks lead to a motion, UC request, or objection."
        gallery = "Clip or note if issue is active for coverage."

    else:
        title, category, urgency = "Floor Update", "Notes", "low"
        takeaway = "General floor update."
        where = "Monitor source before moving."
        movement = "No movement recommended unless tied to a vote, event, or named Senator."
        watch = "Relevant Senators named in the update."
        coverage = "Review context before assigning coverage."
        staff = "Procedural significance unclear from parsed text alone."
        gallery = "Hold as background unless tied to a vote or media event."

    return {
        "category": category,
        "title": title,
        "urgency": urgency,
        "status": "confirmed" if category != "Notes" else "inferred",
        "confidence": "high" if category != "Notes" else "medium",
        "quality": "Congressional Reporters feed",
        "takeaway": takeaway,
        "where_to_be": where,
        "movement_cue": movement,
        "who_to_watch": watch,
        "coverage_note": coverage,
        "staff_note": staff,
        "gallery_note": gallery,
    }




LEADERSHIP_NAMES = ["Thune", "Schumer", "McConnell", "Durbin"]


def compute_press_availability(item: JoltItem) -> tuple[str, str]:
    text = f"{item.title} {item.raw}".lower()
    if any(k in text for k in ["vote underway", "now voting", "cloture", "stakeout", "press conference", "media availability"]):
        level = "High"
    elif any(k in text for k in ["unanimous consent", "objected", "hearing", "markup"]):
        level = "Medium"
    else:
        level = "Low"

    if "vote" in text:
        window = "after vote" if "ended" in text or "by a vote of" in text else "before vote"
    elif "hearing" in text or "markup" in text:
        window = "outside hearing room"
    else:
        window = "scheduled event location"

    return level, window


def normalize_ebb_location_text(text: str) -> str:
    text = re.sub(r"\b(SD|SH|SR)\s*(\d+[A-Z]?)\b", r"\1-\2", text, flags=re.I)
    return clean(text)

def apply_past_status(item: JoltItem) -> JoltItem:
    if not item.sort_datetime:
        return item

    try:
        dt = datetime.fromisoformat(item.sort_datetime)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
    except ValueError:
        return item

    now = datetime.now()

    if dt < now - timedelta(minutes=45):
        item.status = "historical"
        item.urgency = "low"
        item.movement_cue = "Coverage window has likely passed; useful for record/context."
        item.coverage_note = "Earlier item. Do not move based on this unless there is follow-up activity."
        item.gallery_note = "Earlier item; keep for reference unless coverage continues."
        item.staff_note = "Earlier item; use for procedural context."
        if item.category in {"Votes", "Floor Action", "Events", "Schedule"}:
            item.category = "Earlier Floor Activity"

    return item


def detect_senators(text: str) -> List[str]:
    found = []
    for senator in SENATORS:
        full = senator["full"]
        last = senator["last"]
        patterns = [
            rf"\b{re.escape(full)}\b",
            rf"\bSenator\s+{re.escape(last)}\b",
            rf"\bLeader\s+{re.escape(last)}\b",
            rf"\b{re.escape(last)}\b",
        ]
        if any(re.search(p, text, re.I) for p in patterns):
            found.append(full)
    return found


def extract_speaker(text: str) -> Optional[str]:
    senators = detect_senators(text)
    return senators[0] if senators else None


def extract_topic(text: str) -> Optional[str]:
    patterns = [
        r"spoke on ([^.;]+)",
        r"spoke about ([^.;]+)",
        r"spoke regarding ([^.;]+)",
        r"spoke in support of ([^.;]+)",
        r"spoke in opposition to ([^.;]+)",
        r"asked unanimous consent to proceed to ([^.;]+)",
        r"objected to ([^.;]+)",
        r"hearing to examine ([^.;]+)",
        r"to hold hearings to examine ([^.;]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return clean(m.group(1)).rstrip(",")
    return None




def parse_measure_for_congress_api(measure: str, default_congress: int = 119) -> Optional[Dict[str, str]]:
    if not measure:
        return None
    m = re.search(r"\b(S\.|S\.Res\.|S\.J\.Res\.|H\.R\.|H\.J\.Res\.)\s*(\d+)\b", measure, re.I)
    if not m:
        return None
    kind = m.group(1).lower().replace(" ", "")
    mapping = {"s.": "s", "s.res.": "sres", "s.j.res.": "sjres", "h.r.": "hr", "h.j.res.": "hjres"}
    bill_type = mapping.get(kind)
    if not bill_type:
        return None
    return {"congress": str(default_congress), "billType": bill_type, "billNumber": m.group(2)}


def coverage_value_for_item(item: JoltItem) -> str:
    text = f"{item.title} {item.raw}".lower()
    if any(k in text for k in ["vote underway", "roll call", "cloture", "stakeout", "press conference", "media availability"]) or any(s in LEADERSHIP_NAMES for s in item.senators_detected):
        return "High"
    if any(k in text for k in ["unanimous consent", "objected", "hearing", "markup", "nomination"]) or item.senators_detected:
        return "Medium"
    return "Low"
def classify_coverage_target(item: JoltItem) -> Optional[str]:
    return infer_coverage_target(item.raw, item.senators_detected, item.committee, item.measure)


def current_congress() -> int:
    year = datetime.now().year
    return 119 + max(0, (year - 2025) // 2)


def parse_measure_for_congress_api(measure: Optional[str]) -> Optional[Tuple[int, str, str]]:
    if not measure:
        return None
    text = clean(measure).replace(" ", "").lower()
    patterns = {
        r"^s\.(\d+)$": "s",
        r"^s\.res\.(\d+)$": "sres",
        r"^s\.j\.res\.(\d+)$": "sjres",
        r"^h\.r\.(\d+)$": "hr",
        r"^h\.j\.res\.(\d+)$": "hjres",
    }
    for pattern, bill_type in patterns.items():
        m = re.match(pattern, text)
        if m:
            return current_congress(), bill_type, m.group(1)
    return None


@lru_cache(maxsize=256)
def congress_api_get(path: str) -> Dict[str, Any]:
    if not CONGRESS_API_KEY:
        raise RuntimeError("missing key")
    url = f"{CONGRESS_API_BASE}{path}"
    r = requests.get(url, params={"api_key": CONGRESS_API_KEY, "format": "json"}, timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_congress_bill_info(measure: Optional[str]) -> Dict[str, Optional[str]]:
    if not measure:
        return {}
    search_url = f"https://www.congress.gov/search?q=%7B%22search%22%3A%22{measure}%22%7D"
    parsed = parse_measure_for_congress_api(measure)
    if not parsed or not CONGRESS_API_KEY:
        return {"congress_url": search_url}
    congress, bill_type, bill_number = parsed
    try:
        bill = congress_api_get(f"/bill/{congress}/{bill_type}/{bill_number}").get("bill", {})
        latest = bill.get("latestAction", {})
        actions = congress_api_get(f"/bill/{congress}/{bill_type}/{bill_number}/actions").get("actions", [])
        summaries = congress_api_get(f"/bill/{congress}/{bill_type}/{bill_number}/summaries").get("summaries", [])
        sponsors = ", ".join([s.get("fullName", "") for s in bill.get("sponsors", [])[:3] if s.get("fullName")])
        latest_action = (actions[0].get("text") if actions else None) or latest.get("text")
        summary = (summaries[0].get("text") if summaries else None) or ""
        summary = clean(summary)[:300] if summary else None
        return {
            "congress_bill_title": bill.get("title"),
            "congress_latest_action": latest_action,
            "congress_policy_area": (bill.get("policyArea") or {}).get("name"),
            "congress_sponsors": sponsors or None,
            "congress_url": bill.get("url") or search_url,
            "congress_summary": summary,
        }
    except Exception:
        SOURCE_STATUS["congress_api"] = "error"
        return {"congress_url": search_url}


def infer_coverage_target(raw: str, senators: List[str], committee: Optional[str], measure: Optional[str]) -> Optional[str]:
    if senators:
        targets = [SENATOR_MAP[s]["coverage_target"] for s in senators if s in SENATOR_MAP]
        if "leadership" in targets:
            return "leadership"
        if measure:
            return "sponsor"
        if committee:
            return "committee"
        return "issue senator"
    if committee:
        return "committee"
    if measure:
        return "sponsor"
    return None


def parse_floor_item(raw: str, fallback_date: Optional[date]) -> JoltItem:
    d = parse_date(raw) or fallback_date
    t = parse_time(raw)
    c = classify_floor(raw)
    measure = extract_measure(raw)
    committee = infer_ebb_committee(raw)
    senators = detect_senators(raw)
    coverage_target = infer_coverage_target(raw, senators, committee, measure)

    if c["category"] == "Remarks" and senators:
        lead = senators[0]
        c["title"] = f"Remarks: {lead}"
        c["takeaway"] = f"{lead} made floor remarks."
        c["who_to_watch"] = lead
        c["movement_cue"] = f"Watch {lead} for hallway follow-up if tied to active floor business."

    if c["category"] == "Notes":
        if senators:
            c["title"] = f"Floor Note: {senators[0]}"
            c["takeaway"] = f"Floor note referencing {senators[0]}."
        elif measure:
            c["title"] = f"Floor Note: {measure}"
            c["takeaway"] = f"Floor note tied to {measure}."

    topic = extract_topic(raw)
    item = JoltItem(
        source="Congressional Reporters",
        raw=raw,
        date_label=fmt_date(d),
        time_label=fmt_time(t),
        sort_datetime=sort_dt(d, t),
        category=c["category"],
        title=c["title"],
        urgency=c["urgency"],
        status=c["status"],
        confidence=c["confidence"],
        quality=c["quality"],
        location="Senate floor / chamber area" if c["category"] in {"Votes", "Floor Action", "Schedule"} else None,
        building="Capitol / Senate side" if c["category"] in {"Votes", "Floor Action", "Schedule"} else None,
        measure=measure,
        takeaway=c["takeaway"],
        where_to_be=c["where_to_be"],
        movement_cue=c["movement_cue"],
        who_to_watch=c["who_to_watch"],
        coverage_note=c["coverage_note"],
        staff_note=c["staff_note"],
        gallery_note=c["gallery_note"],
        senators_detected=senators,
        coverage_target=coverage_target,
        press_availability="",
        best_window="",
        event_type=None,
        committee=committee,
        url=CONGRESSIONAL_REPORTERS_URL,
        topic=topic,
    )
    item.coverage_target = classify_coverage_target(item)
    item.__dict__.update(fetch_congress_bill_info(item.measure))

    return apply_past_status(item)


def get_floor_items() -> List[JoltItem]:
    raw_events = split_floor_events(extract_congressional_reporters_text())

    fallback_date = None
    for event in raw_events:
        fallback_date = parse_date(event)
        if fallback_date:
            break

    items = [parse_floor_item(event, fallback_date) for event in raw_events]
    items.sort(key=lambda x: (x.sort_datetime is None, x.sort_datetime or "9999"))

    return items


def infer_ebb_title(text: str) -> str:
    lower = text.lower()

    if "stakeout" in lower:
        return "Stakeout"
    if "press conference" in lower:
        return "Press Conference"
    if "media availability" in lower or "availability" in lower:
        return "Media Availability"
    if "briefing" in lower:
        return "Briefing"
    if "hearing" in lower:
        return "Hearing"
    if "business meeting" in lower:
        return "Business Meeting"
    if "markup" in lower:
        return "Markup"
    if "photo spray" in lower:
        return "Photo Spray"
    if "camera spray" in lower:
        return "Camera Spray"
    if "pen and pad" in lower:
        return "Pen and Pad"

    if infer_ebb_committee(text) and parse_time(text):
        return f"{infer_ebb_committee(text)} Event"
    return "EBB Event"


def extract_ebb_room(text: str) -> Optional[str]:
    m = re.search(r"\b(?:SD|SH|SR|S)-?\s?\d{1,4}[A-Z]?\b", text, flags=re.I)
    if not m:
        return None
    return normalize_room(m.group(0))


def infer_ebb_committee(text: str) -> Optional[str]:
    patterns = [
        r"\bSenate\s+Committee\s+on\s+([A-Za-z0-9 ,.&'/-]+?)(?:\s+(?:will|to|for|at)\b|$)",
        r"\bCommittee\s+on\s+([A-Za-z0-9 ,.&'/-]+?)(?:\s+(?:will|to|for|at)\b|$)",
        r"\bCommittee\s+of\s+([A-Za-z0-9 ,.&'/-]+?)(?:\s+(?:will|to|for|at)\b|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return f"Committee on {clean(m.group(1))[:90]}"

    m = re.search(r"\b(Appropriations|Armed Services|Banking(?:, Housing, and Urban Affairs)?|Budget|Commerce(?:, Science, and Transportation)?|Energy and Natural Resources|Environment and Public Works|Finance|Foreign Relations|Health, Education, Labor, and Pensions|HELP|Homeland Security(?: and Governmental Affairs)?|Judiciary|Rules(?: and Administration)?|Small Business(?: and Entrepreneurship)?|Veterans'? Affairs|Agriculture(?:, Nutrition, and Forestry)?|Intelligence|Aging)\b", text, flags=re.I)
    if m:
        return clean(m.group(1))

    return None


def split_ebb_events(text: str) -> List[str]:
    text = clean(text)
    if not text:
        return []

    text = re.sub(
        r"(?=\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|a\.m\.|p\.m\.)\b)",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"(?=\b(?:stakeout|press conference|media availability|briefing|hearing|business meeting|markup|photo spray|camera spray)\b)",
        "\n",
        text,
        flags=re.I,
    )

    pieces = [clean(p) for p in text.split("\n") if clean(p)]
    events = []

    for piece in pieces:
        if len(piece) < 20 or is_junk(piece):
            continue

        if not (
            parse_time(piece)
            or infer_location(piece)
            or any(
                x in piece.lower()
                for x in ["stakeout", "press", "hearing", "markup", "briefing", "availability", "meeting"]
            )
        ):
            continue

        events.append(shorten(piece, 800))

    seen = set()
    unique = []

    for event in events:
        key = event.lower()
        if key not in seen:
            seen.add(key)
            unique.append(event)

    return unique[:40]


def classify_ebb(raw: str) -> Dict[str, str]:
    raw = normalize_ebb_location_text(raw)
    title = infer_ebb_title(raw)
    location = extract_ebb_room(raw) or infer_location(raw)
    building = infer_building(location)
    committee = infer_ebb_committee(raw)
    lower = raw.lower()
    parsed_time = parse_time(raw)

    if parsed_time and location:
        confidence = "high"
        quality = "structured time and location parsed"
    elif location:
        confidence = "high"
        quality = "structured location parsed"
    elif parsed_time:
        confidence = "medium"
        quality = "time parsed; location missing"
    else:
        confidence = "low"
        quality = "weak parse"

    urgency = "scheduled"

    if any(x in lower for x in ["stakeout", "press conference", "media availability", "camera spray", "photo spray"]):
        urgency = "move now" if parsed_time else "watch"

    if location:
        where = location
    elif "hearing" in lower or "markup" in lower or "business meeting" in lower:
        where = "Committee room not parsed — check EBB before moving."
    elif "press" in lower or "stakeout" in lower:
        where = "Press location not parsed — check EBB or gallery note before moving."
    else:
        where = "Check EBB for exact room/location before moving."

    if "hearing" in lower or "markup" in lower or "business meeting" in lower:
        movement = "Arrive before start for setup; strongest hallway opportunity is before/after the event."
    elif "stakeout" in lower:
        movement = "Move early; stakeouts are access windows, not just events."
    elif "press conference" in lower or "media availability" in lower:
        movement = "Arrive early for camera position and speaker arrival."
    else:
        movement = "Use time/location to plan crew movement; confirm details before deploying."

    watch = committee or "Event host, committee members, witnesses, leadership, or announced Senators."

    return {
        "title": title,
        "category": "Events",
        "urgency": urgency,
        "status": "confirmed",
        "confidence": confidence,
        "quality": quality if (parse_time(raw) and location) else quality,
        "location": location or "Location not parsed",
        "building": building,
        "takeaway": "Media logistics or event item from EBB.",
        "where_to_be": where,
        "movement_cue": movement,
        "who_to_watch": watch,
        "coverage_note": "Use event time and location to stage cameras, crews, or reporters before arrivals/exits.",
        "staff_note": "Useful for anticipating press presence, member movement, and committee/event traffic.",
        "gallery_note": "Confirm room, camera setup, credential access, pool needs, and whether gallery support is needed.",
        "event_type": title,
        "committee": committee,
    }


def fetch_ebb_items() -> List[JoltItem]:
    try:
        soup = BeautifulSoup(fetch_url(EBB_URL, timeout=15), "html.parser")
        SOURCE_STATUS["ebb"] = "loaded"
    except Exception as exc:
        SOURCE_STATUS["ebb"] = f"error: {exc}"
        return [
            JoltItem(
                source="EBB",
                raw="Could not access ebbs.senate.gov.",
                date_label=None,
                time_label=None,
                sort_datetime=None,
                category="Events",
                title="EBB unavailable",
                urgency="watch",
                status="unavailable",
                confidence="low",
                quality="source unavailable",
                location=None,
                building=None,
                measure=None,
                takeaway="EBB could not be reached.",
                where_to_be="Open EBB directly to confirm logistics.",
                movement_cue="No movement recommendation from EBB until source loads.",
                who_to_watch="N/A",
                coverage_note="EBB events are not available to this app from the current network.",
                staff_note="Use direct EBB access for confirmed events.",
                gallery_note="Confirm EBB availability or add a manual events feed.",
                senators_detected=[],
                coverage_target=None,
                press_availability="Low",
                best_window="scheduled event location",
                event_type=None,
                url=EBB_URL,
                committee=None,
                topic=None,
            )
        ]

    remove_noise(soup)
    text = clean(soup.get_text(" "))
    raw_events = split_ebb_events(text)

    if not raw_events:
        SOURCE_STATUS["ebb"] = "loaded: no event-like items parsed"
        return []

    items = []
    today = datetime.now().date()

    for raw in raw_events:
        d = parse_date(raw) or today
        t = parse_time(raw)
        c = classify_ebb(raw)
        senators = detect_senators(raw)
        committee = infer_ebb_committee(raw)
        coverage_target = infer_coverage_target(raw, senators, committee, None)

        topic = extract_topic(raw)
        item = JoltItem(
            source="EBB",
            raw=shorten(raw, 700),
            date_label=fmt_date(d),
            time_label=fmt_time(t),
            sort_datetime=sort_dt(d, t),
            category=c["category"],
            title=c["title"],
            urgency=c["urgency"],
            status=c["status"],
            confidence=c["confidence"],
            quality=c["quality"],
            location=c["location"],
            building=c["building"],
            measure=None,
            takeaway=c["takeaway"],
            where_to_be=c["where_to_be"],
            movement_cue=c["movement_cue"],
            who_to_watch=c["who_to_watch"],
            coverage_note=c["coverage_note"],
            staff_note=c["staff_note"],
            gallery_note=c["gallery_note"],
            senators_detected=senators,
            coverage_target=coverage_target,
            press_availability="",
            best_window="",
            event_type=c.get("event_type"),
            committee=committee,
            url=EBB_URL,
            topic=topic,
        )
        item.coverage_target = classify_coverage_target(item)

        items.append(apply_past_status(item))

    return dedupe_items(items)[:30]


def fetch_x_items() -> List[JoltItem]:
    if not X_BEARER_TOKEN:
        SOURCE_STATUS["x"] = "disabled: missing X_BEARER_TOKEN"
        return []

    SOURCE_STATUS["x"] = "disabled for now"
    return []


def fetch_committee_meetings_items() -> List[JoltItem]:
    if not CONGRESS_API_KEY:
        SOURCE_STATUS["congress_api"] = "disabled: missing CONGRESS_API_KEY"
        return []
    congress = current_congress() or 119
    try:
        payload = congress_api_get(f"/committee-meeting/{congress}/senate")
        meetings = payload.get("committeeMeetings", []) or payload.get("meetings", [])
        out: List[JoltItem] = []
        for m in meetings[:40]:
            when = (m.get("meetingDate") or m.get("date") or "")[:10]
            at = m.get("startTime") or m.get("time")
            d = datetime.strptime(when, "%Y-%m-%d").date() if when else None
            t = parse_time(str(at)) if at else None
            title = clean(m.get("title") or m.get("description") or "Committee Meeting")
            committee = clean((m.get("committee") or {}).get("name") if isinstance(m.get("committee"), dict) else m.get("committeeName") or "Senate Committee")
            loc = clean(m.get("location") or m.get("room") or "Room TBD")
            event_id = str(m.get("eventId") or "")
            is_press = any(k in title.lower() for k in ["press conference", "stakeout"])
            out.append(JoltItem(
                source="Congress.gov API",
                raw=title,
                date_label=fmt_date(d),
                time_label=fmt_time(t),
                sort_datetime=sort_dt(d, t),
                category="Committee Meetings & Hearings",
                title=title,
                urgency="scheduled",
                status="confirmed",
                confidence="high",
                quality="official Congress.gov committee meeting feed",
                location=loc,
                building=infer_building(loc),
                measure=None,
                takeaway=clean(m.get("description") or m.get("topic") or "Official Senate committee meeting listing."),
                where_to_be=loc,
                movement_cue="Arrive before hearing start; hallway opportunity before/after hearing.",
                who_to_watch=committee,
                coverage_note=f"Official committee eventId: {event_id}" if event_id else "Official committee listing.",
                staff_note="Use official listing to align logistics and witness/member timing.",
                gallery_note="Coordinate camera setup and hallway windows around committee start/end.",
                senators_detected=[],
                coverage_target="committee",
                press_availability="High" if is_press else "Medium",
                best_window="outside hearing room",
                event_type="Hearing/Meeting",
                committee=committee,
                url=m.get("url") or f"https://www.congress.gov/committee-meetings",
                topic=clean(m.get("topic") or m.get("description") or ""),
            ))
        return out
    except Exception:
        SOURCE_STATUS["congress_api"] = "error"
        return []


def dedupe_items(items: List[JoltItem]) -> List[JoltItem]:
    seen = set()
    unique = []

    for item in items:
        key = (
            item.source.lower(),
            item.title.lower(),
            (item.time_label or "").lower(),
            (item.location or "").lower(),
            (item.measure or "").lower(),
            item.takeaway.lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


def get_all_items() -> List[JoltItem]:
    items = get_floor_items() + fetch_ebb_items() + fetch_committee_meetings_items() + fetch_x_items()
    for item in items:
        item.press_availability, item.best_window = compute_press_availability(item)
        if item.status == "historical":
            item.action_line = "Earlier item. Keep for context only."
        elif item.category == "Votes" and item.urgency == "move now":
            item.action_line = "Move to Ohio Clock or chamber exits before Senators clear the floor."
        elif item.category == "Votes":
            item.action_line = "Use the post-vote hallway window for reaction."
        elif item.category in {"Committee Meetings & Hearings"} or ("hearing" in item.title.lower()):
            item.action_line = "Stage outside the committee room before and after the hearing."
        elif item.source == "EBB" and item.location and item.location != "Location not parsed":
            item.action_line = f"Stage at {item.location} before the posted event time."
        elif item.source == "EBB":
            item.action_line = "Confirm location on EBB before staging."
        elif item.category == "Remarks":
            item.action_line = "Monitor for hallway follow-up if tied to active floor business."
        else:
            item.action_line = clean(item.movement_cue) or "Monitor floor updates, EBB, and committee schedule."
    items = dedupe_items(items)
    items.sort(key=lambda x: (x.sort_datetime is None, x.sort_datetime or "9999"))
    return items


def filter_items(items: List[JoltItem], q: Optional[str], view: str, show_earlier: bool = False) -> List[JoltItem]:
    if not show_earlier:
        items = [x for x in items if x.category != "Earlier Floor Activity"]

    if not q:
        return items

    q = q.lower()

    return [
        x for x in items
        if q in x.raw.lower()
        or q in x.title.lower()
        or q in x.category.lower()
        or q in x.urgency.lower()
        or q in x.where_to_be.lower()
        or q in x.movement_cue.lower()
        or q in x.who_to_watch.lower()
        or q in x.coverage_note.lower()
        or q in x.staff_note.lower()
        or q in x.gallery_note.lower()
        or q in x.quality.lower()
        or (x.location and q in x.location.lower())
        or (x.building and q in x.building.lower())
        or (x.measure and q in x.measure.lower())
        or (x.source and q in x.source.lower())
        or (x.date_label and q in x.date_label.lower())
        or (x.time_label and q in x.time_label.lower())
        or (x.topic and q in x.topic.lower())
        or (x.committee and q in x.committee.lower())
        or (x.coverage_target and q in x.coverage_target.lower())
        or (x.press_availability and q in x.press_availability.lower())
        or any(q in s.lower() for s in x.senators_detected)
        or any(q in SENATOR_MAP[s]["party_state"].lower() for s in x.senators_detected if s in SENATOR_MAP)
        or q in SEARCHABLE_LINK_LABELS
    ]


def grouped(items: List[JoltItem]) -> Dict[str, List[JoltItem]]:
    g = {
        "Coverage Timeline": [],
        "Schedule": [],
        "Votes": [],
        "Floor Action": [],
        "Events": [],
        "Committee Meetings & Hearings": [],
        "Live Signals": [],
        "Remarks": [],
        "Notes": [],
        "Earlier Floor Activity": [],
    }

    for item in items:
        g.setdefault(item.category, []).append(item)

        if item.category not in {"Notes", "Remarks", "Earlier Floor Activity"}:
            g["Coverage Timeline"].append(item)

    return g


def score_item(item: JoltItem) -> int:
    score = 0

    if item.status == "historical":
        return -100

    score += {"move now": 100, "watch": 70, "scheduled": 45, "low": 10}.get(item.urgency, 0)
    score += {"high": 30, "medium": 15, "low": 0}.get(item.confidence, 0)

    if item.time_label:
        score += 20
    if item.location and item.location != "Location not parsed":
        score += 30
    if item.category == "Votes":
        score += 15
    if item.category == "Events":
        score += 10

    if item.sort_datetime:
        try:
            dt = datetime.fromisoformat(item.sort_datetime)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)

            minutes = (dt - datetime.now()).total_seconds() / 60

            if 0 <= minutes <= 90:
                score += 40
            elif 90 < minutes <= 240:
                score += 15
            elif minutes < 0:
                score -= 40
        except ValueError:
            pass

    return score


def important_now(items: List[JoltItem]) -> Optional[JoltItem]:
    active = [x for x in items if x.status != "historical"]

    if not active:
        return None

    return sorted(active, key=score_item, reverse=True)[0]


def next_90(items: List[JoltItem]) -> List[JoltItem]:
    now = datetime.now()
    out = []

    for item in items:
        if not item.sort_datetime or item.status == "historical":
            continue

        try:
            dt = datetime.fromisoformat(item.sort_datetime)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
        except ValueError:
            continue

        minutes = (dt - now).total_seconds() / 60

        if 0 <= minutes <= 90:
            out.append(item)

    return sorted(out, key=lambda x: x.sort_datetime or "9999")[:6]






def top_actions(items: List[JoltItem]) -> List[str]:
    ranked = sorted([x for x in items if x.status != "historical"], key=score_item, reverse=True)[:3]
    actions = [clean((it.action_line or it.movement_cue).split(".")[0]) for it in ranked if (it.action_line or it.movement_cue)]
    return actions[:3]
def movement_banner(items: List[JoltItem]) -> Dict[str, str]:
    now = datetime.now()

    def parse_item_dt(item: JoltItem) -> Optional[datetime]:
        if not item.sort_datetime:
            return None
        try:
            dt = datetime.fromisoformat(item.sort_datetime)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except ValueError:
            return None

    votes = [x for x in items if x.category == "Votes"]
    active_votes = [x for x in votes if x.status != "historical"]

    if active_votes:
        return {
            "where_to_be_now": "Ohio Clock / chamber exits",
            "movement": "Move now",
            "watch": "Active floor vote window; watch leadership, sponsors, and swing votes.",
        }

    for vote in votes:
        dt = parse_item_dt(vote)
        if not dt:
            continue
        minutes_since = (now - dt).total_seconds() / 60
        if 0 <= minutes_since <= 30:
            return {
                "where_to_be_now": "Hallway reaction routes near chamber exits and Ohio Clock",
                "movement": "Watch",
                "watch": "Post-vote reactions from sponsors, opponents, leadership, and absences.",
            }

    for item in items:
        if item.source != "EBB":
            continue
        dt = parse_item_dt(item)
        if not dt:
            continue
        minutes_until = (dt - now).total_seconds() / 60
        if 0 <= minutes_until <= 30:
            where = item.location if item.location and item.location != "Location not parsed" else item.where_to_be
            return {
                "where_to_be_now": where,
                "movement": "Move now",
                "watch": "EBB-timed event window is within 30 minutes.",
            }

    return {
        "where_to_be_now": "No active location",
        "movement": "Monitor",
        "watch": "No active floor or media-event trigger.",
    }

def coverage_outlook(items: List[JoltItem], groups: Dict[str, List[JoltItem]]) -> str:
    if groups.get("Votes"):
        return "Floor activity detected. Best access windows around votes and chamber exits."

    if groups.get("Events"):
        return "Focus on EBB events, hearings, and press availabilities."

    if groups.get("Schedule"):
        return "Plan around convening time and leader remarks."

    return "Low activity day — monitor for changes and off-floor movement."


def badge_class(urgency: str) -> str:
    return {
        "move now": "red",
        "watch": "orange",
        "scheduled": "blue",
        "low": "gray",
    }.get(urgency, "gray")


def item_card(item: JoltItem, view: str = "reporter") -> str:
    when = " ".join(x for x in [item.time_label, item.date_label] if x) or "Time TBD"
    place = item.location if item.location and item.location != "Location not parsed" else item.where_to_be
    building = f"<div><strong>Building:</strong> {html.escape(item.building)}</div>" if item.building else ""
    measure = f"<span class='pill'>{html.escape(item.measure)}</span>" if item.measure else ""
    senators_line = ""
    speaker_line = ""
    if item.senators_detected:
        labels = [f"{name} ({SENATOR_MAP[name]['party_state']})" for name in item.senators_detected if name in SENATOR_MAP]
        heading = "Senator" if len(labels) == 1 else "Senators"
        senators_line = f"<div><strong>{heading}:</strong> {html.escape(', '.join(labels))}</div>" if labels else ""
        speaker_line = f"<div><strong>Speaker:</strong> {html.escape(labels[0])}</div>" if labels else ""
    coverage_line = f"<div><strong>Coverage target:</strong> {html.escape(item.coverage_target)}</div>" if item.coverage_target else ""
    press_line = f"<div><strong>Press availability:</strong> {html.escape(item.press_availability)}</div>" if item.press_availability in {"Medium", "High"} else ""
    cov_value = coverage_value_for_item(item)
    cov_line = f"<div><strong>Coverage value:</strong> {html.escape(cov_value)}</div>" if cov_value in {"Medium", "High"} else ""

    note = item.coverage_note
    if view == "staff":
        note = item.staff_note
    elif view == "gallery":
        note = item.gallery_note

    official_context = ""
    if any([item.congress_bill_title, item.congress_latest_action, item.congress_summary, item.congress_sponsors, item.congress_url]):
        official_context = f"""
        <div class="logistics">
            <div><strong>Official context</strong></div>
            {f"<div><strong>Official title:</strong> {html.escape(item.congress_bill_title)}</div>" if item.congress_bill_title else ""}
            {f"<div><strong>Latest action:</strong> {html.escape(item.congress_latest_action)}</div>" if item.congress_latest_action else ""}
            {f"<div><strong>Congress.gov summary:</strong> {html.escape(item.congress_summary)}</div>" if item.congress_summary else ""}
            {f"<div><strong>Sponsor:</strong> {html.escape(item.congress_sponsors)}</div>" if item.congress_sponsors else ""}
            {f"<div><a class='source' href='{html.escape(item.congress_url)}' target='_blank'>Official Congress.gov link</a></div>" if item.congress_url else ""}
        </div>
        """

    return f"""
    <article class="card">
        <div class="row">
            <span class="badge {badge_class(item.urgency)}">{html.escape(item.urgency)}</span>
            <span class="meta">{html.escape(item.source)} · {html.escape(item.status)} · {html.escape(item.confidence)}</span>
        </div>
        <h3>{html.escape(item.title)}</h3>
        <div class="when">{html.escape(when)}</div>
        {measure}
        <p>{html.escape(item.takeaway)}</p>
        <div class="logistics">
            <div><strong>Location:</strong> {html.escape(place)}</div>
            {building}
            <div><strong>Action:</strong> {html.escape(item.action_line or item.movement_cue)}</div>
            <div><strong>Watch:</strong> {html.escape(item.who_to_watch)}</div>
            {speaker_line}
            {senators_line}
            {f"<div><strong>Topic:</strong> {html.escape(item.topic)}</div>" if item.topic else ""}
            {f"<div><strong>Measure:</strong> {html.escape(item.measure)}</div>" if item.measure else ""}
            {coverage_line}
            {press_line}{cov_line}
        </div>
        {f"<a class='source' href='{html.escape(item.congress_url or ('https://www.congress.gov/search?q=%7B%22search%22%3A%22' + item.measure + '%22%7D'))}' target='_blank'>Measure Link</a>" if item.measure else ""}
        {official_context}
        {f"<a class='source' href='{COMMITTEE_SCHEDULE_URL}' target='_blank'>Committee Schedule</a>" if item.committee else ""}
        {f"<a class='source' href='{EBB_URL}' target='_blank'>Open EBB</a>" if item.source == 'EBB' else ""}
        <a class="source" href="{html.escape(item.url or '#')}" target="_blank">{"Open Congressional Reporters" if item.source == "Congressional Reporters" else "Open source"}</a>
    </article>
    """


def empty_message(title: str) -> str:
    messages = {
        "Votes": "No active vote window detected. Monitor Congressional Reporters feed and Roll Call Votes.",
        "News Events & Stakeouts": "No media events parsed. Check EBB for late additions.",
        "Committee Meetings & Hearings": "No committee hearings parsed. Check Congress.gov Committee Schedule and Senate committee pages.",
        "Key Floor Remarks": "No key floor remarks detected.",
        "Legislative Notes": "No legislative notes detected.",
        "Coverage Timeline": "No active coverage timeline yet. Watch for votes, EBB events, or committee hearings.",
        "Live Signals": "Live signals are disabled or no reported signals matched.",
    }
    return f"<p class=\"empty\">{html.escape(messages.get(title, 'No items detected.'))}</p>"


def section(title: str, items: List[JoltItem], view: str, collapsed: bool = False) -> str:
    if collapsed:
        cards = "".join(item_card(item, view) for item in items[:20])

        return f"""
        <section class="section">
            <details>
                <summary><h2>{html.escape(title)} ({len(items)})</h2></summary>
                {cards if cards else empty_message(title)}
            </details>
        </section>
        """

    cards = "".join(item_card(item, view) for item in items)

    return f"""
    <section class="section">
        <h2>{html.escape(title)}</h2>
        {cards if cards else empty_message(title)}
    </section>
    """


def gallery_notes_section() -> str:
    if not MANUAL_GALLERY_NOTES:
        return """
        <section class="section">
            <h2>Gallery Notes</h2>
            <p class="empty">No manual gallery notes added.</p>
        </section>
        """

    notes = "".join(f"<li>{html.escape(note)}</li>" for note in MANUAL_GALLERY_NOTES)

    return f"""
    <section class="section">
        <h2>Gallery Notes</h2>
        <div class="card">
            <ul>{notes}</ul>
        </div>
    </section>
    """




def movement_ticker(items: List[JoltItem]) -> Dict[str, str]:
    now = datetime.now()
    for item in items:
        text = f"{item.title} {item.raw}".lower()
        if item.status != "historical" and ("vote underway" in text or "now voting" in text):
            return {"where": item.where_to_be, "movement": "Move now", "watch": item.who_to_watch}
        if item.sort_datetime:
            try:
                dt = datetime.fromisoformat(item.sort_datetime)
                mins = (dt - now).total_seconds()/60
                if 0 <= mins <= 30 and item.category == "Votes":
                    return {"where": item.where_to_be, "movement": "Prepare to move", "watch": item.who_to_watch}
                if 0 <= mins <= 30 and item.category == "Events":
                    return {"where": item.where_to_be, "movement": "Move to event location", "watch": item.who_to_watch}
            except Exception:
                pass
    return {"where": "Monitor floor + EBB", "movement": "Monitor", "watch": "Leadership and committee principals"}

@app.get("/", response_class=HTMLResponse)
def dashboard(
    q: Optional[str] = Query(None),
    view: str = Query("reporter", pattern="^(reporter|staff|gallery)$"),
    earlier: bool = Query(False),
):
    try:
        all_items = get_all_items()
        items = filter_items(all_items, q, view, show_earlier=earlier)
        low_signal = [x for x in items if not any([x.time_label, x.location and x.location != "Location not parsed", x.senators_detected, x.measure, x.topic, x.action_line])]
        main_items = [x for x in items if x not in low_signal]

        groups = grouped(main_items)
        all_groups = grouped(all_items)

        now_item = important_now(items)
        ticker = movement_ticker(items)
        next_items = next_90(items)
        top_banner = movement_banner(items)

        today = datetime.now().strftime("%A, %B %d, %Y").replace(" 0", " ")

        quick_links = "".join(
            f"<a href='{html.escape(url)}' target='_blank'>{html.escape(name)}</a>"
            for name, url in QUICK_LINKS
        )

        status_bar = f"Sources: Congressional Reporters {html.escape(friendly_status('congressional_reporters'))} · EBB {html.escape(friendly_status('ebb'))} · Congress.gov API {html.escape(friendly_status('congress_api'))} · Committee Schedule {html.escape(friendly_status('committee_schedule'))}"

        outlook = coverage_outlook(items, groups)

        page = f"""
        <!doctype html>
        <html>
        <head>
            <title>{APP_NAME}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta http-equiv="refresh" content="60">
            <style>
                body {{
                    margin: 0;
                    background: #f4f6fb;
                    color: #172033;
                    font-family: Arial, sans-serif;
                }}
                header {{
                    background: linear-gradient(135deg, #172554, #1e3a8a);
                    color: white;
                    padding: 24px 16px;
                }}
                .wrap, main {{
                    max-width: 1080px;
                    margin: auto;
                }}
                main {{
                    padding: 16px;
                }}
                h1 {{
                    margin: 0;
                    font-size: 34px;
                }}
                .sub {{
                    margin-top: 6px;
                    opacity: .92;
                    line-height: 1.35;
                }}
                .searchbox, .card, .stat, .panel, .links, .status, .outlook {{
                    background: white;
                    border-radius: 16px;
                    border: 1px solid #e5e7eb;
                    box-shadow: 0 2px 8px rgba(15,23,42,.07);
                }}
                .searchbox, .status, .outlook {{
                    padding: 12px;
                    margin-bottom: 14px;
                }}
                form {{
                    display: grid;
                    grid-template-columns: 1fr auto;
                    gap: 8px;
                }}
                input, button {{
                    padding: 12px;
                    border-radius: 10px;
                    border: 1px solid #cbd5e1;
                    font-size: 15px;
                }}
                button {{
                    background: #172554;
                    color: white;
                    border: 0;
                    font-weight: bold;
                }}
                .views {{
                    display: flex;
                    gap: 8px;
                    margin-top: 10px;
                    overflow-x: auto;
                }}
                .views a {{
                    text-decoration: none;
                    color: #172554;
                    background: #eef2ff;
                    padding: 9px 12px;
                    border-radius: 999px;
                    font-weight: bold;
                    white-space: nowrap;
                }}
                .ticker {{
                    background: #0f172a;
                    color: white;
                    border-radius: 16px;
                    padding: 12px;
                    margin-bottom: 14px;
                    line-height: 1.6;
                }}
                .summary {{
                    display: grid;
                    grid-template-columns: repeat(5, 1fr);
                    gap: 10px;
                    margin-bottom: 16px;
                }}
                .stat {{
                    padding: 14px;
                }}
                .stat b {{
                    display: block;
                    font-size: 26px;
                    color: #172554;
                }}
                .topgrid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 14px;
                }}
                .panel {{
                    padding: 14px;
                    background: #eef2ff;
                    border-color: #c7d2fe;
                }}
                .section {{
                    margin: 24px 0;
                }}
                .section h2 {{
                    border-bottom: 2px solid #cbd5e1;
                    padding-bottom: 8px;
                    font-size: 21px;
                }}
                details summary {{
                    cursor: pointer;
                }}
                details summary h2 {{
                    display: inline-block;
                    border-bottom: none;
                }}
                .card {{
                    padding: 16px;
                    margin: 12px 0;
                }}
                .row {{
                    display: flex;
                    justify-content: space-between;
                    gap: 8px;
                    align-items: center;
                }}
                .badge {{
                    color: white;
                    border-radius: 999px;
                    padding: 6px 10px;
                    text-transform: uppercase;
                    font-size: 12px;
                    font-weight: bold;
                    letter-spacing: .04em;
                }}
                .red {{ background: #dc2626; }}
                .orange {{ background: #f97316; }}
                .blue {{ background: #2563eb; }}
                .gray {{ background: #64748b; }}
                .meta {{
                    color: #64748b;
                    font-size: 12px;
                    text-transform: uppercase;
                }}
                h3 {{
                    margin: 12px 0 6px;
                    font-size: 20px;
                }}
                .when {{
                    color: #334155;
                    font-weight: bold;
                    margin-bottom: 8px;
                }}
                .pill {{
                    display: inline-block;
                    background: #eef2ff;
                    color: #1e3a8a;
                    padding: 6px 10px;
                    border-radius: 999px;
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 8px;
                }}
                p {{
                    line-height: 1.45;
                }}
                .logistics {{
                    background: #f8fafc;
                    border-left: 4px solid #2563eb;
                    padding: 10px 12px;
                    border-radius: 10px;
                    line-height: 1.5;
                }}
                .source {{
                    display: inline-block;
                    margin: 10px 10px 0 0;
                    color: #1d4ed8;
                    font-weight: bold;
                }}
                .links {{
                    padding: 16px;
                    margin-top: 24px;
                }}
                .links a {{
                    display: inline-block;
                    margin: 6px 8px 6px 0;
                    color: #1d4ed8;
                    font-weight: bold;
                    background: #eef2ff;
                    padding: 8px 10px;
                    border-radius: 10px;
                    text-decoration: none;
                }}
                .empty {{
                    background: white;
                    border-radius: 12px;
                    padding: 14px;
                    color: #64748b;
                }}
                @media(max-width: 760px) {{
                    h1 {{ font-size: 30px; }}
                    form {{
                        grid-template-columns: 1fr;
                    }}
                    .summary, .topgrid {{
                        grid-template-columns: 1fr;
                    }}
                    .stat b {{
                        font-size: 24px;
                    }}
                    .row {{
                        align-items: flex-start;
                        flex-direction: column;
                    }}
                }}
            </style>
        </head>
        <body>
            <header>
                <div class="wrap">
                    <h1>{APP_NAME}</h1>
                    <div class="sub">{today} · Mobile coverage logistics for reporters, Senate staff, and gallery ops</div>
                    <div class="sub">Sources: Congressional Reporters + EBB</div>
                </div>
            </header>

            <main>
                <div class="searchbox">
                    <form method="get">
                        <input name="q" placeholder="Search senator, bill, room, event, vote..." value="{html.escape(q or '')}">
                        <input type="hidden" name="view" value="{html.escape(view)}">
                        <button>Search</button>
                    </form>
                    <div class="views">
                        <a href="/?view=reporter">Reporter View</a>
                        <a href="/?view=staff">Staff View</a>
                        <a href="/?view=gallery">Gallery Ops View</a>
                        <a href="/?earlier=true&view={html.escape(view)}">Show Earlier Activity</a>
                    </div>
                </div>

                <div class="ticker">
                    <strong>WHERE TO BE NOW</strong><br>Status: {html.escape(top_banner["movement"])}<br>Location: {html.escape(top_banner["where_to_be_now"])}<br>Window: {"next 30" if next_items else "None"}<br>Watch: {html.escape(", ".join((now_item.senators_detected if now_item else [])[:3]) or "Leadership, EBB, committee schedule")}<br>Reason: {html.escape(top_banner["watch"])}<br><strong>NEXT MOVE</strong><br>{html.escape(next_items[0].action_line if next_items else "Monitor floor updates, EBB, and committee schedule.")}</div>

                <div class="status">
                    {status_bar}
                </div>

                <div class="outlook">
                    <strong>Today’s Coverage Outlook:</strong> {html.escape(outlook)}
                </div>

                <div class="summary">
                    <div class="stat"><b>{len(items)}</b>Active</div>
                    <div class="stat"><b>{len(groups.get("Votes", []))}</b>Votes</div>
                    <div class="stat"><b>{len(groups.get("Events", []))}</b>Events</div>
                    <div class="stat"><b>{len(groups.get("Coverage Timeline", []))}</b>Timeline</div>
                    <div class="stat"><b>{len([x for x in items if x.urgency == "move now"])}</b>Move now</div>
                </div>

                <section class="section"><h2>Top 3 Actions Right Now</h2>{"".join(f"<div class='card'><p>{html.escape(a)}</p></div>" for a in top_actions(main_items)) if top_actions(main_items) else "<p class='empty'>Monitor. No active vote, event, or hearing movement detected.</p>"}</section>

                {section("Where to Be Now", [now_item] if now_item else [], view)}
                {section("Today’s Coverage Outlook", [now_item] if now_item else [], view, collapsed=True)}
                {section("Senate Floor Schedule", groups.get("Schedule", []), view)}
                {section("Key Votes and Schedule", groups.get("Votes", []), view)}
                {section("News Events & Stakeouts", groups.get("Events", []), view)}
                {section("Committee Meetings & Hearings", groups.get("Committee Meetings & Hearings", []), view)}
                {section("Staff / Gallery Notes", all_groups.get("Floor Action", []), view, collapsed=True)}
                {section("Key Floor Remarks", all_groups.get("Remarks", []), view, collapsed=True)}
                {section("Legislative Notes", all_groups.get("Notes", []), view, collapsed=True)}
                {section("Earlier Floor Activity", all_groups.get("Earlier Floor Activity", []), view, collapsed=True)}
                {section("Low-Signal Items", low_signal, view, collapsed=True)}

                <div class="links">
                    <h2>Helpful Links</h2>
                    {quick_links}
                    <details class="admin"><summary>Admin / Diagnostics</summary><p><a href="/events">Events JSON</a> · <a href="/summary">Summary JSON</a> · <a href="/debug/raw">Debug Raw</a> · <a href="/health">Health</a></p></details>
                </div>
            </main>
        </body>
        </html>
        """

        return page

    except Exception as exc:
        return HTMLResponse(f"<h1>{APP_NAME} error</h1><p>{html.escape(str(exc))}</p>", status_code=500)


@app.get("/events")
def events_endpoint(q: Optional[str] = None, view: str = "reporter", earlier: bool = False):
    all_items = get_all_items()
    items = filter_items(all_items, q, view, show_earlier=earlier)

    return {
        "app": APP_NAME,
        "view": view,
        "items": [asdict(x) for x in items],
    }


@app.get("/summary")
def summary_endpoint():
    items = get_all_items()
    groups = grouped(items)
    now_item = important_now(items)

    return {
        "app": APP_NAME,
        "source_status": SOURCE_STATUS,
        "total": len(items),
        "votes": len(groups.get("Votes", [])),
        "floor_action": len(groups.get("Floor Action", [])),
        "events": len(groups.get("Events", [])),
        "timeline": len(groups.get("Coverage Timeline", [])),
        "earlier_floor_activity": len(groups.get("Earlier Floor Activity", [])),
        "move_now": len([x for x in items if x.urgency == "move now"]),
        "best_coverage_cue": asdict(now_item) if now_item else None,
    }


@app.get("/debug/raw")
def debug_raw():
    floor_text = extract_congressional_reporters_text()
    ebb_items = fetch_ebb_items()

    return {
        "congressional_reporters_source": CONGRESSIONAL_REPORTERS_URL,
        "ebb_source": EBB_URL,
        "source_status": SOURCE_STATUS,
        "floor_preview": floor_text[:2500],
        "floor_raw": split_floor_events(floor_text),
        "ebb_items": [asdict(x) for x in ebb_items],
        "items": [asdict(x) for x in get_all_items()],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "congressional_reporters": CONGRESSIONAL_REPORTERS_URL,
        "ebb": EBB_URL,
        "source_status": SOURCE_STATUS,
    }
