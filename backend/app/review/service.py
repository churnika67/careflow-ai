"""Phase 11's service boundary: invokes Phase 10's graph exactly as
POST /multi-agent already does (via build_multi_agent_graph + build_response
— the same shared helper multi_agent.py now imports too, not a second
divergence-prone copy), applies the deterministic review-trigger policy, and
— only when review is required — persists a review case.

Infrastructure failures (GenerationError, any other exception raised by
ainvoke) are deliberately NOT caught here — they propagate exactly as they
do for /multi-agent, so the API layer maps them to the same 502/503/504
semantics. No review case is ever created for a request that never reached
a final MultiAgentResponse; there is nothing to review."""

from dataclasses import dataclass
from uuid import uuid4

import psycopg

from app.agents.graph import build_multi_agent_graph, build_response
from app.agents.models import MultiAgentResponse, MultiAgentState, WorkflowDecision
from app.core.config import Settings
from app.orchestration.models import Route
from app.review.models import build_evidence_snapshot, compute_evidence_fingerprint
from app.review.policy import determine_review_requirement
from app.review.repository import create_review, review_exists


class UnknownPreviousReviewError(ValueError):
    """Raised when a caller-supplied previous_review_id does not exist.
    Never inferred, never silently ignored, never auto-corrected to the
    most recent review."""

    def __init__(self, previous_review_id: str) -> None:
        self.previous_review_id = previous_review_id
        super().__init__(f"previous_review_id {previous_review_id!r} does not exist")


@dataclass(frozen=True)
class ReviewableQueryResult:
    response: MultiAgentResponse
    review_required: bool
    review_reason_codes: list[str]
    review_id: str | None
    review_status: str | None


async def run_reviewable_query(
    connection: psycopg.AsyncConnection,
    settings: Settings,
    *,
    question: str,
    workflow: WorkflowDecision | None = None,
    policy_question: str | None = None,
    structured_route: Route | None = None,
    tools: list[dict] | None = None,
    explicit_review_requested: bool = False,
    previous_review_id: str | None = None,
) -> ReviewableQueryResult:
    if previous_review_id is not None and not await review_exists(connection, previous_review_id):
        raise UnknownPreviousReviewError(previous_review_id)

    request_id = str(uuid4())
    state: MultiAgentState = {
        "request_id": request_id,
        "question": question,
        "requested_workflow": workflow,
        "requested_policy_question": policy_question,
        "requested_structured_route": structured_route,
        "requested_tools": tools,
    }
    # Not wrapped in try/except: a GenerationError or any other exception
    # here means Phase 10 never produced a final result, so there is no
    # evidence to snapshot and no review to create — let it propagate.
    result = await build_multi_agent_graph(settings).ainvoke(state)
    response = build_response(request_id, result)

    trigger = determine_review_requirement(
        response, explicit_review_requested=explicit_review_requested
    )
    if not trigger.review_required:
        return ReviewableQueryResult(
            response=response,
            review_required=False,
            review_reason_codes=[],
            review_id=None,
            review_status=None,
        )

    snapshot = build_evidence_snapshot(response)
    fingerprint = compute_evidence_fingerprint(snapshot)
    case, _created = await create_review(
        connection,
        request_id=request_id,
        workflow=response.workflow.value,
        trigger_reason_codes=trigger.reason_codes,
        evidence_snapshot=snapshot,
        evidence_fingerprint=fingerprint,
        previous_review_id=previous_review_id,
    )
    return ReviewableQueryResult(
        response=response,
        review_required=True,
        review_reason_codes=trigger.reason_codes,
        review_id=case.review_id,
        review_status=case.status.value,
    )
