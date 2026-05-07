from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# Procedure-to-logistics layer for newsroom awareness.
# This uses the legislative status-step index as its source of truth and does
# not forecast outcomes, whip counts, or political positioning.
@dataclass(frozen=True)
class StatusStep:
    code: str
    label: str
    chamber: str
    phase: str
    incoming: List[str]
    outgoing: List[str]
    notes: str


@dataclass(frozen=True)
class EventRule:
    code: str
    patterns: List[str]
    confidence: str
    significance: Optional[str] = None


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


_RULES: List[EventRule] = [
    EventRule("SIGNED_PRESIDENT", [r"\bsigned\b.*\bpresident\b", r"\bpresident\b.*\bsigned\b", r"\bbecame public law\b"], "high"),
    EventRule("VETO_OVERRIDE", [r"\boverr(?:ode|idden|ide)\b.*\bveto\b", r"\bveto\b.*\boverr"], "high"),
    EventRule("VETOED", [r"\bveto(?:ed| message)?\b", r"\bpresident\b.*\breturned\b.*\bobjections\b"], "high"),
    EventRule("PRESENTED_PRESIDENT", [r"\bpresented to the president\b", r"\bpresented\b.*\bpresident\b"], "high"),
    EventRule("ENROLLED_BILL", [r"\benrolled bill\b", r"\bmessage.*enrolled\b"], "high"),
    EventRule("CONFERENCE_REPORT_AGREED", [r"\bconference report\b.*\b(?:agreed to|adopted)\b", r"\b(?:agreed to|adopted)\b.*\bconference report\b"], "high"),
    EventRule("CONFERENCE_REPORT_FILED", [r"\bconference report\b.*\bfiled\b", r"\bfiled\b.*\bconference report\b"], "high"),
    EventRule("CONFEREES_APPOINTED", [r"\bconferees?\b.*\bappointed\b", r"\bappointed\b.*\bconferees?\b"], "high"),
    EventRule("CONFERENCE_REQUESTED", [r"\bconference\b.*\brequested\b", r"\brequest(?:ed)? a conference\b"], "high"),
    EventRule("PASSED_HOUSE", [r"\bpassed\b.*\bhouse\b", r"\bhouse\b.*\bpassed\b"], "medium"),
    EventRule("PASSED_SENATE", [r"\b(?:reached|agreed to|passed|approved|secured) final passage\b", r"\bpassed (?:the )?senate\b", r"\bsenate passed\b", r"\bpassed by voice vote\b"], "high"),
    EventRule("HOUSE_MESSAGE", [r"\bmessage from the house\b", r"\bhouse message\b", r"\breceived from the house\b"], "high"),
    EventRule("CLOTURE_INVOKED", [r"\binvoked cloture\b", r"\bcloture\b.*\binvoked\b"], "high"),
    EventRule("CLOTURE_REJECTED", [r"\bcloture\b.*\bnot invoked\b", r"\bfailed\b.*\bcloture\b", r"\brejected\b.*\bcloture\b"], "high"),
    EventRule("CLOTURE_FILED", [r"\bfiled cloture\b", r"\bcloture (?:was )?filed\b", r"\bmotion to invoke cloture\b.*\bfiled\b"], "high"),
    EventRule("REPORTED_COMMITTEE", [r"\breported (?:by|from) (?:the )?.*committee\b", r"\bcommittee\b.*\breported\b", r"\bordered reported\b"], "high"),
    EventRule("AMENDMENT_TREE_FILLED", [r"\bamendment tree\b.*\bfilled\b", r"\bfilled the tree\b"], "high"),
    EventRule("SUBSTITUTE_AMENDMENT", [r"\bsubstitute amendment\b", r"\bamendment in the nature of a substitute\b"], "high"),
    EventRule("AMENDMENT_PENDING", [r"\bamendment\b.*\bpending\b", r"\bpending amendment\b"], "medium"),
    EventRule("VOTE_SCHEDULED", [r"\bwill vote\b", r"\bvote scheduled\b", r"\broll call vote(?:s)?\b.*\bat\b"], "medium"),
    EventRule("MOTION_TO_PROCEED", [r"\bmotion to proceed\b.*\bagreed to\b", r"\bagreed to\b.*\bmotion to proceed\b"], "high", "major"),
    EventRule("MOTION_TO_PROCEED", [r"\bmotion to proceed\b", r"\bproceed to (?:the )?consideration\b"], "high"),
    EventRule("PLACED_CALENDAR", [r"\bplaced on (?:the )?calendar\b", r"\bcalendar no\."], "high"),
    EventRule("DISCHARGED", [r"\bdischarged from\b", r"\bmotion to discharge\b", r"\bcommittee discharged\b"], "high"),
    EventRule("COMMITTEE_MARKUP", [r"\bmarkup\b", r"\bexecutive session\b", r"\bbusiness meeting\b"], "high"),
    EventRule("COMMITTEE_HEARING", [r"\bhearing\b", r"\bcommittee meets?\b.*\btestimony\b"], "high"),
    EventRule("REFERRED_COMMITTEE", [r"\breferred to (?:the )?.*committee\b", r"\breferral to (?:the )?.*committee\b"], "high"),
    EventRule("BILL_INTRODUCED", [r"\bintroduced\b", r"\bintroduced (?:a|the) bill\b"], "medium"),
    EventRule("QUORUM_CALL", [r"\bquorum call\b"], "high"),
    EventRule("RECESS", [r"\brecess(?:ed)?\b", r"\bstand(?:s)? in recess\b"], "high"),
]

