from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Route(StrEnum):
    POLICY = "policy"
    SYNPUF = "synpuf"
    FHIR = "fhir"
    ABSTAIN = "abstain"


class Status(StrEnum):
    OK = "ok"
    ABSTAINED = "abstained"
    ERROR = "error"


class AbstentionReason(StrEnum):
    UNSUPPORTED_REQUEST = "unsupported_request"
    AMBIGUOUS_ROUTE = "ambiguous_route"
    CROSS_DATASET_LINKAGE_REQUEST = "cross_dataset_linkage_request"
    MISSING_REQUIRED_IDENTIFIER = "missing_required_identifier"
    UNKNOWN_PATIENT = "unknown_patient"
    UNKNOWN_BENEFICIARY = "unknown_beneficiary"
    UNKNOWN_CLAIM = "unknown_claim"
    UNSUPPORTED_TOOL = "unsupported_tool"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    INCONSISTENT_REQUEST = "inconsistent_request"
    # The policy pipeline itself abstained (Phase 4 evidence/citation safety
    # behavior). Its specific reason (e.g. "no_eligible_evidence") is
    # preserved unchanged inside policy_result.abstention_reason — this
    # value only marks, at the orchestration layer, that that happened.
    POLICY_ABSTAINED = "policy_abstained"


class GraphState(TypedDict, total=False):
    """Bounded orchestration state. Deliberately holds only plain data
    (strings, enums, dicts, None) — no database connections, RAG service
    instances, settings objects, or other framework objects."""

    request_id: str
    question: str
    requested_route: Route | None
    requested_tool: str | None
    requested_tool_arguments: dict[str, Any] | None
    route: Route | None
    tool_name: str | None
    tool_arguments: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    policy_result: dict[str, Any] | None
    structured_result: dict[str, Any] | None
    status: Status | None
    abstention_reason: AbstentionReason | None
    error: str | None


class OrchestrationRequest(StrictModel):
    """The explicit route/tool/tool_arguments fields are the preferred,
    strongest interface (see classify.py's module docstring) — when
    supplied, the deterministic free-text classifier is not consulted at
    all. `tool`/`tool_arguments` are only meaningful with route=synpuf or
    route=fhir; route=policy combined with either is rejected as an
    inconsistent request, not silently corrected."""

    question: str = Field(min_length=1, max_length=4000)
    route: Route | None = None
    tool: str | None = Field(default=None, min_length=1, max_length=100)
    tool_arguments: dict[str, Any] | None = None

    @field_validator("route", mode="before")
    @classmethod
    def _accept_route_as_plain_string(cls, value: object) -> object:
        # A JSON request body can only ever send a plain string for an
        # enum-valued field — strict=True otherwise requires an actual Route
        # instance and rejects every real API request outright. An invalid
        # string is passed through unchanged so the normal enum-membership
        # validation still reports it as an error.
        if isinstance(value, str):
            try:
                return Route(value)
            except ValueError:
                return value
        return value

    @model_validator(mode="after")
    def _reject_contradictory_explicit_request(self) -> "OrchestrationRequest":
        if self.route == Route.POLICY and (
            self.tool is not None or self.tool_arguments is not None
        ):
            raise ValueError("route=policy cannot be combined with a tool or tool_arguments")
        if self.route is None and (self.tool is not None or self.tool_arguments is not None):
            raise ValueError("tool/tool_arguments require an explicit route")
        return self


class OrchestrationResponse(StrictModel):
    request_id: str
    route: Route
    status: Status
    answer: str | None = None
    citations: list[dict[str, Any]] | None = None
    tool: str | None = None
    source_dataset: str | None = None
    record_count: int | None = None
    data: Any | None = None
    abstention_reason: AbstentionReason | None = None
    error: str | None = None
