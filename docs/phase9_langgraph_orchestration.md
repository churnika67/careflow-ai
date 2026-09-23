# Phase 9 — LangGraph router & structured tools

A small, deterministic-by-default orchestration layer that decides whether a
request belongs to the existing CMS policy RAG pipeline (Phases 1–7) or the
structured DE-SynPUF/Synthea FHIR data layer (Phase 8), and dispatches to the
right one. This is not a multi-agent system: one router decision, one
downstream action, one response. No planner/executor, no ReAct loop, no
tool-calling LLM, no human-in-the-loop, no persistence.

## Purpose

CareFlow AI now has two independently verified information systems that
share nothing at the data layer:

- **Unstructured policy intelligence** (Phases 1–7): CMS NCD → chunks →
  dense/BM25/hybrid retrieval → RRF → optional cross-encoder → evidence
  eligibility → generation → citation validation → answer/abstention.
- **Structured synthetic healthcare data** (Phase 8): DE-SynPUF claims and
  Synthea FHIR R4 records in PostgreSQL, behind a parameterized-SQL-only
  repository layer.

Phase 9 adds the smallest orchestration layer that can route a request to
the right one, using the real capabilities already built — nothing here
reimplements retrieval or SQL access.

## Architecture

```
                         User Query
                              │
                              ▼
                      ┌───────────────┐
                      │  route_node   │  explicit route/tool (preferred)
                      │               │  or deterministic classifier
                      └───────┬───────┘  (conservative — no route gets
                              │           unmatched text by default)
              ┌───────────────┼───────────────┬───────────────┐
              ▼               ▼               ▼               ▼
        ┌──────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
        │  policy  │   │  synpuf   │   │   fhir    │   │  abstain  │
        │  (RAG)   │   │(Phase 8)  │   │(Phase 8)  │   │           │
        └────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
             │               │  shared _run_structured_route  │
             │               └───────────────┘                │
             └───────────────────────┬────────────────────────┘
                                      ▼
                               ┌─────────────┐
                               │validate_node│  structural consistency
                               └──────┬──────┘  check before END
                                      ▼
                                Orchestrated
                                  Response
```

This is a real `langgraph.graph.StateGraph`, not a hand-rolled dispatcher —
see "Why LangGraph" below.

## Why LangGraph

The graph itself does not require LangGraph for its complexity (4 branches,
no cycles, one request per invocation) — plain Python functions would work.
It is used here anyway because CareFlow AI is intentionally moving toward an
agentic architecture (Phase 10 introduces multi-agent behavior), and Phase 9
establishes the real execution engine now rather than swapping it in later.
The graph is kept exactly as small as the task needs: no checkpointing, no
memory/persistence, no `ToolNode`/agent-loop helpers from `langgraph-prebuilt`,
no tool-calling LLM.

**Dependency added**: `langgraph==1.2.12` (Python ≥3.10 required; this project
runs 3.12.13). Verified compatible with existing pins (`httpx==0.28.1`,
`pydantic==2.13.5`) via an actual install plus `pip check`, not just reading
PyPI metadata. Pulls in `langchain-core`, `langgraph-checkpoint/-prebuilt/-sdk`,
`langsmith`, and their own transitive dependencies — none of which changed
any existing pin. See `requirements.lock` for the exact resolved set.

## Graph state

A bounded `TypedDict` (`backend/app/orchestration/models.py::GraphState`) —
deliberately holds only plain data (strings, enums, dicts, `None`). No
database connections, RAG service instances, or `Settings` objects live in
state; `Settings` is instead captured via closure in `build_graph(settings)`.

```python
class GraphState(TypedDict, total=False):
    request_id: str
    question: str
    requested_route: Route | None          # explicit caller input
    requested_tool: str | None
    requested_tool_arguments: dict | None
    route: Route | None                     # resolved by route_node
    tool_name: str | None
    tool_arguments: dict | None
    tool_result: dict | None
    policy_result: dict | None               # RAGAnswer.model_dump(mode="json")
    structured_result: dict | None            # {tool, source_dataset, record_count, data}
    status: Status | None                      # ok | abstained | error
    abstention_reason: AbstentionReason | None
    error: str | None
```

## Routes

