# Phase 11 — Human-in-the-loop review & audit workflow

A small, explicit PostgreSQL-persisted review state machine sitting entirely
**after** Phase 10's validation boundary. The goal is not to make CareFlow AI
more autonomous — it is to make uncertain, incomplete, or explicitly
flagged Phase 10 outputs reviewable by a human, with a durable, append-only
audit trail of what was reviewed and what was decided. Phase 10
(`POST /multi-agent`, commit `66551c3`) is untouched and remains frozen.

## Architecture

```
   ReviewableQueryRequest
            │
            ▼
   Phase 10 graph (unchanged)      build_multi_agent_graph(settings).ainvoke(state)
            │
            ▼
   MultiAgentResponse              build_response() — shared with POST /multi-agent
            │
            ▼
   review-trigger policy           determine_review_requirement()
            │
    ┌───────┴────────┐
    ▼                ▼
no review          review required
    │                │
    │                ▼
    │         create_review()  →  review_cases row (status=pending)
    │                            +  review_created event
    │                │
    ▼                ▼
       ReviewableQueryResponse
       (Phase 10 result + review_required/review_reason_codes/review_id/review_status)


Later, asynchronously:

   POST /reviews/{review_id}/decision
            │
            ▼
   optimistic-lock CAS UPDATE  (status='pending' AND version=expected_version)
            │
     ┌──────┴──────┐
     ▼             ▼
  success        conflict (404/409)
     │
     ▼
   INSERT decision event  — same transaction, atomic with the UPDATE
```

## Why a PostgreSQL state machine, not LangGraph interrupt/checkpointing

Both options were evaluated against the actual repository, not chosen by
default. `langgraph-checkpoint==4.2.0` is installed, but only as a
transitive dependency of `langgraph` itself — it is never imported anywhere
in this codebase, both Phase 9's and Phase 10's graphs are compiled with no
checkpointer, and their own docstrings say so explicitly.
**`langgraph-checkpoint-postgres`** — the package that would make an
`interrupt()` genuinely durable across a FastAPI restart or across separate
HTTP requests — is **not installed**, and adding it would be a new
dependency purely to support a feature this phase can get without one.

Beyond the dependency question: a durable human review can span hours or
days, which is not what `interrupt()`/`MemorySaver` are built for (an
in-process, single-run pause); LangGraph's checkpoint format is designed for
resuming *execution*, not for a clean, queryable audit trail; concurrency
between two reviewers acting on the same paused node is not something
LangGraph solves for you; and introducing a checkpointer would compromise
Phase 10's own documented, tested invariant — "no checkpointing... every
`POST /multi-agent` call is fully independent" — on a phase now frozen at
commit `66551c3`.

A hand-written state machine, by contrast, reuses exactly the primitives
already proven across Phases 8–10: `psycopg` async connections, the
migration system (`schema_migrations`, checksum-locked, sequential `.sql`
files), parameterized-SQL-only repository functions, and Pydantic
`StrictModel` contracts. No new dependency. The machine itself is small
enough (4 states, 3 transitions) that a workflow library would be
overhead, not simplification.

## Phase 10 boundary

Phase 11 never modifies Phase 10. `POST /multi-agent`'s own private
response-building logic was extracted into a public `build_response()` in
`backend/app/agents/graph.py` — a pure rename/relocation, verified via the
full Phase 1–10 regression suite (433 tests, identical count before and
after) to be byte-for-byte behavior-preserving — so `POST /reviewable-query`
builds the *exact same* `MultiAgentResponse` shape without a second,
divergence-prone copy of that translation. `POST /query`, `POST /orchestrate`,
and `POST /multi-agent` are all regression-tested unchanged.

## Review-trigger policy

Deterministic, no LLM, derived directly from `MultiAgentResponse.validation`
— the same typed output Phase 10's own evidence validator already produces:

```
review_required = explicit_review_requested OR len(validation.issues) > 0
```

`validation.issues` is non-empty exactly when Phase 10's `validate_node`
found something structurally off (a missing result, a policy success with
no citations, a source/domain mismatch, a genuine partial-specialist-failure,
or a policy/structured shape leak). This already subsumes
`validation.passed == False`, and correctly does **not** over-trigger on a
combined workflow where one side cleanly abstains — `validate_node`
deliberately never records a clean abstention as an issue, since that is
the system working correctly.

| Case | Review? |
|---|---|
| Validation structural issue | Yes |
| Partial specialist failure (status still OK) | Yes |
| Source/provenance mismatch | Yes |
| Explicit caller request | Yes |
| Clean policy abstention | No |
| Clean unknown patient/beneficiary abstention | No |
| Ordinary unsupported/unrelated request | No |
| Combined workflow, one side cleanly abstains, no issue | No |
| Infrastructure failure (`GenerationError`, any exception) | No review case — the request never reached a final `MultiAgentResponse`; the error propagates exactly as `POST /multi-agent` already does |

