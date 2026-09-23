import os
import uuid

import pytest
from app.core.config import get_settings
from app.db.connection import connect
from app.main import app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_REVIEW_INTEGRATION") != "1",
    reason="Set CAREFLOW_REVIEW_INTEGRATION=1 with Compose running and the 0004 migration "
    "already applied to exercise POST /reviewable-query and the review APIs end to end",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"

PARTIAL_FAILURE_BODY = {
    "question": "x",
    "workflow": "structured_only",
    "structured_route": "synpuf",
    "tools": [
        {"tool": "get_beneficiary_summary", "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID}},
        {"tool": "not_a_real_tool", "arguments": {}},
    ],
}


@pytest.fixture
async def created_review_ids():
    ids: list[str] = []
    yield ids
    if ids:
        conn = await connect(get_settings())
        try:
            async with conn.cursor() as cursor:
                for review_id in ids:
                    await cursor.execute(
                        "DELETE FROM review_events WHERE review_id = %s", (review_id,)
                    )
                for review_id in reversed(ids):
                    await cursor.execute(
                        "DELETE FROM review_cases WHERE review_id = %s", (review_id,)
                    )
            await conn.commit()
        finally:
            await conn.close()


# --- POST /reviewable-query: validation -----------------------------------


def test_blank_question_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/reviewable-query", json={"question": ""})
    assert response.status_code == 422


def test_unknown_extra_field_is_rejected():
    with TestClient(app) as client:
        response = client.post("/reviewable-query", json={"question": "x", "not_a_real_field": 1})
    assert response.status_code == 422


def test_more_than_five_tools_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/reviewable-query",
            json={
                "question": "x",
                "structured_route": "synpuf",
                "tools": [{"tool": "get_beneficiary_summary", "arguments": {}}] * 6,
            },
        )
    assert response.status_code == 422


# --- POST /reviewable-query: review-trigger behavior -----------------------


def test_unrelated_question_does_not_trigger_a_review():
    with TestClient(app) as client:
        response = client.post("/reviewable-query", json={"question": "what is the weather"})
    assert response.status_code == 200
    body = response.json()
    assert body["review_required"] is False
    assert body["review_reason_codes"] == []
    assert body["review_id"] is None
    assert body["review_status"] is None


def test_partial_failure_triggers_a_review(created_review_ids):
    with TestClient(app) as client:
        response = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["review_required"] is True
    assert "specialist_failure" in body["review_reason_codes"]
    assert body["review_id"] is not None
    assert body["review_status"] == "pending"
    created_review_ids.append(body["review_id"])


def test_explicit_review_requested_triggers_a_review_even_when_clean(created_review_ids):
    with TestClient(app) as client:
        response = client.post(
            "/reviewable-query",
            json={
                "question": "x",
                "workflow": "structured_only",
                "structured_route": "synpuf",
                "tools": [
                    {
                        "tool": "get_beneficiary_summary",
                        "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
                    }
                ],
                "explicit_review_requested": True,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["review_required"] is True
    assert body["review_reason_codes"] == ["explicit_review_requested"]
    created_review_ids.append(body["review_id"])


def test_unknown_previous_review_id_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/reviewable-query",
            json={**PARTIAL_FAILURE_BODY, "previous_review_id": str(uuid.uuid4())},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_previous_review_id"


def test_valid_previous_review_id_is_linked(created_review_ids):
    with TestClient(app) as client:
        first = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        first_review_id = first.json()["review_id"]
        created_review_ids.append(first_review_id)

        second = client.post(
            "/reviewable-query",
            json={**PARTIAL_FAILURE_BODY, "previous_review_id": first_review_id},
        )
        second_review_id = second.json()["review_id"]
        created_review_ids.append(second_review_id)

        detail = client.get(f"/reviews/{second_review_id}")
    assert detail.json()["case"]["previous_review_id"] == first_review_id


# --- POST /reviews/{review_id}/decision ------------------------------------


def test_decision_on_unknown_review_is_404():
    with TestClient(app) as client:
        response = client.post(
            f"/reviews/{uuid.uuid4()}/decision",
            json={"reviewer_id": "alice", "decision": "approve", "expected_version": 1},
        )
    assert response.status_code == 404


def test_decision_with_malformed_review_id_is_422():
    with TestClient(app) as client:
        response = client.post(
            "/reviews/not-a-uuid/decision",
            json={"reviewer_id": "alice", "decision": "approve", "expected_version": 1},
        )
    assert response.status_code == 422


def test_decision_with_invalid_decision_value_is_422(created_review_ids):
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        response = client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "alice", "decision": "not_a_real_decision", "expected_version": 1},
        )
    assert response.status_code == 422


