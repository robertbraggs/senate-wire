from dataclasses import dataclass, asdict
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict
import re
import html
import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse


APP_NAME = "The Senate JOLT"
CONGRESSIONAL_REPORTERS_URL = "https://www.dailypress.senate.gov/"
EBB_URL = "https://ebbs.senate.gov/"
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

app = FastAPI(title=APP_NAME, version="7.1.0")


QUICK_LINKS = [
    ("Floor Live", "https://www.senate.gov/legislative/floor_activity_pail.htm"),
    ("Roll Calls", "https://www.senate.gov/legislative/votes_new.htm"),
    ("EBB", EBB_URL),
    ("Committee Schedule", "https://www.senate.gov/committees/hearings_meetings.htm"),
    ("Executive Calendar", "https://www.senate.gov/legislative/executive_calendar.htm"),
    ("Congressional Record", "https://www.congress.gov/congressional-record"),
    ("Press Contacts", "https://www.senate.gov/general/contact_information/senators_cfm.cfm"),
    ("Coverage Rules", "https://www.radiotv.senate.gov/about-us/"),
]


MANUAL_GALLERY_NOTES = [
    # Add manually curated notes here when needed.
    # Example:
    # "Cameras should stage near the Ohio Clock ahead of the first vote window.",
]


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
    url: Optional[str]


SOURCE_STATUS = {
    "congressional_reporters": "not loaded",
    "ebb": "not loaded",
    "x": "disabled: missing X_BEARER_TOKEN",
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
        r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.m\.|p\.m\.|AM|PM|am|pm)\b",
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
        r"\bSenate Daily Press Gallery\b",
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
        return "Senate Daily Press Gallery"
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


def parse_floor_item(raw: str, fallback_date: Optional[date]) -> JoltItem:
    d = parse_date(raw) or fallback_date
    t = parse_time(raw)
    c = classify_floor(raw)

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
        measure=extract_measure(raw),
        takeaway=c["takeaway"],
        where_to_be=c["where_to_be"],
        movement_cue=c["movement_cue"],
        who_to_watch=c["who_to_watch"],
        coverage_note=c["coverage_note"],
        staff_note=c["staff_note"],
        gallery_note=c["gallery_note"],
        url=CONGRESSIONAL_REPORTERS_URL,
    )

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

    return "Senate Event"


def infer_ebb_committee(text: str) -> Optional[str]:
    committees = [
        "Appropriations", "Armed Services", "Banking", "Budget", "Commerce",
        "Energy and Natural Resources", "Environment and Public Works",
        "Finance", "Foreign Relations", "Health, Education, Labor, and Pensions",
        "HELP", "Homeland Security", "Judiciary", "Rules", "Small Business",
        "Veterans' Affairs", "Agriculture", "Intelligence", "Aging",
    ]

    for committee in committees:
        if re.search(re.escape(committee), text, flags=re.I):
            return committee

    m = re.search(r"Committee on ([A-Za-z ,&'-]+)", text, flags=re.I)
    if m:
        return "Committee on " + clean(m.group(1))[:80]

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
        r"(?=(?:Stakeout|Press Conference|Media Availability|Briefing|Hearing|Business Meeting|Markup|Photo Spray|Camera Spray)\b)",
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
    title = infer_ebb_title(raw)
    location = infer_location(raw)
    building = infer_building(location)
    committee = infer_ebb_committee(raw)
    lower = raw.lower()

    if location:
        confidence = "high"
        quality = "structured time/location parsed" if parse_time(raw) else "structured location parsed"
    elif parse_time(raw):
        confidence = "medium"
        quality = "time parsed; location missing"
    else:
        confidence = "low"
        quality = "weak parse"

    urgency = "scheduled"

    if any(x in lower for x in ["stakeout", "press conference", "media availability", "camera spray", "photo spray"]):
        urgency = "move now" if parse_time(raw) else "watch"

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
        "quality": quality,
        "location": location or "Location not parsed",
        "building": building,
        "takeaway": "Media logistics or event item from EBB.",
        "where_to_be": where,
        "movement_cue": movement,
        "who_to_watch": watch,
        "coverage_note": "Use event time and location to stage cameras, crews, or reporters before arrivals/exits.",
        "staff_note": "Useful for anticipating press presence, member movement, and committee/event traffic.",
        "gallery_note": "Confirm room, camera setup, credential access, pool needs, and whether gallery support is needed.",
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
                url=EBB_URL,
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
            url=EBB_URL,
        )

        items.append(apply_past_status(item))

    return dedupe_items(items)[:30]


def fetch_x_items() -> List[JoltItem]:
    if not X_BEARER_TOKEN:
        SOURCE_STATUS["x"] = "disabled: missing X_BEARER_TOKEN"
        return []

    SOURCE_STATUS["x"] = "disabled for now"
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
    items = get_floor_items() + fetch_ebb_items() + fetch_x_items()
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
    ]


