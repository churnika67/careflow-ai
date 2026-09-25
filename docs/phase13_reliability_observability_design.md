# Phase 13 — reliability, caching, and observability: design audit

Slice 1 is audit and design only. Nothing in this document has been
implemented; every finding below was verified directly against current
source code, `docker-compose.yml`, and a live (read-only) check of running
dependencies — not assumed or carried forward from memory.

**Slice 2 update:** the Redis client abstraction described as a
recommendation at the end of this document (§"Recommended Slice 2") is now
implemented as infrastructure — see "Slice 2: implemented cache contract"
near the end of this document for the exact, current contract. **No RAG
response, retrieval stage, or structured-tool result is cached yet** —
nothing built in Slice 2 is wired into any request path.

## Current architecture

FastAPI app (`backend/app/main.py`) with 5 routers: `/health`, `/query`
(Phase 1-7 single-mode RAG), `/orchestrate` (Phase 9 router), `/multi-agent`
(Phase 10 bounded multi-agent graph), `/reviewable-query` + `/reviews/*`
(Phase 11 HITL). Three backing services in `docker-compose.yml`: Postgres
(structured data + review state), Qdrant (vector index), Redis (currently
health-check only — see below). No message queue, no cache layer, no
metrics/tracing backend.

## Current Redis state

**Redis is a real, already-provisioned dependency — not absent infrastructure.**

- `pyproject.toml`/`requirements.lock`: `redis==6.4.0` is an installed
  Python dependency.
- `docker-compose.yml`: a `redis:7.4.5-alpine` service, `appendonly yes`
  (persistent), a named volume `redis_data`, port exposed only on
  `127.0.0.1`, with its own healthcheck (`redis-cli ping`). The `backend`
  service's `depends_on` requires Redis's healthcheck to pass
  (`condition: service_healthy`) before the backend container starts.
- `backend/app/core/config.py`: `redis_url: SecretStr` field, default
  `redis://localhost:6379/0`.
- `backend/app/services/health.py::check_redis()`: the **only** application
  code that touches Redis anywhere in the repository. It opens a fresh
  `redis.asyncio.Redis.from_url(...)` connection, sends a `PING`, and closes
  the connection — once per `/health` request. No key is ever read or
  written.
- Confirmed by exhaustive grep: zero other `redis`/`Redis` references
  anywhere in `backend/app/` outside `core/config.py` and `services/health.py`.
- No caching abstraction module exists anywhere (`find backend/app -iname
  "*cache*"` returns only `__pycache__` directories).
- Tests: `tests/test_health.py` and `tests/test_integration.py` assert
  Redis appears in the `/health` dependency map and that a slow/failing
  Redis marks the response `"unavailable"`/degrades overall status — no
  test exercises Redis as a cache.

**Conclusion: Redis is provisioned, healthy-by-default, and a hard startup
dependency for the backend container, but is currently used for exactly one
purpose (a liveness ping) and stores no data.** Phase 13 does not need to
add Redis to the stack — it needs to decide whether and how to start using
the Redis that already exists.

## Current in-process caching

Distinct from Redis, three `@lru_cache` singletons already exist and must
not be confused with a Redis cache:

- `backend/app/core/config.py:39` — `get_settings()`, `@lru_cache` (no
  args), one `Settings` instance per process.
- `backend/app/generation/runtime.py:12,19` — `load_embedding(cache,
  offline)` and `load_reranker(cache, offline)`, both `@lru_cache(maxsize=1)`
  — the embedding/reranker *model objects* are loaded once per process and
  reused for every subsequent request (this is why Slice 5's cold-vs-warm
  latency split showed a ~2.9s first-call cost and a ~25ms warm cost).

These are in-memory, per-process, model/config object reuse — never a
response/data cache, never shared across processes, never expiring, never
touching Redis.

## Current RAG flow

Traced from the API boundary down (POLICY_ONLY path; `/query` is the same
underlying call):

1. `app/api/multi_agent.py` (or `/query`) → `app.orchestration.policy_adapter.call_policy(question)`
2. → `app.generation.runtime.get_rag_service()` → `RAGService(retrieve, create_provider(settings), settings)`
3. `retrieve(question, settings)` (`generation/runtime.py`):
   a. `load_embedding(...)` (cached singleton)
   b. **fresh** `QdrantClient(url=..., timeout=10)` opened via `with closing(...)`, closed at the end of the call — no pooling/reuse across requests
   c. `Retriever(NCDIndex(client, alias), embedding, candidate_k, rrf_k, bm25_k1, bm25_b).search(question, settings.retrieval_mode, depth, for_rag=True)` — dense, BM25, or hybrid/RRF depending on `retrieval_mode`
   d. if `settings.rerank_enabled`: `rerank(question, hits, load_reranker(...), top_k)` (cross-encoder, cached singleton)
4. `RAGService.answer()` (`generation/service.py`, not modified this slice): builds context via `build_context()` (evidence-threshold gate), calls the provider (`DeterministicProvider`/`OpenAIProvider`), validates citations, computes `insufficient_evidence`/`abstention_reason`

**Where caching could theoretically occur** (documented only — none added):
query embedding vector (step 3a's embed call), the dense/BM25/hybrid hit
list (step 3c), the reranked hit list (step 3d), the final generated answer
(step 4), or — for the structured path — a read-only tool's result
(`execute_tool()` in `orchestration/tools.py`). See "Cache candidate
matrix" below.

## Current runtime configuration

Verified directly from `docker-compose.yml` environment defaults and a live
`get_settings()` read in this session — **not** from the Phase 12
evaluation package's own frozen `PRODUCTION_SETTINGS`, which is a distinct,
separately-audited object:

| Setting | Current runtime value | Source |
|---|---|---|
| `retrieval_mode` | `dense` | `docker-compose.yml` default `RETRIEVAL_MODE:-dense`; confirmed live via `get_settings()` |
| `rerank_enabled` | `false` | `docker-compose.yml` default `RERANK_ENABLED:-false`; confirmed live |
| `rag_provider` | `deterministic` | `docker-compose.yml` default `RAG_PROVIDER:-deterministic`; confirmed live |
| `rag_min_score` | `0.6` | unchanged since Phase 4 |

This is the exact configuration Phase 12 documented as `EVAL-RUNTIME-CONFIG-DRIFT`
(distinct from the evaluation package's hybrid+rerank-enabled
`PRODUCTION_SETTINGS`, used only for Slices 2/3/4/6's retrieval-quality
measurements). **Phase 13 Slice 1 does not reconcile this** — it is
restated here only so any future caching/observability design is built
against the configuration that is actually live, not the evaluation
package's configuration.

## Database lifecycle

`backend/app/db/connection.py::connect(settings)` — `return await
psycopg.AsyncConnection.connect(settings.database_url.get_secret_value())`.
**No connection pooling exists anywhere** (`psycopg_pool` is not a
dependency; grepped for `pool`/`Pool` across `backend/app/` — zero matches).
Every call site (`agents/structured_specialist.py`, `orchestration/graph.py`,
`api/reviews.py` ×4, `db/migrate.py`) opens a brand-new TCP connection,
uses it for exactly one request/specialist-call, and closes it. Transaction
behavior itself (Phase 11's `connection.transaction()` + explicit
`connection.commit()` pattern, fixing the ambient-transaction bug found
during Phase 11) is **not touched or re-examined for correctness in this
slice** — it is already correct and tested; the only new observation here
is that connection *creation* is per-call, not pooled.

**Reliability risk identified (not fixed):** a Postgres connection-pool
exhaustion or slow-connect scenario under concurrent load would create one
new TCP handshake + auth round-trip per request, with no pool to absorb
bursts — a plausible, currently-undesigned-for reliability gap for future
load.

## Qdrant lifecycle

`generation/runtime.py::retrieve()` opens a **fresh** `QdrantClient(url=...,
timeout=10)` per policy-RAG call (`with closing(...)`, closed at the end).
Same pattern in every `evaluation/*.py` module and `ingestion/cli.py`
(30s timeout there). No retry wrapper exists anywhere — a single failed
Qdrant call propagates immediately (caught generically in `retrieve()`'s
`except Exception as exc: raise GenerationError("retrieval_unavailable",
503)`). No client reuse across requests. Collection/alias resolution
(`NCDIndex(client, alias).resolve()`) is re-resolved on every call rather
than cached — meaning an alias repoint would be picked up immediately by
the next request (a correctness property), at the cost of one extra Qdrant
round-trip per call.

## Provider failure handling

`backend/app/generation/providers.py` (read in full):

- `DeterministicProvider`: synchronous, no I/O, cannot fail.
- `OpenAIProvider`: single HTTP attempt via `httpx.Client(timeout=settings.rag_provider_timeout_seconds)`,
  **zero retry logic** (no `tenacity`/`backoff`/manual retry loop found
  anywhere in the repository). Exception mapping is precise and total:
  `httpx.TimeoutException` → `GenerationError("provider_timeout", 504)`;
  any other `httpx.HTTPError` → `GenerationError("provider_unavailable", 502)`;
  a non-`"completed"` response status, a malformed body, or a
  parse/key/type error → `GenerationError("malformed_provider_response", 502)`;
  a `"refusal"` content part is treated as a graceful
  `insufficient_evidence=True` result, not an error. `create_provider()`
  raises `GenerationError("provider_not_configured", 503)` immediately at
  construction if `OPENAI_API_KEY` is unset. There is **no fallback from
  OpenAI to the deterministic provider anywhere** — this is confirmed
  existing behavior, and Phase 13 Slice 1 does not add one.

## Existing structured logging

No central logging module exists. Every one of `agents/graph.py`,
`agents/structured_specialist.py`, `api/multi_agent.py`,
`api/orchestrate.py`, `api/reviews.py`, and `reranking/service.py`
independently defines its own private `_log`/`_log_event` helper wrapping
`logger.info("%s", json.dumps({"event": ..., **fields}, default=str))` —
the same pattern reimplemented six times, never shared.

**Fields already logged** (varies by module): `request_id`, `event`,
`node`/`action`, `duration_ms`, `status`, `workflow`, `tool`,
`retrieval_method`... `record_count`, `abstention_reason`, `error_category`,
`citation_count`, `validation_issue` (codes only).

**Deliberately excluded**, per an explicit comment in `api/reviews.py`:
*"no evidence_snapshot, policy answer text, citation excerpts, structured
record contents, or reviewer free-text reason."* The same discipline (only
IDs/counts/reason-codes, never payload text) is consistent across every
module inspected.

