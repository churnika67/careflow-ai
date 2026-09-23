from app.agents.models import MultiAgentResponse, WorkflowDecision
from app.orchestration.models import AbstentionReason, Status
from app.review.models import EXPLICIT_REVIEW_REQUESTED
from app.review.policy import determine_review_requirement


def _response(**overrides) -> MultiAgentResponse:
    defaults = dict(
        request_id="req-1",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        status=Status.OK,
        policy=None,
        structured=None,
        validation={"passed": True, "issues": []},
        final_summary=None,
        abstention_reason=None,
        error=None,
    )
    defaults.update(overrides)
    return MultiAgentResponse(**defaults)


def test_clean_success_does_not_require_review():
    trigger = determine_review_requirement(_response(validation={"passed": True, "issues": []}))
    assert trigger.review_required is False
    assert trigger.reason_codes == []


def test_validation_structural_issue_requires_review():
    trigger = determine_review_requirement(
        _response(
            status=Status.ERROR,
            error="validation_failed",
            validation={
                "passed": False,
                "issues": [{"code": "missing_policy_citations", "detail": "x"}],
            },
        )
    )
    assert trigger.review_required is True
    assert trigger.reason_codes == ["missing_policy_citations"]


def test_partial_specialist_failure_requires_review_even_with_overall_ok_status():
    # status can be OK while an issue is still recorded — partial success is
    # a legitimate response per Phase 10's own validator, but still worth a
    # human looking at the incomplete evidence.
    trigger = determine_review_requirement(
        _response(
            status=Status.OK,
            validation={"passed": True, "issues": [{"code": "specialist_failure", "detail": "x"}]},
        )
    )
    assert trigger.review_required is True
    assert trigger.reason_codes == ["specialist_failure"]


def test_source_mismatch_requires_review():
    trigger = determine_review_requirement(
        _response(
            status=Status.OK,
            validation={"passed": True, "issues": [{"code": "source_mismatch", "detail": "x"}]},
        )
    )
    assert trigger.review_required is True
    assert trigger.reason_codes == ["source_mismatch"]


def test_ordinary_unsupported_request_does_not_require_review():
    trigger = determine_review_requirement(
        _response(
            workflow=WorkflowDecision.ABSTAIN,
            status=Status.ABSTAINED,
            abstention_reason=AbstentionReason.UNSUPPORTED_REQUEST,
            validation={"passed": True, "issues": []},
        )
    )
    assert trigger.review_required is False


def test_clean_policy_abstention_does_not_require_review():
    trigger = determine_review_requirement(
        _response(
            workflow=WorkflowDecision.POLICY_ONLY,
            status=Status.ABSTAINED,
            abstention_reason=AbstentionReason.POLICY_ABSTAINED,
            validation={"passed": True, "issues": []},
        )
    )
    assert trigger.review_required is False


def test_clean_unknown_beneficiary_abstention_does_not_require_review():
    trigger = determine_review_requirement(
        _response(
            workflow=WorkflowDecision.STRUCTURED_ONLY,
            status=Status.ABSTAINED,
            abstention_reason=AbstentionReason.UNKNOWN_BENEFICIARY,
            validation={"passed": True, "issues": []},
        )
    )
    assert trigger.review_required is False


def test_combined_workflow_one_clean_abstention_no_issue_does_not_require_review():
    # Mirrors app.agents.validator's own design: a single clean abstention on
    # one side of a combined workflow is not recorded as an issue.
    trigger = determine_review_requirement(
        _response(
            workflow=WorkflowDecision.POLICY_AND_STRUCTURED,
            status=Status.OK,
            validation={"passed": True, "issues": []},
        )
    )
    assert trigger.review_required is False


def test_explicit_review_request_requires_review_even_with_no_issues():
    trigger = determine_review_requirement(
        _response(validation={"passed": True, "issues": []}),
        explicit_review_requested=True,
    )
    assert trigger.review_required is True
    assert trigger.reason_codes == [EXPLICIT_REVIEW_REQUESTED]


def test_explicit_review_request_combines_with_real_issues():
    trigger = determine_review_requirement(
        _response(
            status=Status.OK,
            validation={"passed": True, "issues": [{"code": "specialist_failure", "detail": "x"}]},
        ),
        explicit_review_requested=True,
    )
    assert trigger.reason_codes == [EXPLICIT_REVIEW_REQUESTED, "specialist_failure"]


def test_missing_validation_is_treated_as_no_issues_not_a_crash():
    trigger = determine_review_requirement(_response(validation=None))
    assert trigger.review_required is False
