from app.procedure_engine import classify_event_text, get_status_step, likely_next_steps


def test_status_lookup_by_code():
    step = get_status_step("CLOTURE_FILED")

    assert step is not None
    assert step.label == "Cloture filed"
    assert step.chamber == "Senate"
    assert "CLOTURE_INVOKED" in step.outgoing


def test_classifies_cloture_filed():
    result = classify_event_text("Sen. Thune filed cloture on the motion to proceed to H.R. 1.")

    assert result["status_code"] == "CLOTURE_FILED"
    assert result["significance"] == "notable"
    assert result["confidence"] == "high"


def test_classifies_motion_to_proceed():
    result = classify_event_text("The Senate resumed consideration of the motion to proceed to S. 123.")

    assert result["status_code"] == "MOTION_TO_PROCEED"
    assert "Amendment pending" in result["likely_next_steps"]


def test_classifies_committee_hearing():
    result = classify_event_text("The Judiciary Committee hearing will receive testimony on the bill.")

    assert result["status_code"] == "COMMITTEE_HEARING"
    assert result["noise_or_movement"] == "noise"


def test_classifies_reported_bill():
    result = classify_event_text("S. 456 was reported by committee with an amendment in the nature of a substitute.")

    assert result["status_code"] == "REPORTED_COMMITTEE"


def test_classifies_house_message():
    result = classify_event_text("Message from the House received on H.R. 22.")

    assert result["status_code"] == "HOUSE_MESSAGE"


def test_classifies_conference_report():
    result = classify_event_text("The conference report was filed for H.R. 99.")

    assert result["status_code"] == "CONFERENCE_REPORT_FILED"
    assert "Conference report agreed to" in result["likely_next_steps"]


def test_classifies_veto():
    result = classify_event_text("The President vetoed the bill and returned it with objections.")

    assert result["status_code"] == "VETOED"
    assert result["significance"] == "major"


def test_classifies_signed_by_president():
    result = classify_event_text("The President signed the enrolled bill into law.")

    assert result["status_code"] == "SIGNED_PRESIDENT"
    assert result["likely_next_steps"] == ["No outgoing transition is mapped in the status index; confirm the next procedural step from official action."]


def test_likely_next_steps_resolve_outgoing_branches():
    step = get_status_step("CLOTURE_FILED")

    assert step is not None
    assert likely_next_steps(step) == ["Cloture invoked", "Cloture rejected", "Vote scheduled"]
