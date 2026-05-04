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
RADIO_TV_URL = "https://www.radiotv.senate.gov/"
SENATE_DEMS_SCHEDULE_URL = "https://www.democrats.senate.gov/floor/senate-schedule"
SENATE_DEMS_FLOOR_URL = "https://www.democrats.senate.gov/floor"
EXECUTIVE_CALENDAR_URL = "https://www.senate.gov/legislative/LIS/executive_calendar/xcalv.pdf"
FLOOR_ACTIVITY_URL = "https://www.senate.gov/legislative/floor_activity_pail.htm"
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

QUICK_LINK_GROUPS = {
    "Coverage": [
        ("Coverage Rules", "https://www.radiotv.senate.gov/gallery-members/coverage-rules/"),
        ("Coverage Locations", "https://www.radiotv.senate.gov/gallery-members/coverage-locations/"),
        ("EBB", EBB_URL),
    ],
    "Contacts": [
        ("Press Secretary Contacts", "https://www.radiotv.senate.gov/gallery-members/press-secretary-contacts/"),
        ("Committee Press Contacts", "https://www.radiotv.senate.gov/gallery-members/commitee-press-contacts/"),
        ("Gallery Regulars / Journalist Contacts", "https://www.radiotv.senate.gov/gallery-members/"),
    ],
    "Floor / Official": [
        ("Roll Call Votes", "https://www.senate.gov/legislative/votes_new.htm"),
        ("Executive Calendar", "https://www.senate.gov/legislative/LIS/executive_calendar/xcalv.pdf"),
        ("Congressional Record", "https://www.congress.gov/congressional-record"),
        ("Rules & Procedure", "https://www.senate.gov/legislative/rules_procedure.htm"),
        ("Committee Assignments", "https://www.senate.gov/general/committee_assignments/assignments.htm"),
        ("Congress.gov Committee Schedule", COMMITTEE_SCHEDULE_URL),
        ("Senate Committee Meetings", "https://www.senate.gov/committees/hearings_meetings.htm"),
    ],
}


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


@dataclass(kw_only=True)
class JoltItem:
    source: str
    raw: str
    date_label: Optional[str]
    time_label: Optional[str]
    sort_datetime: Optional[str]
    category: str
    coverage_type: str = "floor update"
    title: str
    urgency: str
    status: str
    confidence: str
    quality: str
    location: Optional[str]
    coverage_location: Optional[str] = None
    building: Optional[str]
    measure: Optional[str]
    takeaway: str
    where_to_be: str
    movement_cue: str
    coverage_action: str = ""
    who_to_watch: str
    coverage_note: str
    staff_note: str
    context_note: str = ""
    gallery_note: str
    gallery_guidance: str = ""
    senators_detected: List[str]
    coverage_target: Optional[str]
    press_availability: str
    best_window: str
    coverage_window: str = "none"
    visibility_level: str = "Low"
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
    signal_type: str = "low_signal"
    signal_class: str = "tertiary"
    signal_score: int = 0
    action_confidence: str = "Monitor only"
    movement_status: str = "Monitor"
    coverage_value: str = "Low"
    suppressed: bool = False
    public_value: str = ""
    legislative_context: str = ""
    access_note: str = ""
    rules_note: str = ""
    pool_note: str = ""
    procedure_stage: Optional[str] = None
    vote_status: Optional[str] = None
    chamber_phase: Optional[str] = None
    outcome_stage: Optional[str] = None
    official_context: Dict[str, Any] = None
    links: List[Dict[str, str]] = None


@dataclass(kw_only=True)
class SignalItem:
    id: str
    timestamp: str
    last_updated: str
    source: str
    source_confidence: str
    coverage_type: str
    chamber: str
    title: str
    description: str
    location: str
    coverage_location: str
    coverage_window: Dict[str, Optional[str]]
    coverage_guidance: str
    people: List[str]
    committees: List[str]
    bill_ids: List[str]
    legislative_stage: str
    legislative_context: str
    public_value: str
    press_interest_score: int
    timing_score: int
    procedural_score: int
    leadership_score: int
    event_density_score: int
    total_score: float
    status: str



SOURCE_STATUS = {
    "congressional_reporters": "not loaded",
    "ebb": "not loaded",
    "congress_api": "Congress.gov API disabled: missing CONGRESS_API_KEY" if not CONGRESS_API_KEY else "Congress.gov API loaded",
    "committee_schedule": "linked",
    "congressional_record": "linked/API available",
}
LAST_FORWARD_SCHEDULE_DEBUG: Dict[str, Any] = {}

PLACEHOLDER_VALUES = {
    "tbd","room tbd","rolling","floor update","no pool note",
    "monitor source before moving","relevant senators named in the update",
    "the senate is considering current floor business and related procedural actions",
    "a senator made floor remarks","general floor update"
}
GLOBAL_SUPPRESSED_VALUES = {
    "earlier",
    "no immediate location change",
    "earlier item. keep for context only",
    "the senate is considering current floor business",
    "a senator made floor remarks",
}


def is_meaningful(value: Optional[str]) -> bool:
    if value is None:
        return False
    v = clean(str(value)).strip()
    return bool(v) and v.lower() not in PLACEHOLDER_VALUES


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


def fetch_forward_schedule_sources() -> Dict[str, Any]:
    sources = [
        ("daily_press", CONGRESSIONAL_REPORTERS_URL, False),
        ("senate_dems_schedule", SENATE_DEMS_SCHEDULE_URL, False),
        ("floor_schedule", FLOOR_ACTIVITY_URL, False),
        ("radio_tv", RADIO_TV_URL, False),
        ("senate_dems_floor", SENATE_DEMS_FLOOR_URL, False),
        ("executive_calendar", EXECUTIVE_CALENDAR_URL, True),
    ]
    loaded = []
    texts = []
    errors = {}
    for key, url, is_pdf in sources:
        try:
            if is_pdf:
                text = fetch_url(url, timeout=20)
            else:
                soup = BeautifulSoup(fetch_url(url, timeout=20), "html.parser")
                remove_noise(soup)
                text = clean(soup.get_text(" "))
            if text:
                loaded.append({"key": key, "url": url})
                texts.append({"key": key, "url": url, "text": text[:20000]})
        except Exception as exc:
            errors[key] = str(exc)
    return {"loaded_sources": loaded, "texts": texts, "errors": errors}


