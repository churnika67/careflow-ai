import asyncio
import os
import uuid

import psycopg
import pytest
from app.core.config import get_settings
from app.db.connection import connect
from app.review.models import MAX_REVIEW_QUEUE_LIMIT, ReviewDecisionType, ReviewEventType
from app.review.repository import (
    apply_decision,
    create_review,
    get_review,
    list_reviews,
    review_exists,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_REVIEW_INTEGRATION") != "1",
    reason="Set CAREFLOW_REVIEW_INTEGRATION=1 with Compose running and the 0004 migration "
    "already applied to exercise real review persistence",
)


@pytest.fixture
async def connection():
    conn = await connect(get_settings())
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def created_review_ids(connection):
    """Every test appends the review_ids it creates here; cleanup deletes
    exactly those rows and nothing else — never a table truncation, never a
    healthcare source table. Events for all of them are deleted first, then
    cases in REVERSE creation order — a later review may reference an
    earlier one via previous_review_id, and that real FK constraint
    correctly refuses deleting a still-referenced parent before its child."""
    ids: list[str] = []
    yield ids
    if ids:
        async with connection.cursor() as cursor:
            for review_id in ids:
                await cursor.execute("DELETE FROM review_events WHERE review_id = %s", (review_id,))
            for review_id in reversed(ids):
                await cursor.execute("DELETE FROM review_cases WHERE review_id = %s", (review_id,))
        await connection.commit()


def _request_id() -> str:
    return f"test-review-{uuid.uuid4()}"


async def _make_review(connection, created_review_ids, **overrides):
    request_id = overrides.pop("request_id", None) or _request_id()
    kwargs = dict(
        request_id=request_id,
        workflow="structured_only",
        trigger_reason_codes=["specialist_failure"],
        evidence_snapshot={"request_id": request_id},
        evidence_fingerprint="a" * 64,
        previous_review_id=None,
    )
    kwargs.update(overrides)
    case, created = await create_review(connection, **kwargs)
    created_review_ids.append(case.review_id)
    return case, created


# --- create_review -----------------------------------------------------


async def test_create_review_persists_a_pending_case(connection, created_review_ids):
    case, created = await _make_review(connection, created_review_ids)
    assert created is True
    assert case.status == "pending"
    assert case.version == 1


async def test_create_review_inserts_exactly_one_creation_event(connection, created_review_ids):
    case, _ = await _make_review(connection, created_review_ids)
    _, events = await get_review(connection, case.review_id)
    assert len(events) == 1
    assert events[0].event_type == ReviewEventType.REVIEW_CREATED
    assert events[0].actor_id == "system"
    assert events[0].previous_status is None


async def test_create_review_is_durable_after_a_prior_read_on_the_same_connection(
    connection, created_review_ids
):
    # Regression test for a real bug caught via live smoke testing: a bare
    # SELECT before create_review's write opens an ambient transaction
    # (autocommit=False), which turns connection.transaction() into a
    # SAVEPOINT rather than a real top-level transaction — releasing a
    # savepoint makes writes visible only within that same still-open,
    # still-uncommitted connection. Reading back from the SAME connection
    # would pass even with the bug present; only a genuinely separate
    # connection proves the write was actually committed.
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT 1")
        await cursor.fetchone()

    case, created = await _make_review(connection, created_review_ids)
    assert created is True

    fresh = await connect(get_settings())
    try:
        found = await get_review(fresh, case.review_id)
    finally:
        await fresh.close()
    assert found is not None
    assert found[0].status == "pending"
    assert len(found[1]) == 1


async def test_apply_decision_is_durable_after_a_prior_read_on_the_same_connection(
    connection, created_review_ids
):
    case, _ = await _make_review(connection, created_review_ids)
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT 1")
        await cursor.fetchone()

    updated = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.APPROVE,
        reviewer_id="alice",
        reason=None,
    )
    assert updated is not None

    fresh = await connect(get_settings())
    try:
        found = await get_review(fresh, case.review_id)
    finally:
        await fresh.close()
    assert found[0].status == "approved"
    assert found[0].version == 2
    assert len(found[1]) == 2


