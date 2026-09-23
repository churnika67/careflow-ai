import json
import logging
from time import perf_counter
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.connection import connect
from app.generation.providers import GenerationError
from app.review.models import (
    DEFAULT_REVIEW_QUEUE_LIMIT,
    MAX_REVIEW_QUEUE_LIMIT,
    ReviewableQueryRequest,
    ReviewableQueryResponse,
    ReviewCase,
    ReviewDecisionRequest,
    ReviewDetail,
    ReviewQueuePage,
    ReviewStatus,
)
from app.review.repository import apply_decision, get_review, list_reviews, review_exists
from app.review.service import UnknownPreviousReviewError, run_reviewable_query

router = APIRouter(tags=["reviews"])
logger = logging.getLogger(__name__)


def _log(**fields: object) -> None:
    # Deliberately no evidence_snapshot, policy answer text, citation
    # excerpts, structured record contents, or reviewer free-text reason.
    # Callers pass their own correlating id (request_id or review_id) as an
    # explicit keyword — never mislabeled under the wrong key.
    logger.info("%s", json.dumps({"event": "review_action_complete", **fields}, default=str))


@router.post(
    "/reviewable-query",
    response_model=ReviewableQueryResponse,
    responses={
        422: {"description": "Invalid request, or previous_review_id does not exist"},
        502: {"description": "Generation failed or returned malformed output"},
        503: {"description": "Retrieval, provider, or database unavailable"},
        504: {"description": "Generation provider timed out"},
    },
)
async def reviewable_query(request: ReviewableQueryRequest):
    request_id = str(uuid4())
    settings = get_settings()
    connection = await connect(settings)
    started = perf_counter()
    try:
        try:
            result = await run_reviewable_query(
                connection,
                settings,
                question=request.question,
                workflow=request.workflow,
                policy_question=request.policy_question,
                structured_route=request.structured_route,
                tools=[tool.model_dump() for tool in request.tools] if request.tools else None,
                explicit_review_requested=request.explicit_review_requested,
                previous_review_id=request.previous_review_id,
            )
        except UnknownPreviousReviewError:
            _log(
                request_id=request_id,
                action="reviewable_query",
                duration_ms=(perf_counter() - started) * 1000,
                result="unknown_previous_review",
            )
            return JSONResponse(
                status_code=422, content={"error": {"code": "unknown_previous_review_id"}}
            )
        except GenerationError as exc:
            _log(
                request_id=request_id,
                action="reviewable_query",
                error_category=exc.code,
                duration_ms=(perf_counter() - started) * 1000,
            )
            return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code}})
        except Exception as exc:
            # A genuine infrastructure failure — never a semantic abstention,
            # and no review case exists for a request that never completed.
            _log(
                request_id=request_id,
                action="reviewable_query",
                error_category=type(exc).__name__,
                duration_ms=(perf_counter() - started) * 1000,
            )
            return JSONResponse(
                status_code=503, content={"error": {"code": "reviewable_query_unavailable"}}
            )
    finally:
        await connection.close()

    duration_ms = (perf_counter() - started) * 1000
    _log(
        request_id=request_id,
        action="reviewable_query",
        duration_ms=duration_ms,
        status=result.response.status,
        review_required=result.review_required,
        review_id=result.review_id,
        reason_code_count=len(result.review_reason_codes),
    )
    response = result.response
    return ReviewableQueryResponse(
        request_id=response.request_id,
        workflow=response.workflow,
        status=response.status,
        policy=response.policy,
        structured=response.structured,
        validation=response.validation,
        final_summary=response.final_summary,
        abstention_reason=response.abstention_reason,
        error=response.error,
        review_required=result.review_required,
        review_reason_codes=result.review_reason_codes,
        review_id=result.review_id,
        review_status=result.review_status,
    )


@router.post(
    "/reviews/{review_id}/decision",
    response_model=ReviewCase,
    responses={
        404: {"description": "Unknown review_id"},
        409: {"description": "Stale version or the case already left 'pending'"},
        422: {"description": "Invalid request body or malformed review_id"},
    },
)
async def decide_review(review_id: str, request: ReviewDecisionRequest):
    settings = get_settings()
    connection = await connect(settings)
    started = perf_counter()
    try:
        try:
            exists = await review_exists(connection, review_id)
        except psycopg.errors.InvalidTextRepresentation:
            return JSONResponse(status_code=422, content={"error": {"code": "malformed_review_id"}})
        if not exists:
            _log(review_id=review_id, action="decision", result="unknown_review")
            return JSONResponse(status_code=404, content={"error": {"code": "unknown_review"}})

        updated = await apply_decision(
            connection,
            review_id=review_id,
            expected_version=request.expected_version,
            decision=request.decision,
            reviewer_id=request.reviewer_id,
            reason=request.reason,
        )
        if updated is None:
            current, _events = await get_review(connection, review_id)
            _log(
                review_id=review_id,
                action="decision",
                result="conflict",
                previous_status=current.status,
                duration_ms=(perf_counter() - started) * 1000,
            )
            return JSONResponse(
                status_code=409,
                content={
                    "error": {"code": "version_conflict"},
                    "review": current.model_dump(mode="json"),
                },
            )
    finally:
        await connection.close()

    _log(
        review_id=review_id,
        action="decision",
        result="success",
        new_status=updated.status,
        reviewer_id=request.reviewer_id,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return updated


@router.get(
    "/reviews/{review_id}",
    response_model=ReviewDetail,
    responses={
        404: {"description": "Unknown review_id"},
        422: {"description": "Malformed review_id"},
    },
)
async def get_review_detail(review_id: str):
    settings = get_settings()
    connection = await connect(settings)
    try:
        try:
            found = await get_review(connection, review_id)
        except psycopg.errors.InvalidTextRepresentation:
            return JSONResponse(status_code=422, content={"error": {"code": "malformed_review_id"}})
    finally:
        await connection.close()
    if found is None:
        return JSONResponse(status_code=404, content={"error": {"code": "unknown_review"}})
    case, events = found
    return ReviewDetail(case=case, events=events)


@router.get("/reviews", response_model=ReviewQueuePage)
async def list_pending_reviews(
    status: ReviewStatus | None = None,
    limit: int = Query(default=DEFAULT_REVIEW_QUEUE_LIMIT, ge=1, le=MAX_REVIEW_QUEUE_LIMIT),
    cursor: str | None = None,
):
    settings = get_settings()
    connection = await connect(settings)
    try:
        reviews, next_cursor = await list_reviews(
            connection, status=status.value if status else None, limit=limit, cursor=cursor
        )
    finally:
        await connection.close()
    return ReviewQueuePage(reviews=reviews, next_cursor=next_cursor)