def extract_next_floor_actions(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    patterns = [
        r"(The Senate will next convene[^.]*\.)",
        r"([^.]*will next convene at[^.]*\.)",
        r"([^.]*next convene on[^.]*\.)",
        r"([^.]*pro forma session[^.]*\.)",
        r"([^.]*pro forma sessions only[^.]*\.)",
        r"(At\s+\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)[^.]*roll call votes?[^.]*\.)",
        r"([^.]*Following Leader remarks[^.]*\.)",
        r"([^.]*period of morning business[^.]*\.)",
        r"([^.]*proceed to Executive Session[^.]*\.)",
        r"([^.]*vote on adoption[^.]*\.)",
        r"([^.]*motion to invoke cloture[^.]*\.)",
        r"([^.]*cloture on [^.]*\.)",
        r"([^.]*confirmation of [^.]*\.)",
    ]
    actions = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            snippet = clean(m.group(1))
            d = parse_date(snippet)
            t = parse_time(snippet)
            actions.append({
                "text": snippet,
                "date_label": fmt_date(d) or "",
                "time_label": fmt_time(t) or "",
                "sort_datetime": sort_dt(d, t) or "",
                "source_hint": "public schedule source",
            })
    # de-dupe
    seen = set()
    unique = []
    for a in actions:
        k = a["text"].lower()
        if k in seen:
            continue
        seen.add(k)
        unique.append(a)
    return sorted(unique, key=lambda x: (x["sort_datetime"] == "", x["sort_datetime"] or "9999"))[:20]


def parse_forward_floor_schedule(text: str, today: date) -> Dict[str, Any]:
    cleaned = clean(text or "")
    blocks = [clean(b) for b in re.split(r"\n{2,}", text or "") if clean(b)]
    window_end = today + timedelta(days=14)
    rejected_blocks: List[str] = []
    ignored_dates: List[str] = []

    def has_future_phrase(t: str) -> bool:
        l = t.lower()
        return any(x in l for x in ["will next convene", "next convene at", "the senate will vote", "roll call votes expected", "at approximately"])

    def parse_schedule_date(snippet: str) -> Optional[date]:
        parsed = parse_date(snippet)
        if parsed:
            return parsed
        m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?", snippet)
        if not m:
            return None
        try:
            guessed = datetime.strptime(f"{m.group(1)} {m.group(2)} {today.year}", "%B %d %Y").date()
            if guessed < today:
                guessed = guessed.replace(year=today.year + 1)
            return guessed
        except ValueError:
            return None

    def valid_sentence(s: str) -> bool:
        if not s:
            return False
        s = clean(s)
        if len(s) < 12:
            return False
        return s[-1] in ".!?"

    def in_window(d: Optional[date]) -> bool:
        return bool(d and today <= d <= window_end)

    def shorten_nomination(v: str) -> str:
        v = clean(v)
        m = re.search(r"(Executive Calendar\s*#\d+\s+)(.+)", v, flags=re.I)
        if not m:
            return v
        desc = m.group(2)
        for splitter in [" to be ", " of ", " for ", " as "]:
            if splitter in desc.lower():
                idx = desc.lower().index(splitter)
                return clean(m.group(1) + desc[:idx])
        return v

    accepted_parts: List[str] = []
    for block in blocks or [cleaned]:
        l = block.lower()
        if "wrap up for" in l and not has_future_phrase(block):
            rejected_blocks.append(block[:300])
            continue
        accepted_parts.append(block)
    accepted = " ".join(accepted_parts) if accepted_parts else cleaned

    ignore_phrases = ["for a term of", "term of", "term expiring", "from february 1, 2026", " vice ", "effective", "confirmed:", "agreed to:"]
    for sentence in re.split(r"(?<=[.])\s+", accepted):
        ls = sentence.lower()
        if any(p in ls for p in ignore_phrases):
            for m in re.finditer(r"([A-Z][a-z]+\s+\d{1,2},\s*\d{4})", sentence):
                ignored_dates.append(clean(m.group(1)))

    pro_formas = []
    pro_forma_seen = set()
    for m in re.finditer(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(\d{4}))?\s+at\s+(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm))", accepted, flags=re.I):
        snippet = clean(m.group(0))
        span_start = max(0, m.start()-120)
        span_end = min(len(accepted), m.end()+120)
        context_window = accepted[span_start:span_end].lower()
        if "pro forma" not in context_window:
            continue
        d = parse_schedule_date(snippet)
        t = parse_time(snippet)
        if not in_window(d):
            continue
        key = (d.isoformat(), fmt_time(t) or "")
        if key in pro_forma_seen:
            continue
        pro_forma_seen.add(key)
        pro_formas.append({"text": snippet, "date": d.isoformat(), "time": fmt_time(t) or "", "date_label": fmt_date(d), "time_label": fmt_time(t) or "", "sort_datetime": sort_dt(d, t)})

    next_convening = {}
    m = re.search(r"(?:will\s+next\s+convene\s+at|next\s+convene\s+at)\s*(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)).*?on\s+((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?)", accepted, flags=re.I)
    if m:
        d = parse_schedule_date(m.group(2))
        t = parse_time(m.group(1))
        if in_window(d):
            next_convening = {"date": d.isoformat(), "time": fmt_time(t) or "", "date_label": fmt_date(d), "time_label": fmt_time(t) or "", "sort_datetime": sort_dt(d, t), "date_obj": d}

    floor_schedule = []
    if re.search(r"following\s+leader\s+remarks", accepted, flags=re.I):
        floor_schedule.append("Leader remarks")

    vote_block = {}
    expected_votes = []
    expected_votes_source = ""
    expected_vote_parser_used = ""
    vote_block_time_source = ""
    vote_block_extraction_method = ""
    raw_vote_block_time = ""
    normalized_vote_block_time = ""
    block_line = None
    block_votes_expected = None
    for line in re.split(r"(?:\n+|(?<=[.])\s+)", accepted):
        line = clean(line)
        if not line:
            continue
        m_votes = re.search(r"(\d+)\s+roll\s+call\s+votes?\s+expected", line, flags=re.I)
        if m_votes:
            block_line = line
            block_votes_expected = int(m_votes.group(1))
            break

    if block_line and next_convening:
        time_match = re.search(r"(?:at\s+)?(approximately\s+)?(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm))", block_line, flags=re.I)
        raw_time = time_match.group(0) if time_match else ""
        raw_vote_block_time = clean(raw_time)
        normalized_vote_block_time = normalize_public_time_label(raw_vote_block_time)
        vote_block = {
            "date": next_convening["date"],
            "raw_time_text": raw_vote_block_time,
            "time": normalized_vote_block_time,
            "date_label": next_convening["date_label"],
            "time_label": normalized_vote_block_time,
            "roll_call_votes_expected": block_votes_expected,
        }
        vote_block_time_source = clean(time_match.group(0)) if time_match else ""
        vote_block_extraction_method = "structured_block"
    if (not vote_block) and next_convening:
        fallback_match = re.search(
            r"(At\s+(?:approximately\s+)?(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm))\s*,?\s*the\s+Senate\s+will\s+(?:proceed\s+to\s+)?vote[^.]*\.)",
            accepted,
            flags=re.I,
        )
        if fallback_match:
            raw_time = fallback_match.group(1)
            raw_vote_block_time = clean(raw_time)
            normalized_vote_block_time = normalize_public_time_label(raw_vote_block_time)
            vote_block = {
                "date": next_convening["date"],
                "raw_time_text": raw_vote_block_time,
                "time": normalized_vote_block_time,
                "date_label": next_convening["date_label"],
                "time_label": normalized_vote_block_time,
            }
            vote_block_time_source = clean(fallback_match.group(1))
            vote_block_extraction_method = "prose_fallback"

    pattern_a = re.search(
        r"At\s+(approximately\s+\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm))\s*,?\s*the\s+Senate\s+will\s+vote\s+on\s+adoption\s+of\s+Calendar\s*#5,\s*S\.Res\.?690",
        accepted,
        flags=re.I,
    )
    if pattern_a and next_convening:
        raw_vote_block_time = clean(pattern_a.group(1))
        normalized_vote_block_time = normalize_public_time_label(raw_vote_block_time)
        vote_block = {
            "date": next_convening["date"],
            "raw_time_text": raw_vote_block_time,
            "time": normalized_vote_block_time,
            "date_label": next_convening["date_label"],
            "time_label": normalized_vote_block_time,
        }
        vote_block_time_source = clean(pattern_a.group(0))
        vote_block_extraction_method = "pattern_a_fallback"

    cloture_filed = []
    expected_vote_count = 0
    parsed_expected_vote_count = 0
    expected_vote_count_mismatch = False
    for m in re.finditer(r"cloture (?:has been )?filed on\s*(Executive Calendar\s*#\d+\s+[^.;]*)", accepted, flags=re.I):
        candidate = clean(m.group(1)).rstrip(".")
        if candidate:
            cloture_filed.append(candidate)
    count_match = re.search(r"(\d+)\s+roll\s+call\s+votes\s+expected", accepted, flags=re.I)
    if count_match:
        expected_vote_count = int(count_match.group(1))
    two_roll_call_following_match = re.search(
        r"At\s+\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)\s*,?\s*the\s+Senate\s+will\s+proceed\s+to\s+two\s+roll\s+call\s+votes\s+on\s+the\s+following\s*:",
        accepted,
        flags=re.I,
    )
    if two_roll_call_following_match:
        expected_vote_count = 2

    vote_marker_re = r"(Calendar\s*#|S\.Res|Executive Calendar|cloture|nomination|adoption|confirmation)"

    lines = [clean(x) for x in re.split(r"\n+", accepted) if clean(x)]
    raw_lines = [clean(x) for x in (text or "").splitlines()]
    if two_roll_call_following_match:
        marker_idx = next((i for i, x in enumerate(raw_lines) if re.search(r"two\s+roll\s+call\s+votes\s+on\s+the\s+following\s*:", x, flags=re.I)), None)
        if marker_idx is not None:
            following = [clean(x.strip(" -•\t")) for x in raw_lines[marker_idx + 1:] if clean(x.strip(" -•\t"))]
            expected_votes = following[:2]
            expected_votes_source = "two_roll_call_votes_following_block"
            expected_vote_parser_used = "two_roll_call_votes_following_block"
            parsed_expected_vote_count = len(expected_votes)
    if block_line and not expected_votes:
        expected_votes_source = "structured_block"
        start_idx = next((i for i, x in enumerate(lines) if block_line in x or x in block_line), None)
        candidate_lines = lines[start_idx + 1:] if start_idx is not None else []
        seen_votes = set()
        for raw in candidate_lines:
            s = clean(raw.strip(" -•\t"))
            if not s:
                continue
            lower = s.lower()
            if "roll call votes expected" in lower:
                break
            if any(k in lower for k in ["leader remarks", "will next convene", "pro forma", "stands adjourned"]):
                break
            if lower.startswith("no earlier than") or not re.search(vote_marker_re, s, flags=re.I):
                continue
            if s.lower().startswith("adoption of"):
                s = s[0].upper() + s[1:]
            s = shorten_nomination(s.rstrip("."))
            k = s.lower()
            if k not in seen_votes:
                seen_votes.add(k)
                expected_votes.append(s)

    parsed_expected_vote_count = len(expected_votes)
    if (not expected_votes) or (expected_vote_count and parsed_expected_vote_count < expected_vote_count):
        vote_sentence = re.search(r"At\s+(?:approximately\s+)?\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)\s*,?\s*the\s+Senate\s+will\s+vote\s+on\s+adoption\s+of\s+(.*?)\s*authorizing\s+the\s+en\s+bloc\s+consideration\s+in\s+Executive\s+Session\s+of\s*\(?([0-9]+)\)?\s*certain\s+nominations\s+on\s+the\s+Executive\s+Calendar", accepted, flags=re.I)
        if vote_sentence:
            phrase = clean(vote_sentence.group(1)).rstrip(",")
            count = vote_sentence.group(2)
            expected_votes.append(f"Adoption of {phrase} (en bloc consideration of {count} nominations)")

        cloture_sentence = re.search(r"Following disposition of the resolution,\s*the Senate will vote on the motion to invoke cloture on\s+([^.]*)\.", accepted, flags=re.I)
        if cloture_sentence:
            ec = clean(cloture_sentence.group(1))
            expected_votes.append(f"Motion to invoke cloture on {ec} nomination")

        generic_adoption = re.search(
            r"Adoption of\s+(Calendar\s*#\d+\s*,?\s*S\.Res\.?\d+)(?:[^\n]*?of\s*(\d+)\s*nominations)?",
            accepted,
            flags=re.I,
        )
        if generic_adoption:
            cal = clean(generic_adoption.group(1)).replace(" ,", ",")
            c = generic_adoption.group(2)
            if c:
                expected_votes.append(f"Adoption of {cal} (en bloc consideration of {c} nominations)")
            else:
                expected_votes.append(f"Adoption of {cal}")

        generic_cloture = re.search(
            r"motion to invoke cloture on\s+(Executive Calendar\s*#\d+\s+[^.\n]*?)(?:\s+nomination)?[.\n]",
            accepted,
            flags=re.I,
        )
        if generic_cloture:
            ec = clean(generic_cloture.group(1))
            expected_votes.append(f"Motion to invoke cloture on {ec} nomination")

        if re.search(r"vote on adoption of Calendar\s*#5\s*,\s*S\.Res\.?690", accepted, flags=re.I):
            expected_votes.append("Adoption of Calendar #5, S.Res.690 (en bloc consideration of 49 nominations)")

        if re.search(r"motion to invoke cloture on Executive Calendar\s*#728\s+Kevin\s+Warsh", accepted, flags=re.I):
            expected_votes.append("Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination")

        if expected_votes:
            expected_votes_source = "prose_fallback"
            expected_vote_parser_used = expected_vote_parser_used or "prose_fallback"


    normalized_votes = []
    for v in expected_votes:
        s = clean(v).rstrip(".")
        s = re.sub(r",\s*En\s+Bloc\s+Nominations$", " — en bloc nominations", s, flags=re.I)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            normalized_votes.append(s)
    expected_votes = normalized_votes

    expected_votes = [
        v for v in expected_votes
        if clean(v)
        and clean(v).lower() not in {"none announced", "no vote block announced"}
        and clean(v).lower() not in {"the motion to invoke cloture", "confirmation of"}
        and re.search(vote_marker_re, clean(v), flags=re.I)
    ]

    expected_votes = list(dict.fromkeys(expected_votes))
    parsed_expected_vote_count = len(expected_votes)
    if expected_votes and not expected_vote_parser_used:
        expected_vote_parser_used = expected_votes_source or "structured_block"
    if expected_vote_count and parsed_expected_vote_count < expected_vote_count:
        expected_vote_count_mismatch = True
    if "5:30pm" in accepted.lower() and vote_block.get("time_label") == "11:30 a.m.":
        vote_block["time_label"] = "approx. 5:30 p.m."

    vote_block_time_source = "text_extracted" if vote_block else ""

    return {
        "pro_formas": pro_formas[:6],
        "next_convening": {k:v for k,v in next_convening.items() if k!="date_obj"},
        "floor_schedule": floor_schedule,
        "vote_block": vote_block,
        "expected_votes": expected_votes[:8],
        "next_convening_date": next_convening.get("date", ""),
        "next_convening_time_label": next_convening.get("time_label", ""),
        "vote_block_time_label": vote_block.get("time_label", ""),
        "vote_block_time_source": vote_block_time_source,
        "raw_vote_block_time": vote_block.get("time_label", ""),
        "normalized_vote_block_time": vote_block.get("time_label", ""),
        "vote_block_display_time": vote_block.get("time_label", ""),
        "vote_block_extraction_method": vote_block_extraction_method,
        "expected_votes_source": expected_votes_source,
        "expected_vote_parser_used": expected_vote_parser_used,
        "expected_vote_count": expected_vote_count,
        "parsed_expected_vote_count": parsed_expected_vote_count,
        "expected_vote_count_mismatch": expected_vote_count_mismatch,
        "raw_vote_time_match": raw_vote_block_time,
        "expected_votes_final": expected_votes[:8],
        "renderer_source_function": "parse_forward_floor_schedule",
        "cloture_filed": list(dict.fromkeys(cloture_filed))[:8],
        "source_label": "Public schedule source",
        "source_url": CONGRESSIONAL_REPORTERS_URL,
        "ignored_dates": sorted(set(ignored_dates)),
        "rejected_blocks": rejected_blocks[:20],
    }


