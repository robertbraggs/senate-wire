from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# This module turns the legislative status-step map into a lightweight
# procedural state machine for reporter/producer interpretation of parsed events.
@dataclass(frozen=True)
class StatusStep:
    code: str
    label: str
    chamber: str
    phase: str
    incoming: List[str]
    outgoing: List[str]
    notes: str


def _split_codes(value: str) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[|;,]", value) if part.strip()]


def _row_value(row: Dict[str, str], *names: str) -> str:
    normalized = {}
    for k, v in row.items():
        if k is None:
            continue
        if isinstance(v, list):
            value = ", ".join(str(part) for part in v if part is not None)
        else:
            value = v or ""
        normalized[str(k).strip().lower().replace(" ", "_")] = str(value).strip()
    for name in names:
        key = name.strip().lower().replace(" ", "_")
        if normalized.get(key):
            return normalized[key]
    return ""


def default_status_index_path() -> Path:
    candidates = [
        Path("/mnt/data/legislative_status_index.csv"),
        Path(__file__).resolve().parent.parent / "data" / "legislative_status_index.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def load_status_index(path: Optional[Path] = None) -> Dict[str, StatusStep]:
    csv_path = path or default_status_index_path()
    steps: Dict[str, StatusStep] = {}
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = _row_value(row, "code", "status_code", "status")
            if not code:
                continue
            step = StatusStep(
                code=code,
                label=_row_value(row, "label", "status_label", "name"),
                chamber=_row_value(row, "chamber"),
                phase=_row_value(row, "phase", "stage"),
                incoming=_split_codes(_row_value(row, "incoming", "incoming_branches", "incoming_branch")),
                outgoing=_split_codes(_row_value(row, "outgoing", "outgoing_branches", "outgoing_branch")),
                notes=_row_value(row, "notes", "note", "meaning"),
            )
            steps[step.code] = step
    return steps


@lru_cache(maxsize=1)
def status_index() -> Dict[str, StatusStep]:
    return load_status_index()


def get_status_step(code: str) -> Optional[StatusStep]:
    return status_index().get(code)


def likely_next_steps(step: StatusStep, index: Optional[Dict[str, StatusStep]] = None) -> List[str]:
    steps = index or status_index()
    resolved: List[str] = []
    for code in step.outgoing:
        target = steps.get(code)
        resolved.append(target.label if target else f"{code} (unmapped in status index)")
    if not resolved:
        resolved.append("No outgoing transition is mapped in the status index; confirm the next procedural step from official action.")
    return resolved


_RULES: List[tuple[str, List[str], str]] = [
    ("SIGNED_PRESIDENT", [r"\bsigned\b.*\bpresident\b", r"\bpresident\b.*\bsigned\b", r"\bbecame public law\b"], "high"),
    ("VETO_OVERRIDE", [r"\boverr(?:ode|idden|ide)\b.*\bveto\b", r"\bveto\b.*\boverr"], "high"),
    ("VETOED", [r"\bveto(?:ed| message)?\b", r"\bpresident\b.*\breturned\b.*\bobjections\b"], "high"),
    ("PRESENTED_PRESIDENT", [r"\bpresented to the president\b", r"\bpresented\b.*\bpresident\b"], "high"),
    ("ENROLLED_BILL", [r"\benrolled bill\b", r"\bmessage.*enrolled\b"], "high"),
    ("CONFERENCE_REPORT_AGREED", [r"\bconference report\b.*\bagreed to\b", r"\bagreed to\b.*\bconference report\b"], "high"),
    ("CONFERENCE_REPORT_FILED", [r"\bconference report\b.*\bfiled\b", r"\bfiled\b.*\bconference report\b"], "high"),
    ("CONFEREES_APPOINTED", [r"\bconferees?\b.*\bappointed\b", r"\bappointed\b.*\bconferees?\b"], "high"),
    ("CONFERENCE_REQUESTED", [r"\bconference\b.*\brequested\b", r"\brequest(?:ed)? a conference\b"], "high"),
    ("PASSED_HOUSE", [r"\bpassed\b.*\bhouse\b", r"\bhouse\b.*\bpassed\b"], "medium"),
    ("PASSED_SENATE", [r"\bpassed (?:the )?senate\b", r"\bsenate passed\b", r"\bpassed by voice vote\b"], "high"),
    ("HOUSE_MESSAGE", [r"\bmessage from the house\b", r"\bhouse message\b", r"\breceived from the house\b"], "high"),
    ("CLOTURE_INVOKED", [r"\binvoked cloture\b", r"\bcloture\b.*\binvoked\b"], "high"),
    ("CLOTURE_REJECTED", [r"\bcloture\b.*\bnot invoked\b", r"\bfailed\b.*\bcloture\b", r"\brejected\b.*\bcloture\b"], "high"),
    ("CLOTURE_FILED", [r"\bfiled cloture\b", r"\bcloture (?:was )?filed\b", r"\bmotion to invoke cloture\b.*\bfiled\b"], "high"),
    ("REPORTED_COMMITTEE", [r"\breported (?:by|from) committee\b", r"\bcommittee\b.*\breported\b", r"\bordered reported\b"], "high"),
    ("AMENDMENT_TREE_FILLED", [r"\bamendment tree\b.*\bfilled\b", r"\bfilled the tree\b"], "high"),
    ("SUBSTITUTE_AMENDMENT", [r"\bsubstitute amendment\b", r"\bamendment in the nature of a substitute\b"], "high"),
    ("AMENDMENT_PENDING", [r"\bamendment\b.*\bpending\b", r"\bpending amendment\b"], "medium"),
    ("VOTE_SCHEDULED", [r"\bwill vote\b", r"\bvote scheduled\b", r"\broll call vote(?:s)?\b.*\bat\b"], "medium"),
    ("MOTION_TO_PROCEED", [r"\bmotion to proceed\b", r"\bproceed to (?:the )?consideration\b"], "high"),
    ("PLACED_CALENDAR", [r"\bplaced on (?:the )?calendar\b", r"\bcalendar no\."], "high"),
    ("DISCHARGED", [r"\bdischarged from\b", r"\bmotion to discharge\b", r"\bcommittee discharged\b"], "high"),
    ("COMMITTEE_MARKUP", [r"\bmarkup\b", r"\bexecutive session\b", r"\bbusiness meeting\b"], "high"),
    ("COMMITTEE_HEARING", [r"\bhearing\b", r"\bcommittee meets?\b.*\btestimony\b"], "high"),
    ("REFERRED_COMMITTEE", [r"\breferred to (?:the )?.*committee\b", r"\breferral to (?:the )?.*committee\b"], "high"),
    ("BILL_INTRODUCED", [r"\bintroduced\b", r"\bintroduced (?:a|the) bill\b"], "medium"),
]

_MAJOR = {"CLOTURE_INVOKED", "CLOTURE_REJECTED", "PASSED_SENATE", "PASSED_HOUSE", "CONFERENCE_REPORT_AGREED", "SIGNED_PRESIDENT", "VETOED", "VETO_OVERRIDE"}
_NOTABLE = {"CLOTURE_FILED", "MOTION_TO_PROCEED", "AMENDMENT_TREE_FILLED", "CONFERENCE_REQUESTED", "CONFEREES_APPOINTED", "CONFERENCE_REPORT_FILED", "HOUSE_MESSAGE", "REPORTED_COMMITTEE", "DISCHARGED", "PRESENTED_PRESIDENT"}
_NOISE = {"COMMITTEE_HEARING", "BILL_INTRODUCED"}


def classify_event_text(text: str) -> Optional[Dict[str, Any]]:
    value = " ".join((text or "").split()).lower()
    if not value:
        return None
    for code, patterns, confidence in _RULES:
        if any(re.search(pattern, value, flags=re.I) for pattern in patterns):
            return interpret_status(code, source_text=text, confidence=confidence)
    return None


def _significance(code: str) -> str:
    if code in _MAJOR:
        return "major"
    if code in _NOTABLE:
        return "notable"
    return "routine"


def _reporter_note(step: StatusStep, next_steps: List[str], ambiguous: bool) -> str:
    suffix = " The transition map is incomplete, so confirm the next official action." if ambiguous else ""
    return f"Treat as {step.label.lower()} in the {step.phase.lower()} phase. Watch for: {', '.join(next_steps[:3])}.{suffix}"


def _producer_note(step: StatusStep, significance: str) -> str:
    if significance == "major":
        return f"Flag for possible live/update treatment: {step.label} can change the legislative outcome or timing."
    if significance == "notable":
        return f"Add to the coverage watch list: {step.label} may set up the next floor or inter-chamber move."
    return f"Log for context unless tied to a named senator, vote, or leadership announcement: {step.label}."


def interpret_status(code: str, *, source_text: str = "", confidence: str = "medium") -> Optional[Dict[str, Any]]:
    step = get_status_step(code)
    if not step:
        return None
    next_steps = likely_next_steps(step)
    ambiguous = any("unmapped" in value.lower() or "no outgoing transition" in value.lower() for value in next_steps)
    significance = _significance(step.code)
    return {
        "status_code": step.code,
        "label": step.label,
        "chamber": step.chamber,
        "phase": step.phase,
        "meaning": step.notes or f"Status index maps this event to {step.label}.",
        "significance": significance,
        "noise_or_movement": "noise" if step.code in _NOISE else "movement",
        "likely_next_steps": next_steps,
        "reporter_note": _reporter_note(step, next_steps, ambiguous),
        "producer_note": _producer_note(step, significance),
        "confidence": "low" if ambiguous and confidence == "medium" else confidence,
    }


def classify_events(texts: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for text in texts:
        interpretation = classify_event_text(text)
        if not interpretation:
            continue
        key = interpretation["status_code"]
        if key in seen:
            continue
        seen.add(key)
        out.append(interpretation)
    return out