`POLICY`, `SYNPUF`, `FHIR`, `ABSTAIN` — a bounded enum, not free text.
SynPUF and FHIR are kept as separate routes (not merged into one "structured"
route) because they are genuinely independent identity domains with zero
argument overlap, and separating them is what makes a request naming both
domains cleanly detectable as an attempted cross-dataset linkage rather than
just "ambiguous."

## Routing strategy

Two layers, in priority order:

1. **Explicit request (strongest, preferred)** — `OrchestrationRequest.route`
   + `tool` + `tool_arguments`. When supplied, the free-text classifier is
   never consulted. One consistency check is enforced before dispatch:
   `route=policy` combined with a tool is rejected as an inconsistent
   request (422), not silently corrected. `tool`/`tool_arguments` without an
   explicit `route` is also rejected (422) — there is no "guess the route
   from the tool name" fallback.
2. **Deterministic free-text classifier** (`classify.py`), used only when no
   explicit route is given. **Conservative by design — there is no
   "no signal found → POLICY" fallback.** Every route, including POLICY,
   requires positive evidence:
   - A real identifier **shape** (a Synthea FHIR resource UUID, or DE-SynPUF's
     16-hex-character `DESYNPUF_ID` shape) is the strongest signal and wins
     over keyword noise. Both shapes present at once → `ABSTAIN
     (cross_dataset_linkage_request)` — never "pick one."
   - Otherwise, three small (5–7 term) keyword sets — not a giant list —
     one per domain. Exactly one matched → that route (or, for a structured
     domain with no identifier in the text, `ABSTAIN
     (missing_required_identifier)`). More than one matched → `ABSTAIN
     (ambiguous_route)`. None matched → `ABSTAIN(unsupported_request)` — so
     "What is the weather?", "Write Python code.", "Who won the game?" all
     abstain rather than being sent into CMS policy RAG.

No LLM is used for routing. An LLM-assisted routing mode is explicitly not
implemented in this phase (it was optional per the phase design) — if added
later, it would need to be schema-constrained, optional, deterministically
tested, and never itself execute a tool or SQL.

## Structured tools

`backend/app/orchestration/tools.py` — 18 tools, each wrapping exactly one
real Phase 8 repository function. **No `execute_sql`/`run_query`/
`query_database` tool exists, and none ever will in this module** — the only
path to the database is a registered `ToolSpec`'s fixed implementation,
called with arguments that already passed strict Pydantic validation.

FHIR (source: `synthea_fhir`): `get_patient_summary`, `get_patient_encounters`,
`get_patient_conditions`, `get_patient_procedures`, `get_patient_observations`
(optional `code`), `get_patient_medication_requests`, `fhir_encounter_counts`,
`fhir_condition_frequency`, `fhir_procedure_frequency`,
`fhir_medication_frequency`.

SynPUF (source: `cms_desynpuf`): `get_beneficiary_summary`,
`get_claims_for_beneficiary`, `get_claim_details`, `synpuf_claim_counts`,
`synpuf_payment_totals`, `synpuf_diagnosis_frequency`,
`synpuf_procedure_frequency`, `synpuf_hcpcs_frequency`.

`get_claim_details` takes **`claim_row_id`**, not `claim_id` — Phase 8
established that the source `CLM_ID` is not globally unique (some claims
have multiple `SEGMENT` rows), so the real primary key is the deterministic
`uuid5(claim_type, claim_id, segment)`. The tool argument keeps that exact
name so API consumers are not misled about what value is required.

### Argument validation

Every tool has a `StrictModel` (`extra="forbid"`) argument schema:
`PatientIdArgs`, `PatientObservationArgs`, `BeneficiaryIdArgs`,
`ClaimRowIdArgs`, `TopNArgs`, `NoArgs`. Identifier fields are validated by
type and bounded length (not by a rigid format regex — DE-SynPUF/FHIR IDs
are not guaranteed to always be exactly UUID/16-hex shaped at the schema
level, so length bounds match the real datasets without over-constraining
them). `top_n` is bounded 1–100. No `claim_type` argument exists because no
current tool takes one.

### `execute_tool` dispatch