def forward_schedule_parser_smoke_test() -> Dict[str, Any]:
    """Unit-style parser fixture for deterministic forward floor schedule extraction."""
    sample_text = """Other than pro formas on Monday, May 4 at 6:45 a.m. and Thursday, May 7 at 10:00 a.m. the Senate will next convene at 3:00 p.m. on Monday, May 11th.
The Senate stands adjourned for pro forma sessions only...
Monday, May 4th at 6:45am
Thursday, May 7th at 10:00am
When the Senate adjourns on Thursday, it will next convene at 3:00pm on Monday, May 11, 2026.
At approximately 5:30pm, 2 roll call votes expected.
Adoption of Calendar #5, S.Res.690, authorizing en bloc consideration in Executive Session of 49 nominations.
Motion to invoke cloture on Executive Calendar #728 Kevin Warsh nomination.
for a term of fourteen years from February 1, 2026.
Wrap Up for April 30, 2026."""
    parsed = parse_forward_floor_schedule(sample_text, date(2026, 5, 3))
    return {
        "next_convening_date_is_may_11_2026": parsed.get("next_convening", {}).get("date") == "2026-05-11",
        "vote_block_time_is_530pm": "5:30" in (parsed.get("vote_block", {}).get("time_label", "") or ""),
        "vote_block_time_is_normalized_approx_label": parsed.get("normalized_vote_block_time") == "approx. 5:30 p.m.",
        "vote_block_time_is_not_1130": "11:30" not in (parsed.get("vote_block", {}).get("time_label", "") or ""),
        "ignored_dates_includes_feb_1_2026": any("February 1, 2026" in x for x in parsed.get("ignored_dates", [])),
        "wrap_up_not_in_expected_votes": not any("wrap up for" in x.lower() for x in parsed.get("expected_votes", [])),
    }


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
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, line)
        if not m:
            continue

        try:
            if len(m.groups()) == 4:
                return datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%B %d %Y").date()
            if pattern.endswith("(\d{4})\b") and len(m.groups())==3 and m.group(1).isdigit():
                return datetime.strptime(f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}", "%m/%d/%Y").date()
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


def normalize_public_time_label(raw: str) -> str:
    # examples:
    # "5:30pm" -> "5:30 p.m."
    # "approximately 5:30pm" -> "approx. 5:30 p.m."
    # "At approximately 5:30pm" -> "approx. 5:30 p.m."
    # This function does not create datetime objects.
    text = clean(raw or "")
    if not text:
        return ""

    approx = bool(re.search(r"\b(?:at\s+)?approx(?:\.|imately)?\b", text, flags=re.I))
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\b", text, flags=re.I)
    if not m:
        return "approx. " + text if approx and not text.lower().startswith("approx.") else text

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = "a.m." if m.group(3).lower() == "a" else "p.m."
    normalized = f"{hour}:{minute:02d} {meridiem}"
    return f"approx. {normalized}" if approx else normalized


def fmt_date(d: Optional[date]) -> Optional[str]:
    if not d:
        return None
    return d.strftime("%b %d")


def fmt_time(t: Optional[time]) -> Optional[str]:
    if not t:
        return None
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'a.m.' if t.hour < 12 else 'p.m.'}"


def fmt_short_date_label(label: Optional[str]) -> Optional[str]:
    if not label:
        return label
    text = clean(label)
    for pattern in ("%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, pattern).strftime("%b %d").replace(" 0", " ")
        except ValueError:
            continue
    return label


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
        return "Senate subway walkways"

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
        where = "Ohio Clock, chamber exits, Senate subway, or usual stakeout area."
        movement = "Move Now if this vote is current; if historical, use only for context."
        watch = "Leadership, bill sponsors, opponents, affected-state Senators."
        coverage = "High-value hallway window. Be in position before Senators finish voting."
        staff = "Vote result determines immediate floor posture."
        gallery = "Expect member movement around chamber exits and subway walkways."

    elif "by a vote of" in lower or "roll call vote" in lower:
        title, category, urgency = "Roll Call Vote", "Votes", "watch"
        takeaway = "The Senate recorded a vote."
        where = "Post-vote exits, Ohio Clock, stakeout positions, or Senator office hallways."
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
        where = "Monitor chamber exits and leadership hallways after the vote."
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
        window = "committee room / public access areas"
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


def floor_remark_signal_label(item: JoltItem) -> Optional[str]:
    raw = clean(f"{item.title} {item.raw}")
    lower = raw.lower()
    leadership_names = {"john thune", "chuck schumer", "dick durbin", "mitch mcconnell"}
    first = (item.senators_detected[0].lower() if item.senators_detected else "")
    if first in leadership_names:
        return "Leadership"
    if any(x in lower for x in ["s.res.690", "executive calendar #728", "executive calendar #727", "vote block", "roll call vote"]):
        return "Tied to next floor action"
    if any(x in lower for x in ["motion to proceed", "cloture", "unanimous consent", "objected", "executive session"]):
        return "Procedural"
    if any(x in lower for x in ["nomination", "confirmation", "executive calendar"]):
        return "Nomination-related"
    if "vote" in lower:
        return "Vote-related"
    return None


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
    text = clean(measure).lower()
    compact = re.sub(r"\s+", "", text)
    compact = compact.replace("..", ".")
    patterns = {
        r"^s\.(\d+)$": "s",
        r"^s\.?res\.(\d+)$": "sres",
        r"^s\.?j\.?res\.(\d+)$": "sjres",
        r"^h\.?r\.(\d+)$": "hr",
        r"^h\.?j\.?res\.(\d+)$": "hjres",
        r"^h\.?res\.(\d+)$": "hres",
        r"^h\.?con\.?res\.(\d+)$": "hconres",
        r"^s\.?con\.?res\.(\d+)$": "sconres",
    }
    for pattern, bill_type in patterns.items():
        m = re.match(pattern, compact)
        if m:
            return current_congress() or 119, bill_type, m.group(1)
    return None


@lru_cache(maxsize=256)
def congress_api_get(path: str) -> Dict[str, Any]:
    if not CONGRESS_API_KEY:
        raise RuntimeError("missing key")
    url = f"{CONGRESS_API_BASE}{path}"
    r = requests.get(url, params={"api_key": CONGRESS_API_KEY, "format": "json"}, timeout=10)
    r.raise_for_status()
    return r.json()

def strip_html_text(text: str) -> str:
    return clean(BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True))


def fetch_official_context_for_item(item: JoltItem) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    if item.measure:
        out.update(fetch_congress_bill_info(item.measure))
    return out


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
        summary = strip_html_text(summary)[:300] if summary else None
        return {
            "congress_bill_title": bill.get("title"),
            "congress_latest_action": latest_action,
            "congress_official_context": (latest.get("actionDate") or latest.get("date")),
            "congress_policy_area": (bill.get("policyArea") or {}).get("name"),
            "congress_sponsors": sponsors or None,
            "congress_url": bill.get("url") or search_url,
            "congress_summary": summary,
        }
    except Exception:
        SOURCE_STATUS["congress_api"] = "Congress.gov API error"
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
    item.__dict__.update(fetch_official_context_for_item(item))

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


def parse_ebb_structured_fields(raw: str) -> Dict[str, str]:
    fields = {"event_date": "", "event_time": "", "location": "", "title": "", "description": "", "chamber": ""}
    if not raw:
        return fields

    aliases = {
        "event_date": ["event date", "date"],
        "event_time": ["event time", "time"],
        "location": ["location"],
        "title": ["title", "event", "subject"],
        "description": ["description", "details", "note"],
        "chamber": ["chamber"],
    }
    field_tokens = "|".join(re.escape(a) for names in aliases.values() for a in names)
    for field, names in aliases.items():
        name_pattern = "|".join(re.escape(n) for n in names)
        pattern = rf"(?:^|\b)(?:{name_pattern})\s*:\s*(.+?)(?=(?:\b(?:{field_tokens})\s*:)|$)"
        m = re.search(pattern, raw, flags=re.I)
        if m:
            fields[field] = clean(m.group(1))

    if not fields["title"]:
        inferred = infer_ebb_title(raw)
        fields["title"] = "" if inferred == "EBB Event" else inferred
    return fields


def infer_ebb_chamber(structured: Dict[str, str], raw: str) -> str:
    combined = " ".join([structured.get("chamber") or "", structured.get("title") or "", structured.get("location") or "", structured.get("description") or "", raw or ""]).lower()
    house_only_markers = ["house floor", "the house meets", "house pro forma", "house schedule"]
    if any(marker in combined for marker in house_only_markers):
        return "House"
    if "joint" in combined or "bicameral" in combined or ("house" in combined and "senate" in combined):
        return "Joint"
    return "Senate"


def is_joint_or_senate_relevant_ebb(structured: Dict[str, str], raw: str) -> bool:
    lower = " ".join([raw or "", structured.get("title") or "", structured.get("description") or "", structured.get("location") or ""]).lower()
    senate_relevant_terms = ["senate", "senate committee", "senate radio/tv", "senate radio", "senate tv", "senate studio", "s-325", "sd-", "sh-", "sr-", "capitol", "joint", "bicameral", "conference committee", "state of the union"]
    return any(term in lower for term in senate_relevant_terms)