async def test_duplicate_creation_returns_the_same_case_and_creates_no_second_row(
    connection, created_review_ids
):
    request_id = _request_id()
    first, first_created = await _make_review(connection, created_review_ids, request_id=request_id)
    second, second_created = await _make_review(
        connection, created_review_ids, request_id=request_id
    )
    assert first_created is True
    assert second_created is False
    assert second.review_id == first.review_id

    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT count(*) FROM review_cases WHERE request_id = %s", (request_id,)
        )
        (case_count,) = await cursor.fetchone()
        await cursor.execute(
            "SELECT count(*) FROM review_events WHERE review_id = %s", (first.review_id,)
        )
        (event_count,) = await cursor.fetchone()
    assert case_count == 1
    assert event_count == 1


async def test_concurrent_duplicate_creation_produces_exactly_one_case_and_one_event(
    connection, created_review_ids
):
    # The sequential duplicate-creation test above proves the ON CONFLICT
    # path works when the row already exists at INSERT time. This proves
    # the harder case: two create_review calls racing for the SAME
    # request_id, relying on Postgres's real UNIQUE constraint to
    # serialize them — not just application-level logic.
    request_id = _request_id()
    settings = get_settings()
    conn_a = await connect(settings)
    conn_b = await connect(settings)
    try:
        results = await asyncio.gather(
            create_review(
                conn_a,
                request_id=request_id,
                workflow="structured_only",
                trigger_reason_codes=["specialist_failure"],
                evidence_snapshot={"request_id": request_id},
                evidence_fingerprint="a" * 64,
                previous_review_id=None,
            ),
            create_review(
                conn_b,
                request_id=request_id,
                workflow="structured_only",
                trigger_reason_codes=["specialist_failure"],
                evidence_snapshot={"request_id": request_id},
                evidence_fingerprint="a" * 64,
                previous_review_id=None,
            ),
        )
    finally:
        await conn_a.close()
        await conn_b.close()

    (case_a, created_a), (case_b, created_b) = results
    assert case_a.review_id == case_b.review_id
    assert {created_a, created_b} == {True, False}
    created_review_ids.append(case_a.review_id)

    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT count(*) FROM review_cases WHERE request_id = %s", (request_id,)
        )
        (case_count,) = await cursor.fetchone()
        await cursor.execute(
            "SELECT count(*) FROM review_events WHERE review_id = %s", (case_a.review_id,)
        )
        (event_count,) = await cursor.fetchone()
    assert case_count == 1
    assert event_count == 1


async def test_previous_review_id_must_reference_an_existing_case(connection, created_review_ids):
    fake_id = str(uuid.uuid4())
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        # create_review raises before returning, so _make_review's own
        # created_review_ids.append() is never reached — nothing to clean up.
        await _make_review(connection, created_review_ids, previous_review_id=fake_id)
    assert created_review_ids == []
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT count(*) FROM review_cases WHERE previous_review_id = %s", (fake_id,)
        )
        (count,) = await cursor.fetchone()
    assert count == 0


# --- apply_decision / concurrency / idempotency --------------------------


async def test_valid_decision_transitions_and_records_one_event(connection, created_review_ids):
    case, _ = await _make_review(connection, created_review_ids)
    updated = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.APPROVE,
        reviewer_id="alice",
        reason="looks correct",
    )
    assert updated.status == "approved"
    assert updated.version == case.version + 1

    _, events = await get_review(connection, case.review_id)
    assert [e.event_type for e in events] == [
        ReviewEventType.REVIEW_CREATED,
        ReviewEventType.REVIEW_APPROVED,
    ]
    assert events[1].actor_id == "alice"
    assert events[1].previous_status == "pending"
    assert events[1].new_status == "approved"


