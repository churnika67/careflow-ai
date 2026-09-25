"""The deterministic evidence validator/guardrail. Read-only over
already-produced state — no retrieval, no DB, no external tools, no new
tool calls. This is the SOLE place `status`/`abstention_reason`/`error` are
decided for the whole request (see graph.py's module docstring for why:
policy_node and structured_specialist write only their own disjoint keys,
since they may run concurrently in a combined workflow).

"Passed" means nothing is structurally wrong (a missing result where one
was required, a source-domain mismatch, a policy answer claiming success
with no citations, or policy/structured shapes bleeding into each other).
A clean, honest abstention (unknown beneficiary, missing identifier, ...)
is not a validation failure — it is the system working correctly — so it
still reports passed=True.
"""

import logging

from app.agents.models import (
    MultiAgentState,
    ValidationIssue,
    ValidationIssueCode,
    ValidationResult,
    WorkflowDecision,
)
from app.observability.logging import log_event
from app.orchestration.models import AbstentionReason, Route, Status

logger = logging.getLogger(__name__)


def _log_event(request_id: str | None, **fields: object) -> None:
    # Thin, signature-preserving shim over the central helper -- see
    # agents/graph.py's identical shim for the same rationale. Deliberately
    # no patient/beneficiary/claim record contents — only routing/tool
    # metadata, counts, and reason codes, exactly as before this migration.
    log_event(logger, "agent_node_complete", request_id=request_id, **fields)


_EXPECTED_SOURCE_BY_ROUTE = {Route.FHIR: "synthea_fhir", Route.SYNPUF: "cms_desynpuf"}
_TOOL_ERROR_TO_ABSTENTION = {
    "unsupported_tool": AbstentionReason.UNSUPPORTED_TOOL,
    "invalid_tool_arguments": AbstentionReason.INVALID_TOOL_ARGUMENTS,
    "too_many_tool_calls": AbstentionReason.INVALID_TOOL_ARGUMENTS,
    "missing_tool_name": AbstentionReason.MISSING_REQUIRED_IDENTIFIER,
}


def _policy_validation(
    policy_result: dict | None,
) -> tuple[Status, AbstentionReason | None, list[ValidationIssue]]:
    if policy_result is None:
        return (
            Status.ERROR,
            None,
            [ValidationIssue(code=ValidationIssueCode.MISSING_POLICY_RESULT, detail="missing")],
        )
    if policy_result.get("status") == "abstained":
        return Status.ABSTAINED, AbstentionReason.POLICY_ABSTAINED, []
    if not policy_result.get("citations"):
        detail = "policy_result reports success but has no citations"
        issue = ValidationIssue(code=ValidationIssueCode.MISSING_POLICY_CITATIONS, detail=detail)
        return Status.ERROR, None, [issue]
    return Status.OK, None, []


def _structured_validation(
    structured_results: list[dict] | None, route: Route | None
) -> tuple[Status, AbstentionReason | None, list[ValidationIssue]]:
    if structured_results is None:
        return (
            Status.ERROR,
            None,
            [ValidationIssue(code=ValidationIssueCode.MISSING_STRUCTURED_RESULT, detail="missing")],
        )

    expected_source = _EXPECTED_SOURCE_BY_ROUTE.get(route)
    issues: list[ValidationIssue] = []
    successes, failures = [], []
    for item in structured_results:
        source = item.get("source_dataset")
        if source is not None and expected_source is not None and source != expected_source:
            detail = f"expected {expected_source}, got {source} for tool {item.get('tool')}"
            issues.append(ValidationIssue(code=ValidationIssueCode.SOURCE_MISMATCH, detail=detail))
        if item.get("success") and item.get("data") is not None:
            successes.append(item)
        else:
            failures.append(item)

    if successes and failures:
        detail = (
            f"{len(failures)} of {len(structured_results)} requested tool call(s) returned no data"
        )
        issues.append(ValidationIssue(code=ValidationIssueCode.SPECIALIST_FAILURE, detail=detail))

    if successes:
        return Status.OK, None, issues

    first = structured_results[0]
    if first.get("abstention_reason"):
        return Status.ABSTAINED, AbstentionReason(first["abstention_reason"]), issues
    if first.get("error"):
        reason = _TOOL_ERROR_TO_ABSTENTION.get(first["error"], AbstentionReason.UNSUPPORTED_REQUEST)
        return Status.ABSTAINED, reason, issues
    return Status.ERROR, None, issues


def _shape_leak_issues(state: MultiAgentState) -> list[ValidationIssue]:
    """Requirements 11/12: no structured evidence represented as a policy
    citation, no policy result represented as a DB record. Structurally
    guaranteed by construction (nothing in this codebase ever assigns one
    shape into the other's field) — these are cheap defensive checks that
    would catch a future regression, not a currently-reachable bug."""
    issues = []
    policy_result = state.get("policy_result")
    if policy_result and any(
        k in policy_result for k in ("tool", "source_dataset", "record_count")
    ):
        detail = "structured-shaped fields found inside policy_result"
        issues.append(
            ValidationIssue(code=ValidationIssueCode.WORKFLOW_RESULT_MISMATCH, detail=detail)
        )
    for item in state.get("structured_results") or []:
        if "citations" in item or "answer" in item:
            detail = "policy-shaped fields found inside a structured result"
            issues.append(
                ValidationIssue(code=ValidationIssueCode.WORKFLOW_RESULT_MISMATCH, detail=detail)
            )
    return issues


def validate_node(state: MultiAgentState) -> dict:
    request_id = state.get("request_id")
    workflow = state.get("workflow")
    if workflow == WorkflowDecision.ABSTAIN:
        result = ValidationResult(passed=True, issues=[])
        _log_event(
            request_id,
            node="validate",
            action="validate",
            status=str(Status.ABSTAINED),
            validation_issue=[],
        )
        return {"status": Status.ABSTAINED, "validation": result.model_dump(mode="json")}

    issues = _shape_leak_issues(state)
    policy_status = policy_reason = None
    structured_status = structured_reason = None

    if workflow in (WorkflowDecision.POLICY_ONLY, WorkflowDecision.POLICY_AND_STRUCTURED):
        policy_status, policy_reason, policy_issues = _policy_validation(state.get("policy_result"))
        issues.extend(policy_issues)

    if workflow in (WorkflowDecision.STRUCTURED_ONLY, WorkflowDecision.POLICY_AND_STRUCTURED):
        structured_status, structured_reason, structured_issues = _structured_validation(
            state.get("structured_results"), state.get("structured_route")
        )
        issues.extend(structured_issues)

    statuses = [s for s in (policy_status, structured_status) if s is not None]
    validation = ValidationResult(passed=Status.ERROR not in statuses, issues=issues)
    update: dict = {"validation": validation.model_dump(mode="json")}
    issue_codes = [str(issue.code) for issue in issues]

    if Status.ERROR in statuses:
        update["status"] = Status.ERROR
        update["error"] = "validation_failed"
    elif Status.OK in statuses:
        update["status"] = Status.OK
    else:
        update["status"] = Status.ABSTAINED
        update["abstention_reason"] = (
            policy_reason or structured_reason or AbstentionReason.UNSUPPORTED_REQUEST
        )

    _log_event(
        request_id,
        node="validate",
        action="validate",
        status=str(update["status"]),
        validation_issue=issue_codes,
        abstention_reason=(
            update["abstention_reason"].value if update.get("abstention_reason") else None
        ),
        error_category=update.get("error"),
    )
    return update