**Significant gap found:** `backend/app/main.py` contains **no**
`logging.basicConfig()`/`logging.config.dictConfig()` call, and no other
file configures the root logger. The Dockerfile's `CMD` is bare `uvicorn
app.main:app` with no `--log-config`. This means the actual emission
behavior of every `logger.info(...)` call above (level threshold, handler,
output format) is governed entirely by Uvicorn's own default logging setup,
not by any explicit application configuration — this was not verified
empirically against a running server in this slice (out of scope for a
design-only audit) and should be verified before Phase 13 Slice 2 assumes
these structured logs are reliably captured in every environment.

## Current health behavior

Exactly one endpoint: `GET /health` (`backend/app/api/health.py`), which
calls `check_dependencies()` and checks **Postgres, Qdrant, and Redis
together**, in parallel (`asyncio.gather`), each under a
`settings.health_timeout_seconds` (default 3s) timeout. Returns `200
{"status": "ok"}` only if all three succeed, else `503
{"status": "degraded", ...}` with a per-dependency `"ok"/"unavailable"`
breakdown. Failure detail is deliberately narrow: `logger.warning("Dependency
%s failed (%s)", name, type(exc).__name__)` — exception message/connection
string never logged.

**This is a readiness check, not a liveness check** — there is no separate
endpoint that reports "the process is alive" independent of its
dependencies. The Dockerfile's own `HEALTHCHECK` hits this same `/health`
endpoint, so Docker's container-health status is coupled to all three
dependencies, not just the process. No startup-specific check exists beyond
this.

## Current monitoring/metrics

Confirmed absent by exhaustive grep: no Prometheus, OpenTelemetry, Sentry,
Grafana, StatsD, or Datadog reference anywhere in the repository (source,
config, or dependency files). The only "metrics" that exist today are the
structured JSON log lines above and Phase 5/12's own evaluation-time
latency measurements (`evaluation/metrics.py::Latency`, unrelated to
runtime observability).

## Cache candidate matrix

Design only — no selection made, nothing implemented.

| Candidate | Cache key inputs | TTL concept | Invalidating event | Determinism | Staleness risk | Privacy/sensitivity | Expected value | Complexity |
|---|---|---|---|---|---|---|---|---|
| **A. Query embedding vector** | normalized query text, embedding model+revision | long (model-lifetime) | embedding model upgrade | Fully deterministic (same input → same vector) | None while model unchanged | Low — a query string, not patient/claim data | Moderate (saves one embed call, ~ms-scale per Slice 5) | Low |
| **B. Dense retrieval result** | normalized query, embedding model+revision, corpus fingerprint, candidate_k | short–medium | corpus/index change (re-ingestion, alias repoint) | Deterministic given a fixed corpus | Corpus can change without a version bump today (no automatic fingerprint check on every request) | Low — chunk IDs/scores, not patient data | Moderate (Slice 5: dense stage ~16ms; a full skip is small but non-zero) | Medium (needs a reliable corpus-version signal) |
| **C. BM25/hybrid retrieval result** | query, retrieval_mode, corpus fingerprint, candidate_k, RRF k, bm25_k1/b | short–medium | corpus change | Deterministic given a fixed corpus/BM25 index build | Same as B | Low | Moderate (hybrid stage ~26ms per Slice 5) | Medium |
| **D. Reranker result** | query, the exact candidate set (by chunk_id list, order-sensitive), reranker model+revision | short–medium | corpus/candidate-set change | Deterministic given identical candidates | High if the candidate set changes silently (must key on the *actual* candidate list, not just the query) | Low | **Highest of any single stage** — Slice 5/6 measured reranker latency at ~426–474ms, 15.9–17.3x the retrieval stage | Medium-high (key must encode the full candidate set) |
| **E. Final policy/RAG answer** | question, full resolved config identity (retrieval_mode, candidate_k, RRF k, rerank_enabled+model+revision, final_top_k, evidence_threshold, provider identity+model), corpus fingerprint | short (esp. if `rag_provider=openai`, since a live model could be updated) | any config/corpus change; provider model change | Deterministic only under `rag_provider=deterministic`; **not guaranteed deterministic under `openai`** (model behavior can vary run-to-run even at temperature 0, and OpenAI can update a model version server-side) | **Highest of any candidate** — caching a stale OpenAI answer after a policy corpus update is a genuine correctness risk, not just a UX one | Low direct sensitivity (answer text over public CMS policy), but caching provider *output* long-term raises a separate "is this still the current guidance" concern distinct from PHI | Potentially large for repeated identical questions, but only if OpenAI is enabled — currently the live provider is `deterministic`, which is already ~free to recompute | High (requires the full config-identity key from §"Cache key requirements", plus an explicit staleness policy) |
| **F. Structured read-only tool result** | tool name, validated argument set (e.g. `beneficiary_id`), dataset/source version (SynPUF/FHIR ingestion batch identity) | medium–long (data is static/batch-loaded, not live) | a future re-ingestion of that dataset | Deterministic given a fixed dataset snapshot | Low today (Phase 8 data is a static synthetic snapshot, not continuously updated) | **Requires explicit analysis — see Privacy boundary below** | Low-moderate (Slice 5 measured these at sub-millisecond already — a local Postgres read on 15 beneficiaries/5 patients; caching would save very little at this data scale) | Low-medium |

No candidate is selected as a Slice 2 target here — see "Recommended Slice 2" below, which recommends foundational work over any single cache.

## Cache-key requirements

Any future cache design must not use a bare `cache[query]` key. Required
identity components, drawn directly from what `evaluation.config.ExperimentConfig`
already treats as behaviorally significant (Phase 12's own precedent for
"what changes the answer"):

- normalized query text
- corpus fingerprint (`ingestion.models.digest(load_corpus(...))` — already
  exists, reused directly, not reinvented)
- `retrieval_mode`
- embedding model + revision
- `candidate_k`, RRF `k`
- `rerank_enabled`, and if true: reranker model + revision
- `final_top_k`, evidence threshold
- generation provider identity (+ model, if `openai`)

For structured-tool caching specifically: tool name, the validated
(post-Pydantic) argument set — never the raw pre-validation request — and
the dataset/source version identity (which Phase 8's ingestion already
tracks at the batch level).

## Privacy boundaries

CareFlow's current data is CMS policy text (public), DE-SynPUF synthetic
claims, and Synthea synthetic FHIR data — **no real PHI is required for
this project**, stated exactly that way per the approved Phase 12
vocabulary; this document does **not** claim HIPAA compliance, and no
future Phase 13 design should either, unless separately established with
real evidence.

Conservative logging/caching guidance for Phase 13 (design principle,
consistent with the discipline `api/reviews.py`'s own `_log()` already
demonstrates):

- **Never** place into logs: raw patient/beneficiary records, full claim
  rows, full generation prompts, full evidence/context text, or reviewer
  free-text reasons. IDs, counts, durations, and reason/error codes only.
- **For Redis specifically**: even though today's structured data is
  synthetic, caching structured *tool results* (candidate F above) means
  storing record-shaped data (names of fields resembling PHI shapes:
  encounter dates, condition codes, beneficiary IDs) in a third persistence
  layer with its own access surface, TTL, and eviction behavior — a
  distinct risk profile from Postgres, which already has defined access
  controls. **This should be explicitly decided, not defaulted into**, if
  Phase 13 ever caches structured-tool output; it is not a decision this
  audit makes.

## Proposed observability fields

Design only, matching and extending the pattern already used in P9–P11
(never inventing a new shape from scratch):

`request_id`, `endpoint`/`route`, `workflow`, `tool`, `retrieval_mode`,
`cache_status` (`hit`/`miss`/`unavailable`/`read_error`/`write_error`,
once caching exists), `duration_ms`, `record_count`, `abstained`
(bool)/`abstention_reason`, `review_triggered` (bool), `error_category`.

**Must NOT be logged, ever, by default:** the query/question text itself
(only its presence/length, if needed), any evidence/context chunk text,
any structured tool's returned record data, any generated answer text, any
reviewer free-text reason, cache *values* (keys/hit-miss status only), and
anything already on the existing exclusion list above (credentials,
absolute paths, hostnames — consistent with the artifact-safety discipline
already enforced throughout Phase 12).

## Proposed metrics

Design only — no values invented, nothing implemented:

request count (by endpoint/workflow), request latency (histogram, by
endpoint/workflow), error count (by error_category), cache hit/miss count
(once caching exists), cache read/write error count, retrieval latency (by
stage — reusing the exact boundary names Slice 5 already established:
dense/bm25/hybrid/rerank_only), structured-tool latency (by tool),
abstention count (by reason), review-trigger count (by reason code).

## Failure-mode matrix

| Failure | Current behavior | Possible future Phase 13 behavior (not implemented) |
|---|---|---|
| Redis unavailable | `/health` reports `redis: unavailable`, overall `status: degraded`, HTTP 503; **no other code path touches Redis today, so no request-serving functionality is actually affected** | If Redis becomes a cache: distinguish "cache unavailable" from a hard failure — likely read-through-on-miss with Redis errors logged and swallowed, not propagated as request failures (Redis as an optional performance dependency, not a required one) |
| Postgres unavailable | Any `connect()` call raises; `/health` reports `postgresql: unavailable`; structured-tool/review endpoints surface a 503 (`*_unavailable` error codes) per their existing exception handling | Unchanged in spirit; a connection pool (if added) would need its own exhaustion/backoff semantics, not designed here |
| Qdrant unavailable | `retrieve()`'s generic `except Exception` catches any Qdrant client error and raises `GenerationError("retrieval_unavailable", 503)`; `/health` reports `qdrant: unavailable` | Same — retrieval has no fallback and arguably shouldn't get a silent one (an unavailable index must not answer from stale cached retrieval results without saying so) |
| Generation provider unavailable | `OpenAIProvider` maps timeout→504, other HTTP errors→502, malformed body→502; `DeterministicProvider` cannot fail | No fallback to `DeterministicProvider` (explicitly not designed here); a future design would need to decide if that's ever desirable and say so explicitly, not silently |
| Reranker unavailable | Not separately handled — a `RerankQueryError` (query too long) is mapped to `GenerationError("rerank_query_too_long", 422)`; any other reranker exception is caught generically → `GenerationError("reranking_unavailable", 503)` | Unchanged in spirit; if reranker results were cached, a cache miss simply falls through to the same current behavior |
| Malformed cached payload | N/A — no cache exists | Must be treated as a cache miss, never as a fatal error — a corrupted Redis value should never crash a request that would have succeeded without the cache |
| Stale cache | N/A | Directly proportional to which candidate is cached (see matrix above) — reranker/retrieval results are low-risk if keyed on corpus fingerprint; a cached OpenAI *answer* is the highest-risk candidate for staleness |
| Timeout (any dependency) | Postgres/Qdrant/OpenAI each have their own timeout today (implicit/default for Postgres, 10s for Qdrant, `rag_provider_timeout_seconds` for OpenAI); `/health` uses `health_timeout_seconds` (default 3s) uniformly | A future Redis client would need its own explicit timeout, consistent with the other two dependencies, not left to library defaults |
| Partial multi-agent failure | Already handled by Phase 10's validator (`ValidationIssueCode.SPECIALIST_FAILURE` etc.) — a structured-tool failure inside `POLICY_AND_STRUCTURED` does not crash the policy branch; validated and tested today | Unaffected by caching/observability work unless a cached stage itself fails in a new way (see "malformed cached payload" above) |

## Recommended Slice 2

**Redis client abstraction + health/failure semantics — foundational work,
not a specific cache.**

Rationale: every cache candidate in the matrix above (A–F) needs the same
underlying primitive first — a Redis client wrapper with an explicit
timeout, a defined hit/miss/unavailable/read-error/write-error vocabulary,
and a decision (made once, reused everywhere) on whether Redis failures are
swallowed (optional-performance-dependency model) or propagated
(required-dependency model) — Phase 13 Slice 1's audit shows the current
`/health` check already treats Redis as required-for-readiness, which may
or may not be the right model once Redis is *also* used for caching, and
that tension should be resolved deliberately in Slice 2, not implicitly.
Building this abstraction first, with its own focused tests (hit, miss,
simulated-unavailable, simulated-malformed-value, timeout), lets every
subsequent cache candidate (Slice 3+) plug into one already-decided,
already-tested contract instead of each re-deciding failure semantics
independently — avoiding the six-times-reimplemented-logging-helper pattern
this audit found in P9–P11.

Explicitly out of scope for Slice 2 (per this audit, to be judged later):
which cache candidate(s) to implement first, whether to add connection
pooling for Postgres/Qdrant, whether to add a shared structured-logging
helper, and whether to reconcile `EVAL-RUNTIME-CONFIG-DRIFT`.

## Slice 2: implemented cache contract

Built: [backend/app/infrastructure/cache.py](../backend/app/infrastructure/cache.py).
Nothing here is wired into `RAGService`, `Retriever`, reranking, structured
tools, the multi-agent graph, or the review workflow — this section
documents infrastructure, not an active cache.

**Redis's role for future caching:** an **optional performance dependency**.
A cache read/write failure or unavailability must never fail an otherwise
valid request; the authoritative source of truth remains Qdrant/Postgres/
deterministic computation/the generation provider. This is a distinct
decision from `/health`'s current required-dependency treatment of Redis
(§"Current health behavior" above) — that tension is deliberately left
unresolved in Slice 2, to be judged in a future, bounded health/readiness
slice, not implicitly changed here.

**Cache status enum:**
- Read: `HIT`, `MISS`, `UNAVAILABLE` (connection/timeout), `READ_ERROR`
  (any other Redis-side error), `MALFORMED` (value returned but not valid
  JSON — never crashes, never auto-deleted).
- Write: `WRITTEN`, `UNAVAILABLE`, `WRITE_ERROR`.

**Key format:** `careflow:<schema_version>:<operation>:<config_digest>:<input_digest>`,
built by `build_cache_key()`. `config_digest`/`input_digest` reuse
`ingestion.models.digest()` — the same canonical-JSON (`sort_keys`, compact
separators) SHA-256 convention already used for content addressing
throughout Phase 1–12 — never `hash()` (process-randomized) and never raw
query/record text placed directly in the key. Verified by test that dict
key ordering does not affect the resulting key, and that a distinctive raw
query substring never appears in the key it produces.

**Cache schema version:** `Settings.cache_schema_version`, default `"v1"`,
present in every key. Bumping it is the intended invalidation mechanism for
a future slice — `FLUSHDB`/`FLUSHALL` are never called anywhere in this
module (verified by test) and must not be introduced later either.

**Timeout policy:** two new, dedicated settings —
`cache_connect_timeout_seconds` and `cache_socket_timeout_seconds`, both
bounded `(0, 5]` seconds, default `0.5` each. Deliberately separate from
`health_timeout_seconds` (default 3s): a cache operation sits in the hot
request path, where a slow Redis must not dominate request latency, while
the health check is a periodic infrastructure probe that can tolerate more.
No automatic multi-attempt retry loop — one bounded operation per call, as
directed; a caller-level retry policy, if ever wanted, is future work.

**TTL contract:** `CacheClient.set()` requires an explicit, positive
`ttl_seconds`; `ttl_seconds <= 0` raises `InvalidCacheTTLError` before any
Redis I/O is attempted. No final TTL value is chosen for any specific
future cache candidate (embedding/retrieval/reranker/answer) in this
slice — the contract only guarantees no entry can be written without one.

**Serialization:** JSON only (`json.dumps`/`json.loads`), `sort_keys=True`
on write. No `pickle`, `eval`, or `marshal` anywhere in the module
(verified by test checking for actual import/call usage, not just the
absence of the word in a comment). A non-JSON-serializable value raises
immediately (a caller programming error), never silently coerced.

**Failure classification:** three tiers, verified against the real
`redis-py` 6.4.0 exception hierarchy — `redis.exceptions.ConnectionError`/
`TimeoutError` (both subclasses of `RedisError`) → `UNAVAILABLE`; any other
`RedisError` → `READ_ERROR`/`WRITE_ERROR`; a value that fails `json.loads`
→ `MALFORMED`. No raw Redis exception message or the Redis URL/credentials
is ever placed into a returned `CacheReadResult`/`CacheWriteResult` — both
dataclasses structurally contain only a status (+ value, for reads),
verified by test, including a test where the underlying exception message
itself contains a fake credential string.

**Client lifecycle:** one `CacheClient` per process, built by
`get_cache_client()` (`@lru_cache`, matching the exact existing idiom of
`get_settings()`/`load_embedding()`/`load_reranker()`). `redis-py`'s async
`Redis.from_url()` already returns a client backed by its own internal
connection pool, safe to share across concurrent coroutines within one
event loop — this module does not build a second pool on top of it, and
never constructs a fresh client per cache operation.
`reset_cache_client()` clears the singleton for test injection, mirroring
`get_settings.cache_clear()`'s existing convention.

**`check_redis()` left unchanged, duplication documented, not resolved:**
`backend/app/services/health.py::check_redis()` still builds its own
short-lived `Redis.from_url(...)` client per health check, using
`health_timeout_seconds` (default 3s) for both connect and socket timeout,
and closes it immediately via `async with`. This was deliberately **not**
switched to reuse `get_cache_client()`, because doing so would change real
behavior — a different timeout value (0.5s vs 3s) and a different
connection lifecycle (long-lived/reused vs. per-call/closed) — which is
broader than this slice's mandate of "leave `/health` semantics exactly
unchanged." The two Redis-client code paths remain intentionally separate
until a future health/readiness slice addresses this deliberately.

**What remains intentionally unintegrated:** every RAG stage (dense/BM25/
hybrid retrieval, reranking, generation), every structured tool, the
multi-agent graph, and the review workflow. `/health` is unchanged. No
metrics/logging integration beyond typed return values a future
observability layer can consume — this module itself never logs.

**Tests:** 37 pure tests (key determinism, all 5 read statuses, all 3 write
statuses, TTL validation, serialization round-trip, client reuse/reset,
credential-leak and pickle/flushdb/logging structural checks) plus 2 live
tests gated behind `CAREFLOW_CACHE_INTEGRATION=1` (full PING/write/HIT/
MISS/expiry round-trip against the real Redis container; an
unreachable-endpoint check proving `UNAVAILABLE` classification, using an
invalid port rather than stopping the real container).

## Slice 3: implemented central logging + request correlation

Built: [backend/app/observability/logging.py](../backend/app/observability/logging.py)
(central `log_event()` helper + `ContextVar`-based request-ID
propagation) and [backend/app/observability/middleware.py](../backend/app/observability/middleware.py)
(`RequestContextMiddleware`, wired into `main.py`).

**Seven duplicated helpers found and migrated, not six.** Slice 1's audit
(and this slice's own directive) named six: `agents/graph.py`,
`agents/structured_specialist.py`, `api/multi_agent.py`,
`api/orchestrate.py`, `api/reviews.py`, `reranking/service.py`. A
repository-wide re-scan at the start of this slice found a **seventh**,
byte-for-byte identical helper in `agents/validator.py` that both audits
missed — migrated identically to the other `agent_node_complete` emitters.
A final scan (`grep -rln 'json.dumps({.*"event"' backend/app/`) after
migration confirms zero remaining duplicates outside
`backend/app/observability/`.

**Migration strategy:** every one of the seven call sites keeps its exact
existing local function name (`_log`/`_log_event`) and call signature,
now implemented as a thin shim calling the central `log_event()` — this
made the migration mechanical (zero call-site changes in five of the seven
files) while still centralizing structure, serialization, and the
forbidden-field policy. `reranking/service.py` (which never had a wrapper
or a `request_id` parameter at all) now calls `log_event()` directly and
relies on the ambient request-ID context instead.

**Event envelope:** `log_event(logger, event, *, level=logging.INFO,
request_id=None, **fields)`. `request_id` defaults to the current
`ContextVar` value (`get_request_id()`) when not passed explicitly — the
mechanism that lets `reranking/service.py` correlate its logs without a
signature change. All existing field names/event names are preserved
exactly (`agent_node_complete`, `multi_agent_complete`,
`orchestration_complete`, `review_action_complete`, `reranking_complete`).
**Existing convention preserved exactly:** fields are emitted as given,
including explicit `None` values — this was verified against the actual
pre-migration code (every one of the seven already emitted explicit
`null`s for absent optional fields, never omitted the key), so this slice
does not introduce sparse/null-omitting events.

**Safe field policy (enforced, not just documented):** `FORBIDDEN_FIELD_NAMES`
is a bounded, explicit set (`query`, `question`, `answer`,
`generated_answer`, `final_summary`, `prompt`, `evidence`, `context`,
`context_text`, `citation_excerpt`, `citation_text`, `evidence_snapshot`,
`reviewer_reason`, `reason_text`, `free_text`, `cache_value`, `value`,
`redis_url`, `database_url`, `connection_string`, `authorization`,
`password`, `api_key`, `access_token`, `refresh_token`). A field whose name
matches has its value dropped (never logged, regardless of type) and is
listed by name only in a `_redacted_fields` array, so a caller mistake is
visible in the output rather than silently vanishing. This turns
`api/reviews.py`'s previous *comment* ("deliberately no evidence_snapshot,
...") into an *enforced* contract, verified by test for every listed name.

**Value normalization (never `default=str`):** `str`/`int`/`float`/`bool`/
`None` pass through unchanged; `UUID` → `str()`; `Enum` → its own value (if
JSON-safe) else `str()`; `list`/`dict` recursively normalized to depth 3;
anything else becomes a bounded `<unsupported:TypeName>` placeholder —
never the object's own `str()`/`repr()`, which could silently leak a
domain object's full content. Verified by test with a decoy object whose
`__str__` returns fake sensitive text, confirming it never appears in the
emitted JSON.

**Request-ID policy:** exactly one ID per HTTP request, established by
`RequestContextMiddleware` before the route handler runs. An inbound
`X-Request-ID` header is honored only if `uuid.UUID(value)` parses
successfully; anything else (missing, malformed, absurdly long) is
replaced with a freshly generated server UUID — untrusted header text is
never accepted into logs or the response header unvalidated. No
external trace-header convention (W3C traceparent, X-B3-*) is introduced.

**Eliminating duplicate-ID generation:** `api/multi_agent.py`,
`api/orchestrate.py`, and `api/reviews.py`'s `reviewable_query()` no longer
call `uuid4()` themselves — each now reads `get_request_id() or
str(uuid4())` (the fallback only matters for a bare unit-test call that
bypasses the app's middleware stack entirely). This means the ID in the
response body, in `MultiAgentState`/`GraphState["request_id"]` threaded to
every downstream node, and in every structured log line, is now
provably the *same* ID — verified by test comparing the `X-Request-ID`
response header against the `request_id` field of the actual
`orchestration_complete` log line emitted for that request.

**`ContextVar` lifecycle:** `set_request_id()`/`reset_request_id()`
(Token-based, mirroring stdlib `contextvars` convention exactly) plus a
`request_id_context()` context manager for convenience. Verified by test:
set/get, reset restores `None`, nested set/reset restores the *previous*
value (not `None`), two concurrent `asyncio.gather()`-scheduled tasks
never see each other's ID, no leak into the caller's context after a task
completes, and -- specifically because `reranking/service.py` is a sync
function that *could* be invoked via `asyncio.to_thread` inside whatever
LangGraph does internally for a sync node (an open question from Phase 12
Slice 5's concurrency analysis) -- a direct test confirming the ID
propagates correctly across an actual `asyncio.to_thread()` boundary, per
Python's documented `contextvars.copy_context()` behavior. A full
end-to-end verification through the real LangGraph-invoked call path was
not performed (out of scope for this logging-focused slice); the general
propagation mechanism itself is proven directly.

**Middleware behavior:** sets/resets the request-ID context for the
request's lifetime; adds an `X-Request-ID` response header (matches the
resolved/generated ID); on a genuinely unhandled exception (proven against
`/reviews` — the list/detail endpoints have no broad `try/except`, unlike
the three already-migrated POST endpoints which catch everything) logs one
`request_failed` event at ERROR level (method, path, `error_category`
class name, `duration_ms`) and **re-raises unchanged** — the existing
unhandled-exception → framework-default-500 behavior is not altered.
Never logs request/response bodies, query strings, or the Authorization
header (verified by source-pattern test, and the module has no code path
that reads any of them). Does not emit anything for ordinary
success/expected-error responses (avoiding duplicate logging of what each
endpoint's own migrated call already logs, and avoiding log spam from
`/health` — hit repeatedly by Docker's own healthcheck).

**Log-level policy:** the helper never infers level from field content —
always the caller's explicit choice (default `INFO`). Verified by test:
an expected abstention stays `INFO`, not `ERROR`; a cache `MISS` is never
logged as a warning by this module (Slice 2's cache module still does not
log at all); `WARNING`/`ERROR` are honored exactly when a caller passes
them.

**Current-Uvicorn visibility — empirically verified, not assumed, and this
slice does NOT fix it (per explicit instruction to stop and report rather
than add a global logging config):** started the real app
(`uvicorn app.main:app --log-level info`, the exact Dockerfile `CMD`) and
fired a real request through `/orchestrate` that reaches its migrated
`_log()` call. **The resulting `orchestration_complete` structured event
did not appear in the process's stdout/stderr — reproduced twice.**
Root-caused by direct introspection immediately after: the root logger has
zero handlers and its effective level is `WARNING` (Python's built-in
default); the only thing emitting anything at all is
`logging.lastResort`, a fixed-`WARNING`-level `stderr` handler. Uvicorn's
`--log-level info` flag configures only uvicorn's own
`uvicorn`/`uvicorn.access`/`uvicorn.error` loggers — it does not call
`logging.basicConfig()` or otherwise touch the root logger or any `app.*`
logger. **Consequence: every `log_event()` call at its default `INFO`
level is currently invisible under the real launch configuration** (an
explicit `level=logging.WARNING`/`ERROR` call, e.g. this slice's own
`request_failed` middleware event, is expected to reach `lastResort` and
become visible, based on the same level comparison, though this specific
positive case was not separately fired through the live server in this
slice). This is Slice 1's suspected gap, now confirmed, not resolved —
carried forward for a future, deliberately-scoped logging-configuration
slice.

**What remains unimplemented:** no metrics backend of any kind exists.
No distributed tracing exists. No RAG cache is active (Slice 2's cache
infrastructure is still not called from any request path). Retrieval,
reranking, provider, structured-tool, review-transaction, and health-check
business behavior are all unchanged — the only behavioral difference in
this slice is *where* a request's `request_id` value comes from (context
instead of a fresh per-handler `uuid4()` call) and the *addition* of one
new failure-path log line in middleware for routes that previously had
none.

**Tests:** 58 pure tests for the central logging module (envelope, all
normalization types, all `FORBIDDEN_FIELD_NAMES` entries individually,
credential-leak, cache-status-enum interop, log-level mapping, full
`ContextVar` lifecycle including the `asyncio.to_thread` propagation
proof) plus 14 middleware tests (request-ID generation/validation,
response header, downstream log correlation, the unhandled-exception
safety net, source-pattern checks for body/auth-header access, and both a
sequential and a genuinely concurrent -- via `httpx.ASGITransport` +
`asyncio.gather` -- multi-request isolation check).

## Slice 4: application logging configuration + real-runtime visibility

**The gap this closes:** Slice 3 established `log_event()` but, as
documented above, empirically found every `INFO`-level structured event
invisible under the real launch command (`uvicorn app.main:app --log-level
info`, the exact Dockerfile `CMD`) — root cause: the root logger has zero
handlers and effective level `WARNING`; Uvicorn's `--log-level info` only
configures its own `uvicorn`/`uvicorn.access`/`uvicorn.error` loggers, never
root or any `app.*` logger. This slice's problem statement was to make
those events actually observable, with the smallest possible explicit
configuration.

**Built:** [backend/app/observability/config.py](../backend/app/observability/config.py)
— `configure_logging(settings=None)`, called exactly once at
`backend/app/main.py`'s module-import boundary, before `app = FastAPI(...)`
is constructed (not per-request, not inside middleware).

**Logger scope:** configures only the `"app"` logger namespace — the common
parent of every `logging.getLogger(__name__)` call in this codebase, since
every module lives under `app.`. Never touches the bare root logger, never
touches `uvicorn`/`uvicorn.access`/`uvicorn.error`, and never raises a
third-party library (`httpx`, `psycopg`, `qdrant_client`) to `DEBUG` even
when `app` itself is configured to `DEBUG` — verified by test.

**Level:** a new bounded `Settings.log_level: Literal["DEBUG", "INFO",
"WARNING", "ERROR", "CRITICAL"]` field, default `"INFO"`. Pydantic rejects
any other string outright (verified for `"TRACE"`, wrong-case `"info"`,
empty string, `"99"`) — never a silent fallback to a default.

**Handler/formatter:** one `logging.StreamHandler(stream=sys.stdout)`,
tagged `.name = "careflow-app-handler"` so repeated `configure_logging()`
calls remove-and-replace it by name instead of accumulating duplicate
handlers (idempotent — verified by test). The formatter is exactly
`"%(message)s"` — a deliberate pass-through, since `log_event()` already
produces a complete JSON string as the log message; adding any other
formatter directive (e.g. a level or timestamp prefix) would have turned
each line into `{"message": "{...}"}`-style double-encoded JSON, breaking
direct parseability. This is why `log_event()`'s own envelope (Slice 3,
amended in this slice) carries its own `timestamp` field
(`datetime.now(UTC).isoformat()`, generated once per event, matching the
convention already used throughout `evaluation/*.py`) instead of relying on
a handler-level timestamp — `duration_ms` remains a separate,
`perf_counter()`-derived monotonic measurement, never confused with
wall-clock `timestamp`.

**Propagation:** `app_logger.propagate = False` — a deliberate choice, not
an accidental default. It guarantees each event is emitted exactly once
through this one handler, and immunizes against any future, unrelated
root-logger configuration ever causing a duplicate print of the same event.
A direct consequence (discovered while re-running the Slice 2/3 regression
suites): `caplog`, which relies on root-logger propagation, can no longer
observe events from any `app.*` logger. Three tests across
`tests/test_observability_middleware.py` (2) and the pre-existing
`tests/test_reranking.py` (1, from Phase 6/7) were rewritten to attach a
dedicated `io.StringIO`-backed handler directly to the `"app"` logger for
the test's duration instead — every original assertion was preserved
verbatim, none weakened.

**Real-runtime verification (not a unit-test mock):** repeated the exact
Slice 3 failure — a live `uvicorn app.main:app --log-level info` process, a
real `POST /orchestrate` request. With `configure_logging()` wired in, the
`orchestration_complete` event is now printed to stdout exactly once, as a
single directly-parseable JSON line, whose `request_id` field exactly
matches the `X-Request-ID` response header. Uvicorn's own startup, access,
and shutdown log lines all remained intact around it. A representative
sanitized event from that run:
`{"event": "orchestration_complete", "request_id":
"17dd5673-af70-4731-a0dd-4977a201c5d2", "timestamp":
"2026-09-25T21:22:53.456379+00:00", "route": "abstain", "tool": null,
"duration_ms": 5.58, "status": "abstained", "record_count": null,
"abstention_reason": "unsupported_request", "error_category": null}`.

**Idempotency and test-resettability:** calling `configure_logging()`
twice never duplicates handlers or output, and a later call with a new
`log_level` takes effect immediately (verified by test). A test-only
`reset_logging_for_tests()` restores `NOTSET` level / no handler /
`propagate=True`.

**What remains unimplemented:** no metrics backend of any kind exists. No
distributed tracing exists. No RAG cache is active. Retrieval, reranking,
provider, structured-tool, review-transaction, and health-check business
behavior are all unchanged — the only production behavior change in this
slice is that previously invisible `app.*` structured logs become visible
under the real runtime configuration.

**Tests:** 30 pure tests for `configure_logging()`/`reset_logging_for_tests()`
(visibility via `capsys`, per-level configuration, exactly-one-record
integrity, no double-JSON-encoding, timestamp presence/ISO-8601/UTC,
`duration_ms` vs `timestamp` distinctness, idempotency, level filtering,
invalid-level rejection, uvicorn/root/third-party non-mutation,
`propagate is False`, forbidden-field redaction still enforced under the
real handler), plus the 3 regression fixes described above. Full suite:
703 passed, 0 failed, 163 skipped.

## Slice 5: query-embedding cache — the first production cache integration

**Cache boundary:** exactly one — the numeric vector produced by embedding
a *query* string for retrieval. Nothing else is cached: not the final RAG
answer, not retrieved chunks, not BM25/hybrid/reranker output, not a
structured-tool result, not a document/corpus embedding.

**Why this boundary (audited before implementing, per this slice's own
directive):** `provider.embed([query])[0]` in
[ingestion/indexing/qdrant.py](../ingestion/indexing/qdrant.py)'s
`NCDIndex.search()` is the sole query-embedding call site, reached only
through `generation/runtime.py::retrieve()` → `Retriever.search(...,
for_rag=True)`. `for_rag=True` forces the embedding step even for a
non-dense mode, and this session's confirmed production runtime config is
`retrieval_mode=dense` (restated from Slice 1, not changed here) — dense
mode always requires it. So this stage is exercised by *every* production
RAG request, not a conditional path. It is also deterministic for a fixed
model/revision/config: `SentenceTransformerEmbedding` pins an exact model
revision, runs on CPU in `eval()` mode with no dropout, and its `describe()`
method already serves as this codebase's existing embedding-identity
fingerprint (compared with `!=` against each indexed point's stored
config in `NCDIndex.search()` itself). A separate call site,
`ingestion/pipeline.py:32`, embeds *documents* through a different
`SentenceTransformerEmbedding` instance never touched by this slice —
confirmed by direct code search before writing any cache code, so document/
corpus embeddings could not accidentally be caught by this integration.

**Integration point:** a wrapper, not a change to the model or to
`NCDIndex.search()`. `backend/app/generation/embedding_cache.py`'s
`CachingQueryEmbedding` implements the same `describe()`/`embed()`/
`tokenizer` surface as `EmbeddingProvider` and delegates to the real
provider. `generation/runtime.py::retrieve()` wraps `load_embedding()`'s
return value with it only when `settings.query_embedding_cache_enabled` is
true — `load_embedding()` itself (and its existing `@lru_cache` singleton,
relied on by pre-existing tests) is completely untouched, so when the
cache is disabled the code path is not merely equivalent to pre-Slice-5
behavior, it is *the exact same code path*.

**A second, synchronous cache client:** `retrieve()` runs fully
synchronously end-to-end, including from inside a LangGraph-offloaded
worker thread for `policy_node` (a sync node with no ambient asyncio event
loop — the same threading characteristic Slice 3 already documented for
`reranking/service.py`'s logging). Driving Slice 2's `CacheClient`
(`redis.asyncio.Redis`) from there would need an `asyncio.run()` per call,
and an async Redis client's connection pool is bound to whichever event
loop was active when it first connected — reusing one process-level async
client across many independently-created event loops risks
"Future attached to a different loop" failures. Rather than accept that
fragility, `backend/app/infrastructure/cache.py` gained `SyncCacheClient`:
the same `CacheReadStatus`/`CacheWriteStatus`/`CacheReadResult`/
`CacheWriteResult` contract and the same `build_cache_key()`, over
redis-py's plain synchronous `Redis` client. `CacheClient` (async) is
unchanged and remains the right choice for any future cache candidate
reached from genuinely async code.

**Cache key:** `build_cache_key(operation="query_embedding",
config_fingerprint=provider.describe(), input_fingerprint={"query": text},
schema_version=settings.cache_schema_version)`. The entire `describe()`
dict is used as the config fingerprint (model, revision, dimension,
normalization, query-input convention, long-text/windowing strategy,
package versions) rather than a hand-picked subset — any change to any of
those automatically invalidates via a different key, with no risk of an
engineer forgetting to add a new field to a hand-maintained list later.
`input_fingerprint={"query": text}` is digested (SHA-256 over canonical
JSON), never placed raw in the key string — verified by test that no
substring of a representative query appears in the generated key.

**Payload schema (versioned independently of the key's
`cache_schema_version`):** `{"schema_version": "v1", "model": ...,
"revision": ..., "dimension": ..., "embedding": [...]}`. Only the derived
numeric vector plus minimal model-identity metadata is stored — never the
query text, an answer, evidence, or any patient/claim record.
`_validate_query_embedding_payload()` rejects, before any value is
trusted: a non-dict, a wrong/foreign `schema_version`, a `model` or
`dimension` mismatch against the *current* provider, a non-list or
wrong-length `embedding`, a boolean masquerading as numeric (JSON `bool`
is a Python `int` subclass — excluded explicitly), any non-numeric
element, and any non-finite value (`NaN`/`Infinity`/`-Infinity` — `json.
loads` accepts these as literal floats by default, so this check is not
redundant). A payload failing any of these checks is treated exactly like
Slice 2's own `MALFORMED` status: recomputed, never used, best-effort
replaced.

**TTL:** `query_embedding_cache_ttl_seconds`, default 86400 (one day),
bounded to at most 604800 (seven days) — a new explicit `Settings` field,
enforced positive by Slice 2's own contract. A day balances cache benefit
for repeated identical policy questions within normal usage against
unbounded Redis growth from a long tail of distinct queries; model/config
changes already invalidate via the key itself, so this TTL is about
bounding storage and the query distribution's staleness, not correctness.

**Enable/disable switch:** `query_embedding_cache_enabled`, **default
`false`** — a deliberate choice for this first cache integration, so
existing tests, local development, and any environment that has not
explicitly opted in see exactly pre-Slice-5 behavior. When disabled: zero
Redis reads, zero Redis writes (`get_sync_cache_client()` is never even
constructed — verified by a test that makes calling it raise), and the
retrieval path uses the unwrapped `load_embedding()` singleton directly.

**Failure semantics (Redis is an OPTIONAL PERFORMANCE DEPENDENCY here
too):** HIT → cached vector used, model never called, no write. MISS →
model called, fresh vector returned, best-effort write with the explicit
TTL. UNAVAILABLE / READ_ERROR → model called, fresh vector returned, *no*
write attempted (Redis has already demonstrated it is not answering; a
second round-trip would only add latency, not benefit). MALFORMED
(Slice-2-level JSON-parse failure, or this slice's own schema-validation
failure on an otherwise-valid JSON value) → model called, fresh vector
returned, best-effort replace attempted. WRITE_ERROR → the freshly computed
vector is still returned normally; nothing distinguishes a caller's
observable behavior from a successful write except the logged
`cache_write_status`. A real embedding-model failure is never caught by
this module at all (`embedding_cache.py` contains no `except` clause of
its own — verified by test) and propagates exactly as it did before this
slice existed.

**Observability:** one `query_embedding_cache` event per embedded query,
via Slice 3/4's `log_event()`: `cache_status` (`hit`/`miss`/`unavailable`/
`read_error`/`malformed`), `cache_write_status` (`written`/`unavailable`/
`write_error`/`null` when no write was attempted — kept as a separate
field, never overloading `cache_status`, so a `MISS` that was
successfully written is never relabeled `HIT`), `operation`,
`embedding_dimension`, and `duration_ms` (the cache decision's own
`perf_counter()`-measured time, not an end-to-end or model-inference
claim). Never logs the query, the cache key, or the embedding vector —
verified by test against real captured log output for both a `HIT` and a
`MISS`.

**Concurrency (accepted limitation, not built in this slice):** no
distributed lock or single-flight mechanism exists. Two concurrent MISSes
for the same key may each compute and write independently; the second
write simply overwrites the first with an equivalent value (the embedding
is deterministic for the same input/config), so this does not produce
incorrect results, only avoidable duplicate computation under contention.

**Verification:** pure tests cover keying determinism, HIT/MISS/
UNAVAILABLE/READ_ERROR/WRITE_ERROR/MALFORMED behavior (including eleven
distinct malformed-payload shapes), the disabled path (both "Redis client
never even constructed" and "the exact unwrapped object is used"), and
security/privacy structural checks. A live test against the real Redis
container proves a second identical call is served from cache with no
second model computation, a positive TTL, and no raw query text in the
stored value. A real end-to-end test through `POST /orchestrate` (real
Postgres/Qdrant/Redis, the real embedding model) proves the first request
logs `cache_status=miss` and the second logs `cache_status=hit`, each
correlated to its own `X-Request-ID`, with identical `answer`/`citations`
in both responses. A retrieval-equivalence test over two representative
policy questions confirms retrieved chunk IDs and order are identical
whether the cache is disabled, cold, or warm — the cache changes
performance behavior only, never retrieval semantics.

**What remains uncached:** final RAG answers, retrieved chunks/results,
BM25/hybrid results, reranker results, structured-tool results,
multi-agent responses, review results, and document/corpus embeddings. No
metrics backend exists. No distributed tracing exists. `/health` is
unchanged (Redis's health/readiness semantics remain deferred, per Slice
1). Retrieval, reranking, provider, structured-tool, review-transaction,
and health-endpoint business behavior are unchanged — the only production
behavior change in this slice is that a repeated identical query, with
this cache explicitly enabled, can skip recomputing its embedding.

**Tests:** 32 pure tests in `tests/test_query_embedding_cache.py` plus 16
new pure `SyncCacheClient` tests added to `tests/test_infrastructure_cache.py`
(mirroring the async `CacheClient` tests exactly), plus 3 live tests (2
gated behind `CAREFLOW_ORCHESTRATION_INTEGRATION=1`, 1 behind
`CAREFLOW_CACHE_INTEGRATION=1`). Full suite: 751 passed, 0 failed, 166
skipped.

## Slice 6: liveness/readiness semantics + bounded operational metrics

**Existing health audit (verified from code before changing anything):**
[backend/app/services/health.py](../backend/app/services/health.py)'s
`check_dependencies()` probes Postgres, Qdrant, and Redis together in
parallel (`asyncio.gather`, each bounded by `health_timeout_seconds`) and
[backend/app/api/health.py](../backend/app/api/health.py)'s `/health`
returns `200`/`status="ok"` only if all three are `"ok"`, else
`503`/`"degraded"`. This confirms Slice 1's finding exactly: `/health`
behaves like **readiness**, not process liveness, and additionally treats
Redis as if it were authoritative — contradicting Phase 13's own standing
"Redis is an OPTIONAL PERFORMANCE dependency" principle. The Dockerfile's
`HEALTHCHECK` (`--interval=10s --retries=3`) targeted `/health`, so roughly
30+ seconds of Redis-only unavailability was enough to flip the container
to Docker's "unhealthy" state, even though the API remains fully able to
serve authoritative (Postgres/Qdrant-backed) requests throughout. Compose's
`backend.depends_on` (Postgres/Redis: `service_healthy`, Qdrant:
`service_started`) governs container *start order* only, using each
dependency's own container-level healthcheck (`pg_isready`, `redis-cli
ping`) — unrelated to `/health`'s HTTP contract and unchanged by this
slice.

**Liveness definition:** "Is the CareFlow API process itself alive and
capable of serving HTTP?" No dependency, no I/O, no network call.

**Readiness definition:** "Are the dependencies required for CareFlow's
normal, authoritative application behavior available?"

**Dependency classification:**
- **Postgres — authoritative.** Backs every structured healthcare tool and
  all review/HITL persistence; unavailable means an entire major supported
  workflow (structured queries, review actions) cannot function correctly.
- **Qdrant — authoritative.** Backs every retrieval mode, including
  `bm25`/`hybrid`, which still load the corpus from Qdrant
  (`NCDIndex.load_corpus()`); unavailable means the entire policy/RAG
  workflow cannot function correctly.
- **Redis — optional**, per Phase 13's standing principle since Slice 2.
  Its status is still probed and reported for operational visibility, but
  it never gates readiness.

**`GET /live`:** [backend/app/api/health.py](../backend/app/api/health.py)
— returns a static `{"status": "alive", "service": "careflow-ai"}`, `200`,
always, with zero dependency calls (verified by test: all three probes
mocked to raise, `/live` still returns `200`, and the probes are never
even awaited). No internal configuration exposed.

**`GET /ready`:** [backend/app/services/health.py](../backend/app/services/health.py)'s
new `check_readiness()` probes all three dependencies (reusing the exact
same bounded `_probe()` helper `check_dependencies()` uses — extracted
from it without changing `check_dependencies()`'s own observable behavior,
verified by the full pre-existing `/health` test suite passing unchanged)
but computes `status="ready"` from `postgresql == "ok" and qdrant == "ok"`
only. Redis's probed status still appears in the response's `dependencies`
dict, explicitly documented (in `ReadinessResponse`'s own docstring) as
informational-only. `200` when ready, `503` when not — verified by test
for each of: all healthy, Postgres down, Qdrant down, Redis down alone
(readiness unaffected), and Postgres+Redis both down with Qdrant up (still
unready, because of Postgres).

**Partial-functionality rule (deliberately coarse, not per-workflow):**
readiness is a single binary decision — unready if *either* Postgres or
Qdrant is unavailable — rather than exposing separate per-workflow
readiness (e.g. "policy workflow ready" vs. "structured workflow ready").
Justification: each authoritative dependency backs an entire major
supported workflow end-to-end, so its unavailability is already a
significant, orchestrator-worth-signaling degradation; building
finer-grained per-component readiness is explicitly out of scope for this
slice (see Slice 6's own directive).

**`/health` backward compatibility:** completely unchanged in observable
behavior — same three-dependencies-required contract, same `200`/`503`
codes, same response shape. `check_dependencies()`'s body was refactored
to share the extracted `_probe()`/`_probe_all()` helpers with
`check_readiness()`, but this is an internal implementation change only;
all 11 pre-existing `tests/test_health.py` tests pass unchanged, with no
assertion touched.

**Docker `HEALTHCHECK` — changed, deliberately:** switched from `/health`
to `/ready` (see [backend/Dockerfile](../backend/Dockerfile)). Consequence:
a Redis-only outage no longer flips the container to "unhealthy" (previously
it did, after ~30s); a genuine Postgres or Qdrant outage still does, exactly
as before. This was reasoned through, not applied automatically. Verified
by direct HTTP testing (the exact HEALTHCHECK command line — `python -c
"import urllib.request; urllib.request.urlopen(...)"` — run against
`/ready` on a locally-launched instance of the updated app connected to
the real Postgres/Qdrant/Redis, returning `200`) — **not** by rebuilding
and restarting the actual shared `careflow-ai-backend-1` Docker container,
since that container's currently-running image predates this slice's code
entirely (confirmed: it 404s on `/live`/`/ready`) and rebuilding/restarting
a shared long-running container was judged out of proportion for this
slice's verification needs. This is an explicit, disclosed limitation, not
a claim that the container-level `HEALTHCHECK` wrapper itself was
exercised.

**Metrics architecture:** `prometheus_client` is not a project dependency
(confirmed by inspection before writing any code) and is deliberately not
added. [backend/app/observability/metrics.py](../backend/app/observability/metrics.py)
is a small, fixed, thread-safe in-process registry — not a generic metrics
library and not a monitoring platform: `_Counter` (label tuple → int) and
`_LatencyAggregate` (label tuple → count/sum/min/max/bucket counts over a
fixed small bucket set, `_LATENCY_BUCKETS_MS = (5, 10, 25, 50, 100, 250,
500, 1000, 2500, 5000)` ms, exclusive not cumulative). No raw observation
is ever retained; storage is bounded by the product of each label's own
bounded vocabulary, never by request volume. No percentile (p50/p95/p99)
is computed or exposed from the bucket data — doing so would claim
precision this coarse a layout does not have.

**Metric names (the complete, fixed set):** `http_requests_total`
(method, route, status_class), `http_errors_total` (method, route),
`http_request_duration_ms` (method, route), `query_embedding_cache_reads_total`
(cache_status), `query_embedding_cache_writes_total` (write_status),
`query_embedding_cache_duration_ms` (unlabeled).

**Metric cardinality policy:** every label is drawn from a small, fixed
vocabulary known at call time. `method`: bounded by the HTTP protocol/
FastAPI's declared route methods. `route`: the matched route's own
registered path TEMPLATE (e.g. `/reviews/{review_id}/decision`), read from
`request.scope["route"].path` *after* `call_next()` returns (Starlette's
router sets this in place on the request's own scope dict once a route
matches) — never `request.url.path`; an unmatched path (404, or any
routing failure) falls back to the single bounded literal `"unmatched"`.
`status_class`: `"{code // 100}xx"`. `cache_status`/`write_status`: Slice
2's own bounded `CacheReadStatus`/`CacheWriteStatus` enum values.
**Forbidden as labels, by construction** (no code path in `metrics.py`
accepts one): `request_id`, raw URL/path with embedded IDs, query text,
patient/beneficiary/claim/review IDs, cache keys, chunk IDs, exception
messages, tool arguments — verified by test (a distinctive review ID, a
distinctive query string, a distinctive Authorization-header value, and
the real per-request `X-Request-ID` are each confirmed absent from a live
metrics snapshot after a real request using them).

**HTTP error semantics:** `http_errors_total` increments for an HTTP `5xx`
response status *or* an uncaught exception (the same event
`request_failed` already logs) — never for a `4xx` validation error, a
`404`, or an ordinary abstention (which is a `200`). Verified by test:
a 422 validation error, a 404, and a 200 abstention all leave
`http_errors_total` empty; an unhandled exception and a direct 5xx both
increment it exactly once.

**Probe/self-observation exclusion policy:** `/live`, `/ready`, `/health`,
and `/metrics` are excluded from `http_requests_total`/
`http_request_duration_ms`/`http_errors_total` — a fixed, literal
4-path set checked in `RequestContextMiddleware`, to avoid Docker's
10-second `HEALTHCHECK` probe traffic (and any future `/metrics` scraper)
being counted as ordinary application request volume. Verified by test.

**Cache metrics:** `query_embedding_cache_reads_total` increments exactly
once per embedded query with the resolved `cache_status`
(`hit`/`miss`/`unavailable`/`read_error`/`malformed`, matching Slice 5's
own status resolution exactly — including the "valid JSON, wrong shape"
case mapping to `malformed`); `query_embedding_cache_writes_total`
increments only when a write was actually attempted (`written`/
`unavailable`/`write_error`), never for a status where Slice 5's own logic
already skips the write (`unavailable`/`read_error` reads). Verified by
test for every one of Slice 5's documented failure-mode branches.

**Latency:** `http_request_duration_ms` reuses the middleware's own
`perf_counter()` span (request-in to response-out, the same boundary
already used for the `request_failed` log event's `duration_ms`).
`query_embedding_cache_duration_ms` reuses exactly the cache-decision span
Slice 5's `query_embedding_cache` log event already measures — not claimed
as end-to-end RAG latency, and not instrumented at any other internal
function boundary.

**Metrics endpoint:** `GET /metrics`
([backend/app/api/metrics.py](../backend/app/api/metrics.py)) returns the
bounded JSON snapshot above. Explicitly documented (in the route's own
docstring) as **not** Prometheus exposition format — this project has no
`prometheus_client` dependency and makes no conformance claim. No auth
layer exists anywhere in this project; a real deployment would normally
restrict or authenticate an observability endpoint like this one, which is
explicitly out of scope for this slice — the endpoint's content is kept
deliberately non-sensitive (bounded aggregates only) as the compensating
control for now.

**Concurrency/resettability:** all metric mutation goes through `threading.Lock`-
guarded methods, verified by concurrent-increment tests (20 threads ×
200 increments/observations, no lost updates). `reset_metrics_for_tests()`
is test-only — verified by a source-scan test that no file under
`backend/app/api/` ever references it, so it can never become reachable
over HTTP.

**What remains unimplemented:** no distributed tracing, no OpenTelemetry,
no Prometheus server integration, no Grafana/Datadog/Sentry integration,
no percentile/quantile computation, no per-workflow readiness, no metrics
authentication. `/health`'s Redis-required legacy quirk is preserved, not
fixed (by design — see "backward compatibility" above). Retrieval,
reranking, provider, citations, abstention, structured tools, multi-agent,
review/HITL, review transactions, and query-embedding cache semantics are
all unchanged — the only production behavior changes in this slice are
new liveness/readiness endpoints, the Docker `HEALTHCHECK` target, and new
(additive, opt-in-to-observe) operational metrics.

**Tests:** 17 pure tests for the metrics primitives
(`tests/test_observability_metrics.py`: counter/aggregate correctness,
bucket boundaries, concurrency, reset, resettability-not-exposed), 12 for
liveness/readiness (`tests/test_liveness_readiness.py`), 13 for HTTP
metrics integration (`tests/test_http_metrics.py`), and 7 new cache-metrics
tests added to `tests/test_query_embedding_cache.py`. All previously
existing tests (`tests/test_health.py`, Slice 2-5 regressions) pass
unchanged. Full suite: 800 passed, 0 failed, 166 skipped.

## Slice 7 (final): reliability hardening, failure injection, Phase 13 checkpoint

This slice added no new feature. It proved Slices 1–6's architecture
behaves correctly under real and simulated failure, closed one disclosed
gap, and is the final Phase 13 checkpoint before commit.

**Documentation reconciliation:** all six slices' sections were confirmed
present on disk (Slice 1's content is the document's foundational audit
body; Slices 2–6 each have an explicit `## Slice N` section). Spot-checked
current code against documented behavior for Redis optionality, cache
statuses, logging, request IDs, log configuration, the query-embedding
cache, TTL/enable defaults, `/live`/`/ready`/`/health`, the Docker
`HEALTHCHECK` target, and metrics/cardinality — no drift found; nothing
required correction.

**Final configuration defaults (all Phase 13 settings):**
`cache_connect_timeout_seconds=0.5s` (bounded 0–5s), `cache_socket_timeout_seconds=0.5s`
(bounded 0–5s), `cache_schema_version="v1"`, `log_level="INFO"` (bounded to
the 5 standard levels), `query_embedding_cache_enabled=false`,
`query_embedding_cache_ttl_seconds=86400s` (bounded 0–604800s). All
`Field`-bounded and Pydantic-validated; none embeds a credential; all
override correctly through the existing `.env`/environment-variable
`Settings` mechanism (verified by test, matching the pre-existing
`HEALTH_TIMEOUT_SECONDS` convention); no duplicate or conflicting setting
names exist.

**Failure matrix (derived from current architecture, not invented):**

| Component | `/live` | `/ready` | `/health` | Policy/RAG request | Structured (Postgres) request | Query-embedding cache | Metrics/logging |
|---|---|---|---|---|---|---|---|
| Redis down | 200 | 200 (optional) | 503/degraded (legacy) | succeeds (cache UNAVAILABLE, authoritative compute) | unaffected | `cache_status=unavailable`, no write attempt | recorded, no leak |
| Postgres down | 200 | 503 | 503/degraded | succeeds (does not depend on Postgres) | fails with existing bounded `orchestration_unavailable` semantics | unaffected | recorded, no leak |
| Qdrant down | 200 | 503 | 503/degraded | fails with existing bounded `retrieval_unavailable` (503) semantics | succeeds (does not depend on Qdrant) | unaffected | recorded, no leak |
| Embedding provider fails | 200 | 200 (not probed by readiness) | 200 | fails — the real exception propagates through `retrieve()`'s existing `except Exception -> GenerationError("retrieval_unavailable", 503)`, never masked as a cache-shaped result | unaffected | exception propagates unmodified regardless of concurrent cache status (MISS/UNAVAILABLE/READ_ERROR) — never misclassified as a cache failure; a HIT never invokes the provider at all | n/a |

**Failure-injection results — all verified, all matched the matrix above
exactly:**
- **Redis (real, invalid-endpoint isolated process):** `/live` 200,
  `/ready` 200 (Postgres/Qdrant `ok`, Redis `unavailable`), `/health` 503/
  `degraded`. A real `POST /orchestrate` policy question succeeded (200,
  real answer+citations) with `query_embedding_cache_enabled=true`; the
  structured `query_embedding_cache` event logged `cache_status=unavailable`,
  `cache_write_status=null` — bounded by `cache_connect_timeout_seconds`
  (no retry storm, no long stall: the cache decision itself took ~125ms).
- **Postgres (real, invalid-endpoint isolated process):** `/live` 200,
  `/ready` 503, `/health` 503. A policy-only request still succeeded
  (200) — per this slice's explicit instruction, readiness is deployment
  health, not a gate on every endpoint; a policy question genuinely does
  not touch Postgres. A structured SynPUF request failed with the
  pre-existing, unchanged `orchestration_unavailable` (503) — not a new
  failure mode. No credential/connection-string leaked in any response or
  log line (grepped and confirmed absent).
- **Qdrant (real, invalid-endpoint isolated process):** `/live` 200,
  `/ready` 503. A policy request failed with the pre-existing, unchanged
  `retrieval_unavailable` (503). A structured SynPUF request (Postgres-only)
  succeeded normally. No raw Qdrant URL/exception detail leaked.
- **Embedding provider failure (pure tests,
  `tests/test_phase13_resilience.py`):** a provider configured to raise
  propagates that exact exception through `CachingQueryEmbedding.embed()`
  unmodified, whether the cache read was a MISS, UNAVAILABLE, or
  READ_ERROR — never absorbed, never reinterpreted as a cache-shaped
  outcome. A HIT never invokes a provider configured to raise at all. At
  the `retrieve()` level, the same failure surfaces as the exact
  pre-Phase-13 `GenerationError("retrieval_unavailable", 503)` — caching
  introduces no new failure mode for this path.
- **Malformed cache data (reconfirmed):** never used as an authoritative
  vector; the request still succeeds via fresh computation.

**Real Docker verification (closes Slice 6's disclosed gap):** rebuilt
only the `backend` image from the current working tree
(`docker compose build backend`; Docker's own layer cache made this fast
since `pyproject.toml`/the lockfiles were untouched) and recreated only
that one container (`docker compose up -d --no-deps backend`) — Postgres/
Qdrant/Redis containers and their named volumes (`careflow-ai_postgres_data`,
`careflow-ai_qdrant_data`, `careflow-ai_redis_data`) were never stopped,
recreated, or touched (`docker ps` confirms their uptime was unaffected).
Docker's own `HEALTHCHECK` reported the rebuilt container `"healthy"`
within one probe cycle (`docker inspect`, exit code 0), and its baked-in
`Config.Healthcheck.Test` was confirmed to target `/ready`. Direct
requests against the rebuilt container's exposed port: `/live` 200,
`/ready` 200, `/health` 200, `/metrics` 200 with the expected bounded JSON
shape.

**Concurrency:** 20 threads × 200 increments/observations against
`_Counter`/`_LatencyAggregate` (Slice 6) confirm no lost updates. 20
threads concurrently calling `CachingQueryEmbedding.embed()` for the
identical query confirm: no exception escapes any thread, and — the
accepted Slice 5 limitation reconfirmed, not fixed — the cache ends up
with exactly one well-formed, schema-valid stored entry (never a torn or
partially-written payload; concurrent MISSes may each independently
compute, but the deterministic embedding means the last write is always
equally valid).

**Request-ID / cache privacy (reconfirmed together):** a distinctive
ambient request ID is confirmed absent from both the generated cache key
and the stored payload. A live controlled round-trip against real Redis
confirmed (yet again): the key contains no raw query text (SHA-256
digested), the stored value contains only `schema_version`/`model`/
`revision`/`dimension`/`embedding` (no raw query, no request ID), the
entry's TTL is positive, and the test's own key was deleted afterward
(zero stray keys after cleanup, confirmed by `KEYS careflow:*` on the real
Redis instance) — no vector value is printed in this report.

**Security scan (Phase 13 changed files only, each match reviewed
contextually, not by raw substring count):** no `pickle`/`marshal`/`eval(`/
`FLUSHDB`/`FLUSHALL` usage anywhere (only comments/tests documenting their
absence); no Python `hash()` used for a cache key (only a test asserting
this); every `redis://`/`postgresql://` string found is either the
pre-existing local-dev `SecretStr` default (redacted from `repr()`/JSON
dump, verified by existing test) or a test fixture deliberately
constructing a fake credential string to prove it is redacted, never a
real leaked credential; `"authorization"` appears only in
`FORBIDDEN_FIELD_NAMES` and tests proving it is never logged; no
machine-specific absolute path exists in any Phase 13 file.

**PHI/compliance language check:** the document already states, verbatim,
that it "does **not** claim HIPAA compliance" (Slice 1's Privacy
boundaries section) and that CareFlow's data is public CMS policy text
plus synthetic DE-SynPUF/Synthea data — no PHI. No file in this project
claims HIPAA certification, PHI-safety, clinical validation, or coverage-
determination authority. This distinction is preserved, not newly added.

**Final health/metrics contract (code, tests, and documentation agree):**
`/live` — process only, zero dependencies. `/ready` — Postgres + Qdrant
authoritative (`status="ready"` iff both `ok`), Redis reported but
never gates it. `/health` — legacy, unchanged, all three required. Docker
`HEALTHCHECK` — `/ready`, verified against the actual rebuilt container.
`/metrics` — unauthenticated (documented deployment limitation, not fixed
in this slice, per explicit instruction), bounded aggregates only.

**What Phase 13 explicitly does NOT provide** (stated for anyone building
on this branch later): no distributed tracing, no external metrics
backend (Prometheus/Grafana/Datadog/Sentry), no metrics authentication, no
cache single-flight/distributed locking, no general multi-stage caching
(query embeddings only — one boundary, by design), no production
autoscaling, and no HIPAA certification or compliance claim of any kind.

**Tests:** 10 new targeted resilience tests
(`tests/test_phase13_resilience.py`) closing the embedding-failure-
misclassification and cross-cutting concurrency/privacy gaps that no
existing per-slice file covered — everything else in this checklist
reuses Slices 2–6's already-comprehensive existing suites rather than
duplicating them. Full suite: 810 passed, 0 failed, 166 skipped. Live
regression (Redis round-trip, invalid-endpoint classification, query-
embedding cache round-trip, real request-path MISS→HIT, retrieval
equivalence): 5/5 passed.