async def test_stale_version_retry_is_rejected_and_creates_no_new_event(
    connection, created_review_ids
):
    case, _ = await _make_review(connection, created_review_ids)
    first = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.APPROVE,
        reviewer_id="alice",
        reason=None,
    )
    assert first is not None

    retry = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,  # stale: the case already moved to version 2
        decision=ReviewDecisionType.REJECT,
        reviewer_id="bob",
        reason=None,
    )
    assert retry is None

    _, events = await get_review(connection, case.review_id)
    assert len(events) == 2  # created + the one approval; the stale retry added nothing


async def test_terminal_case_rejects_decision_even_with_the_now_current_version(
    connection, created_review_ids
):
    case, _ = await _make_review(connection, created_review_ids)
    approved = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.APPROVE,
        reviewer_id="alice",
        reason=None,
    )
    # Even the CORRECT current version cannot move a terminal case further —
    # the status='pending' condition is a second, independent guard, not
    # just the version check.
    second_attempt = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=approved.version,
        decision=ReviewDecisionType.REJECT,
        reviewer_id="bob",
        reason=None,
    )
    assert second_attempt is None
    _, events = await get_review(connection, case.review_id)
    assert len(events) == 2


async def test_concurrent_competing_decisions_exactly_one_succeeds(connection, created_review_ids):
    case, _ = await _make_review(connection, created_review_ids)
    settings = get_settings()
    conn_a = await connect(settings)
    conn_b = await connect(settings)
    try:
        results = await asyncio.gather(
            apply_decision(
                conn_a,
                review_id=case.review_id,
                expected_version=case.version,
                decision=ReviewDecisionType.APPROVE,
                reviewer_id="alice",
                reason=None,
            ),
            apply_decision(
                conn_b,
                review_id=case.review_id,
                expected_version=case.version,
                decision=ReviewDecisionType.REJECT,
                reviewer_id="bob",
                reason=None,
            ),
        )
    finally:
        await conn_a.close()
        await conn_b.close()

    successes = [r for r in results if r is not None]
    assert len(successes) == 1

    _, events = await get_review(connection, case.review_id)
    decision_events = [e for e in events if e.event_type != ReviewEventType.REVIEW_CREATED]
    assert len(decision_events) == 1


async def test_apply_decision_unknown_review_id_returns_none_not_an_exception(connection):
    result = await apply_decision(
        connection,
        review_id=str(uuid.uuid4()),
        expected_version=1,
        decision=ReviewDecisionType.APPROVE,
        reviewer_id="alice",
        reason=None,
    )
    assert result is None


# --- snapshot / fingerprint immutability through decisions -----------------


async def test_decision_does_not_alter_the_evidence_snapshot_or_fingerprint(
    connection, created_review_ids
):
    case, _ = await _make_review(connection, created_review_ids)
    updated = await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.REQUEST_REVISION,
        reviewer_id="alice",
        reason="need more evidence",
    )
    assert updated.evidence_snapshot == case.evidence_snapshot
    assert updated.evidence_fingerprint == case.evidence_fingerprint
    assert updated.request_id == case.request_id
    assert updated.workflow == case.workflow
    assert updated.trigger_reason_codes == case.trigger_reason_codes
    assert updated.created_at == case.created_at


# --- get_review / review_exists --------------------------------------------


async def test_get_review_returns_none_for_unknown_id(connection):
    assert await get_review(connection, str(uuid.uuid4())) is None


async def test_review_exists_true_and_false(connection, created_review_ids):
    case, _ = await _make_review(connection, created_review_ids)
    assert await review_exists(connection, case.review_id) is True
    assert await review_exists(connection, str(uuid.uuid4())) is False


async def test_get_review_events_are_ordered_oldest_first(connection, created_review_ids):
    case, _ = await _make_review(connection, created_review_ids)
    await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.REJECT,
        reviewer_id="alice",
        reason=None,
    )
    _, events = await get_review(connection, case.review_id)
    timestamps = [e.created_at for e in events]
    assert timestamps == sorted(timestamps)


