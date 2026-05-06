import re

TIME_PATTERN = re.compile(r'^\d{1,2}:\d{2}\s*(a\.m\.|p\.m\.)', re.IGNORECASE)

def is_time_line(line):
    return bool(TIME_PATTERN.match(line.strip()))

def classify_event(line):
    l = line.lower()

    if "did not agree" in l:
        return "failed_vote"
    if "invoked cloture" in l:
        return "cloture_passed"
    if "motion to invoke cloture" in l:
        return "cloture_vote"
    if "now voting" in l:
        return "vote_in_progress"
    if "vote of" in l or "by a vote" in l or "roll call vote" in l:
        return "vote_result"
    if "discharge" in l:
        return "discharge_vote"
    if "unanimous consent" in l:
        return "unanimous_consent"

    return "other"

def clean_line(line):
    return " ".join(line.split())

def parse_events(text):
    lines = text.splitlines()

    timeline = []
    future = []

    for raw in lines:
        line = clean_line(raw)

        if len(line) < 20:
            continue

        if is_time_line(line):
            event_type = classify_event(line)

            if "spoke on" in line.lower():
                continue

            timeline.append({
                "time": line.split(" ", 1)[0],
                "type": event_type,
                "text": line
            })

        elif "the senate will" in line.lower() or line.lower().startswith("at "):
            if (
                "will vote" in line.lower()
                or "roll call" in line.lower()
                or "cloture" in line.lower()
                or "will convene" in line.lower()
            ):
                future.append(line)

    return {
        "timeline": timeline[:10],
        "future": future
    }
