import pytest
from app.agents.models import (
    MAX_STRUCTURED_TOOL_CALLS,
    MultiAgentRequest,
    StructuredToolRequest,
    ValidationIssue,
    ValidationIssueCode,
    ValidationResult,
    WorkflowDecision,
)
from app.orchestration.models import Route
from pydantic import ValidationError


def test_policy_only_request_is_valid():
    request = MultiAgentRequest(question="x", workflow="policy_only")
    assert request.workflow == WorkflowDecision.POLICY_ONLY


def test_policy_only_with_structured_route_is_inconsistent():
    with pytest.raises(ValidationError, match="policy_only"):
        MultiAgentRequest(question="x", workflow="policy_only", structured_route="fhir")


def test_structured_only_with_policy_question_is_inconsistent():
    with pytest.raises(ValidationError, match="structured_only"):
        MultiAgentRequest(
            question="x", workflow="structured_only", structured_route="fhir", policy_question="y"
        )


def test_policy_and_structured_without_structured_route_is_inconsistent():
    with pytest.raises(ValidationError, match="policy_and_structured"):
        MultiAgentRequest(question="x", workflow="policy_and_structured")


def test_policy_and_structured_with_structured_route_is_valid():
    request = MultiAgentRequest(
        question="x", workflow="policy_and_structured", structured_route="fhir"
    )
    assert request.structured_route == Route.FHIR


def test_abstain_with_any_other_field_is_inconsistent():
    with pytest.raises(ValidationError, match="abstain"):
        MultiAgentRequest(question="x", workflow="abstain", structured_route="fhir")


def test_structured_route_must_be_synpuf_or_fhir_not_policy_or_abstain():
    with pytest.raises(ValidationError, match="synpuf or fhir"):
        MultiAgentRequest(question="x", structured_route="policy")


@pytest.mark.parametrize("count", [1, MAX_STRUCTURED_TOOL_CALLS])
def test_tools_within_bound_are_accepted(count):
    request = MultiAgentRequest(
        question="x",
        workflow="structured_only",
        structured_route="fhir",
        tools=[{"tool": "get_patient_summary", "arguments": {}}] * count,
    )
    assert len(request.tools) == count


def test_more_than_max_tools_is_rejected_not_truncated():
    with pytest.raises(ValidationError, match=str(MAX_STRUCTURED_TOOL_CALLS)):
        MultiAgentRequest(
            question="x",
            workflow="structured_only",
            structured_route="fhir",
            tools=[{"tool": "get_patient_summary", "arguments": {}}]
            * (MAX_STRUCTURED_TOOL_CALLS + 1),
        )


def test_tools_without_structured_route_is_inconsistent():
    with pytest.raises(ValidationError, match="structured_route"):
        MultiAgentRequest(
            question="x",
            workflow="structured_only",
            tools=[{"tool": "get_patient_summary", "arguments": {}}],
        )


def test_unknown_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        MultiAgentRequest(question="x", not_a_real_field=1)


def test_invalid_workflow_string_is_rejected():
    with pytest.raises(ValidationError):
        MultiAgentRequest(question="x", workflow="not_a_real_workflow")


def test_structured_tool_request_rejects_extra_fields():
    StructuredToolRequest(tool="x", arguments={})
    with pytest.raises(ValidationError):
        StructuredToolRequest(tool="x", arguments={}, unexpected=1)


def test_validation_result_bounded_issue_codes():
    result = ValidationResult(
        passed=False,
        issues=[
            ValidationIssue(code=ValidationIssueCode.MISSING_POLICY_RESULT, detail="no policy")
        ],
    )
    assert result.passed is False
    assert result.issues[0].code == ValidationIssueCode.MISSING_POLICY_RESULT


def test_validation_issue_rejects_unbounded_code_string():
    with pytest.raises(ValidationError):
        ValidationIssue(code="not_a_real_code", detail="x")