def test_reviewer_id_with_sql_injection_shaped_content_is_stored_verbatim_not_executed(
    created_review_ids,
):
    # Every query in the repository layer is parameterized (%s placeholders,
    # never string-built SQL) — a hostile reviewer_id/reason value must be
    # treated as inert data, never executed. Confirms the endpoint doesn't
    # crash and the value round-trips exactly, rather than being interpreted.
    hostile = "alice'; DROP TABLE review_cases; --"
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        response = client.post(
            f"/reviews/{review_id}/decision",
            json={
                "reviewer_id": hostile,
                "decision": "approve",
                "expected_version": 1,
                "reason": "'; DELETE FROM review_events WHERE '1'='1",
            },
        )
        assert response.status_code == 200

        # review_cases must still exist and be queryable — a real injection
        # would have dropped the table.
        still_there = client.get(f"/reviews/{review_id}")
    assert still_there.status_code == 200
    events = still_there.json()["events"]
    decision_event = [e for e in events if e["event_type"] == "review_approved"][0]
    assert decision_event["actor_id"] == hostile


def test_malformed_json_body_is_a_validation_error(created_review_ids):
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        # missing required expected_version
        response = client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "alice", "decision": "approve"},
        )
    assert response.status_code == 422


def test_valid_decision_transitions_and_is_durable(created_review_ids):
    # Exercises the exact real bug caught during implementation: a fresh
    # GET (a bare read) happens on a different connection than the decision
    # write inside the API handler. Any regression of the repository's
    # explicit commit() would make this fail intermittently or show the
    # case still "pending" on the very next read.
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        decision = client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "alice", "decision": "approve", "expected_version": 1},
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"
        assert decision.json()["version"] == 2

        fresh_get = client.get(f"/reviews/{review_id}")
    assert fresh_get.status_code == 200
    assert fresh_get.json()["case"]["status"] == "approved"
    assert fresh_get.json()["case"]["version"] == 2
    assert [e["event_type"] for e in fresh_get.json()["events"]] == [
        "review_created",
        "review_approved",
    ]


def test_stale_version_decision_is_409(created_review_ids):
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        first = client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "alice", "decision": "approve", "expected_version": 1},
        )
        assert first.status_code == 200

        retry = client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "bob", "decision": "reject", "expected_version": 1},
        )
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "version_conflict"
    assert retry.json()["review"]["status"] == "approved"


def test_terminal_case_rejects_further_decisions_with_409(created_review_ids):
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        first = client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "alice", "decision": "approve", "expected_version": 1},
        )
        current_version = first.json()["version"]

        second = client.post(
            f"/reviews/{review_id}/decision",
            json={
                "reviewer_id": "bob",
                "decision": "reject",
                "expected_version": current_version,
            },
        )
    assert second.status_code == 409


# --- GET /reviews/{review_id} -----------------------------------------------


def test_get_unknown_review_is_404():
    with TestClient(app) as client:
        response = client.get(f"/reviews/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_malformed_review_id_is_422():
    with TestClient(app) as client:
        response = client.get("/reviews/not-a-uuid")
    assert response.status_code == 422


# --- GET /reviews (queue) ---------------------------------------------------


def test_queue_filters_by_status(created_review_ids):
    with TestClient(app) as client:
        created = client.post("/reviewable-query", json=PARTIAL_FAILURE_BODY)
        review_id = created.json()["review_id"]
        created_review_ids.append(review_id)

        pending = client.get("/reviews", params={"status": "pending"})
        assert review_id in {r["review_id"] for r in pending.json()["reviews"]}

        client.post(
            f"/reviews/{review_id}/decision",
            json={"reviewer_id": "alice", "decision": "approve", "expected_version": 1},
        )

        pending_after = client.get("/reviews", params={"status": "pending"})
        approved_after = client.get("/reviews", params={"status": "approved"})
    assert review_id not in {r["review_id"] for r in pending_after.json()["reviews"]}
    assert review_id in {r["review_id"] for r in approved_after.json()["reviews"]}


def test_queue_limit_over_max_is_a_validation_error():
    with TestClient(app) as client:
        response = client.get("/reviews", params={"limit": 101})
    assert response.status_code == 422


def test_queue_limit_below_one_is_a_validation_error():
    with TestClient(app) as client:
        response = client.get("/reviews", params={"limit": 0})
    assert response.status_code == 422


def test_queue_with_no_reviews_is_still_200():
    with TestClient(app) as client:
        response = client.get("/reviews", params={"status": "pending", "limit": 1})
    assert response.status_code == 200
    assert isinstance(response.json()["reviews"], list)


# --- regression: existing endpoints unchanged -------------------------------


def test_existing_query_endpoint_contract_is_unchanged():
    with TestClient(app) as client:
        response = client.post("/query", json={"question": "Does Medicare cover hospital beds?"})
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body and "citations" in body
    assert "review_required" not in body


def test_existing_orchestrate_endpoint_contract_is_unchanged():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "what is the weather"})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "abstain"
    assert "review_required" not in body


def test_existing_multi_agent_endpoint_contract_is_unchanged():
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={"question": "what is the weather"})
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "abstain"
    assert "review_required" not in body