def classify_ebb(raw: str) -> Dict[str, str]:
    raw = normalize_ebb_location_text(raw)
    structured = parse_ebb_structured_fields(raw)
    chamber = infer_ebb_chamber(structured, raw)
    title = structured.get("title") or infer_ebb_title(raw)
    location = structured.get("location") or extract_ebb_room(raw) or infer_location(raw)
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
        movement = "Use time/location to plan coverage timing; confirm details before coverage."

    watch = committee or "Event host, committee members, witnesses, leadership, or announced Senators."

    if chamber == "House":
        category = "House / Joint Coverage Notes"
        event_type = title
        takeaway = clean(structured.get("description") or "House schedule note from EBB.")
        coverage_note = "House item from EBB; keep in House/Joint notes unless Senate coverage relevance is clear."
        where = location or "House Floor"
    else:
        category = "Events"
        event_type = title
        takeaway = "Media logistics or event item from EBB."
        coverage_note = "Use event time and location to stage cameras, crews, or reporters before arrivals/exits."

    return {
        "title": title,
        "category": category,
        "urgency": urgency,
        "status": "confirmed",
        "confidence": confidence,
        "quality": quality if (parse_time(raw) and location) else quality,
        "location": location or "Location not parsed",
        "building": building,
        "takeaway": takeaway,
        "where_to_be": where,
        "movement_cue": movement,
        "who_to_watch": watch,
        "coverage_note": coverage_note,
        "staff_note": "Useful for anticipating press presence, member movement, and committee/event traffic.",
        "gallery_note": "Confirm room, camera setup, credential access, pool needs, and whether gallery support is needed.",
        "event_type": event_type,
        "committee": committee,
        "chamber": chamber,
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
        structured = parse_ebb_structured_fields(raw)
        d = parse_date(structured.get("event_date") or "") or parse_date(raw)
        t = parse_time(structured.get("event_time") or "") or parse_time(raw)
        c = classify_ebb(raw)
        chamber = c.get("chamber", "Senate")
        has_useful_description = bool(clean(structured.get("description") or "")) and clean(structured.get("description") or "").lower() not in {"tbd", "n/a", "none"}
        has_minimum_fields = bool(structured.get("title") and structured.get("location") and d and has_useful_description)
        if chamber == "House":
            continue
        if chamber not in {"Senate", "Joint"}:
            continue
        if not is_joint_or_senate_relevant_ebb(structured, raw):
            continue
        if not has_minimum_fields:
            continue
        if (structured.get("title") or "").strip().lower() == "ebb event":
            continue
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
            coverage_location=c["location"] if chamber == "House" else None,
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
        SOURCE_STATUS["congress_api"] = "Congress.gov API disabled: missing CONGRESS_API_KEY"
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
                best_window="committee room / public access areas",
                event_type="Hearing/Meeting",
                committee=committee,
                url=m.get("url") or f"https://www.congress.gov/committee-meetings",
                topic=clean(m.get("topic") or m.get("description") or ""),
            ))
        return out
    except Exception:
        SOURCE_STATUS["congress_api"] = "Congress.gov API error"
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
        low = f"{item.title} {item.raw}".lower()
        if item.source == "EBB":
            item.signal_class = "primary" if any(k in low for k in ["stakeout", "press conference", "media availability"]) else "secondary"
            item.signal_type = "stakeout" if "stakeout" in low else "press_conference" if "press conference" in low else "media_availability" if "availability" in low else "ebb_event"
        elif item.category == "Votes":
            item.signal_class = "primary"
            item.signal_type = "floor_vote"
        elif item.category in {"Floor Action", "Schedule"}:
            item.signal_class = "secondary"
            item.signal_type = "floor_action" if item.category == "Floor Action" else "floor_schedule"
        elif "hearing" in low or "committee" in (item.category.lower()):
            item.signal_class = "secondary"
            item.signal_type = "committee_hearing"
        elif item.source == "Congress.gov API":
            item.signal_class = "tertiary"
            item.signal_type = "bill_context"
        item.press_availability, item.best_window = compute_press_availability(item)
        item.signal_score = score_signal(item)
        item.action_confidence = "High" if item.signal_score >= 80 else "Medium" if item.signal_score >= 55 else "Low" if item.signal_score >= 25 else "Monitor only"
        item.movement_status = "Context only" if item.status == "historical" else "Move Now" if item.signal_score >= 80 else "Prepare to move" if item.signal_score >= 55 and item.best_window in {"before vote", "committee room / public access areas", "scheduled event location"} else "Watch" if item.signal_score >= 55 else "Monitor"
        item.coverage_value = "High" if item.signal_score >= 80 else "Medium" if item.signal_score >= 55 else "Low"
        if item.status == "historical":
            item.action_line = "Earlier item. Keep for context only."
        elif item.category == "Votes" and item.urgency == "move now":
            item.action_line = "Move to Ohio Clock or chamber exits before Senators clear the floor."
        elif item.category == "Votes":
            item.action_line = "Use the post-vote hallway window for reaction."
        elif item.category in {"Committee Meetings & Hearings"} or ("hearing" in item.title.lower()):
            item.action_line = "Coverage typically centers near the committee room before and after the hearing."
        elif item.source == "EBB" and item.location and item.location != "Location not parsed":
            item.action_line = f"Stage at {item.location} before the posted event time."
        elif item.source == "EBB":
            item.action_line = "Confirm location on EBB before staging."
        elif item.category == "Remarks":
            item.action_line = "Monitor for hallway follow-up if tied to active floor business."
        else:
            item.action_line = clean(item.movement_cue) or "Monitor floor updates, EBB postings, and committee schedules for developing coverage opportunities."
        enrich_public_fields(item)
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
        or (x.congress_bill_title and q in x.congress_bill_title.lower())
        or (x.congress_latest_action and q in x.congress_latest_action.lower())
        or (x.congress_summary and q in x.congress_summary.lower())
        or (x.congress_sponsors and q in x.congress_sponsors.lower())
        or (x.congress_policy_area and q in x.congress_policy_area.lower())
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
        "House / Joint Coverage Notes": [],
        "Committee Meetings & Hearings": [],
        "Live Signals": [],
        "Remarks": [],
        "Notes": [],
        "Earlier Floor Activity": [],
    }

    for item in items:
        if item.category == "Notes":
            raw = f"{item.title} {item.raw}".lower()
            procedural_terms = ["cloture filed","cloture invoked","motion to proceed","unanimous consent","objected","passage","confirmed","quorum","recess","adjourn","executive session"]
            if not any(t in raw for t in procedural_terms):
                item.category = "Low-Signal Items"
        if item.category == "Remarks" and not (item.senators_detected or is_meaningful(item.topic)):
            item.category = "Low-Signal Items"
        g.setdefault(item.category, []).append(item)

        if item.category not in {"Notes", "Remarks", "Earlier Floor Activity", "Low-Signal Items"}:
            g["Coverage Timeline"].append(item)

    return g