Reason codes reuse `ValidationIssueCode` values directly — no parallel
vocabulary — plus one Phase 11-specific addition, `explicit_review_requested`.

## Review states and transitions

Four states, deliberately the smallest useful machine — no `IN_REVIEW`
"claim" step (optimistic locking already gives the needed protection without
it), no `CANCELLED` (no requirement calls for it), and `NOT_REQUIRED` is not
a persisted state at all — when review isn't required, no `review_cases`
row is ever created.

```
PENDING -> APPROVED             (terminal)
PENDING -> REJECTED             (terminal)
PENDING -> REVISION_REQUESTED   (terminal)
```

All three targets are terminal — nothing in Phase 11 ever transitions out of
them, enforced both by the CAS `UPDATE ... WHERE status = 'pending'`
condition and by a dedicated test that a *correct* current version still
cannot move a terminal case further.

## Human decision semantics

`APPROVE`, `REJECT`, `REQUEST_REVISION` — all three carry genuinely distinct
meaning. **`APPROVE` means only that the reviewer accepted the CareFlow
output for this application's review workflow.** It is not, and must never
be represented as, Medicare coverage approval, claim approval, patient
eligibility, clinical correctness, or medical necessity — the same
discipline Phase 10 already applies to its own `Status`/`WorkflowDecision`
vocabulary.

`REQUEST_REVISION` is terminal for the review case it's recorded on — no
autonomous retry, no automatic Phase 10 re-invocation. A follow-up attempt
is a distinct, manually triggered `POST /reviewable-query` call; the caller
may optionally supply `previous_review_id` to record the link. It is never
inferred, and the "most recent review" is never guessed at — a
caller-supplied `previous_review_id` that doesn't exist is rejected outright
(422), not silently ignored.

## Evidence snapshot and fingerprint

`evidence_snapshot JSONB` is exactly `MultiAgentResponse.model_dump(mode="json")`
— the same bounded JSON any `/multi-agent` or `/reviewable-query` caller
already receives (request_id, workflow, status, policy answer + citations,
structured route + results, validation, abstention_reason, error). No raw
source files, settings, credentials, or internal Python state can appear in
it, because none of those are fields on `MultiAgentResponse`. A review must
show exactly what was reviewed even if underlying retrieval or structured
data changes later, so the case stores a real copy, not a live reference.

`evidence_fingerprint TEXT` is a SHA-256 over a deterministic canonical JSON
serialization (`sort_keys=True`, compact separators) of that same snapshot —
reusing `ingestion.models.digest()`, the exact canonicalization already
established for Phase 1–8 content-addressing, rather than a second,
incompatible implementation. **This provides snapshot-integrity comparison
and reproducibility — it is not cryptographic tamper-proofing, and this
codebase makes no claim that the database is tamper-proof or
blockchain-backed.** Neither `evidence_snapshot` nor `evidence_fingerprint`
can ever be modified after creation — no UPDATE path in the repository
touches them; a decision transition may only change `status`, `version`,
and `updated_at`. Verified directly: a decision transition leaves both
fields byte-identical, tested at both the repository and API layers.

## Append-only audit history

`review_events` is an **application-level** audit history: no `UPDATE` or
`DELETE` repository method exists for it anywhere in this codebase. That is
an honest, accurate description — the database itself does not forbid a
privileged administrator from editing rows directly, and this project makes
no claim of database-enforced or cryptographic immutability. Every state
transition inserts exactly one event, atomically with the state change
(same transaction — if the event insert fails, the whole write rolls back,
verified directly by deliberately violating the event's own `CHECK`
constraint mid-transaction and confirming the preceding write never
persists).

## Optimistic concurrency

A decision is one compare-and-swap statement:

```sql
UPDATE review_cases
SET status = %s, version = version + 1, updated_at = now()
WHERE review_id = %s AND version = %s AND status = 'pending'
RETURNING *;
```

Zero rows affected means either a stale `version` or a case that already
left `pending` — both surface as `409 Conflict`, with the *current* row
returned so the caller can see what actually happened.
`SELECT ... FOR UPDATE` was considered and rejected: it would require
holding a transaction open across the network round-trip to a human
decision, the wrong shape for a stateless per-request API. Verified with
real concurrent decisions from two separate connections via
`asyncio.gather` — exactly one succeeds, exactly one event is recorded, the
loser gets `None`/`409` and never overwrites the winner.

## Idempotent creation

