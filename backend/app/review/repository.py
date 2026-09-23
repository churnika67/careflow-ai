"""Parameterized, transaction-safe access to review_cases/review_events.

Every write is exactly one `async with connection.transaction():` block
(commit-on-success, rollback-on-exception): review creation is one INSERT
into review_cases plus one INSERT into review_events, atomically; a
reviewer decision is one version/status-checked UPDATE plus one INSERT,
atomically. If the event insert ever fails, the whole block raises and
psycopg3 rolls back the preceding write automatically — no manual rollback
logic is needed.

Deliberately `connection.transaction()`, not the bare `async with
connection:` used by ingestion/cms_synpuf/loader.py — that pattern commits
*and closes* the connection on exit (verified against psycopg3's own
AsyncConnection.__aexit__), which is correct for a one-shot batch script
that owns its connection's entire lifecycle, but wrong here: repository
functions receive a connection the caller intends to keep using for further
calls in the same request (e.g. get_review then apply_decision).
connection.transaction() scopes only the transaction, never the connection.

No UPDATE or DELETE method exists anywhere in this module for review_events.
"Append-only" here is an application-level guarantee enforced by never
writing such a method — not a database-level restriction, and not a claim
that the rows are tamper-proof."""

import base64
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.review.models import (
    MAX_REVIEW_QUEUE_LIMIT,
    ActorType,
    ReviewCase,
    ReviewDecisionType,
    ReviewEvent,
    ReviewEventType,
    ReviewStatus,
    event_type_for_transition,
    target_status_for,
)


def _encode_cursor(created_at: datetime, review_id: str) -> str:
    raw = f"{created_at.isoformat()}|{review_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    created_at_str, review_id = raw.split("|", 1)
    return datetime.fromisoformat(created_at_str), review_id


async def review_exists(connection: psycopg.AsyncConnection, review_id: str) -> bool:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT 1 FROM review_cases WHERE review_id = %s", (review_id,))
        return await cursor.fetchone() is not None


async def create_review(
    connection: psycopg.AsyncConnection,
    *,
    request_id: str,
    workflow: str,
    trigger_reason_codes: list[str],
    evidence_snapshot: dict,
    evidence_fingerprint: str,
    previous_review_id: str | None,
) -> tuple[ReviewCase, bool]:
    """Idempotent on request_id: if a review already exists for this
    request_id, returns it unchanged with created=False — no second row, no
    second REVIEW_CREATED event.

    The explicit connection.commit() after the transaction() block is
    required, not decorative: connection.transaction() only commits for
    real when it is the FIRST statement on a connection with no ambient
    transaction already open. If a caller (e.g. an API handler) has already
    run any other statement on this same connection first, autocommit=False
    means an ambient transaction is already open, and connection.transaction()
    instead opens a SAVEPOINT — releasing it on success makes the write
    visible only within that same still-open, still-uncommitted ambient
    transaction. Closing such a connection without an explicit commit()
    silently discards the write. Verified empirically: a first draft without
    this commit() passed every test that reused one connection throughout,
    but silently lost writes the moment an API handler read before writing
    on the same connection — caught via a live smoke test reading back from
    a fresh connection, not from unit tests alone."""
    async with connection.transaction():
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "INSERT INTO review_cases "
                "(request_id, workflow, trigger_reason_codes, evidence_snapshot, "
                "evidence_fingerprint, previous_review_id) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (request_id) DO NOTHING "
                "RETURNING *",
                (
                    request_id,
                    workflow,
                    trigger_reason_codes,
                    Jsonb(evidence_snapshot),
                    evidence_fingerprint,
                    previous_review_id,
                ),
            )
            row = await cursor.fetchone()
            if row is not None:
                await cursor.execute(
                    "INSERT INTO review_events "
                    "(review_id, event_type, actor_id, actor_type, previous_status, "
                    "new_status, reason, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        row["review_id"],
                        ReviewEventType.REVIEW_CREATED.value,
                        "system",
                        ActorType.SYSTEM.value,
                        None,
                        ReviewStatus.PENDING.value,
                        None,
                        None,
                    ),
                )
    if row is not None:
        await connection.commit()
        return ReviewCase(**row), True

    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute("SELECT * FROM review_cases WHERE request_id = %s", (request_id,))
        existing = await cursor.fetchone()
    return ReviewCase(**existing), False