def grouped(items: List[JoltItem]) -> Dict[str, List[JoltItem]]:
    g = {
        "Coverage Timeline": [],
        "Schedule": [],
        "Votes": [],
        "Floor Action": [],
        "Events": [],
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
        "where_to_be_now": "No immediate floor or EBB trigger",
        "movement": "Monitor",
        "watch": "Monitor feeds for next vote or EBB timing signal.",
    }

def coverage_outlook(items: List[JoltItem], groups: Dict[str, List[JoltItem]]) -> str:
    if groups.get("Votes"):
        return "Floor activity detected. Best access windows are likely around votes, chamber exits, and leadership routes."

    if groups.get("Events"):
        return "No active vote window detected. Best opportunities may be EBB events, hearings, press availabilities, or committee hallway movement."

    if groups.get("Schedule"):
        return "Schedule items detected. Use convening times and leader remarks to plan first movement window."

    return "No current floor movement detected. Check EBB, committee schedule, or the Congressional Reporters feed for the next coverage window."


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

    note = item.coverage_note
    if view == "staff":
        note = item.staff_note
    elif view == "gallery":
        note = item.gallery_note

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
            <div><strong>Where:</strong> {html.escape(place)}</div>
            {building}
            <div><strong>Movement:</strong> {html.escape(item.movement_cue)}</div>
            <div><strong>Watch:</strong> {html.escape(item.who_to_watch)}</div>
            <div><strong>Note:</strong> {html.escape(note)}</div>
            <div><strong>Quality:</strong> {html.escape(item.quality)}</div>
        </div>
        <a class="source" href="{html.escape(item.url or '#')}" target="_blank">Open source</a>
    </article>
    """


def section(title: str, items: List[JoltItem], view: str, collapsed: bool = False) -> str:
    if collapsed:
        cards = "".join(item_card(item, view) for item in items[:20])

        return f"""
        <section class="section">
            <details>
                <summary><h2>{html.escape(title)} ({len(items)})</h2></summary>
                {cards if cards else '<p class="empty">No items detected.</p>'}
            </details>
        </section>
        """

    cards = "".join(item_card(item, view) for item in items)

    return f"""
    <section class="section">
        <h2>{html.escape(title)}</h2>
        {cards if cards else '<p class="empty">No items detected.</p>'}
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


@app.get("/", response_class=HTMLResponse)
def dashboard(
    q: Optional[str] = Query(None),
    view: str = Query("reporter", pattern="^(reporter|staff|gallery)$"),
    earlier: bool = Query(False),
):
    try:
        all_items = get_all_items()
        items = filter_items(all_items, q, view, show_earlier=earlier)

        groups = grouped(items)
        all_groups = grouped(all_items)

        now_item = important_now(items)
        next_items = next_90(items)
        top_banner = movement_banner(items)

        today = datetime.now().strftime("%A, %B %d, %Y").replace(" 0", " ")

        quick_links = "".join(
            f"<a href='{html.escape(url)}' target='_blank'>{html.escape(name)}</a>"
            for name, url in QUICK_LINKS
        )

        status_bar = (
            f"<strong>Congressional Reporters:</strong> {html.escape(friendly_status('congressional_reporters'))} &nbsp; "
            f"<strong>EBB:</strong> {html.escape(friendly_status('ebb'))} &nbsp; "
            f"<strong>X:</strong> {html.escape(friendly_status('x'))}"
        )

        outlook = coverage_outlook(items, groups)

        page = f"""
        <!doctype html>
        <html>
        <head>
            <title>{APP_NAME}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
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
                    <strong>Where to be now:</strong> {html.escape(top_banner["where_to_be_now"])}
                    <br>
                    <strong>Movement:</strong> {html.escape(top_banner["movement"])}
                    <br>
                    <strong>Watch:</strong> {html.escape(top_banner["watch"])}
                </div>

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

                <div class="topgrid">
                    <div class="panel">
                        <h2>Now / Best Coverage Cue</h2>
                        {item_card(now_item, view) if now_item else '<p class="empty">No active cue detected. Check EBB, committee schedule, or Congressional Reporters feed.</p>'}
                    </div>
                    <div class="panel">
                        <h2>Next 90 Minutes</h2>
                        {''.join(item_card(x, view) for x in next_items) if next_items else '<p class="empty">No timed items in the next 90 minutes.</p>'}
                    </div>
                </div>

                {gallery_notes_section()}
                {section("Coverage Timeline", groups.get("Coverage Timeline", []), view)}
                {section("Votes", groups.get("Votes", []), view)}
                {section("Floor Action", groups.get("Floor Action", []), view)}
                {section("Events / EBB", groups.get("Events", []), view)}
                {section("Schedule", groups.get("Schedule", []), view)}
                {section("Remarks", all_groups.get("Remarks", []), view, collapsed=True)}
                {section("Notes", all_groups.get("Notes", []), view, collapsed=True)}
                {section("Earlier Floor Activity", all_groups.get("Earlier Floor Activity", []), view, collapsed=True)}

                <div class="links">
                    <h2>Quick Links</h2>
                    {quick_links}
                    <p>
                        JSON:
                        <a href="/events">/events</a>
                        <a href="/summary">/summary</a>
                        <a href="/debug/raw">/debug/raw</a>
                    </p>
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
