# Phase 10 — Multi-agent architecture

A small, bounded multi-agent graph coordinating Phase 9's policy RAG and a
new tool-using structured specialist, with a single deterministic validator
as the only place final status/abstention/error is decided. Zero new LLM
reasoning paths. No planner/executor loop, no autonomous retry, no
checkpointing/memory/persistence, no human-in-the-loop, no agent-to-agent
free-form chat.

## Purpose

Phase 9 gave CareFlow AI one router decision → one downstream action → one
response. Real questions sometimes span both information systems at once —
"What does Medicare policy say about hospital beds, and what hospital-bed
information exists for this patient?" Phase 9's router can only pick one
route per request. Phase 10 adds the smallest structure that can honestly
answer a question spanning both systems: run both capabilities, then
validate and report each independently — never merged into one claim.

## Why multi-agent (not one bigger router)

A single node that both queries policy and dispatches tools would have to
serialize two independent, differently-shaped, differently-failing
operations and reconcile their status by hand inside one function. Splitting
into a supervisor (routing only), a reused policy node, a bounded structured
specialist, and a dedicated validator keeps each piece's permissions and
failure modes independently testable, and lets the two evidence-gathering
steps run concurrently when a request genuinely needs both — verified safe
via LangGraph's real fan-out/fan-in semantics (see "Graph architecture"
below), not assumed.

## Agents

| Name | Role | LLM? |
|---|---|---|
| Supervisor | bounded workflow coordinator — resolves `WorkflowDecision` only | No |
| Policy node | reused Phase 9/4 RAG capability, unchanged | Only inside Phase 4's own `GenerationProvider`, already verified in Phases 1–9 |
| Structured specialist | bounded tool-using agent — executes 1–5 Phase 9 tools | No |
| Evidence validator | deterministic guardrail — sole owner of final status | No |

**Zero new LLM reasoning paths** in Phase 10: no LLM-based supervisor,
tool-selection, validation, or summarization. The existing policy pipeline's
own generation call is unchanged from Phase 9 — "zero LLM in Phase 10" means
no *new* one, not that RAG generation stopped existing.

## Agent contracts

**Supervisor** (`backend/app/agents/supervisor.py`, `graph.py::supervisor_node`)
- Allowed inputs: `question`, or an explicit `requested_workflow` +
  `requested_structured_route`.
- Allowed tools: none. No DB, retrieval, tool execution, SQL, or generation.
- Forbidden: any I/O.
- Output: `workflow` (+ `structured_route`/`classified_identifier` for
  structured workflows).
- Failure behavior: never raises for bad input shape — an unclassifiable
  question resolves to `WorkflowDecision.ABSTAIN` with a reason.

**Policy node** (`graph.py::policy_node`, delegating to
`app.orchestration.graph.policy_node`)
- Allowed inputs: `requested_policy_question` or `question`.
- Allowed tools: `call_policy()` → the full Phase 1–7 RAG pipeline, unchanged.
- Forbidden: writing `status`/`abstention_reason`/`error` (may run
  concurrently with the structured specialist; only the validator owns those
  keys — see "Graph architecture").
- Output: `policy_result` only.
- Failure behavior: a `GenerationError` (real infrastructure failure)
  propagates as an exception, exactly as it does in Phase 9/`POST /query`; a
  policy abstention is a normal typed result inside `policy_result`.

**Structured specialist** (`backend/app/agents/structured_specialist.py`)
- Allowed inputs: `requested_tools` (explicit, preferred) or a single
  classifier-derived default tool call.
- Allowed tools: `execute_tool()` / `TOOL_REGISTRY`, reused directly from
  Phase 9 — no second tool implementation layer, no arbitrary SQL, no
  dynamic tool names or imports.
- Forbidden: more than `MAX_STRUCTURED_TOOL_CALLS = 5` tool calls (rejected,
  never silently truncated); writing `status`/`abstention_reason`/`error`
  (same fan-out-safety rule as the policy node).