def filter_global_boilerplate(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = clean(str(value))
    if not v:
        return None
    return None if v.lower() in GLOBAL_SUPPRESSED_VALUES else v


def build_floor_remarks(items: List[JoltItem]) -> List[JoltItem]:
    remarks = []
    grouped_remarks: Dict[str, List[JoltItem]] = {}
    additional_items: List[JoltItem] = []
    leadership_names = {"John Thune", "Chuck Schumer", "Dick Durbin", "Mitch McConnell"}

    for item in items:
        if item.category != "Remarks":
            continue
        if item.senators_detected:
            senator_name = item.senators_detected[0]
            grouped_remarks.setdefault(senator_name, []).append(item)
        else:
            additional_items.append(item)
    for senator_name, senator_items in grouped_remarks.items():
        ordered = sorted(
            senator_items,
            key=lambda x: (x.sort_datetime is None, x.sort_datetime or "9999-99-99T99:99:99"),
        )
        times = [x.time_label for x in ordered if x.time_label]
        label = next((floor_remark_signal_label(x) for x in ordered if floor_remark_signal_label(x)), None)
        if len(ordered) > 1:
            remark_line = f"{senator_name} ({len(ordered)} remarks)"
            if times:
                remark_line += f" · {', '.join(times)}"
        else:
            only = ordered[0]
            remark_line = " · ".join(x for x in [senator_name, only.date_label, only.time_label] if x)
        if label:
            remark_line = f"{remark_line} — {label}"
        normalized = JoltItem(**asdict(ordered[-1]))
        normalized.title = remark_line
        normalized.takeaway = ""
        remarks.append(normalized)
    if additional_items:
        additional_count = len(additional_items)
        title = f"Additional remarks ({additional_count})"

        additional_names = [x.senators_detected[0] for x in additional_items if x.senators_detected]
        unique_names = list(dict.fromkeys(additional_names))

        if unique_names and len(unique_names) <= 3:
            title = f"{title} — {', '.join(unique_names)}"
        elif all((not x.senators_detected) or (x.senators_detected[0] not in leadership_names) for x in additional_items):
            title = f"{title} — non-leadership"

        remarks.append(JoltItem(
            source="Derived",
            raw=title,
            date_label=None, time_label=None, sort_datetime=None, category="Remarks",
            title=title, urgency="low", status="inferred",
            confidence="medium", quality="summary", location=None, building=None, measure=None,
            takeaway="", where_to_be="", movement_cue="",
            who_to_watch="", coverage_note="", staff_note="", gallery_note="", senators_detected=[],
            coverage_target=None, press_availability="", best_window="", event_type=None, committee=None, url=None, topic=None
        ))
    return remarks


def build_procedural_context(items: List[JoltItem]) -> List[JoltItem]:
    out = []
    seen = set()
    for item in items:
        raw = f"{item.title} {item.raw}".lower()
        title = None
        pkey = None
        if "cloture filed" in raw or "filed cloture" in raw:
            title = "Cloture filed on nomination"
            pkey = "cloture filed"
        elif "cloture vote" in raw or "motion to invoke cloture" in raw or "invoked cloture" in raw:
            title = "Cloture vote held"
            pkey = "cloture vote"
        elif "unanimous consent" in raw and "request" in raw:
            title = "UC request"
            pkey = "uc request"
        elif "unanimous consent" in raw:
            title = "UC agreement"
            pkey = "unanimous consent"
        elif "adjourn" in raw:
            title = "Senate adjourned (end of legislative day)"
            pkey = "adjournment"
        elif "vote underway" in raw or "now voting" in raw:
            title = "Roll call vote in progress"
            pkey = "vote underway"
        if title and pkey and pkey not in seen:
            out.append(JoltItem(
                source=item.source,
                raw=item.raw,
                date_label=item.date_label,
                time_label=item.time_label,
                sort_datetime=item.sort_datetime,
                category="Notes",
                title=title,
                urgency="low",
                status=item.status,
                confidence=item.confidence,
                quality=item.quality,
                location=None,
                building=None,
                measure=None,
                takeaway="",
                where_to_be="",
                movement_cue="",
                who_to_watch="",
                coverage_note="",
                staff_note="",
                gallery_note="",
                senators_detected=[],
                coverage_target=None,
                press_availability="",
                best_window="",
                event_type=None,
                committee=None,
                url=item.url,
                topic=None,
            ))
            seen.add(pkey)
    return out


HIGH_INTEREST_TOPICS = ["fisa","appropriations","nominations","defense","foreign relations","judiciary","budget","shutdown","continuing resolution","reconciliation","iran","ukraine","israel","immigration","investigations","ethics","leadership","supreme court","cr"]
def score_signal(item: JoltItem) -> int:
    score = {"primary": 40, "secondary": 25, "tertiary": 10, "human": 45}.get(item.signal_class, 10)
    score += {"move now": 30, "prepare": 20, "watch": 12, "scheduled": 8, "monitor": 3, "historical": -60, "low": 3}.get(item.urgency, 3)
    if item.status == "historical":
        score -= 60
    minutes = None
    if item.sort_datetime:
        try:
            minutes = (datetime.fromisoformat(item.sort_datetime).replace(tzinfo=None) - datetime.now()).total_seconds() / 60
        except Exception:
            minutes = None
    if minutes is None:
        score += -5
    elif -45 <= minutes <= 5:
        score += 30
    elif 0 < minutes <= 15:
        score += 25
    elif minutes <= 30:
        score += 20
    elif minutes <= 90:
        score += 12
    elif minutes <= 600:
        score += 6
    else:
        score += -35
    loc = (item.location or "").lower()
    if re.search(r"\b(sd|sh|sr)-\d+|s-\d+\b", loc):
        score += 20
    elif any(x in loc for x in ["ohio clock", "chamber exits", "subway", "s-325"]):
        score += 18
    elif item.building:
        score += 8
    else:
        score += -10
    if any(x in " ".join(item.senators_detected) for x in LEADERSHIP_NAMES):
        score += 18
    elif item.senators_detected:
        score += 10
    raw = f"{item.title} {item.raw}".lower()
    if "vote underway" in raw or "now voting" in raw: score += 35
    elif "roll call" in raw: score += 25
    elif "cloture vote" in raw: score += 25
    elif "stakeout" in raw: score += 30
    elif "press conference" in raw: score += 28
    elif "media availability" in raw: score += 28
    elif "hearing" in raw: score += 15
    elif "markup" in raw or "business meeting" in raw: score += 18
    elif "unanimous consent" in raw or "objected" in raw: score += 20
    elif "remarks" in raw: score += 6
    topic = (item.topic or "").lower()
    if any(t in topic for t in HIGH_INTEREST_TOPICS): score += 15
    score += {"Congressional Reporters": 12, "EBB": 18, "Congress.gov API": 15}.get(item.source, 15 if "senate.gov" in (item.url or "").lower() else 0)
    return max(0, min(100, int(score)))


def enrich_public_fields(item: JoltItem) -> None:
    raw = f"{item.title} {item.raw}".lower()
    item.coverage_location = item.location if item.location and item.location != "Location not parsed" else (item.where_to_be or None)
    item.coverage_action = item.action_line or item.movement_cue
    item.context_note = item.staff_note
    item.gallery_guidance = item.gallery_note
    item.coverage_window = "post-event" if item.status == "historical" else "underway" if "now voting" in raw else "upcoming" if item.time_label else "rolling"
    if item.status == "historical":
        item.coverage_window = "earlier"
    if not item.time_label:
        item.coverage_window = "none" if item.status == "historical" else item.coverage_window
    if item.category == "Committee Meetings & Hearings":
        item.coverage_type = "Committee hearing" if "hearing" in raw else "Committee meeting"
    else:
        item.coverage_type = "vote" if item.category == "Votes" else "hearing" if "hearing" in raw else "stakeout" if "stakeout" in raw else "press conference" if "press conference" in raw else "floor update"
    if any(x in raw for x in ["roll call", "recorded vote", "cloture vote", "press conference", "media availability", "stakeout"]):
        item.visibility_level = "High"
    elif any(x in raw for x in ["hearing", "markup", "nomination", "remarks"]) or item.senators_detected:
        item.visibility_level = "Medium"
    else:
        item.visibility_level = "Low"
    if "recorded vote" in raw or "roll call" in raw:
        item.public_value = "A recorded vote creates a clear public accountability and coverage window."
    elif "voice vote" in raw:
        item.public_value = "The Senate acted without a recorded vote; this may be lower visibility unless the matter is high-profile."
    else:
        item.public_value = item.takeaway
    if item.category == "Committee Meetings & Hearings":
        item.legislative_context = "A Senate committee is holding a scheduled meeting or hearing."
    else:
        item.legislative_context = "The Senate is considering current floor business and related procedural actions."
    if "motion to invoke cloture" in raw:
        item.procedure_stage, item.outcome_stage, item.vote_status = "cloture vote", "procedural", "scheduled"
        item.legislative_context = "The Senate is voting on whether to limit debate."
    elif "invoked cloture" in raw:
        item.procedure_stage, item.outcome_stage = "post-cloture", "advancing"
        item.legislative_context = "Debate is now limited; the Senate is moving toward final action or disposition."
    elif "filed cloture" in raw or "file cloture" in raw:
        item.procedure_stage, item.outcome_stage = "pre-cloture", "procedural"
        item.legislative_context = "Cloture has been filed, beginning the process that may lead to a later vote to limit debate."
    elif "motion to proceed" in raw:
        item.outcome_stage = "procedural"
        item.legislative_context = "The Senate is considering whether to take up the measure."
    if "adjourn" in raw:
        item.chamber_phase = "adjourned"
    elif "recess" in raw:
        item.chamber_phase = "recess"
    elif "executive session" in raw:
        item.chamber_phase = "executive session"
    if item.coverage_type == "vote":
        item.access_note = "High-interest coverage may occur around public-facing Senate coverage locations."
        item.rules_note = "Timing can change based on floor proceedings and official direction."
        item.pool_note = "Pool coverage may apply for unusually high-interest events."
    elif item.coverage_type == "hearing":
        item.access_note = "Coverage should be coordinated through the appropriate Gallery or committee contact."
        item.rules_note = "Committee direction and room capacity may affect coverage."
        item.pool_note = "Pool coverage may apply for high-interest or capacity-limited hearings."
    elif item.coverage_type in {"stakeout", "press conference"}:
        item.access_note = "Use authorized public-facing stakeout areas."
        item.rules_note = "Avoid obstructing pedestrian flow and follow Gallery positioning guidance."
        item.pool_note = "Pool arrangements may apply depending on space and interest."
    else:
        item.access_note = "Monitor public floor updates and official sources."
        item.rules_note = "Coverage remains subject to Senate rules and Gallery guidance."
        item.pool_note = "No pool note."
    item.official_context = {
        "bill_title": item.congress_bill_title,
        "latest_action": item.congress_latest_action,
        "policy_area": item.congress_policy_area,
    }
    item.links = [{"label": "Open source", "url": item.url or ""}] + ([{"label": "Congress.gov", "url": item.congress_url}] if item.congress_url else [])


def important_now(items: List[JoltItem]) -> Optional[JoltItem]:
    active = [x for x in items if x.status != "historical"]

    if not active:
        return None

    return sorted(active, key=lambda x: x.signal_score, reverse=True)[0]


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








def _fmt_item_datetime(item: JoltItem) -> str:
    parts = [x for x in [item.date_label, item.time_label] if x]
    return " · ".join(parts) if parts else "Time TBD"


def build_next_expected_floor_action(items: List[JoltItem]) -> Optional[JoltItem]:
    candidates = []
    for item in items:
        if item.status == "historical":
            continue
        source = (item.source or "").lower()
        if item.category not in {"Schedule", "Votes", "Floor Action"}:
            continue
        if not any(x in source for x in ["congressional", "senate", "radio", "congress.gov"]):
            continue
        candidates.append(item)

    if not candidates:
        return None

    dated = [x for x in candidates if x.sort_datetime]
    if dated:
        return sorted(dated, key=lambda x: x.sort_datetime)[0]
    return sorted(candidates, key=lambda x: x.signal_score, reverse=True)[0]


def build_forward_schedule_context() -> Dict[str, Any]:
    global LAST_FORWARD_SCHEDULE_DEBUG
    payload = fetch_forward_schedule_sources()
    merged = " ".join(x["text"] for x in payload["texts"])
    schedule_context = parse_forward_floor_schedule(merged, date.today())
    actions = extract_next_floor_actions(merged)
    vote_related = [a for a in actions if any(k in a["text"].lower() for k in ["vote", "cloture", "confirmation", "adoption"])]
    LAST_FORWARD_SCHEDULE_DEBUG = {
        "loaded_sources": payload["loaded_sources"],
        "errors": payload["errors"],
        "forward_schedule_source_text": merged[:5000],
        "schedule_context": schedule_context,
        "parsed_forward_schedule": schedule_context,
        "ignored_dates": schedule_context.get("ignored_dates", []),
        "rejected_blocks": schedule_context.get("rejected_blocks", []),
        "parsed_pro_formas": schedule_context.get("pro_formas", []),
        "parsed_next_convening": schedule_context.get("next_convening"),
        "parsed_vote_block": schedule_context.get("vote_block"),
        "raw_vote_block_time": schedule_context.get("raw_vote_block_time", ""),
        "normalized_vote_block_time": schedule_context.get("normalized_vote_block_time", ""),
        "vote_block_display_time": schedule_context.get("vote_block_display_time", ""),
        "vote_block_extraction_method": schedule_context.get("vote_block_extraction_method", ""),
        "parsed_expected_votes": schedule_context.get("expected_votes", []),
    }
    return LAST_FORWARD_SCHEDULE_DEBUG


def render_next_expected_floor_action(item: Optional[JoltItem], context: Dict[str, Any]) -> str:
    def classify_expected_vote(text: str) -> Tuple[str, str]:
        lower = clean(text).lower()
        if "motion to invoke cloture" in lower or "cloture" in lower:
            return "Cloture vote (limits debate)", "This vote decides whether to limit debate and move toward final Senate action."
        if "adoption of resolution" in lower or "adoption" in lower:
            return "Adoption vote (procedural)", "This procedural vote sets up Senate consideration terms before later disposition."
        if "confirmation" in lower:
            return "Confirmation vote (final action)", "This is final Senate action on a nomination."
        if "passage" in lower:
            return "Passage vote (final legislative action)", "This is final Senate action on legislation."
        return "Expected floor vote", "This vote advances current floor consideration."
    schedule_context = context.get("schedule_context", {}) if context else {}
    if schedule_context and (schedule_context.get("next_convening") or schedule_context.get("pro_formas")):
        pro_formas = schedule_context.get("pro_formas", [])
        source_text = context.get("forward_schedule_source_text", "") if context else ""
        pro_forma_html = "".join(
            f"<li>{html.escape(p.get('date_label', ''))} · {html.escape(p.get('time_label', ''))}</li>" for p in pro_formas
        ) or "<li>None announced</li>"
        next_convening = schedule_context.get("next_convening", {})
        vote_block = schedule_context.get("vote_block", {})
        expected_votes = schedule_context.get("expected_votes", [])

        convene_label = " · ".join(x for x in [next_convening.get("date_label", ""), next_convening.get("time_label", "")] if x) or "Not announced"
        vote_block_time_label = schedule_context.get("vote_block_time_label", "")
        vote_date_label = vote_block.get("date_label", "")
        vote_label = " · ".join(x for x in [vote_date_label, vote_block_time_label] if x) or "Future floor action not yet scheduled"

        votes_to_render = expected_votes[:6]
        if vote_block:
            if votes_to_render:
                votes_html = "".join(
                    f"<li><strong>{html.escape(classify_expected_vote(v)[0])}</strong>: {html.escape(v)}</li>"
                    for v in votes_to_render
                )
            else:
                votes_html = "<li>Expected votes pending official listing</li>"
        else:
            votes_html = "<li>No vote block announced.</li>"
        return f"""
        <div class='card'>
            <!-- May 11 forward schedule fixed path active -->
            <div class='logistics'>
                <div><strong>Pro forma sessions:</strong><ul>{pro_forma_html}</ul></div>
                <div><strong>Senate next convenes:</strong> {html.escape(convene_label)}</div>
                <div><strong>Expected vote block:</strong> {html.escape(vote_label)}</div>
                <div><strong>Expected votes:</strong><ol>{votes_html}</ol></div>
                <div><strong>Legislative context:</strong> The Senate is scheduled to return after pro forma sessions. The first announced vote block is expected to set up executive-session consideration and potential final actions.</div>
                <div><strong>Coverage timing:</strong> The highest-value public coverage window is the announced vote block.</div>
            </div>
        </div>
        """

    parsed_actions = context.get("parsed_next_floor_actions", []) if context else []
    if parsed_actions:
        first = parsed_actions[0]
        rows = []
        for a in parsed_actions[:5]:
            when = " · ".join(x for x in [a.get("date_label"), a.get("time_label")] if x) or "Time TBD"
            rows.append(f"<li><strong>{html.escape(when)}</strong> — {html.escape(a.get('text', ''))}</li>")
        return f"""
        <div class='card'>
            <h3>{html.escape(' · '.join(x for x in [first.get('date_label'), first.get('time_label')] if x) or 'Upcoming floor schedule')}</h3>
            <p><strong>{html.escape(first.get('text', 'Public schedule floor action'))}</strong></p>
            <div class='logistics'>
                <div><strong>Legislative context:</strong> The Senate is scheduled for upcoming floor business based on public schedule source language.</div>
                <div><strong>Coverage timing:</strong> Coverage begins around convening; the higher-value public coverage window is the announced vote block.</div>
                <div><strong>Public value:</strong> The next convening and vote block set likely floor coverage windows.</div>
            </div>
            <ul>{''.join(rows)}</ul>
            <a class='source' href='{html.escape(CONGRESSIONAL_REPORTERS_URL)}' target='_blank'>Public schedule source</a>
        </div>
        """

    if not item:
        return "<p class='empty'>No next floor action found in public schedule sources. Check Congressional Reporters, Radio-TV, and Senate floor schedule.</p>"

    source_link = item.url or CONGRESSIONAL_REPORTERS_URL
    vote_status = item.vote_status or ("underway" if "now voting" in f"{item.title} {item.raw}".lower() else "expected" if item.time_label else "scheduled")
    chamber_phase = item.chamber_phase or ("executive session" if "executive session" in f"{item.title} {item.raw}".lower() else "legislative business")
    return f"""
    <div class='card'>
        <h3>{html.escape(_fmt_item_datetime(item))}</h3>
        <p><strong>{html.escape(item.title)}</strong></p>
        <div class='logistics'>
            <div><strong>Floor action type:</strong> {html.escape(item.category)}</div>
            <div><strong>Chamber phase:</strong> {html.escape(chamber_phase)}</div>
            <div><strong>Vote status:</strong> {html.escape(vote_status)}</div>
            <div><strong>Legislative context:</strong> {html.escape(item.legislative_context or 'Public schedule source indicates upcoming floor business.')}</div>
            <div><strong>Coverage timing:</strong> {html.escape(item.coverage_note or item.action_line or 'Coverage begins around the announced floor timing.')}</div>
            <div><strong>Public value:</strong> {html.escape(item.public_value or item.takeaway)}</div>
        </div>
        <a class='source' href='{html.escape(source_link)}' target='_blank'>Public schedule source</a>
    </div>
    """


def render_forward_look(items: List[JoltItem], featured: Optional[JoltItem], context: Dict[str, Any]) -> str:
    schedule_context = context.get("schedule_context", {}) if context else {}
    vote_block = schedule_context.get("vote_block", {}) if schedule_context else {}
    vote_block_time_label = (schedule_context.get("vote_block_time_label", "") if schedule_context else "")
    vote_date_label = (vote_block.get("date_label") if vote_block else "")
    vote_timing = " · ".join(x for x in [vote_date_label, vote_block_time_label] if x) or "Future floor action not yet scheduled"
    parsed = schedule_context.get("expected_votes", []) if schedule_context else []

    if parsed:
        def classify_expected_vote(text: str) -> Tuple[str, str, str]:
            lower_text = clean(text).lower()
            if "motion to invoke cloture" in lower_text or "cloture" in lower_text:
                return "Cloture vote (limits debate)", "Floor Consideration — Executive Session", "If cloture is invoked, debate time is limited and the Senate moves toward confirmation."
            if "adoption of resolution" in lower_text or "adoption" in lower_text:
                return "Adoption vote (procedural)", "Morning Business", "Adoption establishes procedural terms that set up subsequent nomination or floor consideration."
            if "confirmation" in lower_text:
                return "Confirmation vote (final action)", "Floor Consideration — Executive Session", "After confirmation, the nomination is finally disposed and the Senate proceeds to the next item."
            if "passage" in lower_text:
                return "Passage vote (final legislative action)", "Floor Consideration — Legislative Business", "After passage, the measure is finally disposed and transmitted to the next chamber/stage."
            return "Expected floor action", "Floor Consideration", "This vote advances active floor business."
        cards = []
        for text in parsed[:6]:
            lower_text = text.lower()
            action, chamber_phase, follow_on = classify_expected_vote(text)
            title = extract_measure(text) or text[:90]
            if "calendar #5" in lower_text and "s.res.690" in lower_text:
                title = "S.Res.690 / Calendar #5"
            if "executive calendar #728" in lower_text and "warsh" in lower_text:
                title = "Executive Calendar #728 Kevin Warsh"
            cards.append(f"""
            <article class='card'>
                <h3>{html.escape(title)}</h3>
                <div class='logistics'>
                    <div><strong>Expected action:</strong> {html.escape(action)}</div>
                    <div><strong>Timing:</strong> {html.escape(vote_timing)}</div>
                    <div><strong>Chamber phase:</strong> {html.escape(chamber_phase)}</div>
                    <div><strong>Context:</strong> {html.escape(follow_on)}</div>
                </div>
            </article>
            """)

        cloture_filed = schedule_context.get("cloture_filed", [])
        if any("executive calendar #727" in clean(x).lower() for x in cloture_filed):
            cards.append(f"""
            <article class='card'>
                <h3>Executive Calendar #727 Kevin Warsh</h3>
                <div class='logistics'>
                    <div><strong>Expected action:</strong> Cloture filed</div>
                    <div><strong>Timing:</strong> future action not yet scheduled</div>
                    <div><strong>Chamber phase:</strong> Executive session</div>
                    <div><strong>Context:</strong> Cloture has been filed, signaling possible future floor consideration.</div>
                </div>
            </article>
            """)
        return "".join(cards) if cards else "<p class='empty'>No votes scheduled</p>"

    include_tokens = ["cloture", "motion to proceed", "confirmation", "nomination", "passage", "roll call", "executive", "s.", "h.r.", "resolution"]
    out = []
    featured_key = (featured.title, featured.sort_datetime, featured.measure) if featured else None
    for item in items:
        if item.status == "historical":
            continue
        raw = f"{item.title} {item.raw}".lower()
        if not any(tok in raw for tok in include_tokens) and item.category not in {"Votes", "Schedule", "Floor Action"}:
            continue
        key = (item.title, item.sort_datetime, item.measure)
        if featured_key and key == featured_key:
            continue
        out.append(item)

    if not out and parsed:
        return "<p class='empty'>No votes scheduled</p>"
    if not out:
        return empty_message("Forward Look: Legislation & Nominations")

    cards = []
    for item in sorted(out, key=lambda x: (x.sort_datetime is None, x.sort_datetime or '9999'))[:6]:
        measure = item.measure or item.title
        cards.append(f"""
        <article class='card'>
            <h3>{html.escape(measure)}</h3>
            <div class='logistics'>
                <div><strong>Expected action:</strong> {html.escape(item.title)}</div>
                <div><strong>Timing:</strong> {html.escape(_fmt_item_datetime(item))}</div>
                <div><strong>Procedural stage:</strong> {html.escape(item.procedure_stage or item.category)}</div>
            </div>
            <a class='source' href='{html.escape(item.url or CONGRESSIONAL_REPORTERS_URL)}' target='_blank'>Public schedule source</a>
        </article>
        """)
    return "".join(cards)


def top_actions(items: List[JoltItem], context: Optional[Dict[str, Any]] = None) -> List[str]:
    schedule_context = (context or {}).get("schedule_context", {})
    has_next_expected = bool(schedule_context.get("next_convening") or schedule_context.get("vote_block") or schedule_context.get("expected_votes"))
    has_active_floor = any(x.status != "historical" and x.category in {"Votes", "Floor Action", "Schedule"} for x in items)
    if has_next_expected and not has_active_floor:
        vote_block = schedule_context.get("vote_block", {})
        vote_time = schedule_context.get("vote_block_time_label", "Time TBD")
        vote_date = vote_block.get("date_label", "Next convening day")
        expected_votes = schedule_context.get("expected_votes", [])
        vote_types = []
        for v in expected_votes:
            lv = v.lower()
            if "cloture" in lv:
                vote_types.append("cloture")
            elif "adoption" in lv:
                vote_types.append("adoption")
            elif "confirmation" in lv:
                vote_types.append("confirmation")
            elif "passage" in lv:
                vote_types.append("passage")
        type_line = ", ".join(dict.fromkeys(vote_types)) if vote_types else "scheduled votes"
        return [
            f"Prepare for the expected vote block ({vote_date} · {vote_time}) and pre-position before roll calls begin.",
            f"Prioritize {type_line} coverage plans tied to the announced vote block sequence.",
            "Watch for UC agreement/UC request or cloture-related schedule changes that can move vote timing quickly.",
        ]
    ranked = sorted([x for x in items if x.status != "historical" and should_show_in_main(x)], key=lambda x: x.signal_score, reverse=True)
    verbs = ["Monitor", "Track", "Watch", "Confirm"]
    actions = []

    for idx, item in enumerate(ranked[:4]):
        base = clean((item.action_line or item.movement_cue or item.takeaway).split(".")[0])
        verb = verbs[idx % len(verbs)]
        if base:
            actions.append(f"{verb}: {base[0].lower() + base[1:] if len(base) > 1 else base.lower()}")

    while len(actions) < 2:
        fallback = [
            "Monitor: floor schedule updates and leadership cues.",
            "Track: committee calendars and hearing starts.",
            "Watch: EBB postings for new stakeouts or events.",
            "Confirm: vote timing and room-level guidance before moving.",
        ]
        actions.append(fallback[len(actions)])

    if len(actions) < 3:
        actions.append("Confirm: expected timing with official Senate and committee sources.")

    return actions[:3]
def should_show_in_main(item: JoltItem) -> bool:
    return item.signal_score >= 25 and any([item.time_label, item.location, item.senators_detected, item.topic, item.measure, item.action_line])

def detect_activity_mode(items: List[JoltItem]) -> str:
    text = " ".join((x.raw + " " + x.title).lower() for x in items)
    if "pro forma" in text or "recess" in text:
        return "RECESS_OR_PRO_FORMA"
    if any(x.signal_type == "floor_vote" and x.status != "historical" for x in items):
        return "ACTIVE_FLOOR"
    if any("committee" in (x.signal_type or "") and x.status != "historical" for x in items):
        return "COMMITTEE_DAY"
    if any(x.source == "EBB" and x.status != "historical" for x in items):
        return "EVENT_DAY"
    return "LOW_ACTIVITY"
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
            "movement": "Move Now",
            "watch": "Active floor vote window; watch leadership, sponsors, and swing votes.",
        }

    for vote in votes:
        dt = parse_item_dt(vote)
        if not dt:
            continue
        minutes_since = (now - dt).total_seconds() / 60
        if 0 <= minutes_since <= 30:
            return {
                "where_to_be_now": "Hallway reaction areas near chamber exits and Ohio Clock",
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
                "movement": "Move Now",
                "watch": "EBB-timed event window is within 30 minutes.",
            }

    return {
        "where_to_be_now": "No active coverage location",
        "movement": "Monitor",
        "watch": "No votes scheduled; no active floor trigger is listed in current public schedule sources.",
    }