# --- list_reviews (queue) ---------------------------------------------------


async def test_queue_is_ordered_oldest_first(connection, created_review_ids):
    request_id = _request_id()
    first, _ = await _make_review(connection, created_review_ids, request_id=f"{request_id}-a")
    second, _ = await _make_review(connection, created_review_ids, request_id=f"{request_id}-b")

    reviews, _ = await list_reviews(connection, status="pending", limit=MAX_REVIEW_QUEUE_LIMIT)
    ids_in_order = [r.review_id for r in reviews]
    assert ids_in_order.index(first.review_id) < ids_in_order.index(second.review_id)


async def test_queue_filters_by_status(connection, created_review_ids):
    case, _ = await _make_review(connection, created_review_ids)
    await apply_decision(
        connection,
        review_id=case.review_id,
        expected_version=case.version,
        decision=ReviewDecisionType.APPROVE,
        reviewer_id="alice",
        reason=None,
    )
    pending, _ = await list_reviews(connection, status="pending", limit=MAX_REVIEW_QUEUE_LIMIT)
    approved, _ = await list_reviews(connection, status="approved", limit=MAX_REVIEW_QUEUE_LIMIT)
    assert case.review_id not in {r.review_id for r in pending}
    assert case.review_id in {r.review_id for r in approved}


async def test_queue_limit_is_clamped_not_rejected(connection, created_review_ids):
    await _make_review(connection, created_review_ids)
    # A limit far beyond MAX_REVIEW_QUEUE_LIMIT must not error and must not
    # be honored literally — it is silently clamped to the maximum.
    reviews, _ = await list_reviews(connection, limit=10_000)
    assert len(reviews) <= MAX_REVIEW_QUEUE_LIMIT


# --- transaction atomicity: event-insertion failure rolls back the write ---
# These exercise the underlying connection.transaction() guarantee directly
# with a deliberately invalid event row (violates review_events' event_type
# CHECK constraint), proving the preceding write in the same transaction is
# never persisted — the same mechanism create_review/apply_decision rely on.


async def test_transaction_rolls_back_case_creation_if_event_insert_fails(connection):
    request_id = _request_id()
    with pytest.raises(psycopg.errors.CheckViolation):
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO review_cases "
                    "(request_id, workflow, trigger_reason_codes, evidence_snapshot, "
                    "evidence_fingerprint) VALUES (%s, %s, %s, %s, %s) RETURNING review_id",
                    (request_id, "structured_only", [], psycopg.types.json.Jsonb({}), "a" * 64),
                )
                (review_id,) = await cursor.fetchone()
                await cursor.execute(
                    "INSERT INTO review_events "
                    "(review_id, event_type, actor_id, actor_type, new_status) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (review_id, "not_a_real_event_type", "system", "system", "pending"),
                )

    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT count(*) FROM review_cases WHERE request_id = %s", (request_id,)
        )
        (count,) = await cursor.fetchone()
    assert count == 0


async def test_transaction_rolls_back_decision_if_event_insert_fails(
    connection, created_review_ids
):
    case, _ = await _make_review(connection, created_review_ids)
    with pytest.raises(psycopg.errors.CheckViolation):
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE review_cases SET status = 'approved', version = version + 1 "
                    "WHERE review_id = %s AND version = %s AND status = 'pending'",
                    (case.review_id, case.version),
                )
                await cursor.execute(
                    "INSERT INTO review_events "
                    "(review_id, event_type, actor_id, actor_type, new_status) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (case.review_id, "not_a_real_event_type", "alice", "reviewer", "approved"),
                )

    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT status, version FROM review_cases WHERE review_id = %s", (case.review_id,)
        )
        status, version = await cursor.fetchone()
    assert status == "pending"
    assert version == case.version