- Output: `structured_results` — a list, one entry per attempted call,
  preserving `tool`, `success`, `source_dataset`, `data`, `record_count`,
  `error`, `abstention_reason` for every attempt (a failed call never
  silently disappears from a multi-tool batch).
- Failure behavior: the >5-tools bound and the missing-route/identifier case
  are both rejected *before* any DB connection opens (verified with a live
  test passing `settings=None`, which would raise if the check happened
  after `connect()`).

**Evidence validator** (`backend/app/agents/validator.py`)
- Allowed inputs: the full `MultiAgentState` — read-only.
- Allowed tools: none. No retrieval, DB, or new tool calls (structurally
  guarded by a test that greps the module source for forbidden symbols).
- Forbidden: any I/O; any mutation of `policy_result`/`structured_results`.
- Output: `status`, `validation` (`passed` + typed `issues`), and — only
  here — `abstention_reason`/`error`.
- Failure behavior: never raises. A structural problem (missing result,
  success-with-no-citations, source/domain mismatch, a policy/structured
  shape bleeding into the other) becomes `Status.ERROR` with a typed issue,
  never a silent pass.

## Permission matrix

| Agent | DB read | Retrieval/RAG | Tool execution | SQL | Generation (LLM) | Writes shared status |
|---|---|---|---|---|---|---|
| Supervisor | No | No | No | No | No | No |
| Policy node | No (via RAG service) | Yes (Phase 1–7 pipeline) | No | No | Yes (Phase 4's existing provider) | No |
| Structured specialist | Yes (parameterized only, via Phase 9's repository layer) | No | Yes (bounded, ≤5, registry-only) | No — no `execute_sql`/`run_query`/raw cursor path exists in this module | No | No |
| Evidence validator | No | No | No | No | No | Yes (sole owner) |

## LLM usage by agent

Only the policy node touches an LLM, and only via Phase 4's existing,
already-verified `GenerationProvider` — the same call `POST /query` and
Phase 9's `POST /orchestrate` already make. No Phase 10 file imports a
generation provider directly.

## Graph architecture

```
                              question
                                 │
                                 ▼
                         ┌───────────────┐
                         │  supervisor   │  explicit workflow (preferred)
                         │               │  or deterministic classifier
                         └───────┬───────┘
              ┌──────────────────┼──────────────────┬──────────────┐
              ▼                  ▼                   ▼              ▼
        ┌──────────┐   ┌──────────────────┐   ┌───────────┐  ┌───────────┐
        │  policy  │   │ policy+structured│   │ structured│  │  abstain  │
        │  only    │   │  (parallel fan-  │   │  only     │  │           │
        │          │   │   out, both run) │   │           │  │           │
        └────┬─────┘   └────────┬─────────┘   └─────┬─────┘  └─────┬─────┘
             │                  │                    │              │
             └──────────────────┴────────────────────┴──────────────┘
                                 ▼
                          ┌─────────────┐
                          │  validate   │  sole owner of status/
                          │             │  abstention_reason/error
                          └──────┬──────┘
                                 ▼
                          MultiAgentResponse
```

No cycles, no re-entrant edges, no LLM-driven branch selection.

**Fan-out/fan-in verified empirically, before any node was written**
(`tests/test_agents_graph.py::TestFanOutFanInProof`, run manually against
real LangGraph first): a conditional edge returning `["policy", "structured"]`
schedules both nodes in the same superstep; two nodes writing the **same**
state key in that superstep raise `langgraph.errors.InvalidUpdateError`
loudly, not silently; two nodes writing **disjoint** keys merge correctly;
the downstream node (`validate`) runs **exactly once** regardless of how
many upstream branches fired. This directly shaped the design rule below.

**Fan-out-safety rule**: any node that may run in parallel with another
(`policy` and `structured`, inside `POLICY_AND_STRUCTURED`) writes *only*
its own disjoint key (`policy_result` / `structured_results`) and never
touches `status`/`abstention_reason`/`error`. Those three keys are the
exclusive responsibility of `validate_node`, guaranteed by the same test to
run once after all upstream branches complete. `abstain_node` is exempt —
it is single-node-path-only and may set `abstention_reason` directly.

## Graph state

A separate `TypedDict` from Phase 9's `GraphState` — the shapes genuinely
differ (`structured_results` is a list, not one result). No `Settings`
object, DB connection, or RAG service instance lives in state; `Settings` is
captured via closure in `build_multi_agent_graph(settings)`, same discipline
as Phase 9.

```python
class MultiAgentState(TypedDict, total=False):
    request_id: str
    question: str
    requested_workflow: WorkflowDecision | None
    requested_policy_question: str | None
    requested_structured_route: Route | None
    requested_tools: list[dict[str, Any]] | None
    workflow: WorkflowDecision | None
    structured_route: Route | None
    classified_identifier: str | None
    policy_result: dict[str, Any] | None
    structured_results: list[dict[str, Any]] | None
    validation: dict[str, Any] | None
    status: Status | None
    abstention_reason: AbstentionReason | None
    error: str | None
```

## Supervisor

Honors an explicit `requested_workflow` (+ `requested_structured_route`)
directly when supplied — the strongest interface; `MultiAgentRequest`
already rejected any contradictory combination at the API boundary before
this node runs. Otherwise falls back to `classify_workflow()`
(`backend/app/agents/supervisor.py`), which reuses Phase 9's `classify()`
and its public constants (`FHIR_ID_PATTERN`, `SYNPUF_ID_PATTERN`,
`POLICY_KEYWORDS`) directly and adds exactly one new rule on top: a real
identifier shape (FHIR or SynPUF, not both) *combined with* a policy
keyword hit becomes `POLICY_AND_STRUCTURED`. Everything else — including
every existing abstention case — delegates unchanged to Phase 9's
classifier. **Combined routing requires positive evidence of both intents
together**, not "policy keyword present, fall back to structured on
anything else": an identifier alone routes `STRUCTURED_ONLY`; a policy
keyword alone routes `POLICY_ONLY`; both keyword-sets firing with no
identifier stays `ambiguous_route` under Phase 9's own rule, not combined.

## Structured specialist

Resolves calls in priority order: (1) explicit `requested_tools` (bounded to
5, checked *before* any DB connection opens); (2) an explicit workflow with
no tools → final abstention (`missing_required_identifier`) — the
classifier's default-tool fallback only applies when the classifier itself
chose the workflow; (3) the classifier's `classified_identifier` → one
default tool per route (`get_beneficiary_summary`/`get_patient_summary`).
Every attempted call's outcome is preserved — success or failure never
silently disappears from a multi-call batch (verified live with a
2-call request where one tool is invalid: both the successful and the
failed attempt appear in the result).

## Validator

See "Agent contracts" above for its full input/output contract.
Status-combination rule for `POLICY_AND_STRUCTURED`: `ERROR` on either side
→ overall `ERROR`; otherwise `OK` on either side → overall `OK` (partial
success is a legitimate response — a real policy answer plus an honestly
unknown patient ID is still useful); both sides `ABSTAINED` → overall
`ABSTAINED`, with `policy_reason or structured_reason` (policy takes
precedence when both fire — an arbitrary but consistent choice; both
specific reasons stay visible in `policy_result`/`structured_results`
regardless of which one becomes the top-level `abstention_reason`).

## Combined workflow

`POLICY_AND_STRUCTURED` runs the policy node and the structured specialist
concurrently (see "Graph architecture"). Their results are never merged into
one claim — the response keeps `policy` and `structured` as separate,
independently validated top-level fields. A combined response about
"Medicare hospital-bed policy" plus "this patient's hospital-bed-related
records" is never treated as "this policy applies to this patient" — no
eligibility, coverage, medical-necessity, or clinical inference is ever
synthesized from the pairing.

## Tool security

Structured tool execution is bounded to the same 18 Phase 9 tools, reached
only through `execute_tool()`/`TOOL_REGISTRY` — no second implementation
layer. `MAX_STRUCTURED_TOOL_CALLS = 5` is enforced at two independent
layers: `MultiAgentRequest`'s Pydantic validator (422 at the API boundary)
and `run_structured_specialist()`'s own check (defense in depth for any
caller that builds the graph directly, not just the API). No
`execute_sql`/`run_query`/`query_database`/raw-cursor path exists anywhere
in `structured_specialist.py` (structurally verified by a test).

## Identity boundary

Unchanged from Phase 8/9: DE-SynPUF beneficiaries and Synthea FHIR patients
remain unrelated synthetic populations. The Phase 10 structured specialist
handles exactly one structured domain per workflow (`structured_route` is
singular, not a list) — there is no code path that could look up "the same
person" across both datasets, combined or not.

## Provenance

- **Policy**: `policy` carries Phase 4's full citation list unchanged.
- **Structured**: each entry in `structured.results` carries its own
  `source_dataset` (`"cms_desynpuf"` or `"synthea_fhir"`), `tool` name, and
  real record data — never a fabricated document-style citation.
- The two are never flattened together in the response; `validation`
  actively flags (`workflow_result_mismatch`) if a policy-shaped field
  (`citations`/`answer`) ever appeared inside a structured result or vice
  versa — a defensive check against a future regression, not a currently
  reachable bug.

## Clinical safety boundary

No component in Phase 10 performs diagnosis, treatment or medication
recommendation, risk prediction, medical-necessity determination, coverage
approval, claim approval, or eligibility decision. The combined workflow
surfaces policy text and patient/beneficiary records side by side — it does
not, and structurally cannot, assert that one applies to the other.

## Abstention

First-class, typed, HTTP 200 — abstaining correctly is success, not
failure. Sources: the supervisor's own classification (`unsupported_request`,
`ambiguous_route`, `cross_dataset_linkage_request`,
`missing_required_identifier` — all reused from Phase 9), the structured
specialist's per-tool outcomes (`unknown_patient`/`unknown_beneficiary`/
`unknown_claim`, `unsupported_tool`, `invalid_tool_arguments`), and the
policy node's own abstention (surfaced as `policy_abstained`). For
`POLICY_AND_STRUCTURED`, both sides' specific reasons stay visible in their
own result blocks even when only one becomes the top-level
`abstention_reason`.