`review_cases.request_id` is `UNIQUE`. Creation uses
`INSERT ... ON CONFLICT (request_id) DO NOTHING RETURNING *`, falling back
to a `SELECT` on conflict — the exact idiom already used in
`ingestion/cms_synpuf/loader.py`. Verified both sequentially and under real
concurrency (two `create_review` calls racing for the same `request_id` via
`asyncio.gather`): exactly one row, exactly one `review_created` event,
serialized correctly by Postgres's own `UNIQUE` constraint, not just
application logic.

## Decision retry semantics

Retries are **safe, not perfectly idempotent**: a retried decision after it
already succeeded returns `409 Conflict` (the case is no longer `pending`),
not a repeated `200`. This is a deliberate v1 scope decision — a true
idempotent-retry guarantee would need a client-supplied idempotency key,
which was evaluated and deferred rather than built preemptively.

## A real durability bug found and fixed during implementation

`POST /reviews/{review_id}/decision` calls `review_exists()` (a bare,
untransacted `SELECT`) before `apply_decision()`. Because
`psycopg.AsyncConnection` defaults to `autocommit=False`, that `SELECT`
silently opens an ambient transaction on the connection; `apply_decision`'s
own `connection.transaction()` then becomes a **nested SAVEPOINT** instead
of a real top-level transaction — releasing it makes the write visible only
within that same still-open connection. Closing the connection afterward
silently discarded the write entirely, even though the decision endpoint's
own HTTP response looked completely correct. This was invisible to every
early test because they all read back from the *same* connection that did
the write. It surfaced only via a live smoke test that read back from a
**fresh** connection between two sequential API calls — a stale-version
retry that should have been rejected instead silently succeeded and
overwrote what looked like a completed decision.

Root-caused against psycopg3's actual transaction/savepoint nesting
behavior (verified with an isolated probe, not assumed) and fixed at the
repository layer: `create_review`/`apply_decision` now call an explicit
`connection.commit()` after their `transaction()` block, so the durability
guarantee holds regardless of what a caller already did on the connection.
Two regression tests (`test_create_review_is_durable_after_a_prior_read...`,
`test_apply_decision_is_durable_after_a_prior_read...`) now guard this
specifically, reading back from a genuinely separate connection.

## Reviewer identity

**No authentication, authorization, or reviewer-account system exists
anywhere in this repository**, confirmed by direct search before Phase 11
began — no `class Auth/User/Session/JWT`, no `fastapi.security` import,
nothing. Phase 11 does not invent one. `reviewer_id` is a required
request-body field (`min_length=1, max_length=100`) on the decision
endpoint — a **caller-asserted development/demo label, not an authenticated
identity**. It is not authorization, not RBAC, not verified reviewer
identity. `review_events.actor_type` distinguishes `system` (automatic
creation) from `reviewer` (a human decision) so the distinction is
structurally visible in the audit trail even without real auth. Full
authentication is explicitly out of scope for this phase.

## API

Purely additive. `POST /query`, `POST /orchestrate`, and `POST /multi-agent`
are all unchanged, regression-tested by dedicated tests.

- **`POST /reviewable-query`** — everything `MultiAgentRequest` accepts,
  plus optional `explicit_review_requested` and `previous_review_id`.
  Returns the exact `MultiAgentResponse` shape plus `review_required`,
  `review_reason_codes`, `review_id`, `review_status` (all `false`/`[]`/`null`
  when no review was needed). `200` on success (Phase 10's own 502/503/504
  pass through unchanged for infrastructure failures); `422` for a
  contradictory request or an unknown `previous_review_id`.
- **`POST /reviews/{review_id}/decision`** — `reviewer_id`, `decision`
  (`approve`/`reject`/`request_revision`), optional `reason`,
  `expected_version`. `200` on success; `404` unknown `review_id`; `409`
  stale version or already-terminal; `422` invalid body or a malformed
  (non-UUID-shaped) `review_id`.
- **`GET /reviews/{review_id}`** — the case plus its full event history,
  ordered `created_at ASC, event_id ASC`. `200` or `404`/`422`.
- **`GET /reviews`** — bounded, paginated queue: `status` filter, `limit`
  (default 20, max 100, rejected with `422` outside that range — not
  silently clamped at the API layer, though the repository clamps
  defensively too, mirroring Phase 10's `MAX_STRUCTURED_TOOL_CALLS`
  two-layer pattern), keyset `cursor`. FIFO — `created_at ASC, review_id ASC`
  (oldest pending first). No unbounded listing endpoint exists.

`POST /multi-agent` itself was deliberately **not** changed to
auto-create reviews — that would add a hidden database side effect to a
previously side-effect-free, now-frozen endpoint's contract.

## Observability

