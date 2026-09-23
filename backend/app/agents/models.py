"""Phase 10 contracts: a bounded workflow coordinator (supervisor), a
tool-using structured specialist, the reused Phase 9 policy node, and a
deterministic evidence validator. Route/Status/AbstentionReason are reused
directly from Phase 9 (app.orchestration.models) rather than duplicated —
they are the same bounded vocabularies, not a coincidence."""

from enum import StrEnum
from typing import Any, TypedDict

from pydantic import Field, field_validator, model_validator

from app.orchestration.models import AbstentionReason, Route, Status, StrictModel

# Bounds unbounded structured-tool execution: prevents unbounded work per
# request, keeps latency predictable, and keeps the workflow testable. Five
# is enough for a useful single-patient/beneficiary summary (e.g. summary +
# conditions + procedures + observations + medications) without approaching
# an open-ended tool loop.
MAX_STRUCTURED_TOOL_CALLS = 5


class WorkflowDecision(StrEnum):
    POLICY_ONLY = "policy_only"
    STRUCTURED_ONLY = "structured_only"
    POLICY_AND_STRUCTURED = "policy_and_structured"
    ABSTAIN = "abstain"


class ValidationIssueCode(StrEnum):
    MISSING_POLICY_RESULT = "missing_policy_result"
    MISSING_POLICY_CITATIONS = "missing_policy_citations"
    MISSING_STRUCTURED_RESULT = "missing_structured_result"
    SOURCE_MISMATCH = "source_mismatch"
    SPECIALIST_FAILURE = "specialist_failure"
    CROSS_DATASET_IDENTITY_VIOLATION = "cross_dataset_identity_violation"
    WORKFLOW_RESULT_MISMATCH = "workflow_result_mismatch"


class ValidationIssue(StrictModel):
    code: ValidationIssueCode
    detail: str = Field(min_length=1, max_length=500)


class ValidationResult(StrictModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class StructuredToolRequest(StrictModel):
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


def _accept_enum_as_plain_string(enum_cls: type[StrEnum], value: object) -> object:
    # Mirrors app.orchestration.models._accept_route_as_plain_string: a JSON
    # request body can only ever send a plain string for an enum field, and
    # StrictModel's strict=True otherwise rejects every real request outright.
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            return value
    return value


class MultiAgentRequest(StrictModel):
    """The explicit workflow/policy_question/structured_route/tools fields
    are the preferred, strongest interface — when workflow is supplied, the
    deterministic supervisor classifier is not consulted. Contradictory
    combinations are rejected outright (422), never silently repaired."""

    question: str = Field(min_length=1, max_length=4000)
    workflow: WorkflowDecision | None = None
    policy_question: str | None = Field(default=None, min_length=1, max_length=4000)
    structured_route: Route | None = None
    tools: list[StructuredToolRequest] | None = None

    @field_validator("workflow", mode="before")
    @classmethod
    def _workflow_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(WorkflowDecision, value)

    @field_validator("structured_route", mode="before")
    @classmethod
    def _structured_route_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(Route, value)

    @model_validator(mode="after")
    def _reject_contradictory_request(self) -> "MultiAgentRequest":
        if self.structured_route is not None and self.structured_route not in (
            Route.SYNPUF,
            Route.FHIR,
        ):
            raise ValueError("structured_route must be synpuf or fhir")
        if self.workflow == WorkflowDecision.POLICY_ONLY and (
            self.structured_route is not None or self.tools is not None
        ):
            raise ValueError("workflow=policy_only cannot be combined with structured_route/tools")
        if self.workflow == WorkflowDecision.STRUCTURED_ONLY and self.policy_question is not None:
            raise ValueError("workflow=structured_only cannot be combined with policy_question")
        if (
            self.workflow == WorkflowDecision.POLICY_AND_STRUCTURED
            and self.structured_route is None
        ):
            raise ValueError("workflow=policy_and_structured requires structured_route")
        if self.workflow == WorkflowDecision.ABSTAIN and (
            self.policy_question is not None
            or self.structured_route is not None
            or self.tools is not None
        ):
            raise ValueError(
                "workflow=abstain cannot be combined with policy_question/structured_route/tools"
            )
        if self.tools is not None:
            if self.structured_route is None:
                raise ValueError("tools requires an explicit structured_route")
            if len(self.tools) > MAX_STRUCTURED_TOOL_CALLS:
                raise ValueError(f"at most {MAX_STRUCTURED_TOOL_CALLS} tools may be requested")
        return self


class MultiAgentResponse(StrictModel):
    request_id: str
    workflow: WorkflowDecision
    status: Status
    policy: dict[str, Any] | None = None
    structured: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    final_summary: str | None = None
    abstention_reason: AbstentionReason | None = None
    error: str | None = None


class MultiAgentState(TypedDict, total=False):
    """Deliberately a separate TypedDict from Phase 9's GraphState — the
    shapes genuinely differ (a list of structured tool results, not one).
    Same discipline as Phase 9: no database connections, RAG service
    instances, or Settings objects in state."""

    request_id: str
    question: str
    requested_workflow: WorkflowDecision | None
    requested_policy_question: str | None
    requested_structured_route: Route | None
    requested_tools: list[dict[str, Any]] | None
    workflow: WorkflowDecision | None
    structured_route: Route | None  # resolved structured domain: explicit or classified
    classified_identifier: str | None  # ID extracted by the classifier, if any (not user-supplied)
    policy_result: dict[str, Any] | None
    structured_results: list[dict[str, Any]] | None
    validation: dict[str, Any] | None
    status: Status | None
    abstention_reason: AbstentionReason | None
    error: str | None
