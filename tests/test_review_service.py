import os
import uuid

import pytest
from app.agents.models import WorkflowDecision
from app.core.config import Settings, get_settings
from app.db.connection import connect
from app.orchestration.models import Route
from app.review.repository import get_review
from app.review.service import UnknownPreviousReviewError, run_reviewable_query

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_REVIEW_INTEGRATION") != "1",
    reason="Set CAREFLOW_REVIEW_INTEGRATION=1 with Compose running and the 0004 migration "
    "already applied to exercise the real Phase 10 graph + review persistence",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"


@pytest.fixture
async def connection():
    conn = await connect(get_settings())
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def created_review_ids(connection):
    """Tests append review_ids here in creation order. Cleanup deletes events
    for all of them first (no FK risk there), then cases in REVERSE order —
    a later review may reference an earlier one via previous_review_id, and
    that real FK constraint correctly refuses deleting a still-referenced
    parent before its child."""
    ids: list[str] = []
    yield ids
    if ids:
        async with connection.cursor() as cursor:
            for review_id in ids:
                await cursor.execute("DELETE FROM review_events WHERE review_id = %s", (review_id,))
            for review_id in reversed(ids):
                await cursor.execute("DELETE FROM review_cases WHERE review_id = %s", (review_id,))
        await connection.commit()


async def test_clean_structured_success_does_not_create_a_review(connection, created_review_ids):
    result = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            }
        ],
    )
    assert result.response.status == "ok"
    assert result.review_required is False
    assert result.review_reason_codes == []
    assert result.review_id is None
    assert result.review_status is None


async def test_unknown_tool_produces_a_clean_abstention_and_no_review(
    connection, created_review_ids
):
    # A single, honestly-abstained structured result carries no validation
    # issue by design — matches the approved policy's "unknown record" case.
    result = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[{"tool": "not_a_real_tool", "arguments": {}}],
    )
    assert result.response.status == "abstained"
    assert result.review_required is False
    assert result.review_id is None


async def test_partial_multi_tool_failure_creates_a_review(connection, created_review_ids):
    result = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
            {"tool": "not_a_real_tool", "arguments": {}},
        ],
    )
    assert result.review_required is True
    assert "specialist_failure" in result.review_reason_codes
    assert result.review_id is not None
    assert result.review_status == "pending"
    created_review_ids.append(result.review_id)


async def test_persisted_snapshot_matches_the_returned_response(connection, created_review_ids):
    result = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
            {"tool": "not_a_real_tool", "arguments": {}},
        ],
    )
    assert result.review_id is not None
    created_review_ids.append(result.review_id)

    case, _events = await get_review(connection, result.review_id)
    assert case.evidence_snapshot == result.response.model_dump(mode="json")
    assert case.request_id == result.response.request_id
    assert case.workflow == result.response.workflow


async def test_explicit_review_requested_creates_a_review_even_when_clean(
    connection, created_review_ids
):
    result = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            }
        ],
        explicit_review_requested=True,
    )
    assert result.review_required is True
    assert result.review_reason_codes == ["explicit_review_requested"]
    assert result.review_id is not None
    created_review_ids.append(result.review_id)


async def test_unknown_previous_review_id_raises_and_creates_no_review(
    connection, created_review_ids
):
    fake_id = str(uuid.uuid4())
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM review_cases")
        (before,) = await cursor.fetchone()

    with pytest.raises(UnknownPreviousReviewError):
        await run_reviewable_query(
            connection,
            get_settings(),
            question="x",
            workflow=WorkflowDecision.STRUCTURED_ONLY,
            structured_route=Route.SYNPUF,
            tools=[
                {
                    "tool": "get_beneficiary_summary",
                    "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
                }
            ],
            previous_review_id=fake_id,
        )

    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM review_cases")
        (after,) = await cursor.fetchone()
    assert after == before


async def test_valid_previous_review_id_is_linked(connection, created_review_ids):
    first = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
            {"tool": "not_a_real_tool", "arguments": {}},
        ],
    )
    created_review_ids.append(first.review_id)

    second = await run_reviewable_query(
        connection,
        get_settings(),
        question="x",
        workflow=WorkflowDecision.STRUCTURED_ONLY,
        structured_route=Route.SYNPUF,
        tools=[
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
            {"tool": "not_a_real_tool", "arguments": {}},
        ],
        previous_review_id=first.review_id,
    )
    created_review_ids.append(second.review_id)

    case, _events = await get_review(connection, second.review_id)
    assert case.previous_review_id == first.review_id


async def test_infrastructure_failure_propagates_and_creates_no_review(
    connection, created_review_ids
):
    broken_settings = Settings(database_url="postgresql://bad:bad@localhost:1/nope")
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM review_cases")
        (before,) = await cursor.fetchone()

    with pytest.raises(Exception):  # noqa: B017 - the real, unmodified exception type from psycopg
        await run_reviewable_query(
            connection,
            broken_settings,
            question="x",
            workflow=WorkflowDecision.STRUCTURED_ONLY,
            structured_route=Route.SYNPUF,
            tools=[
                {
                    "tool": "get_beneficiary_summary",
                    "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
                }
            ],
        )

    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM review_cases")
        (after,) = await cursor.fetchone()
    assert after == before