Structured JSON logs, matching the exact convention already established in
Phase 10 (`_log_event`-style local helper, no shared logging utility exists
anywhere in this codebase): `request_id`/`review_id`, `action`,
`previous_status`/`new_status`, `reviewer_id`, `duration_ms`, `result`,
`error_category`. **Verified directly against real log output** — a live
decision was sent with a deliberately sensitive `reason` string, and
confirmed absent from every log line, along with `evidence_snapshot`,
policy answer text, citation excerpts, and structured record contents. Only
ids, status, counts, and reason codes are ever logged.

## Security

Every review-table query is parameterized (`%s` placeholders) — no
string-built SQL. Verified directly, not just by code inspection: a decision
was submitted with a `reviewer_id` shaped like a SQL injection payload
(`"alice'; DROP TABLE review_cases; --"`) and a `reason` containing a
`DELETE FROM review_events` payload; both round-tripped as inert stored
data and the tables were untouched.

## Synthetic-data boundary

Underlying data remains synthetic DE-SynPUF/Synthea FHIR (Phase 8) — this
project makes **no HIPAA-compliance claim and no production-PHI-safety
claim** anywhere. `evidence_snapshot` duplicates only what a
`/reviewable-query` caller already receives in the response body — no new
data exposure. Review/audit tables are a wholly separate domain from
`synpuf_*`/`fhir_*`/`ingestion_runs`/`source_files` (migration
`0004_review_workflow.sql`, confirmed as the next sequential migration
number before implementation, not assumed).

## Clinical safety boundary

No component in Phase 11 performs or represents diagnosis, treatment,
coverage, claim, or eligibility approval, or medical necessity
determination. A reviewer decision is an application-workflow acceptance
signal only — see "Human decision semantics" above. The system remains an
information/evidence workflow, not clinical decision support.

## Testing

- `tests/test_review_models.py` (40) — enums, transition rules, snapshot/
  fingerprint helpers (determinism, key-order insensitivity, content
  sensitivity), request/response schema validation, UUID/enum
  before-validators.
- `tests/test_review_policy.py` (11) — every review-trigger case in the
  table above.
- `tests/test_review_repository.py` (21) — creation, idempotency
  (sequential and concurrent), decision transitions, stale-version and
  terminal-state rejection, real concurrent decisions, transaction
  atomicity (event-insert failure rolls back the write), snapshot/
  fingerprint immutability, queue ordering/filtering/limit clamping, and
  the two durability regression tests.
- `tests/test_review_service.py` (8) — wiring Phase 10's graph + policy +
  repository, snapshot correctness, `previous_review_id` linking and
  rejection, infrastructure-failure propagation with no review created.
- `tests/test_review_api.py` (25) — full HTTP-semantics matrix, review
  queue, SQL-injection-shaped input, malformed request bodies, and
  dedicated `POST /query`/`POST /orchestrate`/`POST /multi-agent`
  contract-unchanged regressions.

Live tests are gated on `CAREFLOW_REVIEW_INTEGRATION=1`, matching the
established convention. Tests clean up their own `review_cases`/
`review_events` rows (deleting events for all tracked ids, then cases in
reverse creation order to respect the `previous_review_id` foreign key) —
a deliberate departure from `ingestion_runs`' accumulate-forever test
convention, since review/audit tables are operational workflow records, not
immutable source provenance.

## Known limitations

- No real authentication — `reviewer_id` is self-asserted, documented
  everywhere as non-authoritative.
- Decision retries are safe, not perfectly idempotent (see above); a client
  idempotency-key mechanism was evaluated and deliberately deferred.
- No `IN_REVIEW`/"claim" step and no `CANCELLED` state — evaluated and
  omitted as unnecessary for the smallest useful machine; could be added
  later if a real multi-reviewer workflow need materializes.
- `evidence_fingerprint` provides integrity comparison and reproducibility,
  not cryptographic tamper-proofing.
- `trigger_reason_codes` is a `TEXT[]` column rather than a fully
  normalized join table — a deliberate simplicity choice for a small,
  bounded value set.
- `REQUEST_REVISION` never triggers an automatic Phase 10 re-run — by
  design, not as a missing feature.

## Reproduction

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q                                            # unit tests
CAREFLOW_REVIEW_INTEGRATION=1 \
  .venv/bin/pytest -q tests/test_review_*.py                    # live Phase 11 tests
CAREFLOW_API_URL=http://localhost:18000 \
  CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 CAREFLOW_RAG_INTEGRATION=1 \
  CAREFLOW_HYBRID_INTEGRATION=1 CAREFLOW_RERANK_INTEGRATION=1 CAREFLOW_STRUCTURED_INTEGRATION=1 \
  CAREFLOW_ORCHESTRATION_INTEGRATION=1 CAREFLOW_MULTI_AGENT_INTEGRATION=1 \
  CAREFLOW_REVIEW_INTEGRATION=1 \
  .venv/bin/pytest -q                                            # full Phase 1-11 live suite
```
