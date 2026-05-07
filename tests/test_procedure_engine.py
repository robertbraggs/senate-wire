from app.procedure_engine import classify_event_text, get_status_step, likely_next_steps


def test_status_lookup_by_code():
    step = get_status_step("CLOTURE_FILED")

    assert step is not None
    assert step.label == "Cloture filed"
    assert step.chamber == "Senate"
    assert "CLOTURE_INVOKED" in step.outgoing


def test_status_index_loads_operational_noise_steps():
    quorum = get_status_step("QUORUM_CALL")
    recess = get_status_step("RECESS")

    assert quorum is not None
    assert quorum.label == "Quorum call"
    assert recess is not None
    assert recess.phase == "Floor timing"


def test_classifies_cloture_filed():
    result = classify_event_text("Sen. Thune filed cloture on the nomination.")

    assert result["status_code"] == "CLOTURE_FILED"
    assert result["status_label"] == "Cloture filed"
    assert result["significance"] == "major"
    assert result["noise_or_movement"] == "movement"
    assert result["confidence"] == "high"


def test_classifies_motion_to_proceed():
    result = classify_event_text("The Senate resumed consideration of the motion to proceed to S. 123.")

    assert result["status_code"] == "MOTION_TO_PROCEED"
    assert "Amendment pending" in result["likely_next_steps"]
    assert result["significance"] == "notable"


def test_motion_to_proceed_agreed_to_is_major_movement():
    result = classify_event_text("The motion to proceed was agreed to by the Senate.")

    assert result["status_code"] == "MOTION_TO_PROCEED"
    assert result["significance"] == "major"
    assert result["noise_or_movement"] == "movement"


def test_classifies_committee_hearing():
    result = classify_event_text("The Judiciary Committee hearing will receive testimony on the bill.")

    assert result["status_code"] == "COMMITTEE_HEARING"
    assert result["noise_or_movement"] == "noise"


def test_classifies_committee_markup_and_executive_session():
    result = classify_event_text("The committee will hold an executive session to markup S. 10.")

    assert result["status_code"] == "COMMITTEE_MARKUP"
    assert result["noise_or_movement"] == "movement"


def test_classifies_reported_bill():
    result = classify_event_text("S. 456 was reported from the Committee on Finance with an amendment.")

    assert result["status_code"] == "REPORTED_COMMITTEE"


def test_classifies_house_message():
    result = classify_event_text("Message from the House received on H.R. 22.")

    assert result["status_code"] == "HOUSE_MESSAGE"


def test_classifies_conference_report():
    result = classify_event_text("The conference report was filed for H.R. 99.")

    assert result["status_code"] == "CONFERENCE_REPORT_FILED"
    assert "Conference report agreed to" in result["likely_next_steps"]


def test_classifies_conference_report_adopted():
    result = classify_event_text("The Senate adopted the conference report for H.R. 99.")

    assert result["status_code"] == "CONFERENCE_REPORT_AGREED"
    assert result["significance"] == "major"


def test_classifies_veto():
    result = classify_event_text("The President vetoed the bill and returned it with objections.")

    assert result["status_code"] == "VETOED"
    assert result["significance"] == "major"


def test_classifies_signed_by_president():
    result = classify_event_text("The President signed the enrolled bill into law.")

    assert result["status_code"] == "SIGNED_PRESIDENT"
    assert result["likely_next_steps"] == ["No outgoing transition is mapped in the status index; confirm the next procedural step from official action."]


def test_classifies_vote_scheduled_and_final_passage():
    vote = classify_event_text("The Senate will vote at 5:30 p.m. on final passage.")
    passage = classify_event_text("The Senate reached final passage on S. 1.")

    assert vote["status_code"] == "VOTE_SCHEDULED"
    assert passage["status_code"] == "PASSED_SENATE"


def test_significance_scoring_for_routine_noise_examples():
    quorum = classify_event_text("The Senate entered a quorum call.")
    recess = classify_event_text("The Senate stands in recess subject to the call of the chair.")

    assert quorum["significance"] == "routine"
    assert quorum["noise_or_movement"] == "noise"
    assert recess["significance"] == "routine"
    assert recess["noise_or_movement"] == "noise"


def test_contextual_motion_to_proceed_does_not_make_cloture_ambiguous():
    result = classify_event_text("Sen. Thune filed cloture on the motion to proceed to H.R. 1.")

    assert result["status_code"] == "CLOTURE_FILED"
    assert result["confidence"] == "high"


def test_ambiguity_handling_lowers_confidence_and_explains():
    result = classify_event_text("A pending amendment includes a substitute amendment to the bill.")

    assert result["confidence"] == "medium"
    assert "Procedure wording overlaps" in result["reporter_note"]
    assert "confirm against the official action" in result["reporter_note"]


def test_likely_next_steps_resolve_outgoing_branches():
    step = get_status_step("CLOTURE_FILED")

    assert step is not None
    assert likely_next_steps(step) == ["Cloture invoked", "Cloture rejected", "Vote scheduled"]
