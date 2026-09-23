from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.agents.models import MultiAgentResponse, ValidationIssueCode, WorkflowDecision
from app.orchestration.models import AbstentionReason, Status
from app.review.models import (
    EXPLICIT_REVIEW_REQUESTED,
    VALID_TRIGGER_REASON_CODES,
    ActorType,
    ReviewCase,
    ReviewDecisionRequest,
    ReviewDecisionType,
    ReviewEvent,
    ReviewEventType,
    ReviewStatus,
    ReviewTrigger,
    build_evidence_snapshot,
    compute_evidence_fingerprint,
    event_type_for_transition,
    is_terminal,
    is_valid_transition,
    target_status_for,
)
from pydantic import ValidationError

# --- transition rules --------------------------------------------------


@pytest.mark.parametrize(
    "decision,expected_status",
    [
        (ReviewDecisionType.APPROVE, ReviewStatus.APPROVED),
        (ReviewDecisionType.REJECT, ReviewStatus.REJECTED),
        (ReviewDecisionType.REQUEST_REVISION, ReviewStatus.REVISION_REQUESTED),
    ],
)
def test_target_status_for_every_decision(decision, expected_status):
    assert target_status_for(decision) == expected_status


@pytest.mark.parametrize(
    "status,expected_event",
    [
        (ReviewStatus.APPROVED, ReviewEventType.REVIEW_APPROVED),
        (ReviewStatus.REJECTED, ReviewEventType.REVIEW_REJECTED),
        (ReviewStatus.REVISION_REQUESTED, ReviewEventType.REVISION_REQUESTED),
    ],
)
def test_event_type_for_every_terminal_status(status, expected_event):
    assert event_type_for_transition(status) == expected_event


def test_pending_is_not_terminal():
    assert is_terminal(ReviewStatus.PENDING) is False


@pytest.mark.parametrize(
    "status", [ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.REVISION_REQUESTED]
)
def test_every_decision_target_is_terminal(status):
    assert is_terminal(status) is True


@pytest.mark.parametrize(
    "decision",
    [ReviewDecisionType.APPROVE, ReviewDecisionType.REJECT, ReviewDecisionType.REQUEST_REVISION],
)
def test_pending_accepts_any_decision(decision):
    assert is_valid_transition(ReviewStatus.PENDING, decision) is True


@pytest.mark.parametrize(
    "current_status",
    [ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.REVISION_REQUESTED],
)
def test_no_transition_out_of_a_terminal_status(current_status):
    for decision in ReviewDecisionType:
        assert is_valid_transition(current_status, decision) is False


# --- trigger reason vocabulary ------------------------------------------


def test_valid_trigger_reasons_include_every_validation_issue_code():
    for code in ValidationIssueCode:
        assert code.value in VALID_TRIGGER_REASON_CODES


def test_valid_trigger_reasons_include_explicit_review_requested():
    assert EXPLICIT_REVIEW_REQUESTED in VALID_TRIGGER_REASON_CODES
    assert EXPLICIT_REVIEW_REQUESTED == "explicit_review_requested"


def test_valid_trigger_reasons_has_no_extra_unexpected_members():
    assert VALID_TRIGGER_REASON_CODES == {c.value for c in ValidationIssueCode} | {
        EXPLICIT_REVIEW_REQUESTED
    }


# --- evidence snapshot / fingerprint -------------------------------------


def _sample_response(**overrides) -> MultiAgentResponse:
    defaults = dict(
        request_id="req-1",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        status=Status.OK,
        policy=None,
        structured={"route": "synpuf", "results": [{"tool": "get_beneficiary_summary"}]},
        validation={"passed": True, "issues": []},
        final_summary=None,
        abstention_reason=None,
        error=None,
    )
    defaults.update(overrides)
    return MultiAgentResponse(**defaults)


def test_build_evidence_snapshot_matches_response_json_dump():
    response = _sample_response()
    snapshot = build_evidence_snapshot(response)
    assert snapshot == response.model_dump(mode="json")
    assert snapshot["request_id"] == "req-1"
    assert snapshot["workflow"] == "structured_only"


def test_snapshot_contains_no_unexpected_fields():
    response = _sample_response()
    snapshot = build_evidence_snapshot(response)
    assert set(snapshot) == set(MultiAgentResponse.model_fields)


def test_fingerprint_is_deterministic_for_the_same_snapshot():
    snapshot = build_evidence_snapshot(_sample_response())
    assert compute_evidence_fingerprint(snapshot) == compute_evidence_fingerprint(snapshot)


def test_fingerprint_is_insensitive_to_key_order():
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert compute_evidence_fingerprint(a) == compute_evidence_fingerprint(b)


def test_fingerprint_changes_when_snapshot_content_changes():
    snapshot_a = build_evidence_snapshot(_sample_response(status=Status.OK))
    snapshot_b = build_evidence_snapshot(
        _sample_response(
            status=Status.ABSTAINED, abstention_reason=AbstentionReason.POLICY_ABSTAINED
        )
    )
    assert compute_evidence_fingerprint(snapshot_a) != compute_evidence_fingerprint(snapshot_b)


