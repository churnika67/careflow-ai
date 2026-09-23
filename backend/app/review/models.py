"""Phase 11 contracts: an explicit PostgreSQL-persisted review state machine
sitting entirely after Phase 10's validation boundary. Nothing here touches
Phase 10 execution — this module only defines types, transition rules, and
pure snapshot/fingerprint helpers over an already-produced MultiAgentResponse.

Deliberately no LangGraph checkpointer/interrupt: this project has no durable
checkpointer installed (only the in-memory, single-process langgraph-checkpoint
base package is a transitive dependency, unused anywhere), and a hand-rolled
four-state machine backed by Postgres needs no workflow library."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.models import (
    MultiAgentRequest,
    MultiAgentResponse,
    ValidationIssueCode,
    WorkflowDecision,
)
from app.orchestration.models import StrictModel
from ingestion.models import digest as _canonical_digest

# Bounds the review queue listing, same two-layer-enforcement idea as Phase
# 10's MAX_STRUCTURED_TOOL_CALLS: the API layer clamps/validates the
# requested limit, and the repository clamps defensively too.
DEFAULT_REVIEW_QUEUE_LIMIT = 20
MAX_REVIEW_QUEUE_LIMIT = 100


def _accept_enum_as_plain_string(enum_cls: type[StrEnum], value: object) -> object:
    # Same pattern as app.orchestration.models/app.agents.models: StrictModel's
    # strict=True blocks plain-string-to-enum coercion, but a JSON request body
    # can only ever send a plain string for an enum field.
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            return value
    return value


def _accept_uuid_object(value: object) -> object:
    # review_id/event_id/previous_review_id are native Postgres UUID columns
    # (migration 0004), so a row fetched via dict_row arrives as uuid.UUID,
    # not str — same reasoning as app.orchestration.tools.ClaimRowIdArgs.
    return str(value) if isinstance(value, UUID) else value


# The one Phase 11-specific trigger reason. Every other trigger reason reuses
# ValidationIssueCode's own values directly — no parallel vocabulary.
EXPLICIT_REVIEW_REQUESTED = "explicit_review_requested"

VALID_TRIGGER_REASON_CODES: frozenset[str] = frozenset(
    code.value for code in ValidationIssueCode
) | {EXPLICIT_REVIEW_REQUESTED}


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ReviewDecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"


class ReviewEventType(StrEnum):
    REVIEW_CREATED = "review_created"
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    REVISION_REQUESTED = "revision_requested"


class ActorType(StrEnum):
    SYSTEM = "system"
    REVIEWER = "reviewer"


# --- transition rules -------------------------------------------------------
# PENDING -> APPROVED | REJECTED | REVISION_REQUESTED. All three targets are
# terminal: nothing in Phase 11 ever transitions out of them.

_TARGET_STATUS_BY_DECISION: dict[ReviewDecisionType, ReviewStatus] = {
    ReviewDecisionType.APPROVE: ReviewStatus.APPROVED,
    ReviewDecisionType.REJECT: ReviewStatus.REJECTED,
    ReviewDecisionType.REQUEST_REVISION: ReviewStatus.REVISION_REQUESTED,
}

_EVENT_TYPE_BY_TARGET_STATUS: dict[ReviewStatus, ReviewEventType] = {
    ReviewStatus.APPROVED: ReviewEventType.REVIEW_APPROVED,
    ReviewStatus.REJECTED: ReviewEventType.REVIEW_REJECTED,
    ReviewStatus.REVISION_REQUESTED: ReviewEventType.REVISION_REQUESTED,
}


def target_status_for(decision: ReviewDecisionType) -> ReviewStatus:
    return _TARGET_STATUS_BY_DECISION[decision]


def event_type_for_transition(new_status: ReviewStatus) -> ReviewEventType:
    return _EVENT_TYPE_BY_TARGET_STATUS[new_status]


def is_terminal(status: ReviewStatus) -> bool:
    return status != ReviewStatus.PENDING


def is_valid_transition(current_status: ReviewStatus, decision: ReviewDecisionType) -> bool:
    # The only non-terminal status is PENDING, and every decision targets a
    # terminal status — so a transition is valid exactly when the case is
    # still PENDING. decision's own type already bounds it to one of the
    # three known decisions; there is no "unknown decision" case to reject
    # here (Pydantic rejects that before this function is ever called).
    return current_status == ReviewStatus.PENDING


# --- evidence snapshot / fingerprint ----------------------------------------


def build_evidence_snapshot(response: MultiAgentResponse) -> dict[str, Any]:
    """The reviewed evidence is exactly the bounded, already-public
    MultiAgentResponse body — the same JSON any /multi-agent or
    /reviewable-query caller already receives. No raw source files,
    settings, credentials, or internal Python state ever enter this
    snapshot, because none of those are fields on MultiAgentResponse."""
    return response.model_dump(mode="json")


def compute_evidence_fingerprint(evidence_snapshot: dict[str, Any]) -> str:
    """SHA-256 over a deterministic canonical JSON serialization of the
    snapshot. Reuses ingestion.models.digest — the same canonicalization
    (sort_keys, compact separators) already used for Phase 1-8 content
    addressing — rather than a second, incompatible implementation.

    This provides snapshot-integrity comparison and reproducibility. It does
    NOT make the database tamper-proof, cryptographically immutable, or
    blockchain-backed — no such claim is made anywhere in Phase 11."""
    return _canonical_digest(evidence_snapshot)


# --- typed row/response models ----------------------------------------------


class ReviewCase(StrictModel):
    """Constructed either from a live Postgres row (plain TEXT columns) or
    from already-typed Python values — the before-validators accept both,
    same reasoning as every other StrictModel in this codebase."""

    review_id: str
    request_id: str
    workflow: WorkflowDecision
    status: ReviewStatus
    trigger_reason_codes: list[str]
    evidence_snapshot: dict[str, Any]
    evidence_fingerprint: str
    version: int = Field(ge=1)
    previous_review_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("review_id", "previous_review_id", mode="before")
    @classmethod
    def _uuid_fields_from_object(cls, value: object) -> object:
        return _accept_uuid_object(value)

    @field_validator("workflow", mode="before")
    @classmethod
    def _workflow_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(WorkflowDecision, value)

    @field_validator("status", mode="before")
    @classmethod
    def _status_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(ReviewStatus, value)


class ReviewEvent(StrictModel):
    event_id: str
    review_id: str
    event_type: ReviewEventType
    actor_id: str
    actor_type: ActorType
    previous_status: ReviewStatus | None
    new_status: ReviewStatus
    reason: str | None
    metadata: dict[str, Any] | None
    created_at: datetime

    @field_validator("event_id", "review_id", mode="before")
    @classmethod
    def _uuid_fields_from_object(cls, value: object) -> object:
        return _accept_uuid_object(value)

    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(ReviewEventType, value)

    @field_validator("actor_type", mode="before")
    @classmethod
    def _actor_type_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(ActorType, value)

    @field_validator("previous_status", "new_status", mode="before")
    @classmethod
    def _status_from_string(cls, value: object) -> object:
        if value is None:
            return None
        return _accept_enum_as_plain_string(ReviewStatus, value)


class ReviewDecisionRequest(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=100)
    decision: ReviewDecisionType
    reason: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)

    @field_validator("decision", mode="before")
    @classmethod
    def _decision_from_string(cls, value: object) -> object:
        return _accept_enum_as_plain_string(ReviewDecisionType, value)


class ReviewTrigger(StrictModel):
    review_required: bool
    reason_codes: list[str]


class ReviewableQueryRequest(MultiAgentRequest):
    """Everything MultiAgentRequest accepts, plus two Phase 11-only fields.
    Subclassing (not composition) so every existing MultiAgentRequest
    consistency rule — the contradictory-combination checks — keeps applying
    unchanged; nothing here weakens or bypasses them."""

    explicit_review_requested: bool = False
    previous_review_id: str | None = None


class ReviewableQueryResponse(MultiAgentResponse):
    """The exact MultiAgentResponse shape /multi-agent already returns, plus
    the review outcome. When no review was required, review_id/review_status
    are null and reason_codes is empty — review state is never hidden inside
    free-form prose."""

    review_required: bool
    review_reason_codes: list[str]
    review_id: str | None
    review_status: ReviewStatus | None

    @field_validator("review_status", mode="before")
    @classmethod
    def _review_status_from_string(cls, value: object) -> object:
        if value is None:
            return None
        return _accept_enum_as_plain_string(ReviewStatus, value)


class ReviewDetail(StrictModel):
    case: ReviewCase
    events: list[ReviewEvent]


class ReviewQueuePage(StrictModel):
    reviews: list[ReviewCase]
    next_cursor: str | None