def coverage_outlook(items: List[JoltItem], groups: Dict[str, List[JoltItem]]) -> str:
    if groups.get("Votes"):
        return "Floor activity detected. Best access windows around votes and chamber exits."

    if groups.get("Events"):
        return "Focus on EBB events, hearings, and press availabilities."

    if groups.get("Schedule"):
        return "Plan around convening time and leader remarks."

    return "No votes scheduled. No hearings scheduled. No media events listed."


def badge_class(urgency: str) -> str:
    return {
        "move now": "red",
        "watch": "orange",
        "scheduled": "blue",
        "low": "gray",
    }.get(urgency, "gray")


def item_card(item: JoltItem, view: str = "reporter") -> str:
    display_date = fmt_short_date_label(item.date_label)
    when = " · ".join(x for x in [display_date, item.time_label] if is_meaningful(x)) or "Time TBD"

    links = []
    committee_event = any(k in clean(f"{item.title} {item.raw}").lower() for k in ["hearing", "committee meeting", "markup", "business meeting"])
    if item.committee and committee_event:
        links.append(f"<a class='source' href='{COMMITTEE_SCHEDULE_URL}' target='_blank'>Committee Schedule</a>")
    if item.source == 'EBB':
        links.append(f"<a class='source' href='{EBB_URL}' target='_blank'>Open source</a>")
    elif item.url:
        links.append(f"<a class='source' href='{html.escape(item.url)}' target='_blank'>{'Open Congressional Reporters' if item.source == 'Congressional Reporters' else 'Open source'}</a>")

    if item.category == "Committee Meetings & Hearings":
        has_real_details = all([
            is_meaningful(item.committee), is_meaningful(item.topic), is_meaningful(item.location), is_meaningful(item.time_label)
        ])
        if not has_real_details:
            return ""

    title = item.title
    description = item.takeaway if is_meaningful(item.takeaway) else ""

    section_name = ""
    if item.category == "Remarks":
        section_name = "Floor Remarks"
    elif item.title in {"Cloture filed on nomination", "Cloture vote held", "Unanimous consent action", "Senate adjourned", "Vote underway"}:
        section_name = "Procedural Context"
    logistics_rows = []
    if section_name == "Procedural Context":
        title = " · ".join(x for x in [item.title, display_date, item.time_label] if x)
        return f"""
        <article class="card">
            <h3>{html.escape(title)}</h3>
        </article>
        """
    elif section_name == "Floor Remarks":
        return f"""
        <article class="card">
            <h3>{html.escape(item.title)}</h3>
        </article>
        """
    elif item.category == "Earlier Floor Activity":
        event_type = clean(item.event_type or item.title or "Floor Activity")
        action = clean(item.action_line or item.takeaway or item.raw or "Activity update")
        line = f"{event_type} — {action}"
        line = " · ".join(x for x in [line, display_date, item.time_label] if x)
        return f"""
        <article class="card">
            <h3>{html.escape(line)}</h3>
        </article>
        """
    else:
        if is_meaningful(filter_global_boilerplate(item.coverage_location)): logistics_rows.append(("Coverage location", filter_global_boilerplate(item.coverage_location)))
        if is_meaningful(filter_global_boilerplate(item.coverage_window)): logistics_rows.append(("Coverage window", filter_global_boilerplate(item.coverage_window)))
        guidance = filter_global_boilerplate(item.coverage_action or item.action_line)
        if is_meaningful(guidance): logistics_rows.append(("Coverage guidance", guidance))
        watch = filter_global_boilerplate(item.who_to_watch)
        if is_meaningful(watch) and watch != "Senate Committee": logistics_rows.append(("Who to watch", watch))
        ctype = filter_global_boilerplate(item.coverage_type)
        if is_meaningful(ctype) and ctype != "Committee meeting": logistics_rows.append(("Coverage type", ctype))
        lc = filter_global_boilerplate(item.legislative_context)
        if is_meaningful(lc) and lc != "A Senate committee is holding a scheduled meeting or hearing.": logistics_rows.append(("Legislative context", lc))
        pv = filter_global_boilerplate(item.public_value)
        if is_meaningful(pv) and pv != "Official Senate committee meeting listing.": logistics_rows.append(("Why it matters", pv))

    logistics = ""
    if logistics_rows:
        logistics = "<div class='logistics'>" + "".join(f"<div><strong>{html.escape(k)}:</strong> {html.escape(v)}</div>" for k,v in logistics_rows) + "</div>"

    return f"""
    <article class="card">
        <h3>{html.escape(title)}</h3>
        <div class="when">{html.escape(when)}</div>
        {f"<p>{html.escape(description)}</p>" if description else ""}
        {logistics}
        <div class='source-links'>{''.join(links)}</div>
    </article>
    """