`execute_tool(connection, route, tool_name, raw_arguments)` is the single
entrypoint: unknown tool name → `unsupported_tool`; a tool registered under
a **different** route than the one being executed → also `unsupported_tool`
(this is what rejects, for example, a SynPUF tool requested under the FHIR
route — a natural consequence of keeping the registries domain-separated,
not special-cased logic); argument validation failure → `invalid_tool_arguments`
(reported, never raised as an exception). A tool call that succeeds but
finds nothing (e.g. an unknown beneficiary) returns `success=True, data=None`
— `execute_tool` itself doesn't know which tools are "single record lookups";
that interpretation (→ `unknown_beneficiary`/`unknown_claim`/`unknown_patient`)
happens one layer up, in the graph's `_run_structured_route`.

### A bug this caught (fixed at the Phase 9 boundary, not in Phase 8)

`synpuf_claims.claim_row_id` is a native Postgres `UUID` column (Phase 8's
own migration), so a value fetched from `get_claims_for_beneficiary` and
passed straight into `get_claim_details` arrives as a `uuid.UUID` object —
not a `str`. The first strict-typed `ClaimRowIdArgs` schema rejected that
outright; live testing caught it before it reached any committed test.
Fixed with a `field_validator(mode="before")` that normalizes a `UUID`
input to `str`, so both a chained-internal call and an external JSON string
work. Phase 8's repository behavior was correct and untouched.

A second, separate issue of the same shape: `StrictModel`'s `strict=True`
blocks Pydantic's normal string→enum coercion — since JSON has no enum
type, a JSON request could never set `OrchestrationRequest.route` at all
without a fix. Same pattern: a `field_validator(mode="before")` on `route`
accepts a plain string and converts it to `Route` before strict validation
applies, while an invalid string still correctly fails validation.

## Policy adapter

`backend/app/orchestration/policy_adapter.py::call_policy(question)` is a
one-line call into `get_rag_service().answer(question)` — the exact function
`POST /query` already uses. Dense/BM25/hybrid retrieval, RRF, the optional
cross-encoder, evidence eligibility, citation validation, and Phase 4's own
abstention behavior are all reused unchanged, not reimplemented.

Phase 4's `abstention_reason` (e.g. `no_eligible_evidence`) is a *different*
vocabulary from Phase 9's orchestration-level `AbstentionReason` — the two
are kept distinct rather than merged. When the policy pipeline itself
abstains, the orchestration layer sets `abstention_reason=policy_abstained`
while Phase 4's specific reason is preserved verbatim inside `policy_result`.
Nothing is lost; both layers are represented.

A `GenerationError` (genuine retrieval/provider infrastructure failure) is
deliberately **not** caught inside `policy_node` — per keeping abstention and
error semantically separate, it propagates as a real exception through
`graph.ainvoke()` and is caught at the API layer, preserving its original
HTTP status code exactly as `POST /query` already does (502/503/504).

## Identity boundary

DE-SynPUF beneficiaries and Synthea FHIR patients remain unrelated synthetic
populations (established in Phase 8; unchanged here). The router/tool layer
never infers `beneficiary X == patient X`, and there is no "combined patient
profile" anywhere in this code. A request naming both a beneficiary-ID-shaped
and a patient-ID-shaped identifier abstains with
`cross_dataset_linkage_request` rather than picking one or merging them.

## Provenance

- **Policy**: `policy_result` carries Phase 4's full citation list unchanged
  (`document_id`, `document_version`, `chunk_id`, `source`).
- **Structured**: `structured_result`/the API response's `source_dataset`
  field is always exactly `"cms_desynpuf"` or `"synthea_fhir"`, plus the tool
  name and the real record data (including its natural identifiers — e.g. a
  beneficiary summary includes `beneficiary_id`). No document-style citation
  is fabricated for a database record.

## Abstention vs. error

Kept semantically separate throughout, per design:

- **Abstention** (`Status.ABSTAINED`) is a first-class, typed, expected
  result — `unsupported_request`, `ambiguous_route`,
  `cross_dataset_linkage_request`, `missing_required_identifier`,
  `unknown_patient`, `unknown_beneficiary`, `unknown_claim`,
  `unsupported_tool`, `invalid_tool_arguments`, `inconsistent_request`,
  `policy_abstained`. Always HTTP 200 — abstaining correctly is success, not
  failure.
- **Error** (`Status.ERROR` internally; HTTP 502/503/504 at the API) is a
  genuine infrastructure/provider/database failure — a real Python
  exception, never silently swallowed into an abstention.