async def apply_decision(
    connection: psycopg.AsyncConnection,
    *,
    review_id: str,
    expected_version: int,
    decision: ReviewDecisionType,
    reviewer_id: str,
    reason: str | None,
) -> ReviewCase | None:
    """Returns the updated case on success, or None if the compare-and-swap
    condition failed (stale version, or the case already left 'pending').
    The caller is responsible for distinguishing "unknown review_id" from
    "conflict" via review_exists(), since a 0-row UPDATE can't tell them
    apart on its own. Never inserts an event on the conflict path.

    See create_review's docstring for why the explicit connection.commit()
    after the transaction() block is required, not decorative — the same
    ambient-transaction/savepoint risk applies here whenever a caller has
    already run a statement (e.g. review_exists()) on this connection
    first."""
    new_status = target_status_for(decision)
    event_type = event_type_for_transition(new_status)
    async with connection.transaction():
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "UPDATE review_cases "
                "SET status = %s, version = version + 1, updated_at = now() "
                "WHERE review_id = %s AND version = %s AND status = %s "
                "RETURNING *",
                (new_status.value, review_id, expected_version, ReviewStatus.PENDING.value),
            )
            row = await cursor.fetchone()
            if row is not None:
                await cursor.execute(
                    "INSERT INTO review_events "
                    "(review_id, event_type, actor_id, actor_type, previous_status, "
                    "new_status, reason) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        review_id,
                        event_type.value,
                        reviewer_id,
                        ActorType.REVIEWER.value,
                        ReviewStatus.PENDING.value,
                        new_status.value,
                        reason,
                    ),
                )
    if row is None:
        return None
    await connection.commit()
    return ReviewCase(**row)


async def get_review(
    connection: psycopg.AsyncConnection, review_id: str
) -> tuple[ReviewCase, list[ReviewEvent]] | None:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute("SELECT * FROM review_cases WHERE review_id = %s", (review_id,))
        case_row = await cursor.fetchone()
        if case_row is None:
            return None
        await cursor.execute(
            "SELECT * FROM review_events WHERE review_id = %s "
            "ORDER BY created_at ASC, event_id ASC",
            (review_id,),
        )
        event_rows = await cursor.fetchall()
    return ReviewCase(**case_row), [ReviewEvent(**row) for row in event_rows]


async def list_reviews(
    connection: psycopg.AsyncConnection,
    *,
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[ReviewCase], str | None]:
    """FIFO: created_at ASC, review_id ASC (oldest pending first). Fetches
    one extra row to determine whether a next page exists, without an
    unbounded COUNT(*). `status`/`cursor` values are always passed as
    parameters, never interpolated into the SQL text — only the fixed
    WHERE-clause fragments themselves are assembled conditionally."""
    bounded_limit = min(max(limit, 1), MAX_REVIEW_QUEUE_LIMIT)

    conditions: list[str] = []
    params: list[object] = []
    if status is not None:
        conditions.append("status = %s")
        params.append(status)
    if cursor is not None:
        cursor_created_at, cursor_review_id = _decode_cursor(cursor)
        conditions.append("(created_at, review_id) > (%s, %s)")
        params.extend([cursor_created_at, cursor_review_id])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(bounded_limit + 1)

    async with connection.cursor(row_factory=dict_row) as db_cursor:
        await db_cursor.execute(
            f"SELECT * FROM review_cases {where_clause} "
            "ORDER BY created_at ASC, review_id ASC LIMIT %s",
            params,
        )
        rows = await db_cursor.fetchall()

    has_more = len(rows) > bounded_limit
    page_rows = rows[:bounded_limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last["created_at"], str(last["review_id"]))
    return [ReviewCase(**row) for row in page_rows], next_cursor