def test_fingerprint_is_a_64_char_hex_sha256():
    snapshot = build_evidence_snapshot(_sample_response())
    fingerprint = compute_evidence_fingerprint(snapshot)
    assert len(fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint)


# --- ReviewDecisionRequest ------------------------------------------------


def test_decision_request_accepts_plain_decision_strings():
    for raw in ("approve", "reject", "request_revision"):
        request = ReviewDecisionRequest(reviewer_id="alice", decision=raw, expected_version=1)
        assert request.decision == ReviewDecisionType(raw)


def test_decision_request_rejects_invalid_decision_string():
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(
            reviewer_id="alice", decision="not_a_real_decision", expected_version=1
        )


def test_decision_request_rejects_blank_reviewer_id():
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(reviewer_id="", decision="approve", expected_version=1)


def test_decision_request_rejects_overlong_reviewer_id():
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(reviewer_id="x" * 101, decision="approve", expected_version=1)


def test_decision_request_rejects_non_positive_expected_version():
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(reviewer_id="alice", decision="approve", expected_version=0)


def test_decision_request_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(
            reviewer_id="alice", decision="approve", expected_version=1, not_a_real_field=1
        )


def test_decision_request_reason_is_optional():
    request = ReviewDecisionRequest(reviewer_id="alice", decision="approve", expected_version=1)
    assert request.reason is None


# --- ReviewCase / ReviewEvent constructed from raw DB-row-shaped values ---


def test_review_case_accepts_plain_strings_as_from_a_db_row():
    case = ReviewCase(
        review_id="r1",
        request_id="req-1",
        workflow="structured_only",
        status="pending",
        trigger_reason_codes=["specialist_failure"],
        evidence_snapshot={"a": 1},
        evidence_fingerprint="a" * 64,
        version=1,
        previous_review_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert case.workflow == WorkflowDecision.STRUCTURED_ONLY
    assert case.status == ReviewStatus.PENDING


def test_review_case_accepts_uuid_objects_as_psycopg_would_return():
    # review_id/previous_review_id are native Postgres UUID columns; psycopg
    # returns uuid.UUID objects for those, not str.
    review_uuid = uuid4()
    previous_uuid = uuid4()
    case = ReviewCase(
        review_id=review_uuid,
        request_id="req-1",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        status=ReviewStatus.PENDING,
        trigger_reason_codes=[],
        evidence_snapshot={},
        evidence_fingerprint="a" * 64,
        version=1,
        previous_review_id=previous_uuid,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert case.review_id == str(review_uuid)
    assert case.previous_review_id == str(previous_uuid)


def test_review_event_accepts_uuid_objects_as_psycopg_would_return():
    event = ReviewEvent(
        event_id=uuid4(),
        review_id=uuid4(),
        event_type=ReviewEventType.REVIEW_CREATED,
        actor_id="system",
        actor_type=ActorType.SYSTEM,
        previous_status=None,
        new_status=ReviewStatus.PENDING,
        reason=None,
        metadata=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert isinstance(event.event_id, str)
    assert isinstance(event.review_id, str)


def test_review_case_version_must_be_positive():
    with pytest.raises(ValidationError):
        ReviewCase(
            review_id="r1",
            request_id="req-1",
            workflow="structured_only",
            status="pending",
            trigger_reason_codes=[],
            evidence_snapshot={},
            evidence_fingerprint="a" * 64,
            version=0,
            previous_review_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_review_event_accepts_plain_strings_and_null_previous_status():
    event = ReviewEvent(
        event_id="e1",
        review_id="r1",
        event_type="review_created",
        actor_id="system",
        actor_type="system",
        previous_status=None,
        new_status="pending",
        reason=None,
        metadata=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert event.event_type == ReviewEventType.REVIEW_CREATED
    assert event.actor_type == ActorType.SYSTEM
    assert event.previous_status is None
    assert event.new_status == ReviewStatus.PENDING


def test_review_event_decision_event_carries_previous_status():
    event = ReviewEvent(
        event_id="e2",
        review_id="r1",
        event_type="review_approved",
        actor_id="alice",
        actor_type="reviewer",
        previous_status="pending",
        new_status="approved",
        reason="looks good",
        metadata=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert event.previous_status == ReviewStatus.PENDING
    assert event.new_status == ReviewStatus.APPROVED


# --- ReviewTrigger ----------------------------------------------------------


def test_review_trigger_no_review_required():
    trigger = ReviewTrigger(review_required=False, reason_codes=[])
    assert trigger.review_required is False
    assert trigger.reason_codes == []


def test_review_trigger_review_required_with_reasons():
    trigger = ReviewTrigger(review_required=True, reason_codes=["specialist_failure"])
    assert trigger.review_required is True