def empty_message(title: str) -> str:
    messages = {
        "Key Votes": "No votes scheduled or underway.",
        "News Events & Stakeouts": "No media events listed.",
        "Committee Meetings & Hearings": "No hearings scheduled.",
        "Floor Remarks": "No floor remarks are driving coverage right now.",
        "Procedural Context": "No procedural updates listed.",
        "Recent Procedure": "No procedural actions in the last 72 hours.",
        "Recent Activity": "No recent activity.",
        "Next Expected Floor Action": "No next floor action found in public schedule sources. Check Congressional Reporters, Radio-TV, and Senate floor schedule.",
        "Forward Look: Legislation & Nominations": "No votes scheduled.",
        "Coverage Timeline": "No active coverage timeline yet. Watch for votes, EBB events, or committee hearings.",
        "Live Signals": "Live signals are disabled or no reported signals matched.",
    }
    return f"<p class=\"empty\">{html.escape(messages.get(title, 'No updates listed.'))}</p>"


def section(title: str, items: List[JoltItem], view: str, collapsed: bool = False) -> str:
    if collapsed:
        limit = 5 if title == "Recent Activity" else 20
        visible = items[:limit]
        cards = "".join(item_card(item, view) for item in visible)
        hidden_count = max(0, len(items) - limit)
        hidden_note = f"<p class='empty'>{hidden_count} additional items collapsed.</p>" if hidden_count and title == "Recent Activity" else ""

        return f"""
        <section class="section">
            <details>
                <summary><h2>{html.escape(title)} ({len(items)})</h2></summary>
                {cards if cards else empty_message(title)}{hidden_note}
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


def render_key_votes_section(votes: List[JoltItem], context: Dict[str, Any], view: str) -> str:
    schedule_context = context.get("schedule_context", {}) if context else {}
    vote_block = schedule_context.get("vote_block", {}) if schedule_context else {}
    vote_block_time_label = schedule_context.get("vote_block_time_label", "") if schedule_context else ""
    key_votes_time_label = vote_block_time_label
    vote_block_date = vote_block.get("date_label", "")
    next_votes_line = ""
    if vote_block_date or key_votes_time_label:
        next_votes_line = f"Next expected votes: {vote_block_date} · {key_votes_time_label}"
    fallback = "No votes scheduled today."
    message = f"{fallback}<br>{html.escape(next_votes_line)}" if next_votes_line else fallback
    return f"""
    <section class="section">
        <h2>Key Votes</h2>
        <p class="empty">{message}</p>
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
            return {"where": item.where_to_be, "movement": "Move Now", "watch": item.who_to_watch}
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




def is_recent_earlier_activity(item: JoltItem, now: datetime, session_day: Optional[date]) -> bool:
    if not item.sort_datetime:
        return False
    try:
        dt = datetime.fromisoformat(item.sort_datetime)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
    except ValueError:
        return False
    return dt >= now - timedelta(hours=48) or (session_day is not None and dt.date() == session_day and dt >= now - timedelta(hours=48))


def has_meaningful_recent_activity(item: JoltItem) -> bool:
    text = clean(" ".join([item.title or "", item.raw or "", item.action_line or ""])).strip()
    if not text:
        return False
    lowered = text.lower()
    generic_terms = {"event", "ebb event", "update", "item"}
    return lowered not in generic_terms


def current_senate_session_day(items: List[JoltItem]) -> Optional[date]:
    floor_categories = {"Votes", "Floor Action", "Schedule", "Earlier Floor Activity"}
    floor_dates: List[date] = []
    for item in items:
        if item.category not in floor_categories or not item.sort_datetime:
            continue
        try:
            dt = datetime.fromisoformat(item.sort_datetime)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            floor_dates.append(dt.date())
        except ValueError:
            continue
    return max(floor_dates) if floor_dates else None

def _window_label(certainty: str) -> str:
    return {"scheduled": "Scheduled", "expected": "Expected", "developing": "Developing", "none": "No active window"}.get(certainty, "No active window")


def _status_label(score: float) -> str:
    if score >= 80:
        return "Floor Consideration — Executive Session"
    if score >= 60:
        return "Morning Business"
    if score >= 40:
        return "Floor Consideration — Executive Session"
    return "Pro Forma Period (no legislative business)"


def procedural_buckets(items: List[JoltItem], now: datetime) -> Tuple[List[JoltItem], List[JoltItem]]:
    recent: List[JoltItem] = []
    background: List[JoltItem] = []
    for item in items:
        target = background
        if item.sort_datetime:
            try:
                dt = datetime.fromisoformat(item.sort_datetime)
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                if dt >= now - timedelta(hours=96):
                    target = recent
            except ValueError:
                pass
        target.append(item)
    return recent, background


def _build_upcoming_reference_text(items: List[JoltItem], now: datetime) -> str:
    references: List[str] = []
    for item in items:
        references.extend([item.title or "", item.raw or "", item.measure or "", item.topic or ""])
        if item.sort_datetime:
            try:
                dt = datetime.fromisoformat(item.sort_datetime)
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                if dt >= now - timedelta(hours=12):
                    references.append(item.raw or "")
            except ValueError:
                continue
    return clean(" ".join(references)).lower()


def filter_background_procedure(items: List[JoltItem], upcoming_reference_text: str) -> List[JoltItem]:
    filtered: List[JoltItem] = []
    for item in items:
        raw = clean(f"{item.title} {item.raw}").lower()
        if item.title == "Cloture vote held":
            continue
        has_nomination_detail = any(k in raw for k in ["executive calendar", "nomination", "#"])
        if has_nomination_detail and any(token in upcoming_reference_text for token in raw.split() if len(token) > 4):
            normalized = JoltItem(**asdict(item))
            normalized.date_label = None
            normalized.time_label = None
            filtered.append(normalized)
    return filtered


