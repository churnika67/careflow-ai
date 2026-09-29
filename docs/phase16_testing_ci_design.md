# Phase 16 — Testing / CI design

## Slice 1 — Audit + test matrix + CI design foundation

Phase 16's goal is to improve confidence in the existing CareFlow
application — not to add product features. Slice 1 is primarily an audit
and a design document; the only code change permitted is a small,
justified test-isolation fix if the audit found a real bug (see "Flaky
test audit").

### 1. Starting baseline (this slice)

- Frontend: 309 passed, 0 failed (`npm test`); `npm run lint`, `npm run
  typecheck`, `npm run build` all clean; all 9 routes present in the build
  output.
- Backend: 830 passed, 169 skipped, 0 failed (`python -m pytest tests/
  -q`); `ruff check .` and `ruff format --check .` clean (162 files);
  `pip check` clean.
- Production invariants (read-only verified): Qdrant 39 points; SynPUF 15
  beneficiaries / 219 claims / 732 diagnoses / 29 procedures / 848 lines;
  FHIR 5 patients / 177 encounters / 187 conditions / 234 procedures /
  1341 observations / 865 components / 116 medication requests; Review 4
  cases / 8 events.

### 2. No GitHub repository or CI yet

`git remote -v` returns nothing — this project has never been pushed to
GitHub. `.github/workflows/` exists but contains only a `.gitkeep`
placeholder; no workflow YAML exists anywhere in the repository. This
means Phase 16's CI work is necessarily **design-first**: a workflow can
be authored and reviewed, but it cannot actually execute anywhere until
the repository is pushed to a GitHub remote (out of this phase's scope
unless explicitly instructed).

### 3. Frontend route coverage matrix

All 9 routes have component-level (Vitest + Testing Library, jsdom) test
coverage. No route has browser E2E coverage (see §10 — no E2E framework
is installed at all). Test counts below are `it(` occurrences, cross-
verified independently.

| Route | Test file | Tests | Loading | Success | Error | Empty/abstention | Readiness-gating | Interaction |
|---|---|---:|---|---|---|---|---|---|
| `/` | `SystemOverview.test.tsx` | 6 | Yes | Yes | Yes | n/a (page itself is the status surface) | No (nothing to gate) | No |
| `/ask` | `AskCareFlow.test.tsx` | 13 | Yes | Yes | Yes | Yes | Yes (Qdrant-blocks, Redis-permissive) | Yes |
| `/assistant` | `Assistant.test.tsx` | 15 | No | Yes | Yes | Yes (4 abstention variants) | Yes | Yes |
| `/patient-data` | `PatientData.test.tsx` | 11 | Yes | Yes | Yes | Yes (both empty-result and unknown-ID) | Yes | Yes |
| `/claims` | `Claims.test.tsx` | 11 | Yes | Yes | Yes | Yes (both) | Yes | Yes |
| `/workflow` | `Workflow.test.tsx` | 25 | Implicit only | Yes | Yes | Yes (validator failure, partial specialist failure) | Yes | Yes |
| `/reviews` | `ReviewQueue.test.tsx` | 10 | No | Yes | Yes | Yes (empty queue) | Yes (both directions) | Yes |
| `/reviews/[reviewId]` | `ReviewDetail.test.tsx` | 18 | No | Yes | Yes | Yes (not-found) | Partial (blocks only; no explicit "allows" case) | Yes |
| `/analytics` | `Analytics.test.tsx` | 25 | Yes | Yes | Yes | Yes (empty aggregates, not-evaluated) | **No** | **No** |

Cross-cutting, not mapped to one route: `Sidebar.test.tsx` (6 tests, nav
active-state), `datasetSeparation.test.tsx` (3 tests, cross-route
FHIR/SynPUF identifier-isolation assertions).

**Gaps this matrix surfaces:**
- `/analytics` has zero readiness-gating tests and zero interaction tests
  (all 25 tests are render/assert-only — no `userEvent` call anywhere in
  the file). This is a real, specific gap: the page does have retry
  buttons (`ErrorPanel`'s Retry) and a `<details>` disclosure that are
  never exercised via simulated interaction, and its two independent
  readiness policies (`isEvaluationSnapshotAllowed`,
  `isStructuredAnalyticsAllowed`) are exercised only indirectly (through
  their unit-level readiness modules, not through an Analytics-level test
  proving the panel actually blocks/unblocks).
- `/`, `/reviews`, `/reviews/[reviewId]` have no explicit loading-state
  test (the closest is a duplicate-submission-prevention test on some
  pages).
- `/workflow` has no dedicated loading-state test either (only implicit
  coverage via the duplicate-submission test).

### 4. Backend API endpoint coverage matrix

Routers registered in `backend/app/main.py`: `health_router`,
`metrics_router`, `query_router`, `orchestrate_router`,
`multi_agent_router`, `reviews_router`, `analytics_router`.

| Endpoint | Test file(s) | Success | 422 | Failure (5xx/dep-down) | Live-gated |
|---|---|---|---|---|---|
| GET `/health` | `test_health.py`, `test_liveness_readiness.py` | Yes | Yes | Yes | No |
| GET `/live` | `test_liveness_readiness.py`, `test_cors.py` | Yes | n/a | n/a (never fails by design) | No |
| GET `/ready` | `test_liveness_readiness.py` | Yes | n/a | Yes (postgres/qdrant/redis-down combinations) | No |
| GET `/metrics` | `test_http_metrics.py` | Yes | n/a | n/a | No |
| POST `/query` | `test_basic_rag.py`, `test_basic_rag_live.py` | Yes | Yes | Yes (`GenerationError`→502/503/504) | Yes — `CAREFLOW_RAG_INTEGRATION` |
| POST `/orchestrate` | `test_orchestration_api.py` (+graph/classify/tools unit files) | Yes | Yes | Abstention paths yes; **no API-level 502/503/504 test through the route handler** | Yes — `CAREFLOW_ORCHESTRATION_INTEGRATION` |
| POST `/multi-agent` | `test_agents_api.py` (+graph/supervisor/validator/specialist unit files) | Yes | Yes | Same gap as `/orchestrate` | Yes — `CAREFLOW_MULTI_AGENT_INTEGRATION` |
| POST `/reviewable-query` | `test_review_api.py`, `test_review_service.py` | Yes | Yes | **No API-level 503/500 test through the route** (service-layer only) | Yes — `CAREFLOW_REVIEW_INTEGRATION` |
| POST `/reviews/{id}/decision` | `test_review_api.py` | Yes | Yes | Yes (404, 409 stale-version, 409 terminal-state) | Yes |
| GET `/reviews/{id}` | `test_review_api.py` | n/a | Yes | Yes (404) | Yes |
| GET `/reviews` | `test_review_api.py` | Yes | Yes | n/a | Yes |
| GET `/analytics/evaluation/snapshot` | `test_analytics_api.py` | Yes | n/a | Yes (503 missing artifact) | Yes — `CAREFLOW_ANALYTICS_INTEGRATION` |
| GET `/analytics/structured/overview` | `test_analytics_api.py` | Yes | n/a | Yes (503 DB unreachable) | Yes — `CAREFLOW_ANALYTICS_INTEGRATION` |

**Gaps this matrix surfaces:** `/orchestrate`, `/multi-agent`, and
`/reviewable-query` each have solid unit-level error-path coverage (the
graph/generation layer's `GenerationError` handling is tested in
isolation) but no API-level (`TestClient`) test that forces a real
502/503/504 through the actual route handler. This is a legitimate
integration-test gap: it's possible for the route-handler's exception
mapping to silently diverge from the unit-tested behavior without any
test catching it.

### 5. Existing test inventory (full)

54 test files under `tests/`, 999 tests collected (`pytest
--collect-only -q`), 830 passed / 169 skipped / 0 failed on every
observed run. No `conftest.py` exists anywhere — every fixture is
file-local. No `pytest-xdist` or `pytest-randomly` is installed, so test
order is fixed and identical run to run.

| Category | Files (representative) | Approx. tests |
|---|---|---:|
| Backend unit | `test_agents_models.py` | 15 |
| Backend repository (Postgres CRUD) | `test_review_repository.py`, `test_structured_db_constraints.py`, `test_structured_repository.py` | 38 |
| Backend API | `test_health.py`, `test_liveness_readiness.py`, `test_cors.py`, `test_http_metrics.py` | 39 |
| Backend integration (multi-service) | `test_integration.py`, `test_db_migrations.py` | 8 |
| RAG/retrieval | `test_basic_rag.py`, `test_basic_rag_live.py`, `test_hybrid_retrieval.py`, `test_hybrid_live.py`, `test_reranking.py`, `test_reranking_live.py`, `test_ncd_ingestion.py`, `test_ncd_live.py` | 79 |
| Evaluation (Phase 12) | `test_evaluation_*.py` (9 files), `test_retrieval_evaluation.py` | 199 |
| Structured-data ETL (Phase 8) | `test_fhir_ingestion.py`, `test_synpuf_ingestion.py`, `test_structured_reports.py` | 41 |
| Orchestration (Phase 9) | `test_orchestration_api.py`, `test_orchestration_classify.py`, `test_orchestration_graph.py`, `test_orchestration_tools.py` | 71 |
| Multi-agent (Phase 10) | `test_agents_api.py`, `test_agents_graph.py`, `test_agents_structured_specialist.py`, `test_agents_supervisor.py`, `test_agents_validator.py` | 73 |
| HITL/review (Phase 11) | `test_review_api.py`, `test_review_models.py`, `test_review_policy.py`, `test_review_service.py` | 74 |
| Caching/reliability (Phase 13) | `test_infrastructure_cache.py`, `test_query_embedding_cache.py`, `test_observability_*.py` (4 files), `test_phase13_resilience.py` | 188 |
| Analytics (Phase 15) | `test_analytics_api.py`, `test_analytics_snapshot.py` | 16 |
| Frontend component | 11 `.test.tsx` files under `frontend/components/` | ~143 |
| Browser/manual-only | none automated (see §10) | 0 |

The 13 known live-integration env-var gates (12 given plus one omnibus
`CAREFLOW_INTEGRATION` found during the audit, used only by
`test_integration.py`) account for **all 169 skips** — none fall outside
this set (no `pytest.importorskip`, no platform-conditional skip, no
`xfail`).

### 6. Skip-reason audit (169 skips, all accounted for)

Verified via `python -m pytest tests/ -q -rs`, which prints one line per
skip with its exact reason. Grouped by underlying dependency:

| Category | Count | Representative verbatim reason |
|---|---:|---|
| `CAREFLOW_REVIEW_INTEGRATION` (Postgres + 0004 migration) | 54 | "Set CAREFLOW_REVIEW_INTEGRATION=1 with Compose running and the 0004 migration already applied to exercise POST /reviewable-query and the review APIs end to end" |
| `CAREFLOW_STRUCTURED_INTEGRATION` (real Postgres) | 37 | "Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running and the Phase 8 dev-subset ingestion already applied to test the repository/analytics layer" |
| Live Qdrant/model/CMS-index asset dependency | 28 | "Requires the reviewed CMS index and cached MiniLM model"; "Requires downloaded cross-encoder and existing CMS index" |
| `CAREFLOW_MULTI_AGENT_INTEGRATION` (Compose + Qdrant) | 14 | "Set CAREFLOW_MULTI_AGENT_INTEGRATION=1 with Compose running and the Phase 8 dev-subset ingestion already applied to exercise POST /multi-agent end to end" |
| `CAREFLOW_ORCHESTRATION_INTEGRATION` (Postgres+Qdrant) | 12 | "Set CAREFLOW_ORCHESTRATION_INTEGRATION=1 with Compose running and the Phase 8 dev-subset ingestion already applied to exercise POST /orchestrate end to end" |
| `CAREFLOW_INGESTION_INTEGRATION` (frozen CMS snapshot) | 7 | "Set CAREFLOW_INGESTION_INTEGRATION=1 with Compose running and the frozen CMS source snapshot present to exercise real chunking/indexing" |
| `CAREFLOW_LATENCY_INTEGRATION` (Postgres+Qdrant+cached models) | 5 | "Set CAREFLOW_LATENCY_INTEGRATION=1 with Compose running (Postgres, Qdrant), the Phase 8 dev-subset ingestion applied, and models cached to exercise the real Slice 5 latency benchmarks" |
| `CAREFLOW_ANALYTICS_INTEGRATION` (real Postgres) | 3 | "Set CAREFLOW_ANALYTICS_INTEGRATION=1 with Compose running to exercise GET /analytics/structured/overview against the real Postgres instance" |
| Downloaded model / published local index | 3 | "Requires downloaded model, CMS snapshot and published local Qdrant index" |
| `CAREFLOW_CACHE_INTEGRATION` (real Redis) | 3 | "Set CAREFLOW_CACHE_INTEGRATION=1 with Compose running (Redis) to exercise the real Redis client contract" |
| `CAREFLOW_INTEGRATION` (omnibus, real services) | 2 | "Set CAREFLOW_INTEGRATION=1 with Compose running to test real services" |
| `CAREFLOW_RERANKER_COMPARISON_INTEGRATION` | 1 | "Set CAREFLOW_RERANKER_COMPARISON_INTEGRATION=1 with Compose running and the frozen CMS source snapshot present to exercise the real paired hybrid/hybrid_reranked comparison" |
| **Total** | **169** | |

Every skip resolves to one of two underlying needs: (a) a live Postgres/
Qdrant/Redis instance reachable via the exact `CAREFLOW_*_INTEGRATION`
env-var convention already established across this codebase, or (b) a
downloaded/cached embedding or reranker model plus the reviewed CMS
index. Nothing is skipped for an undocumented or unexplained reason.

### 7. Flaky-test audit: `test_query_embedding_cache.py`

**Finding: no evidence of a real test-isolation bug.** A full audit of
`tests/test_query_embedding_cache.py` (701 lines) and the code it
exercises found every global/shared surface the suspect test touches —
the `"app"` logger's handlers/level/propagate flag, and the
`query_embedding_cache_*` metric counters — is protected by a
documented, function-scoped save/restore or reset mechanism:

- The file's only fixture (`_reset_metrics`, `autouse=True`) is
  function-scoped, not module/session-scoped, and resets counters both
  before and after every test.
- The class under test (`CachingQueryEmbedding`) holds no module- or
  class-level mutable cache; every test constructs its own fake
  provider/cache instances.
- `test_observability_config.py`'s own autouse fixture snapshots and
  restores the `"app"` logger's level/handlers/propagate exactly, rather
  than merely resetting to a default — so it cannot leave residual state
  for a later-running file.
- `configure_logging()` is idempotent by handler name (removes any
  pre-existing handler with the same name before adding a fresh one).
- The two `monkeypatch` uses in the file both use pytest's own
  auto-reverting fixture, not custom cleanup.
- No `conftest.py` exists anywhere under `tests/`, so no hidden
  cross-file fixture coupling is possible.
- No `pytest-xdist`/`pytest-randomly` is installed — execution is
  single-process and file/definition-order deterministic, identical
  every run.

Five full-suite-equivalent executions during this audit (three
consecutive full `python -m pytest tests/ -q` runs, one `-rs` run, one
isolated single-test run) all reported **830 passed, 169 skipped, 0
failed** — the historical single failure could not be reproduced.
**Conclusion**: most plausibly transient infrastructure/environment
flakiness at the time it was observed (e.g., a one-off OS-level timing
hiccup), not a reproducible defect. **No code change was made** — per
the directive, a fix is only justified if a real isolation bug is
found, and none was. One caveat carried into Slice 2 planning: this
conclusion has not been validated under parallel test execution
(`pytest-xdist`), which is exactly the kind of change that could first
expose a latent shared-state issue in the global metrics counters or the
`"app"` logger singleton — if Phase 16 later considers parallelizing
the backend suite for CI speed, this should be re-checked at that
point, not assumed still true.

### 8. Critical user journeys — current automation status

| Journey | Backend coverage | Frontend coverage | Browser E2E |
|---|---|---|---|
| A. Policy Q&A → `/query` → citations | `test_basic_rag.py` + live | `AskCareFlow.test.tsx` | None |
| B. Assistant → router → FHIR tool → UI | `test_orchestration_api.py` + live | `Assistant.test.tsx` | None |
| C. Assistant → router → SynPUF tool → UI | same file, SynPUF cases | `Assistant.test.tsx` | None |
| D. Multi-agent workflow → validation → separation | `test_agents_api.py` + live | `Workflow.test.tsx` | None |
| E. Reviewable workflow → queue → detail → decision → audit | `test_review_api.py` + live | `ReviewQueue.test.tsx`, `ReviewDetail.test.tsx` | None |
| F. Evaluation analytics → snapshot → dashboard | `test_analytics_api.py` + live | `Analytics.test.tsx` | None |
| G. Structured analytics → Postgres aggregates → dashboard | `test_analytics_api.py` + live | `Analytics.test.tsx` | None |
| H. Dependency degradation → readiness/error behavior | `test_liveness_readiness.py` | readiness describe-blocks in most component test files | None |

**Every journey has solid component/API-level coverage. Zero journeys
have real-browser, cross-page, HTTP-driven end-to-end coverage.** This is
the single largest gap Phase 16 exists to close, and it is the reason
Slice 2 should prioritize E2E over anything else.

### 9. E2E framework decision

**Decision: Playwright (`@playwright/test`), not installed in this
slice.**

Audited first, not assumed: `frontend/package-lock.json` already
contains `@playwright/test@^1.51.1` and `@vitest/browser-playwright`,
but only as **unused optional peerDependencies** of `next` and `vitest`
respectively — neither is an actual project dependency, and neither is
referenced anywhere in source. No `playwright.config.ts`, no `cypress.config.ts`,
no `e2e/`/`tests-e2e/` directory exists. Cypress and Puppeteer have zero
footprint anywhere in the tree.

Reasoning for Playwright over the alternatives, given this project's
actual constraints:
- **Next.js/React version compatibility**: Playwright drives a real
  browser against rendered HTML/DOM — it has no framework-version
  coupling the way a React-internals testing tool would, so Next.js
  16.3.6 / React 19.2.8 pose no compatibility risk.
- **Node version**: this project already targets Node 20 (`@types/node
  ^20`); Playwright requires Node 18+, so no upgrade is needed.
- **CI compatibility**: Playwright ships an official GitHub Action
  (`microsoft/playwright-github-action`) and a documented `webServer`
  config option that can boot `npm run dev` (or a production build)
  automatically and wait for it to be ready before running tests —
  fitting this project's existing `npm run dev`/`npm run build && npm
  start` workflow without inventing a new process-management layer.
- **Browser installation**: `npx playwright install --with-deps
  chromium` downloads one browser binary (~150-300MB); this is a real,
  one-time CI cost that must be cached (see §16/§36), but it is bounded
  and well-documented, unlike Cypress's heavier Electron-based runner or
  Puppeteer's more limited multi-tab/multi-origin support (this project
  has no multi-tab needs today, but Playwright's `webServer` + trace
  viewer + built-in auto-waiting reduce flake risk for the specific
  async-loading patterns this frontend already uses — e.g. `aria-live`
  regions, readiness gating, retry buttons).
- **Docker/backend startup requirement**: E2E tests need the full
  backend stack (Postgres, Qdrant, Redis, backend) running before the
  browser tests start — this is identical to the existing
  `CAREFLOW_*_INTEGRATION` pytest pattern's own precondition, so the
  same `docker compose up --wait` + `/ready` polling approach carries
  over directly (see §13/§17).
- **Existing dependencies**: no conflicting or redundant tooling exists
  to displace; TypeScript (`^5`) is already present, and
  `@playwright/test` ships its own TypeScript types, so no additional
  type-tooling is needed.

**Why not installed in Slice 1**: per the directive, Slice 1 is audit
and design; a "minimal E2E framework bootstrap" is allowed only if the
audit clearly establishes the correct choice. It does — but actually
installing it now, before the E2E data/isolation strategy (§11) and CI
architecture (§13) are reviewed and approved, risks locking in
assumptions about `webServer` config, base URL, and test-data isolation
before they've been designed. Bootstrapping is deferred to Slice 2,
immediately following this design's approval.

### 10. E2E environment design

Existing `docker-compose.yml` already defines exactly the services E2E
needs: `postgres` (17.6-bookworm, healthcheck via `pg_isready`),
`qdrant` (v1.15.4, **no healthcheck defined** — a real gap, see below),
`redis` (7.4.5-alpine, healthcheck via `redis-cli ping`), and `backend`
(builds from `backend/Dockerfile`, `HEALTHCHECK` already targets `/ready`
— correctly Redis-non-blocking, unlike `/health`). There is **no
`frontend` service** in docker-compose — the frontend runs natively via
`npm run dev`/`npm start`, never containerized.

Proposed E2E flow, reusing what exists rather than inventing a
production-semantics change:
1. `docker compose up -d postgres qdrant redis backend --wait` (the
   `--wait` flag already works correctly for postgres/redis/backend
   since each has a healthcheck; **Qdrant's missing healthcheck means
   `--wait` cannot gate on it directly** — a startup script would need
   to poll Qdrant's own `/` or `/collections` endpoint separately, or
   rely on the backend's own `/ready` check, which does include Qdrant,
   as the effective gate).
2. Poll `GET http://localhost:<BACKEND_PORT>/ready` until it returns 200
   (Postgres + Qdrant both healthy) — never poll `/health` for this,
   since `/health` incorrectly requires Redis too (see §17 of the
   original phase 13 design) and would block a valid, ready-for-testing
   environment on an optional dependency.
3. Start the frontend (`npm run build && npm start`, or `npm run dev`
   for faster iteration) pointed at the running backend via
   `NEXT_PUBLIC_API_BASE_URL`.
4. Run `npx playwright test` against the frontend's local URL.

No production-semantics change is proposed anywhere in this flow — it
only sequences existing, already-correct primitives.

### 11. E2E data strategy

Audited rather than assumed: after `docker compose up`, Postgres starts
empty (no ingestion runs automatically), Qdrant starts empty, and the
FHIR/SynPUF/policy data that exists in the current environment
(5 patients, 15 beneficiaries, 39 Qdrant points, 4 review cases) was
loaded by earlier, manually-run ingestion steps, not by compose startup
itself. This means **a clean CI checkout + `docker compose up` alone
does NOT reproduce the current developer environment's data** — the
Phase 8 dev-subset ingestion and Phase 4-7 CMS NCD ingestion must run
explicitly first (this is exactly why the existing pytest integration
gates document ingestion as a precondition, e.g. "...with the Phase 8
dev-subset ingestion already applied...").

Phase 12 evaluation artifacts (`artifacts/evaluation/`, `docs/evaluation/`)
**are committed to git** (confirmed: 181 + 10 files respectively, tracked
since the Phase 12 commit `24824f2`) — these need no seeding step at all;
a clean checkout already has them, and the backend Docker image already
copies them in (Phase 15's Dockerfile change). This means Journey F
(evaluation analytics) is the cheapest journey to make E2E-reproducible:
it needs no data seeding beyond a normal `docker compose build && up`.

Journeys B/C/D/G (structured FHIR/SynPUF data) need the Phase 8
ingestion step run as part of E2E setup — this is a real, non-trivial
setup cost that Slice 2 must budget for, likely by running the existing
documented ingestion command(s) once per CI job (not per test) and
treating the result as read-only fixture data for the whole E2E run,
mirroring how `CAREFLOW_STRUCTURED_INTEGRATION`-gated pytest tests
already assume this precondition rather than re-deriving it.

### 12. Review/HITL E2E isolation strategy

Review data is genuinely stateful and must not depend on the mutable "4
cases / 8 events" baseline. The project already has an established,
working pattern for exactly this problem: `tests/test_review_api.py`'s
`created_review_ids` fixture creates review cases during a test, tracks
their IDs, and — in fixture teardown — connects directly to Postgres and
`DELETE`s the tracked `review_events` then `review_cases` rows, restoring
the baseline count. `tests/test_analytics_api.py`'s
`test_structured_overview_does_not_mutate_production_invariants` uses the
same direct-Postgres-connection pattern to assert before/after counts are
identical.

**Recommended for E2E**: the same track-and-cleanup pattern, adapted for
a browser context — an E2E test that creates a review case (via the UI,
triggering `POST /reviewable-query` with `explicit_review_requested`)
captures the resulting `review_id` (visible in the UI's own "Review
required" panel, or interceptable from the network response), and a
Playwright test-level `afterEach`/fixture teardown connects directly to
Postgres (the same way the pytest fixture does) to delete that specific
`review_id`'s rows. This is architecture-consistent (reuses the exact
DELETE pattern already proven correct by the backend's own tests) and
avoids standing up a second, separate test database or introducing
transaction-rollback machinery this stack doesn't otherwise use. A
dedicated test database is explicitly **not** recommended for Slice 2:
it would require a new docker-compose profile/service, duplicate schema
migrations, and diverge from how every other test in this project
already validates against the real configured Postgres instance.

### 13. Test environment boundary

Four distinct environments, kept explicitly separate:

| Environment | What runs | Dependencies | Mutates shared state? |
|---|---|---|---|
| Unit test | `python -m pytest tests/ -q` (no env var), `npm test` | None (all mocked/faked) | Never |
| Integration test | `CAREFLOW_*_INTEGRATION=1 python -m pytest tests/ -q` | Real Postgres/Qdrant/Redis via docker-compose | Only rows it creates itself, cleaned up via tracked-ID fixtures |
| Browser E2E | `npx playwright test` | Full stack (Postgres/Qdrant/Redis/backend) + running frontend | Only rows/state a specific E2E test creates, cleaned up the same way (§12) |
| Developer production-like Docker | `docker compose up --build` | Full stack, host-local persistent volumes | Whatever the developer does manually |

No integration or E2E test should ever point at an arbitrary developer's
already-running, already-populated Docker environment as its target —
each of the three automated tiers above must be runnable against a
freshly-started (even if not freshly-seeded) compose stack, and must
never assume or depend on manually-created state beyond what its own
setup step establishes.

### 14. Existing CI

**None.** `git remote -v` returns nothing (no GitHub remote configured
yet). `.github/workflows/` exists but contains only a `.gitkeep`
placeholder — zero workflow YAML files anywhere. No `.gitlab-ci.yml`,
`.circleci/`, `Jenkinsfile`, or `azure-pipelines.yml` exists either. This
is a genuine greenfield CI design, not a modification of anything
existing.

### 15. Proposed CI architecture

Five jobs, not more — avoiding unnecessary fragmentation while keeping
fast/slow and dependency-light/heavy work separated:

1. **`backend-quality`** — `ruff check .`, `ruff format --check .`,
   `pip check`. No services needed. Fastest job, should fail first.
2. **`frontend-quality`** — `npm ci`, `npm run lint`, `npm run
   typecheck`, `npm run build`. No services needed.
3. **`backend-tests`** — `python -m pytest tests/ -q` (unit-tier only,
   no `CAREFLOW_*_INTEGRATION` set). No services needed — this is the
   830-test tier that already runs in ~5 seconds locally.
4. **`frontend-tests`** — `npm test` (the 309-test Vitest suite). No
   services needed.
5. **`integration-tests`** — Postgres + Qdrant + Redis + backend via
   `docker compose up --wait`, then the relevant
   `CAREFLOW_*_INTEGRATION=1` pytest runs. This is the only job that
   needs real services and is therefore the slowest and most
   infrastructure-dependent; it should be allowed to run in parallel
   with jobs 1-4, not after them.

**`e2e` is deliberately not included as a Slice 1 job** — it depends on
the E2E bootstrap work explicitly deferred to Slice 2 (§9). When added,
it becomes a 6th job with the same service dependencies as
`integration-tests` plus a running frontend, kept separate so a slow
browser suite never blocks the fast quality/unit gates from reporting.

Jobs 1-4 have zero service dependencies and should be the default gate
for every PR; job 5 (and, later, `e2e`) can be scoped to run on every PR
too once proven stable, or restricted to merge-queue/main-branch runs if
service-startup cost becomes a bottleneck — that trade-off should be
revisited once real CI minutes are observed, not decided speculatively
now.

### 16. Backend quality gate

`ruff check .`, `ruff format --check .`, `pip check` — exactly the three
checks already run locally and in every prior phase's own verification
routine (confirmed clean throughout Phases 1-15). **No `mypy` is
recommended** — this project has never used static type-checking for
Python, has no existing type-checking configuration, and introducing one
now would be a new, unreviewed project-wide decision outside this
slice's audit/design scope, not a "quality gate" in the sense of
verifying existing, established practice.

### 17. Frontend quality gate

`npm ci` (not `npm install` — `frontend/package-lock.json` exists and is
committed, so `npm ci` is the correct, faster, lockfile-enforcing choice
for CI), `npm run lint`, `npm run typecheck`, `npm test`, `npm run
build`. All five commands already exist as-is in `frontend/package.json`
and were run as this slice's own baseline (§1) with 0 errors.

### 18. Python dependency strategy

Canonical install, audited from the actual local-dev instructions in
`README.md`'s "Native backend development" section and mirrored by
`backend/Dockerfile`:
```
pip install -r requirements-dev.lock
pip install --no-deps -e .   # or --no-deps . in CI, no editable install needed
```
`requirements-dev.lock` chains to `requirements-ingestion.lock` (which
chains to `requirements.lock`) via `-r` directives — a single lock file
covers dev tooling (`pytest`, `ruff`), ingestion/ML dependencies
(`sentence-transformers`, `torch`, `qdrant-client`), and core runtime
dependencies together. `pyproject.toml` declares `requires-python =
">=3.12,<3.15"`. This is the same dependency truth `backend/Dockerfile`
already uses (with `torch` additionally pinned to a CPU-only wheel index
there to avoid a multi-GB CUDA download) — CI should install `torch`
the same CPU-only way for the same reason.

### 19. Node dependency strategy

`frontend/package-lock.json` exists and is committed. `npm ci` is the
correct CI command (not `npm install`) — it installs exactly what the
lockfile specifies and fails if `package.json`/lockfile are out of sync,
which `npm install` would silently paper over. No explicit Node
`engines` field exists in `package.json`, but `@types/node: ^20` and
Next.js 16.3.6's own requirements imply Node 20+ as the target; CI should
pin an exact Node 20.x LTS version via `actions/setup-node`.

### 20. Service dependency strategy

| Service | Image | Healthcheck | Port | Key env vars |
|---|---|---|---|---|
| Postgres | `postgres:17.6-bookworm` | `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` (5s interval, 12 retries) | 5432 (host 55432 in dev) | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| Qdrant | `qdrant/qdrant:v1.15.4` | **none defined** — a real gap | 6333 (host 6333) | none required |
| Redis | `redis:7.4.5-alpine` | `redis-cli ping` (5s interval, 12 retries) | 6379 (host 6379) | none required (appendonly persistence) |
| Backend | built from `backend/Dockerfile` | `HEALTHCHECK` → `GET /ready` (10s interval, 15s start period, 3 retries) | 8000 | `DATABASE_URL`, `QDRANT_URL`, `REDIS_URL`, `RAG_PROVIDER=deterministic` by default |

All four values come directly from `docker-compose.yml` and
`backend/Dockerfile`, not assumed. **Qdrant's missing healthcheck is a
genuine, pre-existing gap** (not introduced by this audit) — CI's
`integration-tests` job must not rely on `docker compose up --wait`
alone to confirm Qdrant readiness; it should poll the backend's own
`/ready` (which does check Qdrant) as the effective combined gate, per
§10.

### 21. Model-download strategy

Audited via `backend/app/core/config.py` and `docker-compose.yml`:
`rag_model_cache`/`rerank_model_cache` both default to `.cache/models`
(mounted read-only into the backend container from the host at
`/models`), and `rag_embedding_offline`/`rerank_offline` both default to
`true` — meaning the running backend **expects models already present
locally and will not attempt a network fetch**. Locally, `.cache/models`
already holds the pinned `sentence-transformers/all-MiniLM-L6-v2` and
`cross-encoder/ms-marco-MiniLM-L6-v2` revisions (confirmed present on
this machine); a fresh CI runner has no such directory.

**Recommendation**: the default `backend-tests` CI job (unit tier, no
integration env vars) never needs these models at all — `RAG_PROVIDER`
defaults to `deterministic`, and the model-dependent tests are precisely
the ones already gated behind `CAREFLOW_RAG_INTEGRATION`/
`CAREFLOW_HYBRID_INTEGRATION`/`CAREFLOW_RERANK_INTEGRATION`/etc. and
skipped by default. For the `integration-tests` job, if/when it chooses
to exercise those specific gates, two options exist: (a) let the first
CI run download and cache the ~90MB+430MB model files via a keyed cache
action (e.g. `actions/cache` keyed on the model revision strings already
pinned in `pyproject.toml`), so only the first run pays the network cost;
or (b) scope `integration-tests` to skip the model-dependent gates by
default and only run them on a separate, explicitly-triggered schedule.
Given this project's small, pinned model set, option (a) is preferable —
it preserves meaningful coverage without making every PR's default path
fragile to a large network download, consistent with the directive's
explicit instruction not to weaken coverage while avoiding fragility.

### 22. External API (OpenAI) strategy

`RAG_PROVIDER` defaults to `deterministic` in both `.env.example` and
`backend/app/core/config.py`; `OPENAI_API_KEY` defaults to empty and is
"used only when RAG_PROVIDER=openai" per `.env.example`'s own comment.
**Confirmed: the entire default test suite (unit and integration alike)
runs against the deterministic provider and requires no OpenAI key at
all.** No CI job proposed in §15 needs any secret for standard PR
validation. If a future slice wants to add a live-OpenAI-gated test tier
(mirroring the `CAREFLOW_*_INTEGRATION` pattern), it should be a
separate, explicitly-opt-in job reading a repository secret — never a
default-path requirement.

### 23. Evaluation-artifact clean-checkout audit

`artifacts/evaluation/` (181 files) and `docs/evaluation/` (10 files) are
both **committed to git**, tracked since the Phase 12 commit `24824f2`
("feat(evaluation): add advanced RAG evaluation framework") — confirmed
via `git ls-files` and `git log --follow`. The `evaluation/` Python
package (15 files) is likewise committed. A clean CI checkout therefore
already has everything `GET /analytics/evaluation/snapshot` needs; no
seeding step is required for Journey F. `backend/Dockerfile` (modified in
Phase 15) already `COPY`s all three directories into the backend image
with a permission fix for their host-inherited `0700` directory modes —
this was verified working end-to-end against a real rebuilt container
multiple times during Phase 15.

### 24. Docker build audit

`docker compose build backend` was run and verified successful multiple
times during Phase 15 work this session, from this exact clean-checkout
state — confirming the backend image builds reproducibly. Only
`backend/Dockerfile` exists; there is no frontend Dockerfile and no
`frontend` service in `docker-compose.yml` — the frontend runs natively
(`npm run dev`/`npm run build && npm start`), never containerized in this
project. `.dockerignore` correctly excludes `.git`, `.venv`, `.cache`,
`.env*`, `__pycache__`, `node_modules`, and `frontend` from the backend
build context. No gap was found in the backend's own buildability; the
only structural gap is the complete absence of a frontend container,
which is out of scope for Phase 16 (deployment packaging belongs to
Phase 17 per the existing roadmap) and is not redesigned here.

### 25. Readiness strategy for CI

`backend/Dockerfile`'s own `HEALTHCHECK` already targets `GET /ready`,
not `/health` — correct, since `/ready` treats only Postgres and Qdrant
as authoritative (Redis reported but never gating), while `/health`
incorrectly requires Redis too and would block a valid, ready-for-testing
environment on an optional dependency. CI's `integration-tests` (and
later `e2e`) startup gate should poll `GET /ready` directly (e.g. via
`curl --retry` or a small polling loop) rather than reusing
`scripts/verify_services.py` as-is — that script calls
`check_dependencies()` (the same stricter check `/health` uses, which
does require Redis), not `check_readiness()`, so it would incorrectly
block CI on a Redis hiccup. This is a precise, source-verified
distinction, not a guess.

### 26. Failure-injection matrix

Mapped from actual backend semantics (verified in source and/or existing
tests during this slice's own audit and Phase 14-15 work), not assumed:

| Failure | Expected HTTP | Expected app status | Existing test? |
|---|---|---|---|
| Postgres unavailable | `/ready` → 503 | `dependencies.postgresql.status=unavailable` | Yes (`test_liveness_readiness.py`) |
| Qdrant unavailable | `/ready` → 503 | `dependencies.qdrant.status=unavailable` | Yes |
| Redis unavailable | `/ready` → 200 (non-gating), `/health` → 503 | `dependencies.redis.status=unavailable` reported, never blocks `/ready` | Yes |
| Evaluation artifact unavailable | `GET /analytics/evaluation/snapshot` → 503 | `{"error":{"code":"evaluation_snapshot_unavailable"}}` | Yes (`test_analytics_api.py`) |
| Unsupported/out-of-corpus policy evidence | `/query`, `/orchestrate` → 200 | abstention, not an error | Yes |
| Structured identifier not found | `/orchestrate` → 200 | `abstention_reason=unknown_patient`/`unknown_beneficiary` | Yes |
| Invalid/unsupported structured tool | `/orchestrate`, `/multi-agent` → 200 | `abstention_reason=unsupported_tool` | Yes (multiple layers) |
| Review stale CAS | `POST /reviews/{id}/decision` → 409 | `{"error":{"code":"version_conflict"},"review":{...}}` | Yes |
| Review terminal-state conflict | same endpoint → 409 | same shape, case already non-pending | Yes |
| Cross-dataset linkage request | request schema itself rejects (422) or `unsupported_tool` (200) | structurally inexpressible, not a runtime check | Partially — no test with this exact framing exists; recommend one |
| Generation/provider failure | `/query`, `/orchestrate`, `/multi-agent` → 502/503/504 | `GenerationError` code-mapped | Unit-tested; **no API-level TestClient test found** — recommend one |

### 27. Security-test matrix

| Area | Status |
|---|---|
| SQL-injection-shaped values | FOUND — `test_review_api.py` (hostile `reviewer_id`/`reason` stored verbatim, table survives), `test_orchestration_tools.py` (no tool schema exposes sql/table/column fields), `test_observability_middleware.py` (hostile `X-Request-ID` replaced) |
| Artifact path traversal | Architecturally prevented (zero request parameters on either `/analytics/*` route — confirmed by reading `backend/app/api/analytics.py`), but no test locks this in via the OpenAPI schema — recommend one |
| Arbitrary/unsupported tool execution | FOUND — `test_orchestration_tools.py`, `test_orchestration_api.py`, `test_agents_api.py` all cover unknown-tool and domain-mismatch cases returning `unsupported_tool` with 200, never 500 |
| Cross-dataset linkage | Structurally prevented (single `structured_route` field, `extra="forbid"` strict models) but no test proves the schema itself rejects a combined request — recommend one |
| Review CAS | FOUND — stale-version and terminal-state 409 tests both exist |
| Request-ID handling | FOUND — extensive coverage in `test_observability_middleware.py` and `test_cors.py` |
| Sensitive logging | FOUND — `FORBIDDEN_FIELD_NAMES` frozenset enforced and tested field-by-field in `test_observability_logging.py` |
| CORS | FOUND — `test_cors.py`, 7 tests covering allowed/unlisted origins, preflight, credential exclusion |

No generic penetration testing is recommended, per the directive. The two
genuine gaps (artifact-path-traversal-by-schema and
cross-dataset-linkage-by-schema regression tests) are both small,
high-value, and low-effort — good Slice 2 candidates.

### 28. Accessibility automation

No dedicated accessibility-testing tool (`@axe-core/*`, `axe-playwright`,
etc.) is installed — plain `axe-core` appears only as a transitive
dependency of `eslint-plugin-jsx-a11y` (a lint-time rule package, not a
runtime test tool). `eslint-config-next/core-web-vitals` (already active
in `frontend/eslint.config.mjs`) bundles `jsx-a11y`'s recommended rules,
so **static accessibility linting already runs on every `npm run lint`**
— this is real, existing coverage, just not runtime/DOM-level. No new
dependency is recommended in Slice 1. If Slice 2 adds Playwright, adding
`@axe-core/playwright` as a small addition to the same E2E suite (running
an axe scan on 2-3 key pages) would close a concrete gap cheaply; it
should not be added merely for optics before that E2E foundation exists.

### 29. Coverage reporting

Neither backend (`pytest-cov`) nor frontend (`@vitest/coverage-v8`/
`-istanbul`) has coverage tooling installed — both appear only as unused
optional peerDependencies, confirmed absent from actual `dependencies`/
`devDependencies` and from `pyproject.toml`. No coverage percentage
threshold is recommended — per the directive, coverage percentage is not
equivalent to test quality, and this project's actual gap (zero E2E
journeys, a handful of specific API-error-path gaps) is precisely
documented above without needing a blanket percentage metric to find it.
If Slice 2 or later wants basic coverage *reporting* (not gating) for
visibility, `pytest-cov` and `@vitest/coverage-v8` are both low-cost,
well-maintained additions — but that's a separate decision from this
audit's scope.

### 30. CI security design

- **Minimum permissions**: every workflow should declare `permissions:
  contents: read` at the top level (GitHub Actions defaults to broader
  permissions otherwise); no job in the proposed architecture needs
  write access to the repository, issues, or packages.
- **No plaintext secrets**: confirmed no CI job needs one by default
  (§22); if a future OpenAI-gated tier is added, it must read from
  GitHub encrypted secrets, never a committed file.
- **No production credentials**: `.env.example`'s bundled Postgres
  password is explicitly documented as "local development only" — CI
  should use its own throwaway values via the same env vars, never
  anything resembling a real credential.
- **Pinned action versions**: every third-party action reference should
  pin at least a major version (e.g. `actions/checkout@v4`,
  `actions/setup-python@v5`, `actions/setup-node@v4`) — full SHA-pinning
  is stronger but a major-version pin is the documented minimum bar here.
- **Dependency caching**: `actions/setup-python` and `actions/setup-node`
  both have built-in, safe pip/npm caching (keyed on the lock file hash)
  that should be enabled — this caches dependency downloads only, never
  secrets or credentials.

### 31. CI failure artifacts

Once `e2e` exists (Slice 2+), Playwright's own trace/screenshot/video
capture (`trace: 'on-first-retry'`, `screenshot: 'only-on-failure'`) is
the standard, low-cost way to capture failure diagnostics — traces are
small and self-contained (viewable via `npx playwright show-trace`).
Recommend uploading these only `if: failure()`, never on every green run,
to avoid unnecessary artifact storage. For `backend-tests`/
`integration-tests`, pytest's own `-v` output plus the existing
structured JSON logging (`app.observability.logging`) is sufficient for
Slice 1/2 — no new artifact-generation tooling is needed for the backend
tiers.

### 32. Concurrency / cancellation

Recommend a top-level `concurrency: { group: ${{ github.workflow }}-${{
github.ref }}, cancel-in-progress: true }` block once CI is actually
added — so a new push to the same PR/branch cancels an obsolete
in-progress run rather than wasting runner time on stale code. Not
implemented in this slice since no CI workflow exists yet to attach it
to; documented here for Slice 2 to apply when the first real workflow
file is authored.

### 33. Local developer workflow (design only)

Conceptually, once E2E exists: `backend checks` (`ruff check . && ruff
format --check . && pip check && python -m pytest tests/ -q`),
`frontend checks` (`npm run lint && npm run typecheck && npm test && npm
run build`), `integration` (`docker compose up --wait` +
`CAREFLOW_*_INTEGRATION=1 python -m pytest tests/ -q`), `E2E` (`npx
playwright test`). No wrapper script is written in this slice — the
individual commands above are already exactly what a developer runs
today (confirmed throughout every phase of this project's own
verification routine), and inventing a monolithic shell script before
the E2E commands actually exist would be premature. A thin
`Makefile`/`package.json` script wrapper is a reasonable Slice 2+
addition once all four tiers are real.

### 34. Highest-priority gaps (ranked)

1. **Zero browser E2E coverage** across all 8 critical journeys — the
   single largest gap, and the primary justification for Phase 16
   existing at all.
2. **`/analytics` has no readiness-gating or interaction tests** at the
   component level — a real, specific, low-effort fix independent of
   E2E.
3. **No API-level 502/503/504 test** through `/orchestrate`,
   `/multi-agent`, or `/reviewable-query`'s actual route handlers (unit
   coverage exists; the route-handler mapping itself is untested).
4. **Qdrant has no Docker healthcheck** — `docker compose up --wait`
   cannot gate on it directly; CI/E2E startup must poll the backend's own
   `/ready` instead, which does check Qdrant.
5. **No regression test proves** the artifact-path-traversal and
   cross-dataset-linkage protections structurally, only that the
   request/response shapes happen to prevent them today.
6. **No CI exists at all** — this project has never been pushed to
   GitHub; even the fast, zero-service quality/unit gates (jobs 1-4 in
   §15) currently only run when a human remembers to run them locally.

### 35. Test pyramid / strategy

CareFlow's existing test suite is already, by accident of how each phase
was built, a reasonably-shaped pyramid: 830 fast deterministic
unit/component tests (backend + frontend combined) at the base, ~169
bounded integration tests gated behind explicit env vars in the middle,
and — the gap this phase exists to close — a small, bounded browser E2E
layer at the top, not yet built. The intended strategy going forward:

- **Many deterministic unit/API tests** (current: 830 backend + 309
  frontend) — cheap, fast, run on every commit, no services needed.
- **Bounded integration tests against real services** (current: 169,
  gated behind 13 `CAREFLOW_*_INTEGRATION` env vars) — real Postgres/
  Qdrant/Redis, run less often (every PR via CI once added, or on
  demand), proves the wiring between components actually works.
- **A small browser E2E suite covering critical journeys only** (target:
  5-10 scenarios, §36) — the most expensive tier per test, reserved for
  what only a real browser can prove (navigation, multi-page state,
  actual rendered DOM, real network timing).
- **Manual visual checks only where automation has low value** — e.g.
  one-off design review of a new page's visual polish; every phase of
  this project has already used real-browser manual verification
  extensively (Phases 14-15) for exactly this purpose, and that practice
  continues for genuinely one-off visual judgment calls, not as a
  substitute for the automated tiers above.

Explicitly avoided: hundreds of slow browser tests duplicating what the
830+309 unit/component tests already prove cheaply.

### 36. Browser E2E scope (proposed for Slice 2)

Target 5-10 scenarios, chosen to cover what only a real browser proves —
navigation, multi-page state, actual readiness-driven UI gating — not one
test per backend behavior (those stay at the API-test tier):

1. Policy Q&A: ask a question on `/ask`, see a rendered answer with
   citations (Journey A).
2. Assistant → FHIR: a free-text question on `/assistant` routes to a
   structured FHIR result (Journey B).
3. Assistant → SynPUF: same page, a SynPUF-routed question (Journey C).
4. Assistant → cross-dataset refusal: a question implying FHIR+SynPUF
   linkage shows the explicit non-linkage message, never attempts a join
   (safety-critical, currently only component-tested).
5. Evidence Workflow: submit a combined policy+structured request on
   `/workflow`, see both sections rendered separately with the safety
   disclaimer (Journey D).
6. Full review lifecycle: submit a workflow request with
   `explicit_review_requested`, navigate to `/reviews`, find the new
   case, open `/reviews/[reviewId]`, approve it, see the audit event —
   the single most valuable E2E scenario since it's the only journey that
   genuinely spans multiple pages/navigation (Journey E, with cleanup
   per §12).
7. Analytics evaluation snapshot: load `/analytics`, confirm real Phase
   12 numbers render (Journey F).
8. Analytics structured overview: same page, confirm real FHIR/SynPUF
   aggregates render as two separate sections (Journey G).
9. Dependency degradation: with Postgres stopped, confirm `/patient-data`
   correctly blocks submission with the right message, while `/ask`
   (Qdrant-dependent only) remains usable (Journey H — the one journey
   that specifically requires a real, live service being stopped, which
   no component test can simulate honestly).
10. Mobile viewport smoke (see §38): one or two pages only.

This list is a proposal for Slice 2 to refine against the finalized E2E
data/isolation design (§11-12), not a commitment made in this slice.

### 37. Cross-browser scope

**Chromium only for Phase 16.** This project has no stated requirement
for Safari/Firefox-specific behavior, no CSS/JS feature usage identified
during Phase 14-15 manual verification that behaved differently across
engines, and Playwright's Chromium channel is the fastest and
lowest-CI-cost option to start with. Expanding to WebKit/Firefox later is
a cheap, additive change (Playwright's own multi-browser config is a
one-line addition) that should be justified by an actual observed
cross-browser issue, not added speculatively now.

### 38. Responsive E2E

Recommend automated mobile-viewport smoke coverage on exactly **one or
two** pages, not a reproduction of every Phase 14/15 manual responsive
check across all 9 routes (that manual verification already happened
thoroughly, phase by phase, and re-automating all of it would be exactly
the "hundreds of slow browser tests" anti-pattern §35 warns against).
Best candidates: `/analytics` (the most content-dense page, with tables,
bar charts, and long codes/hashes — the page most likely to regress
visually) and `/workflow` or `/reviews/[reviewId]` (the most
interaction-heavy stateful page). A single `page.setViewportSize({width:
375, height: 812})` + a `document.documentElement.scrollWidth ===
clientWidth` assertion, matching the exact manual-check pattern already
used throughout Phase 14-15, is sufficient — no new responsive-testing
library is needed.

### 39. Slice 1 implementation

**NONE.** The flaky-test audit (§7) found no real isolation bug, so the
one code change Slice 1 was conditionally permitted to make was not
justified — making it anyway would violate the directive's explicit "do
not hide flaky tests behind retries" / "only if a small deterministic fix
is clearly justified" instruction. No E2E framework was installed (§9
explains why bootstrapping is deferred to Slice 2). No CI workflow file
was created (design-only, per §14-15). This slice is audit and design
only, exactly as scoped.

### 40. Recommended Slice 2

1. Bootstrap Playwright (`@playwright/test`) per the §9 decision:
   `playwright.config.ts` with a `webServer` block, Chromium only (§37).
2. Implement the E2E data/isolation strategy from §11-12: a documented
   one-time ingestion step for FHIR/SynPUF fixture data, and the
   track-and-cleanup pattern for review rows.
3. Implement the 5-10 scenarios proposed in §36, refined against
   whatever the data-strategy work in step 2 actually makes practical.
4. Add the two small regression tests identified in §27 (artifact-path-
   traversal-by-schema, cross-dataset-linkage-by-schema) and the
   API-level 502/503/504 test gap identified in §26/§4 — all backend-only,
   no E2E dependency, could land independently of steps 1-3 if useful to
   sequence first.
5. Add the two `/analytics` component-test gaps identified in §3
   (readiness-gating, interaction coverage) — also independent of E2E.
6. Author the first real CI workflow YAML implementing the 5-job
   architecture from §15 (backend-quality, frontend-quality,
   backend-tests, frontend-tests, integration-tests), with the security
   practices from §30 and concurrency/cancellation from §32 — this can
   only actually *run* once the repository has a GitHub remote, but the
   YAML itself can be authored, reviewed, and committed regardless.
7. Add the `e2e` job once step 1-3 are stable enough to run in CI
   reliably.

## Slice 2 — Targeted regression tests + Playwright foundation + first E2E journeys

Slice 2 had three bounded goals: close the highest-value gaps Slice 1
found, bootstrap Playwright correctly, and automate exactly five first
critical browser journeys. No CI workflow, no product feature, no
review/HITL or degradation E2E — all deliberately out of this slice's
scope.

### 41. A corrected flaky-test finding

Slice 1's flaky-test audit concluded "no evidence of a real isolation bug
found" for `test_query_embedding_cache.py::test_hit_returns_cached_vector_without_calling_the_model`,
based on 5 clean reruns. **That conclusion was wrong** — it was based on
too small a sample for a low-frequency flake. During this slice's own
"everything must remain green" regression pass (directive §11), the
exact same test failed again, live. Given the mandate to diagnose rather
than re-run until green, this was pursued to a full, mechanistic
root-cause:

The test asserted `"1.0" not in log_text and "2.0" not in log_text and
"3.0" not in log_text` against the *entire* raw JSON log line, to prove
the seeded cached vector `[1.0, 2.0, 3.0]` never leaks into logging. But
that same log line also contains a genuine, non-deterministic ISO-8601
`timestamp` field with fractional seconds (real wall-clock time, never
mocked). Whenever the timestamp's seconds value ends in a digit that,
combined with the first digit of the following fractional part, spells
out "1.0" (e.g. `"...11.092043+00:00"` contains the substring `"11.0"`,
which contains `"1.0"`) — a roughly 1-in-100 chance per run, independently
for each of the three checked substrings — the assertion fails for a
reason **completely unrelated to any actual vector leakage**.

This was proven three ways: (1) captured a live failure and confirmed the
exact substring collision in the real `timestamp` field's digits; (2) a
standalone script confirmed the *old* assertion logic fails against a
crafted event with that same collision, and a *new*, corrected assertion
logic passes against the identical event; (3) stress-tested the fix with
60 consecutive runs of the file (0 failures) plus 5 consecutive full-suite
runs (0 failures), after previously reproducing the original failure 3
times across roughly 90 total attempts (a rate consistent with the
~1-3% mechanistic prediction).

**Fix applied** (the one code change this slice's targeted-gap-closing
work made to already-existing test code, distinct from the new tests
added below): the assertion now excludes the `timestamp` and
`duration_ms` fields — the only two fields whose value is ever
non-deterministic — before checking for the vector substrings, so a
genuine vector leak in any *other* field is still caught, but an
unrelated timestamp digit collision no longer can be. See
`tests/test_query_embedding_cache.py`'s own updated comment for the exact
reasoning, referenced from here rather than duplicated.

### 42. Targeted regression tests closed

Six gaps from Slice 1, each closed with the smallest test that actually
proves the property, reusing existing patterns rather than inventing new
ones:

- **`/analytics` readiness** (`frontend/lib/evaluationSnapshotReadiness.test.ts`,
  `frontend/lib/structuredAnalyticsReadiness.test.ts`, new files,
  matching the exact convention every other readiness module already has
  its own test file for): proves the evaluation-snapshot panel is
  allowed even when Postgres/Qdrant/Redis are all reported unavailable
  (it never touches any of them), and the structured-analytics panel is
  blocked only on Postgres, never Qdrant/Redis.
- **"one panel failing doesn't hide the other"** (two new tests in
  `Analytics.test.tsx`): explicit proof, not just an absence of a
  counter-example — when structured analytics 503s, the Evaluation
  Overview and Claim Matrix headings still render; when the evaluation
  snapshot 503s, both structured dataset headings still render.
  Positive/negative pointing to the *same* root cause were made a single
  pair of tests to keep this bounded (six-gap directive, not a broad new
  category).
  Neither policy's underlying logic needed to change — no bug was found,
  only a coverage gap.
- **Evaluation Provenance interaction** (extended the existing provenance
  test in `Analytics.test.tsx`): proves the `<details>` starts genuinely
  collapsed (`details.open === false` and the field content
  `not.toBeVisible()` — jsdom respects native `<details>` visibility
  semantics for `toBeVisible`, so this is a real, not merely
  DOM-presence, check), then a real `userEvent.click()` (not a raw DOM
  `.click()`, which the pre-existing test had used) expands it and
  reveals the real experiment IDs and corpus fingerprint.
- **API-level generation-failure mapping** for `/orchestrate`
  (`tests/test_orchestration_api.py`), `/multi-agent`
  (`tests/test_agents_api.py`), and `/reviewable-query` (new file
  `tests/test_reviewable_query_api_route_boundary.py`, kept separate
  because `test_review_api.py` has an existing module-level
  `CAREFLOW_REVIEW_INTEGRATION` skip marker covering its whole file,
  which would have silently made a new "always run" test skip too if
  added there): each gets exactly two new tests, monkeypatching the
  route's own graph-builder function to raise first a `GenerationError`
  (asserting its declared status code/error code reach the HTTP
  response) and then a bare `RuntimeError` (asserting a 503 with a
  generic code, and that the exception's message text never appears in
  the response body). No live Postgres/Qdrant/generation provider
  needed — these are pure route-handler unit tests, unconditional, never
  skipped.
- **Analytics path-selector security regression** (`tests/test_analytics_api.py`):
  two new tests read the app's own OpenAPI schema and assert both
  `/analytics/*` GET operations declare zero parameters and no request
  body (the authoritative description of the actual contract), plus a
  live request proving an attempted `?experiment_id=../../etc/passwd`
  style query string is silently ignored -- the response is
  byte-for-byte identical to a plain request. (The structural "no public
  function accepts a path/experiment_id argument" check already existed
  from Phase 15 Slice 2 -- not duplicated.)
- **Cross-dataset linkage regression** (`tests/test_orchestration_tools.py`):
  two new tests attempt to resolve a real SynPUF-shaped beneficiary
  identifier under an FHIR route and vice versa, proving each is
  rejected (`unsupported_tool`, `data=None`, `source_dataset=None`) with
  no trace of the other dataset's data anywhere in the result. A third
  test proves this isn't merely a runtime check but a schema property:
  `MultiAgentRequest.structured_route` is a single `Route`, never a
  list, so a request naming both `"fhir"` and `"synpuf"` fails Pydantic
  validation before any handler code runs at all.

All twelve new backend tests plus the frontend additions are
unconditional (never live-gated) since none need real Postgres/Qdrant —
they monkeypatch or inspect contracts/schemas directly.

### 43. Playwright version and installation

`node --version` → v25.6.1, `npm --version` → 11.9.0 (both well above
Playwright's Node 18+ minimum). `@playwright/test@^1.63.0` installed as
a **devDependency only** via `npm install --save-dev`, so
`package-lock.json` stays authoritative. No Cypress, no Puppeteer.

### 44. Browser scope

Chromium only, exactly as Slice 1 decided — no Firefox/WebKit project in
`playwright.config.ts`.

### 45. A real, documented environment constraint: the bundled Chromium binary could not be downloaded

`npx playwright install --with-deps chromium` failed in this sandboxed
session — every attempt to reach `cdn.playwright.dev` and
`storage.googleapis.com` timed out (30s), even with the sandbox's network
restrictions explicitly bypassed for the attempt, while `registry.npmjs.org`
remained reachable throughout. This is a genuine network-egress
allowlist restriction specific to this execution environment, not a
project or code defect, and not expected to occur on a normal CI runner
(e.g. GitHub Actions' hosted runners have unrestricted internet access,
where `playwright install` works exactly as documented).

**Resolution used for this session only**: this machine has a system
Google Chrome already installed (`/Applications/Google Chrome.app`).
Playwright supports launching a system browser via its documented
`channel` option (Chrome and Chromium share the same Blink/V8 engine —
this is a supported substitution, not a workaround). `playwright.config.ts`
reads `PLAYWRIGHT_BROWSER_CHANNEL` from the environment, defaulting to
`undefined` (Playwright's own bundled Chromium — the correct default for
a normal CI runner where the download works). Running with
`PLAYWRIGHT_BROWSER_CHANNEL=chrome` in this session launched the real
system Chrome with zero network download, verified with a standalone
smoke script before relying on it for the real suite. **The committed
config itself makes no environment-specific assumption** — a developer
or CI runner with normal internet access needs no environment variable
at all.

### 46. Playwright configuration

`frontend/playwright.config.ts`: `testDir: "./e2e"`, one `chromium`
project, `timeout: 30_000`, `expect.timeout: 5_000`, `retries: 0`
unconditionally (never hides a flaky result behind a re-run — matching
this slice's own §41 precedent of diagnosing rather than re-running),
`trace: "on-first-retry"`, `screenshot: "only-on-failure"`, `baseURL`
from `E2E_BASE_URL` (default `http://localhost:3000`), and a `webServer`
block (see §47).

### 47. Frontend server strategy

Audited `frontend/package.json`'s actual scripts first: `dev`, `build`,
`start` (`next start`, a real production server) all already exist.
Chose **`npm run build && npm run start`** — a production-style server,
per the directive's stated preference, since build time proved fast
enough (~1-2s compile, full cold `webServer` boot-to-ready in this
session's own measurements) to not be a real cost. `webServer.url:
"http://localhost:3000"` with `reuseExistingServer: !process.env.CI` —
locally reuses an already-running server if present (fast iteration);
always fresh in CI.

### 48. Backend service stack

Reused `docker-compose.yml` exactly as-is — Postgres/Qdrant/Redis/backend,
already running throughout this session. No second compose file, no new
frontend Docker service (still out of scope; Phase 17 territory per the
existing roadmap).

### 49. Readiness gate

New `scripts/wait_for_backend_ready.py` (Python, matching the existing
`scripts/verify_services.py` style) polls `check_readiness()` — the
exact same Postgres+Qdrant-authoritative, Redis-non-gating rule
`GET /ready` itself uses — every 1s for up to 60s, printing the final
readiness JSON and exiting 0/1. Deliberately does **not** reuse
`verify_services.py` as-is, since that script calls the stricter
`check_dependencies()` (the same rule `/health` uses, which incorrectly
requires Redis) — reusing it here would have risked blocking a
genuinely E2E-ready environment on an optional dependency, exactly the
mistake Slice 1's design flagged. Verified working against the real
running stack (`status: "ready"` returned immediately).

### 50. Structured-data fixture strategy

Audited the actual documented ingestion commands (`docs/phase8_structured_health_data.md`,
`README.md`) rather than inventing a second ETL path:
`python -m ingestion.cli ingest-fhir` and `python -m ingestion.cli
ingest-synpuf`, reading from the committed
`cms_inspection/synthea_dev_subset.json` / `desynpuf_dev_subset.json`
dev-subset files. This session's environment already had this data
loaded (5 patients, 15 beneficiaries, matching the standing production
invariants throughout every phase of this project) — Slice 2 did not
need to re-run ingestion, only document the real command for a genuinely
fresh environment, and reuse the exact same fixture identifiers the
project's own live-gated pytest suite already depends on
(`KNOWN_PATIENT_ID`/`KNOWN_BENEFICIARY_ID` constants mirrored verbatim
into `frontend/e2e/fixtures.ts`) rather than inventing new ones.

### 51. Review/HITL state — untouched

No review/HITL E2E was implemented, per scope. All 5 journeys are
read-only; the review baseline (4 cases / 8 events) was verified
byte-identical before and after every E2E run in this slice (see §54).

### 52. The five E2E journeys

All in `frontend/e2e/`, using `frontend/e2e/fixtures.ts`'s shared known
identifiers/questions and an automatic console/page-error-capturing
`page` fixture (any uncaught exception or `console.error` call fails the
test by default, with an `allowConsoleError(pattern)` escape hatch a
test can call if a specific, investigated message needs excluding — none
currently do).

- **E2E-1** (`e2e-1-application-smoke.spec.ts`): loads `/`, confirms the
  "Ready" status badge, then clicks through all 8 Sidebar destinations,
  confirming each one's own heading renders and none ever shows the
  generic "backend is currently unavailable" message.
- **E2E-2** (`e2e-2-policy-journey.spec.ts`): submits the real,
  committed, `exact_lexical`-category golden question
  ("When arterial blood gas and oximetry studies conflict for home
  oxygen, which study is preferred?", case `cms-v1-009`, Hit@1=1.0 across
  every mode per the Phase 12 audit — re-verified live against `/query`
  before use, never invented), asserts "Citation 1" and the real cited
  document's own title text render — evidence/citation semantics, not
  exact generated prose.
- **E2E-3** / **E2E-4** (`e2e-3-fhir-journey.spec.ts`,
  `e2e-4-synpuf-journey.spec.ts`): free-text questions through the real
  `/assistant` page (`"Show me FHIR patient
  31a2e8ec-69fc-8a71-3ab6-36cbdd508713"`,
  `"Look up SynPUF beneficiary 00013D2EFD8E45D1"` — both re-verified live
  against the real classifier before use), asserting the real ID renders
  in the structured result's own `<dd>` (not the form echo or the
  example chip, which coincidentally contain the same text), the correct
  synthetic/sample-data disclaimer is visible, and no trace of the other
  dataset appears.
- **E2E-5** (`e2e-5-analytics-journey.spec.ts`): loads `/analytics`,
  confirms both independently-loaded panels render using stable semantic
  labels (dataset names, all four claim-matrix category names, the
  `EVAL-RUNTIME-CONFIG-DRIFT` warning, the provenance disclosure
  control's presence, both structured dataset headings, "Top 5" wording)
  — deliberately not re-asserting every exact number the component tests
  already cover.

### 53. Locator strategy

Per the directive's explicit preference order (role/label/heading/button
name/accessible text over brittle CSS), every locator in all five specs
uses `getByRole`, `getByLabel`, or a scoped `getByText`/tag-filter — no
`nth-child`, no generated CSS class name, no test-only `data-testid`
added anywhere. Three real, instructive locator bugs were found and
fixed while first running the suite (not application bugs):

1. `getByText(<ID>)` for a FHIR/SynPUF identifier matched 2-3 legitimate
   occurrences at once (the disabled form's echoed text, the "example
   request" chip, and the real result) — fixed by scoping to the
   `<dd>` tag specifically (`page.locator("dd").filter({ hasText: ID
   })`), which targets only the actual structured-record data.
2. `getByText("Supported")` (and the other three claim-matrix category
   names) matched unrelated prose elsewhere on the content-dense
   Analytics page — fixed by scoping to the `<dt>` tag with an exact-match
   regex, since the categories are genuinely `<dt>` elements in the
   existing markup.
3. `getByRole("heading", { name: "Structured Analytics" })` (substring
   match by default) also matched the "Structured Analytics Limitations"
   heading — fixed with `exact: true`.

Each is a real example of Playwright's strict-mode locator resolution
correctly catching genuine ambiguity — not a flake, and not hidden by a
looser selector.

### 54. Failure diagnostics

`trace: "on-first-retry"` and `screenshot: "only-on-failure"` are
configured; since `retries: 0`, a real failure captures a screenshot
(verified: the three real locator-ambiguity failures above each produced
a `test-results/.../test-failed-1.png` and a full `error-context.md`
with the complete accessibility-tree page snapshot, which is exactly how
the ambiguities in §53 were diagnosed and fixed). No secrets or full
sensitive payloads are logged anywhere — all E2E data is synthetic, and
no test asserts on or prints any credential-shaped value.

### 55. Real E2E run + repeatability

All 3 required consecutive runs, against the real Docker stack (no
mocked backend, no intercepted fake responses), via
`PLAYWRIGHT_BROWSER_CHANNEL=chrome npx playwright test`:

| Run | Result | Runtime | Notes |
|---|---|---|---|
| 1 | 5 passed, 0 failed | 12.2s | server reused from prior manual verification |
| 2 | 5 passed, 0 failed | 13.2s | server reused |
| 3 | 5 passed, 0 failed | 12.1s | **cold start** -- port 3000 killed first, full `npm run build && npm run start` boot from scratch |

Zero retries used anywhere (`retries: 0` throughout). No flakiness
observed across all 3 runs plus the additional runs during initial
locator debugging (8 total suite executions this session, the first 3
of which surfaced the real, now-fixed locator bugs in §53 — every run
since has been clean). Production invariants (Qdrant 39; SynPUF
15/219/732/29/848; FHIR 5/177/187/234/1341/865/116; Review 4/8) were
re-verified identical after this E2E work — all 5 journeys are
read-only, confirmed by zero mutation.

### 56. Remaining E2E gaps (unchanged scope, for Slice 3)

Review/HITL lifecycle E2E (explicitly deferred — needs the
track-and-cleanup isolation design from Slice 1 §12 actually
implemented), dependency-degradation E2E (needs a real service stopped
mid-test, not attempted this slice), the combined policy+structured
multi-agent workflow journey, and any CI workflow to actually run this
suite automatically. The Chromium-binary-download constraint (§45) means
a genuinely fresh environment (a new CI runner, a new developer machine)
should default to the standard `npx playwright install chromium` path
(which this config supports natively) — the `PLAYWRIGHT_BROWSER_CHANNEL`
escape hatch exists for environments like this session's sandbox, not as
the primary expected path.

## Slice 3 — Complete bounded critical E2E coverage + failure/degradation validation

### 57. Trace-policy correction (verified empirically, not assumed)

Slice 2's config paired `retries: 0` with `trace: "on-first-retry"`.
`"on-first-retry"` only records a trace on a test's *first retry attempt*
— with `retries: 0` a test is never retried at all, so a genuine
single-attempt failure produced a screenshot but zero trace file. Rather
than trust that reading of the Playwright docs, this was verified with a
temporary, deliberately-failing probe test
(`frontend/e2e/_tmp_trace_probe.spec.ts`, deleted immediately after use):
under the old config it produced `test-failed-1.png` and
`error-context.md` but no `trace.zip`; after changing
`use.trace` to `"retain-on-failure"` (`frontend/playwright.config.ts`),
the exact same probe produced all three, including a real `trace.zip`.
`retries: 0` and `screenshot: "only-on-failure"` are unchanged —
`"retain-on-failure"` records a trace for every test and keeps only the
ones for tests that actually failed, which is the correct behavior when
retries stay at zero.

### 58. Clean-environment bootstrap: isolation strategy

`scripts/bootstrap_clean_e2e_env.sh` proves every E2E prerequisite
(Postgres, Qdrant, Redis, backend, CMS retrieval index, FHIR fixtures,
SynPUF fixtures) can be established deterministically from a genuinely
fresh environment, without ever touching the developer stack's data.

Isolation mechanism: a **separate Docker Compose project**
(`careflow-ai-e2e-clean` by default) reusing the exact same
`docker-compose.yml` service definitions, on different host ports
(Postgres 25432, Qdrant 26333, Redis 26379, backend 28000 by default) and
its own Postgres database name (`careflow_e2e_clean`). Compose namespaces
named volumes by project name, so this project's `postgres_data`/
`qdrant_data` volumes are entirely separate from the developer stack's —
nothing this script does can read, write, or delete the developer
stack's data, and the developer stack's containers are never stopped by
it.

Schema and data are established using the exact same commands the
developer stack itself was built with — no second ETL implementation:

- `python -m app.db.migrate` (idempotent schema migrations)
- `python -m ingestion.cli ingest --reindex` (CMS policy corpus → Qdrant)
- `python -m ingestion.cli ingest-fhir` (Synthea dev subset → Postgres)
- `python -m ingestion.cli ingest-synpuf` (DE-SynPUF dev subset → Postgres)

`RAG_PROVIDER=deterministic` and `OPENAI_API_KEY=""` are exported by the
script itself — establishing this environment requires no OpenAI key at
all.

### 59. Clean-environment bootstrap: proof

A full `up` run (`scripts/bootstrap_clean_e2e_env.sh up`) completed in
**34 seconds** end to end (isolated Postgres/Qdrant/Redis started and
healthy, schema migrated, CMS/FHIR/SynPUF ingested, backend built and
started, `/ready` confirmed) — fast because the sentence-transformer
model was already present in the shared, read-only `.cache/models` mount
and the backend image's layers were already cached; a genuinely
never-built environment would additionally pay a one-time image build
and model-download cost.

Data invariants verified directly against the isolated stack after `up`,
matching the developer stack's own known-good shape exactly:

- Qdrant: **39** points
- FHIR: **5** patients / **177** encounters / **187** conditions / **234**
  procedures / **1341** observations / **865** components / **116**
  medication requests
- SynPUF: **15** beneficiaries / **219** claims / **732** diagnoses /
  **29** procedures / **848** claim lines
- Review: **0** cases / **0** events (correctly empty — a fresh
  environment has no review history)

The developer stack was re-verified immediately after (`docker ps`, and
`review_cases`/`review_events` counts) to confirm it was never touched:
still exactly **4** review cases / **8** review events, all of the
developer stack's own containers still running unmodified.

A first-run-only characteristic was found and fixed during this proof:
the very first real `/query` call against a freshly started backend
process lazily loads the sentence-transformer embedding model inside
that process (the ingestion CLI's own model load, above, happens in a
separate short-lived process and does not warm the backend). This made
E2E-2 time out once against a cold isolated backend (15s citation
timeout) while passing in under 1s once warm. Fixed by adding one
throwaway `POST /query` call to the bootstrap script immediately after
`/ready` succeeds, discarding the response — a legitimate part of
"prerequisites are established," not a test change. `scripts/
bootstrap_clean_e2e_env.sh down` tears the isolated project down
completely (`docker compose down -v`), confirmed via `docker ps -a`
to leave zero containers, networks, or volumes behind.

### 60. E2E-6: combined policy + structured (POLICY_AND_STRUCTURED) workflow

`frontend/e2e/e2e-6-multi-agent-workflow.spec.ts` drives the real
`/workflow` page (backed by `POST /reviewable-query` → the real Phase 10
multi-agent graph) with the same golden policy question already proven
in E2E-2 and the same known FHIR patient ID already proven in E2E-3 —
combined for the first time into one request. Structured route is FHIR
only (never FHIR + SynPUF as the same request/person — Phase 10's
dataset-boundary rule).

Asserts, each scoped to its own `<section>` (proving the two evidence
sources render separately, not merged): the Medicare Policy Evidence
section shows a real citation for the real expected chunk; the Synthetic
Healthcare Data section shows the real FHIR patient id back from the
real tool call plus its synthetic-data notice; a Validation section is
present; the application's own safety disclaimer ("Policy information
and synthetic healthcare data are shown as separate evidence sources...
does not establish individual coverage, eligibility, medical...") is
visible. The test itself never asserts or implies policy applies to the
patient, a coverage determination, medical necessity, or eligibility —
it explicitly asserts the *absence* of exactly that framing as a second
safety check.

### 61. E2E-7: HITL review lifecycle + cleanup

`frontend/e2e/e2e-7-review-lifecycle.spec.ts` drives create → queue →
detail → decision → audit event entirely through the real UI: submits a
combined workflow request with "Request human review" checked (`/
workflow`), follows the "View review" link it produces, finds the same
review in the `/reviews` pending queue, opens it from there, fills in a
reviewer identifier and reason, clicks Approve, and verifies both the
status badge and the Audit History list reflect the decision.

Cleanup: every `review_id` this test creates is tracked in
`createdReviewIds`, and `scripts/cleanup_review_ids.py` is invoked in a
`finally` block regardless of pass/fail. That script is not a
reimplementation — it is `tests/test_review_api.py`'s own
`created_review_ids` fixture logic (delete `review_events`, then
`review_cases` in reverse creation order, then commit), factored out to
run standalone from Node via `frontend/e2e/reviewCleanup.ts`
(`execFileSync`), since a Playwright test cannot import a pytest
fixture directly. Verified twice: once when the test passed cleanly
(a locator bug — see §63 — was caught and fixed) and once when the test
itself failed on that bug, confirming cleanup runs on both outcomes.
The developer stack's baseline review count was re-checked after every
run in this slice and was exactly **4** cases / **8** events every time.

### 62. E2E-8: dependency readiness degradation + recovery

`frontend/e2e/e2e-8-dependency-degradation.spec.ts` stops and restarts
real Docker containers (`docker stop`/`docker start`, never `rm` or
`down` — volumes and data are never touched) via the `/` page's System
Status panel, which exposes per-dependency Available/Unavailable badges
and a manual Refresh button (no automatic polling in this app — see
`hooks/useSystemStatus.ts`).

Two claims proven live, each already true at the unit level in
`backend/app/services/health.py::check_readiness()` but not previously
exercised end to end:

1. Stopping Redis alone leaves overall status "Ready" (its badge alone
   turns Unavailable; Postgres/Qdrant/overall stay Available/Ready) —
   Redis is non-authoritative.
2. Stopping Postgres (chosen over Qdrant as "the more deterministic to
   test" per the Slice 3 directive: Postgres has a real Docker
   `HEALTHCHECK`, Qdrant has none) makes the Postgres badge Unavailable
   and overall readiness degrade, confirmed via the same UI a user would
   see.

Both dependencies are restored in `finally` blocks, each gated on the
container's own Docker healthcheck (`docker inspect ... .State.Health.
Status`, polled — never a fixed sleep) rather than assumed instantaneous,
plus an outer belt-and-suspenders `finally` that restarts either
container if it is not already healthy when the test ends — the suite
cannot finish with a dependency left down even if an assertion inside
throws. Container names are overridable via `E2E_REDIS_CONTAINER`/
`E2E_POSTGRES_CONTAINER` so the identical test also runs correctly
against the isolated clean-bootstrap stack's own container names
(exercised during this slice's clean-bootstrap full-suite run, §64).

The expected `GET /ready` 503 the browser itself logs while Postgres is
down is allowlisted narrowly (`allowConsoleError(/status of 503
\(Service Unavailable\)/)`) — scoped to that exact message, per the
directive's "no global suppression" rule; every other console/page error
still fails the test.

### 63. Locator bugs found and fixed this slice

Two genuine test-authoring bugs, found via the same "run it against the
real app and read the real failure" discipline as Slice 2's three:

- E2E-7: `page.getByRole("heading", { name: "Review" })` on the review
  detail page hit Playwright's strict-mode violation — it also matches
  the `<h2>` "Review Metadata" heading (substring match). Fixed with
  `exact: true`, mirroring Slice 2's own precedent for this exact class
  of bug.
- E2E-8: the fixture's blanket console-error capture (real, deliberate
  design — see `frontend/e2e/fixtures.ts`) correctly caught the
  browser's own "failed to load resource: 503" log during the intentional
  Postgres-down step. This is not a bug in the app or the fixture; the
  Slice 3 directive explicitly anticipated it ("for intentional-
  degradation journeys only the expected failure should be tolerated") —
  fixed with the scoped `allowConsoleError` call described in §62, not by
  weakening the fixture itself.

A third issue, found in this slice but not a test bug: `npm run lint`
scanned `frontend/playwright-report/`'s own generated, minified trace-
viewer assets as if they were project source once that directory existed
on disk (it did not exist yet when Slice 2's own lint run happened to be
checked). Fixed by adding `playwright-report/**` and `test-results/**` to
`eslint.config.mjs`'s `globalIgnores` — both already gitignored, but
ESLint's ignore list is independent of git's.

### 64. Full Slice 3 suite: 3 consecutive runs + repeatability

All 9 scenarios (E2E-1 through E2E-9, see §65) run together, in file
order, single worker, zero retries. Three consecutive clean runs, one of
which used the isolated clean-bootstrap stack end to end (frontend
rebuilt with `NEXT_PUBLIC_API_BASE_URL` pointed at the isolated
backend's port, `DATABASE_URL`/`QDRANT_URL`/`REDIS_URL` pointed at the
isolated stack for E2E-7's cleanup script, `E2E_REDIS_CONTAINER`/
`E2E_POSTGRES_CONTAINER` pointed at the isolated stack's own container
names for E2E-8):

| Run | Environment | Frontend start | Result | Runtime |
|---|---|---|---|---|
| 1 | developer stack | cold (`npm run build && npm run start`) | 9/9 passed | 25.3s |
| 2 | developer stack | cold (rebuilt) | 9/9 passed | 28.3s |
| 3 | **isolated clean-bootstrap stack** | cold (rebuilt, pointed at isolated backend) | 9/9 passed | 29.6s |
| 4 (extra) | developer stack, `.env.local` restored | cold (rebuilt) | 9/9 passed | 31.5s |

Zero retries in every run (`retries: 0` throughout). Zero flaky
failures across all four runs. Two real bugs (§63) were found and fixed
between the first attempt and these four clean runs — none reappeared.
Data invariants (developer stack review count, isolated stack review
count, both stacks' container health) were verified after every run;
see §61 and §65.

### 65. Final scenario count and dataset boundary

Nine scenarios total (within the ~8–10 target):

1. E2E-1 — application smoke
2. E2E-2 — policy question journey
3. E2E-3 — FHIR structured assistant journey
4. E2E-4 — SynPUF structured assistant journey
5. E2E-5 — Analytics journey
6. E2E-6 — combined policy + structured (FHIR) multi-agent workflow
7. E2E-7 — HITL review lifecycle + cleanup
8. E2E-8 — dependency readiness degradation + recovery
9. E2E-9 — abstention journey (bounded, optional; reuses the already-
   proven `test_unrelated_question_abstains_with_200` backend behavior,
   never a forced OpenAI failure or an invented failure mode)

No scenario combines FHIR and SynPUF in the same request/person at any
point in this suite.

### 66. Corrected flaky-test re-verification

`tests/test_query_embedding_cache.py::
test_hit_returns_cached_vector_without_calling_the_model` (Slice 2's fix:
exclude `timestamp`/`duration_ms` before the "no leaked vector digits"
substring check) was run **20 consecutive times** this slice, isolated to
just this test: **20/20 passed**, 0 retries, 0 flaky failures.

### 67. Regression, invariants, and security (Slice 3)

Full frontend regression: 330/330 unit+component tests passed (unchanged
from Slice 2's baseline), lint clean (after the `playwright-report`/
`test-results` ignore fix, §63), typecheck clean, `next build` clean.
Full backend regression: 842 passed / 169 skipped / 0 failed (unchanged
skip count and reasons from Slice 1/2's audit), `ruff check` clean,
`ruff format --check` clean (165 files), `pip check` clean, `git diff
--check` clean.

Production invariants (developer stack) re-verified identical before and
after every run in this slice: Qdrant 39 points; FHIR 5/177/187/234/
1341/865/116; SynPUF 15/219/732/29/848; Review 4/8. The isolated stack's
own invariants (§59, §61) are reported separately and never conflated
with the developer stack's.

Security check: no `OPENAI_API_KEY` value anywhere in this slice's new
files (the bootstrap script explicitly exports it empty); no production
secret (`POSTGRES_PASSWORD` defaults match the repo's existing, already-
committed local-only placeholder, nothing new); no real PHI (only the
same synthetic FHIR/SynPUF ids already used throughout this suite); no
browser binary, trace, or screenshot committed (`test-results/`,
`playwright-report/` remain gitignored and confirmed absent from `git
status` after every run); `scripts/cleanup_review_ids.py` uses
parameterized queries only (`%s` placeholders, no string-interpolated
SQL); E2E-6 never combines FHIR and SynPUF in one request; no test
locator depends on a `test-results/` artifact path; the review cleanup
mechanism only ever deletes review_ids the test itself created and
tracked; no credential appears in `playwright.config.ts` or `scripts/
bootstrap_clean_e2e_env.sh` beyond the repo's existing local-only
default.

### 68. Remaining Phase 16 work

Slice 4: GitHub Actions CI workflow(s) implementing the 5-job
architecture designed in Slice 1, wiring this now-complete, now-proven-
stable 9-scenario E2E suite (plus the clean-bootstrap script) into CI for
the first time. Slice 5: final clean-checkout QA and the one Phase 16
checkpoint commit. Neither is started by this slice.

## Slice 4 — GitHub Actions CI/CD quality + test automation

### 69. Re-audited job architecture: six jobs, not the original five

Slice 1's five-job sketch (§15) predates browser E2E entirely. With
Slice 3's 9-scenario Playwright suite now proven stable, the workflow
(`.github/workflows/ci.yml`) uses **six** jobs: `backend-quality`,
`frontend-quality`, `backend-tests`, `frontend-tests`,
`integration-tests`, `e2e`.

`integration-tests` and `e2e` were evaluated for merging (directive §4)
and kept separate. Reasoning:

- **Test semantics differ.** `integration-tests` proves repository/API-
  boundary correctness across ~99 deterministic cases (many small,
  focused assertions against real Postgres/Redis). `e2e` proves 9 real-
  browser user journeys end to end through the actual UI. A single
  failing signal from a merged job would conflate "an API contract
  broke" with "a user-facing journey broke" — genuinely different
  triage paths.
- **Dependency weight differs.** `integration-tests` never touches
  Qdrant content, the embedding model, or a built Docker image — it
  runs against the same Python environment already installed for
  `backend-quality`/`backend-tests`, plus lightweight Postgres/Redis/
  Qdrant service containers. `e2e` always needs the full clean-bootstrap
  stack (Docker image build, CMS/FHIR/SynPUF ingestion, a running
  frontend, an installed Chromium). Merging would force the cheaper job
  to always pay the expensive one's setup cost.
- **Failure isolation matters for maintenance.** Keeping them separate
  means a PR author's CI summary line already says which class of thing
  broke before opening any log.

They are not serialized relative to each other — no `needs` between
them — since their infrastructure is fully independent and nothing is
gained by waiting.

### 70. Triggers, permissions, concurrency

Triggers: `pull_request` (all branches) and `push` to `main` — confirmed
the actual default/primary development branch via `git branch -a`
(`main` exists; every phase branch in this repo branches from and is
compared against it). No scheduled/cron trigger added.

Permissions: `contents: read` at the workflow level, nothing more. No
job writes to the repository, comments on a PR, publishes a package, or
requests an OIDC token — none of the jobs need it (`actions/upload-
artifact` and `actions/cache` do not require elevated `permissions:`
scopes).

Concurrency: `group: ci-${{ github.workflow }}-${{ github.ref }}`,
`cancel-in-progress: true` — a new push to the same PR/branch cancels
its own superseded run; a different branch or PR is a different group
and is never affected.

### 71. Dependency versions

Python: **3.12**, read from `pyproject.toml`'s `requires-python =
">=3.12,<3.15"` and `backend/Dockerfile`'s `FROM python:3.12-slim` — not
an arbitrary newer version. Node: **20.x** via `actions/setup-node`
(no `engines` field or `.nvmrc` exists in the repo to override this;
`@types/node: ^20` and Next.js 16.3.6 both imply 20+ as the target).
Actions used, all stable official first-party actions, no third-party
substitutes: `actions/checkout@v4`, `actions/setup-python@v5`,
`actions/setup-node@v4`, `actions/cache@v4`, `actions/upload-artifact@v4`.

### 72. Backend dependency install (every backend-touching job)

```
pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.lock
pip install --no-deps -e .
```

This exactly mirrors `backend/Dockerfile`'s own order, not README's plain
`pip install -r requirements-dev.lock` alone — `requirements-dev.lock`
(via `requirements-ingestion.lock`) pins `torch==2.8.0` with no index-url
directive of its own, so installing it plain on a Linux CI runner would
resolve PyPI's default CUDA-enabled wheel (multi-GB). Installing the CPU
wheel first means the later `-r requirements-dev.lock` sees `torch`
already satisfied at the exact pinned version and does not touch it —
the identical mechanism `backend/Dockerfile` already uses for the same
reason.

### 73. Frontend dependency install

`npm ci` everywhere (never `npm install`) — `frontend/package-lock.json`
is committed, and `npm ci` is lockfile-enforcing and fails on drift.
`actions/setup-node`'s `cache: npm` is keyed against
`frontend/package-lock.json`.

### 74. backend-quality / frontend-quality / backend-tests / frontend-tests jobs

Each runs exactly the commands already run locally every slice, unchanged:
`ruff check .`, `ruff format --check .`, `pip check` (backend-quality);
`npm ci`, `npm run lint`, `npm run typecheck`, `npm run build`
(frontend-quality); `python -m pytest tests/ -q` with no
`CAREFLOW_*_INTEGRATION` variable set, i.e. the unit tier only
(backend-tests); `npm ci`, `npm test` (frontend-tests). No service
containers, no Docker, no model download in any of the four — they are
the fastest jobs and should report first.

### 75. Integration-test decision: which of the 169 gated tests run in CI

Re-audited from Slice 1's skip-reason table (§6), each of the 13 gates
was classified A (deterministic, Postgres/Redis-only, appropriate for
every PR) / B (model- or CMS-Qdrant-index-heavy) / C (redundant with the
now-existing E2E suite) / D (external-asset/network-dependent) / E
(benchmark/comparison, not correctness — manual/nightly territory, not
built this slice):

| Gate | Count | Class | In CI integration-tests? | Reason |
|---|---:|---|---|---|
| `CAREFLOW_REVIEW_INTEGRATION` | 54 | A | **Yes** | Postgres + migration only |
| `CAREFLOW_STRUCTURED_INTEGRATION` | 37 | A | **Yes** | Postgres + real FHIR/SynPUF fixtures only |
| `CAREFLOW_ANALYTICS_INTEGRATION` | 3 | A | **Yes** | Postgres only |
| `CAREFLOW_CACHE_INTEGRATION` | 3 | A | **Yes** | Redis only |
| `CAREFLOW_INTEGRATION` (omnibus) | 2 | A | **Yes** | Connectivity-only smoke check (`check_dependencies` + `GET /health`), no model |
| `CAREFLOW_MULTI_AGENT_INTEGRATION` | 14 | B/C | No | Needs Qdrant + embedding model; the combined policy+structured workflow is already proven live by E2E-6/E2E-7 |
| `CAREFLOW_ORCHESTRATION_INTEGRATION` | 12 | B/C | No | Needs Qdrant + embedding model for the policy route; already proven live by E2E-2/3/4/9 |
| Live Qdrant/model/CMS-index dependency | 28 | B | No | Retrieval-quality tests needing the full corpus + model |
| `CAREFLOW_INGESTION_INTEGRATION` | 7 | B/C | No | Needs the frozen CMS snapshot + model; the ingest CLI is already exercised as a black box by the E2E bootstrap script |
| `CAREFLOW_LATENCY_INTEGRATION` | 5 | E | No | Timing benchmarks, not correctness — unsuitable for shared-runner PR gating |
| Downloaded model / published local index | 3 | B | No | Model-heavy |
| `CAREFLOW_RERANKER_COMPARISON_INTEGRATION` | 1 | E | No | A comparison tool, not a correctness test |
| **Enabled total** | **99** | | | |
| **Excluded total** | **70** | | | |

**Verified, not assumed**: running `pytest tests/ -q` with exactly the 5
enabled gates set to `1` (and the other 8 left unset) against the
developer stack produced **941 passed, 70 skipped, 0 failed** — 842 (the
unit-tier baseline) + 99 (the newly-enabled subset) = 941, and 169 − 99 =
70, both matching exactly. The developer stack's review baseline was
re-checked after and was still exactly 4/8 — the review-gate tests'
own fixture-based cleanup (the same `created_review_ids` pattern E2E-7
reuses) left no residue.

This gives the integration tier real, additional signal beyond
`backend-tests` (which never touches a real database) and beyond `e2e`
(which asserts through the UI on 9 broad journeys, not ~99 focused
API/repository-layer cases) — genuinely complementary, not duplicate,
coverage.

### 76. Integration-tests job implementation

GitHub-hosted `services:` containers for Postgres/Qdrant/Redis (the exact
images/versions from `docker-compose.yml`). The backend itself runs as a
plain host process (`python -m uvicorn app.main:app`), not the Docker
image — it reuses the same Python environment already installed for
`backend-quality`/`backend-tests`, avoiding a redundant Docker image
build for a job that has no other reason to touch Docker. Setup: `python
-m app.db.migrate`, then `ingestion.cli ingest-fhir` and `ingest-synpuf`
only (no CMS/Qdrant ingestion — none of the 5 enabled gates need it, so
this tier never downloads or loads the embedding model at all). Readiness
is polled two ways: `scripts/wait_for_backend_ready.py` (Postgres/Qdrant
connectivity, reused as-is, not reimplemented) before starting the
backend process, then a direct `curl .../ready` poll to confirm the host
uvicorn process itself is actually serving (the library-level script
alone cannot confirm that).

### 77. E2E job implementation

Gated behind `backend-quality`, `frontend-quality`, `backend-tests`,
`frontend-tests` all succeeding first (§38: avoids paying for a Chromium
install + Docker image build + model load on a commit already known
broken by a 10-second lint failure) but runs independently of, and in
parallel with, `integration-tests` — no shared infrastructure, no reason
to serialize.

Orchestrates, rather than reimplements, the exact Slice 3 mechanism:
`scripts/bootstrap_clean_e2e_env.sh up` (same isolated Compose project,
same reused `app.db.migrate`/`ingestion.cli` commands, same
`careflow-ai-e2e-clean-*` container names), `npx playwright test`, then
`scripts/bootstrap_clean_e2e_env.sh down` in an `if: always()` step so
the isolated stack's containers are never left running on the runner
regardless of pass/fail. `E2E_POSTGRES_CONTAINER`/`E2E_REDIS_CONTAINER`
are set to the isolated stack's own container names, so E2E-8's
dependency-degradation test (unmodified from Slice 3) operates on the
isolated stack in CI rather than a "developer stack" that does not exist
on a GitHub runner. `frontend/e2e/reviewCleanup.ts` gained a `PYTHON_BIN`
override (defaulting to the local `.venv/bin/python` convention) because
CI installs backend dependencies directly onto the runner's Python via
`actions/setup-python`, not into a project-local `.venv` — the workflow
sets `PYTHON_BIN: python`.

The CI environment starts at Review 0/0 (a genuinely fresh database, per
the Slice 3 bootstrap proof) — the workflow never depends on, or
conflates itself with, the developer stack's 4/8 baseline; E2E-7's own
cleanup still returns the isolated stack to 0/0 after each run.

### 78. Chromium installation

`npx playwright install --with-deps chromium` — the normal, documented
CI installation path, installing Chromium's system dependencies via
`apt` on the Ubuntu runner. This is deliberately **not** the
`PLAYWRIGHT_BROWSER_CHANNEL=chrome` workaround Slices 2-3 used locally
for this sandboxed session's specific `cdn.playwright.dev`/
`storage.googleapis.com` network restriction — `playwright.config.ts`'s
`channel` option defaults to `undefined` (bundled Chromium) whenever
`PLAYWRIGHT_BROWSER_CHANNEL` is unset, which is exactly the CI job's
env — GitHub-hosted runners have normal outbound internet access, so the
standard path is expected to work there without the workaround. No
Firefox or WebKit is installed. **This exact step could not be executed
inside this development session** (same network constraint documented in
Slice 2 §45) — the rest of the E2E mechanism (bootstrap, all 9
scenarios, cleanup, teardown) was reproduced locally against the real
isolated stack using the `chrome`-channel path instead, proving the
Playwright suite itself; only the bundled-Chromium *download* step is
unverified outside a real CI runner, which is the documented, expected
Playwright installation method and not new orchestration logic this
project invented.

### 79. Model download / cache strategy

`backend-quality`/`frontend-quality`/`backend-tests`/`frontend-tests`/
`integration-tests` never download the embedding or reranker model at
all (§75/§76). Only `e2e` needs it, via the bootstrap script's `ingest`
step. `actions/cache@v4` caches `.cache/models` keyed on `${{ runner.os
}}-models-all-MiniLM-L6-v2-${{ hashFiles('requirements-ingestion.lock')
}}` — the model's own identity plus the dependency/lock context that
governs how `sentence-transformers` reads/writes that cache directory,
per the directive's explicit cache-key guidance. Nothing else is
cached — no credentials, no Postgres data, no review state; Docker
volumes for the isolated E2E stack are never part of any cache key and
are destroyed every run by `bootstrap_clean_e2e_env.sh down`.

### 80. OpenAI strategy

Every job sets `RAG_PROVIDER: deterministic` and `OPENAI_API_KEY: ""`
explicitly (mirroring `.env.example`'s own documented default) — no
GitHub repository secret is read, referenced, or required anywhere in
this workflow. This is also what makes the workflow safe for ordinary
fork pull requests (§36): nothing in it can fail specifically because a
fork PR lacks access to repository secrets, because none are used.

### 81. Readiness, HITL, and dependency-degradation CI behavior

Readiness is gated on `GET /ready` throughout (`wait_for_backend_ready.py`
in `integration-tests`; the bootstrap script's own `/ready` poll in
`e2e`) — never the stricter legacy `GET /health`, except in the single
`CAREFLOW_INTEGRATION` omnibus test itself, which deliberately exercises
`/health`'s stricter (Redis-required) contract as its own documented
behavior, unchanged from Phase 13. Phase 13's "Postgres+Qdrant
authoritative, Redis optional" semantics are not regressed anywhere in
this workflow.

E2E-7 (HITL lifecycle) runs unmodified in the `e2e` job; its cleanup
mechanism (§77) still deletes exactly the review rows it created,
verified locally to return the isolated stack to 0/0 after a run. E2E-8
(dependency degradation) runs unmodified against the isolated stack's
own containers via the `E2E_POSTGRES_CONTAINER`/`E2E_REDIS_CONTAINER`
overrides — GitHub-hosted runners have ordinary Docker CLI access for
the runner's own user with no privileged/sudo requirement, so `docker
stop`/`docker start` need no special runner permissions beyond what
`ubuntu-latest` already grants.

### 82. Failure artifacts and cleanup

`actions/upload-artifact@v4` uploads `frontend/playwright-report/` and
`frontend/test-results/` (trace.zip, screenshots included) only `if:
failure()`, with `retention-days: 7` — nothing is uploaded on a
successful run. No `.env` file, database dump, credential, or raw
secret-bearing log is ever part of the artifact path. `scripts/
bootstrap_clean_e2e_env.sh down` runs in an `if: always()` step
regardless of the E2E outcome, so the isolated stack's containers,
network, and volumes are removed at the end of every run, pass or fail.

### 83. Timeouts

`timeout-minutes` set per job based on observed local runtime plus CI
overhead, not an arbitrarily large value: `backend-quality`/
`frontend-quality`/`backend-tests`/`frontend-tests` at 10 minutes (all
observed to complete in well under 1 minute locally); `integration-tests`
at 15 minutes (observed ~65 seconds locally against an already-running
stack, plus real CI service-container startup overhead);
`e2e` at 20 minutes (observed ~30 seconds for the suite itself, plus a
Docker image build, Chromium+system-dependency install, and a model
download that only happen on a cache-cold run).

### 84. Security audit

No plaintext secret anywhere in the workflow (confirmed via a direct
grep for `secrets.`/`SECRET`/`TOKEN`/`pull_request_target` — zero
matches). `permissions: contents: read` only. No shell step interpolates
untrusted pull-request-supplied text (PR title, body, branch name, etc.)
into a `run:` block — every `${{ }}` expression used is `runner.os`,
`env.*`, or `hashFiles(...)`, none of which are attacker-controlled.
`pull_request_target` is not used anywhere, so no job ever runs with
elevated permissions or secret access against untrusted fork code.
Fork PRs are safe: nothing in this workflow requires a repository
secret, so no fork-PR run can fail purely for lacking one.

### 85. YAML validation and local reproduction

Validated with `python3 -c "import yaml; yaml.safe_load(...)"` plus a
structural check that every step declares `uses` or `run` — no dedicated
GitHub Actions linter (e.g. `actionlint`) was already available in this
environment, and per the directive's own instruction not to add a large
new tool dependency solely for YAML validation, none was installed.
(PyYAML parses the bare `on:` key as the boolean `True` under YAML 1.1
coercion rules — a well-known, purely cosmetic artifact of using a
generic YAML parser against a GitHub Actions file; GitHub's own parser
handles `on:` correctly, and the raw file was independently confirmed to
contain the literal `on:` key via `grep`.)

Local command reproduction, actual results: `backend-quality` (`ruff
check .`, `ruff format --check .`, `pip check` — all clean, matching
§1/§41's baseline); `frontend-quality` (`npm run lint`, `npm run
typecheck`, `npm run build` — all clean); `backend-tests` (`pytest
tests/ -q` — 842 passed/169 skipped/0 failed); `frontend-tests` (`npm
test` — 330 passed); `integration-tests`' pytest selection (the exact 5
env vars) — reproduced directly against the developer stack: **941
passed, 70 skipped, 0 failed**, review baseline unaffected (§75); `e2e`
— reproduced via the full Slice 3 mechanism (clean bootstrap up, 9/9
Playwright scenarios against the isolated stack including E2E-8 with the
same `E2E_POSTGRES_CONTAINER`/`E2E_REDIS_CONTAINER` override this
workflow uses, teardown) — the only step not reproducible in this
sandboxed session is the bundled-Chromium download itself (§78).

### 86. Clean-checkout simulation

Simulated without deleting the working repository: the `integration-tests`
reproduction above used fresh env vars pointed at the developer stack's
existing service containers (standing in for GitHub's ephemeral
`services:` containers, which are always freshly created per job run);
the `e2e` reproduction used the genuinely fresh, from-scratch
`careflow-ai-e2e-clean` Compose project (§58-59 of Slice 3), which is the
same isolation mechanism the CI job itself invokes — not a separate,
CI-only simulation path. Evaluation artifacts (`artifacts/evaluation/`,
`docs/evaluation/`) are committed project assets already copied into the
backend Docker image by `backend/Dockerfile` (Phase 15's own
`COPY artifacts/evaluation` step) — confirmed present and unchanged this
slice; CI never generates a new Phase 12 experiment.

## Slice 5 — Final QA, reproducibility audit, and Phase 16 checkpoint

### 87. Phase 16 status: complete at the checkpoint

Phase 16 implementation is complete as of this checkpoint commit. Final,
actually-measured state:

- **Frontend tests**: 330 passed, 0 failed (Vitest, component/unit tier).
- **Backend default tests**: 842 passed, 169 skipped, 0 failed (unit
  tier, no `CAREFLOW_*_INTEGRATION` set).
- **Backend integration tier** (the CI-selected deterministic subset —
  `CAREFLOW_REVIEW_INTEGRATION`, `CAREFLOW_STRUCTURED_INTEGRATION`,
  `CAREFLOW_ANALYTICS_INTEGRATION`, `CAREFLOW_CACHE_INTEGRATION`,
  `CAREFLOW_INTEGRATION`): 941 passed, 70 skipped, 0 failed.
- **E2E**: 9 scenarios (E2E-1 through E2E-9), 9 passed, 0 failed, 0
  retries, run repeatedly across Slices 3-5 with no observed flakiness.
- **CI jobs**: 6 — `backend-quality`, `frontend-quality`,
  `backend-tests`, `frontend-tests`, `integration-tests`, `e2e` — defined
  in `.github/workflows/ci.yml`.
- **Clean-bootstrap behavior**: `scripts/bootstrap_clean_e2e_env.sh`
  proven repeatedly (Slice 3 and Slice 4) to establish a fully isolated
  Postgres/Qdrant/Redis/backend stack with real CMS/FHIR/SynPUF data from
  a completely fresh state, in ~34 seconds warm / longer on a genuinely
  cold cache, without ever touching the developer stack's data.
  Idempotent teardown via the same script's `down` subcommand.
  Playwright's `retries: 0`, `trace: "retain-on-failure"`,
  `screenshot: "only-on-failure"` (corrected in Slice 3, §57 — kept
  unchanged since).
- **Security properties**: no OpenAI key or any other secret required by
  any test tier or CI job (`RAG_PROVIDER=deterministic` throughout);
  `contents: read`-only workflow permissions; no `pull_request_target`;
  no untrusted-input shell interpolation; fork-PR safe; no committed
  browser binary, trace, screenshot, or model file (all covered by
  `.gitignore`); no arbitrary/string-interpolated SQL; review-row cleanup
  scoped to only the rows a test itself created; no cross-dataset (FHIR ×
  SynPUF) patient linkage anywhere in the suite.

### 88. Known limitation: GitHub Actions has not yet run on GitHub's own infrastructure

**The GitHub Actions workflow has been locally validated (YAML structure,
every job's key commands reproduced locally against real services with
matching results) but has NOT yet been proven by an actual GitHub-hosted
Actions run.** This repository has no `git remote` configured (confirmed
via `git remote -v` at the time of this checkpoint) and this slice does
not push. The one step of the `e2e` job that could not be exercised at
all in this development session is `npx playwright install --with-deps
chromium` itself (blocked by this sandboxed session's own network
egress restrictions, unrelated to the workflow's correctness) — the rest
of that job's logic was reproduced via the same clean-bootstrap
mechanism using a local Chromium substitute. First hosted CI run remains
pending a future push to a configured GitHub remote (Phase 17).