# Logistics significance is tied to movement through the status map, not
# politics or the probability that a measure will pass.
_MAJOR = {
    "CLOTURE_FILED",
    "CLOTURE_INVOKED",
    "CLOTURE_REJECTED",
    "PASSED_SENATE",
    "PASSED_HOUSE",
    "CONFERENCE_REPORT_AGREED",
    "SIGNED_PRESIDENT",
    "VETOED",
    "VETO_OVERRIDE",
}
_NOTABLE = {
    "MOTION_TO_PROCEED",
    "AMENDMENT_TREE_FILLED",
    "CONFERENCE_REQUESTED",
    "CONFEREES_APPOINTED",
    "CONFERENCE_REPORT_FILED",
    "HOUSE_MESSAGE",
    "REPORTED_COMMITTEE",
    "DISCHARGED",
    "PRESENTED_PRESIDENT",
    "SUBSTITUTE_AMENDMENT",
}
_NOISE = {"COMMITTEE_HEARING", "BILL_INTRODUCED", "QUORUM_CALL", "RECESS"}


def classify_event_text(text: str) -> Optional[Dict[str, Any]]:
    value = " ".join((text or "").split()).lower()
    if not value:
        return None

    matches: List[EventRule] = []
    seen_codes = set()
    for rule in _RULES:
        if any(re.search(pattern, value, flags=re.I) for pattern in rule.patterns):
            matches.append(rule)
            seen_codes.add(rule.code)

    if not matches:
        return None

    chosen = matches[0]
    ambiguous_codes = [code for code in seen_codes if code != chosen.code]
    # Cloture is often filed on a motion to proceed; that phrase supplies
    # procedural context and should not be treated as a competing status.
    if chosen.code == "CLOTURE_FILED":
        ambiguous_codes = [code for code in ambiguous_codes if code != "MOTION_TO_PROCEED"]
    confidence = chosen.confidence
    if ambiguous_codes and confidence == "high":
        confidence = "medium"
    elif ambiguous_codes:
        confidence = "low"

    return interpret_status(
        chosen.code,
        source_text=text,
        confidence=confidence,
        significance_override=chosen.significance,
        ambiguous_codes=ambiguous_codes,
    )


def _significance(code: str) -> str:
    if code in _MAJOR:
        return "major"
    if code in _NOTABLE:
        return "notable"
    return "routine"


def _reporter_note(step: StatusStep, next_steps: List[str], ambiguous: bool, ambiguous_labels: List[str]) -> str:
    suffix = ""
    if ambiguous_labels:
        suffix += f" Procedure wording overlaps with {', '.join(ambiguous_labels)}; confirm against the official action."
    if ambiguous:
        suffix += " The transition map is incomplete, so confirm the next official action."
    return f"Logistics read: {step.label.lower()} in the {step.phase.lower()} phase. Watch timing for: {', '.join(next_steps[:3])}.{suffix}"


def _producer_note(step: StatusStep, significance: str) -> str:
    if significance == "major":
        return f"Flag for staffing/timing review: {step.label} can materially change floor posture or timing."
    if significance == "notable":
        return f"Add to the coverage watch list: {step.label} may set up the next floor coverage window or inter-chamber move."
    return f"Log only if it affects press positioning, a named senator, a vote, or leadership availability: {step.label}."


def interpret_status(
    code: str,
    *,
    source_text: str = "",
    confidence: str = "medium",
    significance_override: Optional[str] = None,
    ambiguous_codes: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    step = get_status_step(code)
    if not step:
        return None
    next_steps = likely_next_steps(step)
    transition_ambiguous = any("unmapped" in value.lower() or "no outgoing transition" in value.lower() for value in next_steps)
    ambiguous_labels = [status_index()[value].label for value in (ambiguous_codes or []) if value in status_index()]
    significance = significance_override or _significance(step.code)
    return {
        "status_code": step.code,
        "status_label": step.label,
        "label": step.label,
        "chamber": step.chamber,
        "phase": step.phase,
        "meaning": step.notes or f"Status index maps this event to {step.label}.",
        "significance": significance,
        "noise_or_movement": "noise" if step.code in _NOISE else "movement",
        "likely_next_steps": next_steps,
        "reporter_note": _reporter_note(step, next_steps, transition_ambiguous, ambiguous_labels),
        "producer_note": _producer_note(step, significance),
        "confidence": "low" if transition_ambiguous and confidence == "medium" else confidence,
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