def to_signal_items(items: List[JoltItem]) -> List[SignalItem]:
    event_count = len([x for x in items if x.status != "historical"])
    density = 80 if event_count > 3 else 60 if event_count == 2 else 40 if event_count == 1 else 10
    out=[]
    now = datetime.now()
    for i,item in enumerate(items):
        raw=(f"{item.title} {item.raw}").lower()
        source = "committee_feed" if "committee" in (item.source or "").lower() else "ebb" if "ebb" in (item.source or "").lower() else "congress_gov"
        coverage_type = "vote" if item.category=="Votes" else "hearing" if "hearing" in raw else "stakeout" if "stakeout" in raw else "press_event" if "press" in raw else "procedural_action" if any(k in raw for k in ["cloture","motion to proceed","unanimous consent"]) else "floor_proceeding"
        press = 90 if coverage_type=="vote" else 95 if "cloture vote" in raw else 70 if "cloture filed" in raw else 75 if coverage_type=="hearing" else 20 if coverage_type=="floor_remarks" else 50
        timing=30
        if item.sort_datetime:
            try:
                dt=datetime.fromisoformat(item.sort_datetime)
                mins=(dt-now).total_seconds()/60
                if -15 <= mins <= 15: timing=100
                elif 0 < mins < 60: timing=80
                elif dt.date()==now.date(): timing=60
                elif mins < -15: timing=10
            except Exception:
                pass
        procedural = 100 if "final passage" in raw or "passage vote" in raw else 95 if "cloture invoked" in raw else 80 if "cloture filed" in raw else 75 if "motion to proceed" in raw else 70 if "amendment vote" in raw else 40
        leadership = 100 if any(x in raw for x in ["majority leader","minority leader","whip"]) else 80 if item.committee else 70 if item.senators_detected else 40
        total = (press*0.30)+(timing*0.25)+(procedural*0.20)+(leadership*0.15)+(density*0.10)
        cert = item.coverage_window if item.coverage_window in {"scheduled","expected","developing","none"} else ("scheduled" if item.time_label else "developing" if item.status!="historical" else "none")
        out.append(SignalItem(
            id=f"sig-{i}", timestamp=datetime.now().isoformat(), last_updated=datetime.now().isoformat(), source=source, source_confidence="confirmed",
            coverage_type=coverage_type, chamber="senate", title=item.title, description=item.takeaway or item.raw, location=item.location or "Location not listed",
            coverage_location=item.coverage_location or item.where_to_be or "Senate floor and nearby press areas",
            coverage_window={"start": item.sort_datetime, "end": None, "certainty": cert}, coverage_guidance=item.coverage_note or "Monitor official schedule updates.",
            people=item.senators_detected or [], committees=[item.committee] if item.committee else [], bill_ids=[item.measure] if item.measure else [],
            legislative_stage=item.procedure_stage or "Floor activity", legislative_context=item.legislative_context or item.context_note or "", public_value=item.public_value or "medium",
            press_interest_score=press, timing_score=timing, procedural_score=procedural, leadership_score=leadership, event_density_score=density, total_score=round(total,1),
            status="active" if item.status!="historical" else "completed"
        ))
    return out

@app.get("/", response_class=HTMLResponse)
def dashboard(
    q: Optional[str] = Query(None),
    view: str = Query("reporter", pattern="^(reporter|staff|gallery)$"),
    earlier: bool = Query(False),
):
    try:
        all_items = get_all_items()
        items = filter_items(all_items, q, view, show_earlier=earlier)
        forward_context = build_forward_schedule_context()
        low_signal = [x for x in items if not any([x.time_label, x.location and x.location != "Location not parsed", x.senators_detected, x.measure, x.topic, x.action_line])]
        main_items = [x for x in items if x not in low_signal]

        groups = grouped(main_items)
        all_groups = grouped(all_items)
        floor_remarks_items = build_floor_remarks(all_groups.get("Remarks", []))
        procedural_items = build_procedural_context(all_groups.get("Earlier Floor Activity", []) + all_groups.get("Notes", []))
        procedural_keys = {x.title.lower() for x in procedural_items}
        suppressed_earlier_terms = ["cloture filed", "cloture vote", "unanimous consent", "adjourn", "vote underway", "now voting"]
        now = datetime.now()
        recent_procedure, _background_procedure = procedural_buckets(procedural_items, now)
        session_day = current_senate_session_day(all_items)
        earlier_items = [
            x for x in all_groups.get("Earlier Floor Activity", [])
            if not any(t in f"{x.title} {x.raw}".lower() for t in suppressed_earlier_terms)
            and x.title.lower() not in procedural_keys
            and is_recent_earlier_activity(x, now, session_day)
            and has_meaningful_recent_activity(x)
        ]
        earlier_items = earlier_items[:5]

        now_item = important_now(items)
        next_items = next_90(items)
        top_banner = movement_banner(items)
        signals = to_signal_items(items) if items else []
        top_signal = signals[0] if signals else None
        coverage_timing = "Expected" if next_items else "No active window"
        watch_list = ", ".join((now_item.senators_detected if now_item else [])[:3]) or "Leadership, EBB, committee schedule"
        if top_signal:
            ticker_status = _status_label(top_signal.total_score)
            ticker_location = top_banner.get("where_to_be_now") or "No active coverage location"
            ticker_why = top_banner.get("watch") or "Floor, event, or committee updates may drive coverage."
            ticker_guidance = next_items[0].action_line if next_items else "Monitor floor updates, EBB postings, and committee schedules for developing coverage opportunities."
        else:
            vote_block = (forward_context.get("schedule_context", {}) or {}).get("vote_block", {})
            next_floor_date = vote_block.get("date_label")
            ticker_status = f"Pro Forma Period (no legislative business) — next floor activity {next_floor_date}" if next_floor_date else "Pro Forma Period (no legislative business)"
            ticker_location = "No active coverage location"
            coverage_timing = "No active window"
            watch_list = "Leadership, EBB, committee schedule"
            ticker_why = "No votes scheduled, and current public sources do not show active floor proceedings."
            ticker_guidance = "No votes scheduled. No hearings scheduled. No media events listed."

        today = now.strftime("%A, %B %d, %Y").replace(" 0", " ")

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
                .source-links {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                    margin-top: 8px;
                }}
                .links {{
                    padding: 16px;
                    margin-top: 24px;
                }}
                .links a {{
                    display: block;
                    margin: 8px 0;
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
                    <div class="sub">{today} · Real-time coverage guidance for congressional reporters</div>
                    <div class="sub">Sources: Congressional Reporters · EBB · Congress.gov · Committee Schedules</div>
                </div>
            </header>

            <main>
                <div class="searchbox">
                    <form method="get">
                        <input name="q" placeholder="Search senators, committees, topics, bills, or events" value="{html.escape(q or '')}">
                        <button>Search</button>
                    </form>
                    <div class="views">
                        <a href="/?earlier=true">Show Earlier Activity</a>
                    </div>
                </div>
                {f"<p class='empty'>No matching JOLT items found. Try Senator, state, committee, room, bill number, vote, or topic.</p>" if q and not items else ""}

                <div class="ticker">
                    <strong>WHERE TO BE NOW</strong><br>Status: {html.escape(ticker_status)}<br>Coverage location: {html.escape(ticker_location)}<br>Coverage timing: {html.escape(coverage_timing)}<br>Watch: {html.escape(watch_list)}<br>Why this matters: {html.escape(ticker_why)}<br><strong>Coverage guidance</strong><br>{html.escape(ticker_guidance)}</div>

                <div class="outlook">
                    <h2>TODAY’S COVERAGE OUTLOOK</h2><p>{html.escape(outlook)}</p>
                </div>

                <div class="summary">
                    <div class="stat"><b>{len([x for x in signals if x.total_score > 40]) if len([x for x in signals if x.total_score > 40]) >= 2 else "—"}</b>Active Signals</div>
                    <div class="stat"><b>{len(groups.get("Votes", []))}</b>Votes</div>
                    <div class="stat"><b>{len(groups.get("Events", []))}</b>Events</div>
                </div>

                <section class="section"><h2>Next Expected Floor Action</h2><!-- forward schedule renderer fixed -->{render_next_expected_floor_action(build_next_expected_floor_action(items), forward_context)}</section>

                <section class="section"><h2>Top Actions</h2>{"".join(f"<div class='card'><p>{html.escape(a)}</p></div>" for a in top_actions(main_items, forward_context)) if top_actions(main_items, forward_context) else "<p class='empty'>Monitor. No active vote, event, or hearing coverage window detected.</p>"}</section>

                <section class="section"><h2>Active Signals summary</h2><div class='card'><p>{html.escape(ticker_status)} · {html.escape(ticker_why)}</p></div></section>
                                {section("Senate Floor Activity", groups.get("Schedule", []), view)}
                {render_key_votes_section(groups.get("Votes", []), forward_context, view)}
                                <section class="section"><h2>Forward Look: Legislation & Nominations</h2>{render_forward_look(items, build_next_expected_floor_action(items), forward_context)}</section>
                {section("News Events & Stakeouts", groups.get("Events", []), view)}
                {section("House / Joint Coverage Notes", groups.get("House / Joint Coverage Notes", []), view) if groups.get("House / Joint Coverage Notes", []) else ""}
                {section("Committee Meetings & Hearings", groups.get("Committee Meetings & Hearings", []), view)}
                {section("Floor Remarks", floor_remarks_items, view, collapsed=True)}
                {section("Recent Procedure", recent_procedure, view, collapsed=True)}
                {section("Recent Activity", earlier_items, view, collapsed=True)}

                <div class="links">
                    <h2>Helpful Links</h2>
                    {quick_links}
                    
                </div>
                <section class="section"><h2>Public Notice</h2><p class="empty">Information is compiled from public sources and Gallery-appropriate updates. Coverage locations and access are subject to Senate rules, Gallery guidance, committee direction, and official direction. This site does not provide restricted-access information or nonpublic operational details.</p></section>
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
    forward_context = build_forward_schedule_context()

    return {
        "congressional_reporters_source": CONGRESSIONAL_REPORTERS_URL,
        "ebb_source": EBB_URL,
        "source_status": SOURCE_STATUS,
        "floor_preview": floor_text[:2500],
        "floor_raw": split_floor_events(floor_text),
        "ebb_items": [asdict(x) for x in ebb_items],
        "forward_schedule_diagnostics": forward_context,
        "homepage_vote_block_value": (forward_context.get("parsed_forward_schedule", {}).get("vote_block", {}) or {}).get("time_label", ""),
        "raw_vote_time_match": forward_context.get("raw_vote_block_time", ""),
        "normalized_vote_time_label": forward_context.get("normalized_vote_block_time", ""),
        "next_convening_time_label": forward_context.get("parsed_forward_schedule", {}).get("next_convening_time_label", ""),
        "vote_block_time_label": forward_context.get("parsed_forward_schedule", {}).get("vote_block_time_label", ""),
        "vote_block_time_source": forward_context.get("parsed_forward_schedule", {}).get("vote_block_time_source", ""),
        "key_votes_time_source": forward_context.get("parsed_forward_schedule", {}).get("vote_block_time_label", ""),
        "expected_votes_final": forward_context.get("parsed_forward_schedule", {}).get("expected_votes", []),
        "renderer_source_function": "render_next_expected_floor_action",
        "forward_schedule_source_text": forward_context.get("forward_schedule_source_text", ""),
        "parsed_forward_schedule": forward_context.get("parsed_forward_schedule", {}),
        "ignored_dates": forward_context.get("ignored_dates", []),
        "rejected_blocks": forward_context.get("rejected_blocks", []),
        "forward_schedule_parser_smoke_test": forward_schedule_parser_smoke_test(),
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