`validate_node` is the graph's own consistency check: every path must leave
a definite `status`; an abstained result must carry its reason; a success
result must carry a payload. This doesn't re-validate business correctness —
only that the graph itself didn't leave state inconsistent.

## API

`POST /orchestrate` — a new endpoint (`backend/app/api/orchestrate.py`),
registered alongside the existing routers. **`POST /query`'s contract is
completely unchanged** — verified by a dedicated regression test.

Request (`OrchestrationRequest`): `question` (required), optional `route`,
`tool`, `tool_arguments`. `extra="forbid"` — unknown fields are rejected
(422), not silently ignored.

Response (`OrchestrationResponse`): `request_id`, `route`, `status`,
`answer`/`citations` (policy), `tool`/`source_dataset`/`record_count`/`data`
(structured), `abstention_reason`, `error`.

## Observability

Every request logs one structured JSON line: `request_id`, `route`, `tool`,
`duration_ms`, `status`, `record_count`, `abstention_reason`,
`error_category`. Deliberately **no patient/claim record contents** are
logged — only routing/tool metadata and counts, following the same privacy
discipline as Phase 8's own ingestion logging, even though the data is
synthetic.

## Testing

- `tests/test_orchestration_classify.py` (13) — routing semantics via
  semantically equivalent examples of every case, including the three
  unrelated-question non-defaults, both missing-identifier cases, ambiguous
  and cross-dataset-linkage abstention, and determinism.
- `tests/test_orchestration_tools.py` (31) — argument schema validation,
  registry integrity (exact tool-name set, no `sql`/`query`/`table`/`column`
  fields anywhere), `execute_tool` dispatch semantics, and live execution of
  all 18 tools against the real Phase 8 dev-subset data (including the
  claim_row_id UUID regression).
- `tests/test_orchestration_graph.py` (22) — pure-unit tests for every path
  that resolves to abstention before touching a live service, plus a live
  section exercising real policy/synpuf/fhir node execution end to end
  (START→ROUTER→POLICY/SYNPUF/FHIR/ABSTAIN→VALIDATE→END), tool-failure and
  validation-failure behavior, policy citation/abstention preservation, and
  same-input determinism.
- `tests/test_orchestration_api.py` (13) — validation errors, domain
  mismatch, unrelated-question abstention, valid policy/structured
  responses, unknown-beneficiary abstention, and the `POST /query`
  contract-unchanged regression.

Live tests are gated on `CAREFLOW_ORCHESTRATION_INTEGRATION=1` (structured
tool/graph/API tests additionally need `CAREFLOW_STRUCTURED_INTEGRATION=1`
for the Phase 8 dev-subset data), matching the established convention.

## Known limitations

- The free-text classifier is a small, curated heuristic — not NLP, and
  deliberately not exhaustive; ambiguous or oddly-phrased real questions may
  abstain rather than route correctly. The explicit `route`/`tool`/
  `tool_arguments` path is the reliable interface for any caller that knows
  what it wants.
- Structured routes return deterministic data, not a natural-language
  answer — no LLM synthesizes prose from tool results in this phase, by
  design (keeps the phase fully testable without a live LLM dependency).
- No routing to multiple tools in one request, no follow-up/multi-turn
  context, no memory across requests.
- `langgraph-prebuilt`'s `ToolNode`/agent helpers are installed (transitive
  dependency) but intentionally unused — this graph is hand-wired with
  explicit nodes and conditional edges, not an agent loop.

## Reproduction

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q                                            # unit tests
CAREFLOW_ORCHESTRATION_INTEGRATION=1 CAREFLOW_STRUCTURED_INTEGRATION=1 \
  .venv/bin/pytest -q tests/test_orchestration_*.py             # live orchestration tests
CAREFLOW_API_URL=http://localhost:18000 CAREFLOW_INTEGRATION=1 \
  CAREFLOW_INGESTION_INTEGRATION=1 CAREFLOW_RAG_INTEGRATION=1 \
  CAREFLOW_HYBRID_INTEGRATION=1 CAREFLOW_RERANK_INTEGRATION=1 \
  CAREFLOW_STRUCTURED_INTEGRATION=1 CAREFLOW_ORCHESTRATION_INTEGRATION=1 \
  .venv/bin/pytest -q                                            # full Phase 1-9 live suite
```