## Error handling

`Status.ERROR` (HTTP 502/503/504 at the API) is reserved for genuine
infrastructure/provider/database failure — a real exception, never silently
turned into an abstention. A `GenerationError` from the policy pipeline
propagates through `graph.ainvoke()` unchanged and is mapped to its own
`status_code` at the API layer, exactly as `POST /query`/`POST /orchestrate`
already do. A validator-detected structural problem (missing result,
success-with-no-citations, source mismatch) also becomes `Status.ERROR`,
with the specific issue recorded in `validation.issues`.

## API

`POST /multi-agent` (`backend/app/api/multi_agent.py`), registered in
`main.py` alongside the existing routers. **`POST /query` and
`POST /orchestrate` are both unchanged** — verified by dedicated regression
tests in `tests/test_agents_api.py`.

Request (`MultiAgentRequest`, `extra="forbid"`): `question` (required),
optional `workflow`, `policy_question`, `structured_route`, `tools`
(≤`MAX_STRUCTURED_TOOL_CALLS`). Contradictory combinations are rejected
outright (422), never silently repaired — e.g. `workflow=policy_only` with
a `structured_route`, `workflow=policy_and_structured` without one,
`tools` without an explicit `structured_route`.

Response (`MultiAgentResponse`): `request_id`, `workflow`, `status`,
`policy` (Phase 4's answer/citations shape, or `null`), `structured`
(`{"route": ..., "results": [...]}`, or `null`), `validation`
(`{"passed": bool, "issues": [...]}`), `final_summary` (always `null` in
Phase 10 — no LLM summarizer was added; deferred, see "Known limitations"),
`abstention_reason`, `error`.

## Observability

Structured JSON logging at every node, not just one end-of-request summary
line — each carries `request_id`, `node`, `action`, and a subset of `tool`,
`duration_ms`, `status`, `record_count`, `citation_count`, `abstention_reason`,
`error_category`/`validation_issue` relevant to that node
(`supervisor`/`policy` in `graph.py`, `structured` per tool call in
`structured_specialist.py`, `validate` in `validator.py`), plus one
`multi_agent_complete` summary line in the API layer. **Deliberately no
patient/beneficiary/claim record contents are logged anywhere** — verified
by inspecting real log output from a live combined-workflow request.

## Testing

- `tests/test_agents_models.py` (16) — every `MultiAgentRequest`
  consistency rule, `StructuredToolRequest`/`ValidationIssue`/
  `ValidationResult` schema validation.
- `tests/test_agents_supervisor.py` (13) — every classification case
  including the exact combined-intent example, and the case that must stay
  `ambiguous_route` rather than becoming combined.
- `tests/test_agents_structured_specialist.py` (13) — call resolution, the
  >5-tools and missing-route/identifier bounds enforced before any DB
  connection, and live multi-tool/partial-failure/unknown-record execution.
- `tests/test_agents_validator.py` (20) — every structural check, both
  combined-workflow status-combination cases, and a structural guard that
  the validator touches no retrieval/DB symbol.
- `tests/test_agents_graph.py` (19) — the isolated fan-out/fan-in LangGraph
  proof (disjoint-key merge + exactly-once downstream execution; same-key
  conflict raises `InvalidUpdateError`), full-graph integration for all 4
  workflow branches, and determinism.
- `tests/test_agents_api.py` (17) — validation errors, all workflow
  branches end to end, abstention, and `POST /query`/`POST /orchestrate`
  contract-unchanged regressions.

Live tests are gated on `CAREFLOW_MULTI_AGENT_INTEGRATION=1`, matching the
established convention from every prior phase.

## Known limitations

- No LLM summarizer — `final_summary` is always `null`. Deferred as
  low-value for Phase 10: the response already separates policy text and
  structured records cleanly, and a summarizer would be the first new LLM
  reasoning path in this phase, which the approved design excluded.
- The structured specialist handles exactly one structured domain
  (`structured_route`) per workflow — no cross-dataset combined structured
  query, by design (identity boundary).
- No follow-up/multi-turn context, no memory across requests, no
  checkpointing — every `POST /multi-agent` call is fully independent.
- The supervisor's classifier is the same small, curated heuristic as
  Phase 9 (plus one combined-intent rule) — not NLP, not exhaustive. The
  explicit `workflow`/`policy_question`/`structured_route`/`tools` interface
  is the reliable path for any caller that knows what it wants.

## Reproduction

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q                                            # unit tests
CAREFLOW_MULTI_AGENT_INTEGRATION=1 \
  .venv/bin/pytest -q tests/test_agents_*.py                    # live Phase 10 tests
CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 \
  CAREFLOW_RAG_INTEGRATION=1 CAREFLOW_HYBRID_INTEGRATION=1 \
  CAREFLOW_RERANK_INTEGRATION=1 CAREFLOW_STRUCTURED_INTEGRATION=1 \
  CAREFLOW_ORCHESTRATION_INTEGRATION=1 CAREFLOW_MULTI_AGENT_INTEGRATION=1 \
  .venv/bin/pytest -q                                            # full Phase 1-10 live suite
```
