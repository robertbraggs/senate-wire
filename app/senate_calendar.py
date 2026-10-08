"""Senate Calendar of Business (govinfo.gov) integration.

The Calendar of Business is the authoritative daily source for the Senate's
orders: unanimous consent agreements, scheduled votes, and motions. It is
published as a PDF per session day at:

    https://www.govinfo.gov/content/pkg/CCAL-119scal-YYYY-MM-DD/pdf/CCAL-119scal-YYYY-MM-DD.pdf

This module resolves the latest available calendar, extracts its text, and
parses the UNANIMOUS CONSENT AGREEMENTS section into structured orders with
real dates -- so a vote scheduled for November 9 is never reported as "today".
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

CALENDAR_BASE = "https://www.govinfo.gov/content/pkg"
DEFAULT_CONGRESS = 119

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MEASURE_RE = re.compile(
    r"^(H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.|H\.Con\.Res\.|S\.Con\.Res\.|H\.Res\.|S\.Res\.)\s*(\d+)\s*\(ORDER NO\.\s*(\d+)\)",
    re.MULTILINE,
)
_SEQ_RE = re.compile(r"^(\d+)\.\u2014Ordered,\s*", re.MULTILINE)
# "on Monday, November 9, 2026" -- the operative date of the order
_OPERATIVE_DATE_RE = re.compile(
    r"\b(?:on\s+)?(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s+(\d{4})"
)
# Trailing "(Sept. 30, 2026.)" -- when the agreement was reached, not the vote date
_AGREEMENT_DATE_RE = re.compile(
    r"\(([A-Za-z]+)\.?\s+(\d{1,2}),\s+(\d{4})\.?\)\s*$"
)
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.))", re.IGNORECASE)
_VOTE_ACTION_RES = [
    (re.compile(r"cloture motion[^.]*ripen", re.I), "cloture vote"),
    (re.compile(r"invoke cloture", re.I), "cloture vote"),
    (re.compile(r"motion to proceed", re.I), "motion to proceed"),
    (re.compile(r"resume consideration", re.I), "resume consideration"),
    (re.compile(r"\bvote\b", re.I), "vote"),
]


def calendar_url_for(congress: int, day: date) -> str:
    ds = day.strftime("%Y-%m-%d")
    pkg = f"CCAL-{congress}scal-{ds}"
    return f"{CALENDAR_BASE}/{pkg}/pdf/{pkg}.pdf"


def latest_calendar_url(
    congress: int = DEFAULT_CONGRESS,
    today: Optional[date] = None,
    lookback_days: int = 14,
    head_fn=None,
) -> Optional[Tuple[str, str]]:
    """Walk back from today to find the latest published calendar.

    Returns (url, YYYY-MM-DD) for the first date with an available PDF,
    or None. head_fn(url) -> bool lets tests stub the network.
    """
    today = today or date.today()
    check = head_fn or _default_head
    for offset in range(lookback_days + 1):
        day = today - timedelta(days=offset)
        url = calendar_url_for(congress, day)
        try:
            if check(url):
                return url, day.strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _default_head(url: str) -> bool:
    import urllib.request
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0 TheSenateJOLT/8.2"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from calendar PDF bytes. Raises on failure."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_uc_section(full_text: str) -> str:
    """Return just the UNANIMOUS CONSENT AGREEMENTS section."""
    # The phrase also appears in the table of contents ("... ON P. 2");
    # the real section is the occurrence directly followed by measure headers.
    best = -1
    idx = full_text.find("UNANIMOUS CONSENT AGREEMENTS")
    while idx >= 0:
        following = full_text[idx:idx + 1200]
        m = _MEASURE_RE.search(following)
        if m:
            best = idx + m.start()
            break
        idx = full_text.find("UNANIMOUS CONSENT AGREEMENTS", idx + 1)
    if best < 0:
        return ""
    section = full_text[best:]
    # Section ends at the next form-feed (page break into the session calendar grid)
    ff = section.find("\x0c")
    if ff > 0:
        section = section[:ff]
    return section.strip()


def _parse_date_string(month_name: str, day: str, year: str) -> Optional[date]:
    month = MONTHS.get(month_name.lower().rstrip("."))
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_uc_agreements(section_text: str) -> List[Dict]:
    """Parse UC agreements into structured orders.

    Each: {measure, measure_no, order_no, seq, text, agreement_date,
            operative_dates, time_labels, action}
    """
    agreements: List[Dict] = []
    if not section_text:
        return agreements
    # Split on measure headers; keep the header with each chunk
    parts = _MEASURE_RE.split(section_text)
    # parts[0] is preamble; then groups of (prefix, number, order_no, body)
    for i in range(1, len(parts), 4):
        if i + 3 >= len(parts):
            break
        prefix, number, order_no, body = parts[i], parts[i + 1], parts[i + 2], parts[i + 3]
        body = body.strip()
        seq_m = _SEQ_RE.match(body)
        seq = int(seq_m.group(1)) if seq_m else None
        text = _SEQ_RE.sub("", body, count=1).strip()
        text = re.sub(r"\s+", " ", text)
        # Trailing parenthetical = when the agreement was reached
        agreement_date = None
        am = _AGREEMENT_DATE_RE.search(text)
        if am:
            agreement_date = _parse_date_string(am.group(1), am.group(2), am.group(3))
        operative_dates = []
        for dm in _OPERATIVE_DATE_RE.finditer(text):
            d = _parse_date_string(dm.group(2), dm.group(3), dm.group(4))
            if d:
                operative_dates.append({"label": dm.group(0), "date": d})
        time_labels = [m.group(1) for m in _TIME_RE.finditer(text)]
        action = ""
        for rx, label in _VOTE_ACTION_RES:
            if rx.search(text):
                action = label
                break
        agreements.append({
            "measure": f"{prefix.strip()} {number}",
            "order_no": order_no,
            "seq": seq,
            "text": text,
            "agreement_date": agreement_date.isoformat() if agreement_date else "",
            "operative_dates": [{"label": o["label"], "date": o["date"].isoformat()} for o in operative_dates],
            "time_labels": time_labels,
            "action": action,
        })
    return agreements


def dated_vote_events(agreements: List[Dict], today: Optional[date] = None) -> List[Dict]:
    """Extract dated vote events from UC agreements.

    Only agreements with an operative future-or-today date AND a vote-like
    action produce events. The event carries the TRUE date -- never "today"
    by default.
    """
    today = today or date.today()
    events = []
    for a in agreements:
        if not a["action"]:
            continue
        for od in a["operative_dates"]:
            event_date = date.fromisoformat(od["date"])
            if event_date < today:
                continue
            events.append({
                "measure": a["measure"],
                "order_no": a["order_no"],
                "action": a["action"],
                "event_date": od["date"],
                "event_weekday": event_date.strftime("%A"),
                "time_label": a["time_labels"][0] if a["time_labels"] else "",
                "is_today": event_date == today,
                "summary": f"{a['measure']}: {a['action']}" + (
                    f" at {a['time_labels'][0]}" if a["time_labels"] else ""),
            })
    events.sort(key=lambda e: (e["event_date"], e["time_label"]))
    # Dedupe by measure+date
    seen = set()
    unique = []
    for e in events:
        key = (e["measure"], e["event_date"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def summarize_for_dashboard(events: List[Dict], agreements: List[Dict], max_orders: int = 8) -> Dict:
    """Build the dashboard payload: next vote + day's orders."""
    next_vote = events[0] if events else None
    orders = []
    for a in agreements[:max_orders]:
        od = a["operative_dates"][0] if a["operative_dates"] else None
        orders.append({
            "measure": a["measure"],
            "order_no": a["order_no"],
            "action": a["action"] or "order",
            "when": (od["label"] if od else "") + (
                f" at {a['time_labels'][0]}" if a["time_labels"] else ""),
            "text": a["text"][:280],
        })
    return {"next_vote": next_vote, "orders": orders, "order_count": len(agreements)}
