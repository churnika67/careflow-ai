# Phase 14 — frontend foundation

## Slice 1: audit, Next.js foundation, backend connectivity

This slice establishes the CareFlow AI frontend's foundation only: an
application shell, backend connectivity for system status, and the
supporting typed client/test/documentation infrastructure. No product
feature (Ask CareFlow, patient/claims lookup, review UI, analytics) exists
yet — see "Scope boundary for Slice 2+" at the end of this document.

## Frontend audit (performed before any file was created)

Searched the repository for `frontend/`, `web/`, `ui/`, `client/`, `app/`
directories, `package.json`/lockfiles, Next.js/React/TypeScript/Tailwind
config, existing components, CSS, API clients, environment variables, and
Docker frontend configuration, plus README/docs for any planned frontend
architecture.

**Found:** a `frontend/` directory already existed at the repository root,
containing only a `.gitkeep` placeholder — no `package.json`, no lockfile,
no source. `README.md` explicitly documented it: `| frontend/ | Reserved
for Next.js in Phase 14 |`, and separately: "Planned: Next.js/TypeScript
frontend → analysis → validation → cited report and human review." No
other frontend artifact existed anywhere in the repository (`backend/`,
`ingestion/`, `evaluation/`, `tests/`, `scripts/` are all Python; a
top-level `infrastructure/` directory is likewise an empty `.gitkeep`
placeholder, reserved for later and unrelated to the frontend).

**Conclusion:** no existing frontend to reuse or extend, and a clearly
pre-designated location already existed. Built directly into that
`frontend/` directory rather than creating a new one elsewhere.

## Framework / versions

- **Next.js 16.3.6** (App Router, TypeScript) — current stable at scaffold
  time (`npm view create-next-app version`).
- **React 19.2.8** / **react-dom 19.2.8** (Next.js 16's own default pairing).
- **TypeScript ^5** (`strict: true`, retained from the scaffold; not
  weakened).
- **Node.js v25.6.1** / **npm 11.9.0** (this machine's installed toolchain;
  Next.js 16 requires Node ≥18.18, comfortably satisfied).

Scaffolded via `create-next-app@latest` with: TypeScript, ESLint, App
Router, no `src/` directory, `@/*` import alias, npm, Tailwind **declined**
(see "Styling decision" below), Turbopack declined for the build step
(kept the stable webpack-based `next build`/`next dev` path for this
foundation slice rather than opting into Turbopack's still-evolving
production build support).

## Package manager

**npm** — no `pnpm-lock.yaml`/`yarn.lock`/other frontend package-manager
evidence existed anywhere in the repository, and npm is universally
available; matches this slice's instruction to default to npm absent a
repository-specific reason otherwise. Exactly one lockfile
(`frontend/package-lock.json`) exists.

## Dependency minimalism

Beyond the Next.js/React/TypeScript/ESLint scaffold, this slice added only
test tooling: `vitest`, `@vitejs/plugin-react`, `jsdom`,
`@testing-library/react`, `@testing-library/jest-dom`,
`@testing-library/user-event`. No state-management library, no data-fetching
library (React Query/SWR), no HTTP client library (Axios — native `fetch`
is used throughout), no UI component library, no chart library, no
authentication library, no form library, no animation library. All of
those remain explicitly out of scope until a later slice demonstrates an
actual need.

## Frontend location / directory structure

```
frontend/
  app/
    layout.tsx        # root shell: fonts, metadata, wraps children in AppShell
    page.tsx           # "/" — renders SystemOverview
    globals.css         # design tokens (CSS custom properties) + base styles
  components/
    AppShell.tsx / .module.css       # header + sidebar + main content grid
    Header.tsx / .module.css          # title, tagline, status badge
    Sidebar.tsx / .module.css         # nav (one active item, five inactive placeholders)
    StatusBadge.tsx / .module.css      # shared, never-color-only status indicator
    SystemStatusProvider.tsx           # React context wrapping useSystemStatus()
    SystemOverview.tsx / .module.css   # the actual home-page content + its test
  hooks/
    useSystemStatus.ts                # fetch-on-mount + manual refresh, no polling
  lib/
    config.ts (+ .test.ts)             # NEXT_PUBLIC_API_BASE_URL validation
    api/
      types.ts        # LivenessResponse / ReadinessResponse / DependencyHealth
      errors.ts         # ApiClientError (bounded)
      client.ts (+ .test.ts)           # typed fetch wrapper
      systemStatus.ts (+ .test.ts)     # /live + /ready -> SystemStatus mapping
  public/               # empty; no static assets needed yet
  .env.example
```

No `types/` directory was created separately — with only three small
interfaces so far, `lib/api/types.ts` is sufficient; a dedicated `types/`
directory can be introduced later if/when it earns its place.

## Styling decision

**CSS Modules + global CSS custom properties (design tokens). Tailwind was
deliberately declined.** Rationale: the audit found no existing Tailwind
config anywhere in the repository (a clean-slate decision), and this
slice's entire visible surface is one page and five small components —
far too small to justify a utility-CSS framework and its associated
tooling/mental-model overhead. CSS Modules ship with Next.js at zero extra
dependency cost, and `app/globals.css` defines a small, explicit set of
design tokens (`--color-bg`, `--color-surface`, `--color-text`,
`--color-text-muted`, `--color-border`, the four status colors each with a
tint background, spacing scale, radii) so no visual value is repeated
ad hoc across components. Dark mode was explicitly deferred (light theme
only) — not requested, and doubling the token surface for a one-page
foundation slice was judged premature.

## Application shell

Header (title "CareFlow AI", tagline "Healthcare Intelligence Platform",
status badge) + a left sidebar (collapses to a horizontal bar under 768px)
+ a main content area. Only **System Overview** is a real, functional nav
item (`href="/"`, `aria-current="page"`); "Ask CareFlow", "Patient Data",
"Claims", "Reviews", "Analytics" render as visibly present but
`aria-disabled="true"` `<span>`s with a "Coming soon" note — never a
`<Link>`, never a route that exists, so nothing fakes functionality.

## Backend API audit (performed before writing the API client)

Inspected the current FastAPI app directly (not assumed from memory):

| Route | Method | Response model |
| --- | --- | --- |
| `/live` | GET | `LivenessResponse {status: "alive", service}` |
| `/ready` | GET | `ReadinessResponse {status: "ready"\|"unready", service, version, dependencies: {postgresql, qdrant, redis: {status: "ok"\|"unavailable"}}}` |
| `/health` | GET | `HealthResponse` (legacy, all three dependencies required — Phase 13, unchanged) |
| `/metrics` | GET | bounded JSON aggregate metrics (Phase 13 Slice 6) |
| `/query` | POST | `QueryRequest` → `RAGAnswer` |
| `/orchestrate` | POST | orchestration request/response models |
| `/multi-agent` | POST | multi-agent request/response models |
| `/reviewable-query`, review endpoints | POST/GET | review request/response models |

Only `/live` and `/ready` are called in this slice. The others were
inspected only to confirm the frontend's type/client architecture (a
small typed `apiGet` wrapper, a bounded error model) will not need to be
redesigned when later slices add `POST` support for them.

## API base URL strategy

`NEXT_PUBLIC_API_BASE_URL`, read and validated exactly once in
`lib/config.ts`. No `localhost`/`127.0.0.1`/production hostname is
hard-coded anywhere in application logic — the module throws a clear,
actionable error if the variable is unset, empty, not a valid URL, or not
`http`/`https`. `frontend/.env.example` documents the two ports this
repository actually uses (`8000` native default,`18000` if running the
repo's own `docker-compose` stack) and is the only `.env*` file tracked in
git (`frontend/.gitignore`'s blanket `.env*` exclusion was fixed to add a
local `!.env.example` exception, matching the root `.gitignore`'s existing
convention — without it, `.env.example` was itself being silently
git-ignored). `.env.local` (created locally for dev/build verification,
copied from `.env.example`) is not committed.

## Typed API client

`lib/api/client.ts`'s `apiGet<T>(path, options?)` — base URL handling,
`AbortController`-based timeout (default 5000ms, overridable per call,
externally-abortable), JSON parsing, and normalizing only genuine
transport failures (network error, timeout, an unparseable body) into a
thrown `ApiClientError`. A non-2xx response with a valid JSON body is
**not** thrown — it is returned normally as `{data, status, ok:
false, requestId}` — because `GET /ready`'s `503` carries a real, useful,
well-typed body (which dependency failed) that the generic client must not
discard. Endpoint-specific interpretation of status codes belongs to the
caller (`lib/api/systemStatus.ts`), not the client — the client itself
contains no business logic.

## Request-ID handling

`X-Request-ID` is read from every response (`response.headers.get(...)`)
and threaded through `ApiResponse`/`ApiClientError`/`SystemStatus` as
`requestId`. It is shown only in a small monospace "technical detail" line
when the backend is unavailable — never used as React key/state identity,
never a prominent UI element.

## System status semantics

- **Checking** — a request is in flight. The hook's initial state, before
  `fetchSystemStatus()` resolves; the UI shows "Checking system status…"
  and never flashes "Ready" first.
- **Ready** — `GET /ready` succeeded with `status: "ready"`.
- **Degraded** — the API process is reachable (`GET /live` succeeded) but
  readiness is not satisfied: either `/ready` responded `status:
  "unready"`, or `/ready` itself failed at the transport level even though
  `/live` did not (a narrower, more accurate reading than treating that as
  a full outage).
- **Unavailable** — `GET /live` itself could not be reached, timed out, or
  failed at the network level.

## Redis optionality

Not special-cased in the frontend at all, deliberately. Phase 13's
`check_readiness()` already guarantees `ReadinessResponse.status` is never
affected by Redis alone — trusting that field directly is correct and
sufficient. The UI renders each dependency (Postgres, Qdrant, "Cache
(Redis)") with its own actual status row, so an operator can see "Cache:
Unavailable" while the overall badge still reads "Ready" — proven by a
dedicated test (`lib/api/systemStatus.test.ts`: "Redis being unavailable
does not by itself mark overall state as unavailable or degraded") and
verified against the real backend (see "Real backend connectivity" below).

## CORS

**Backend audit:** no `CORSMiddleware` existed anywhere in
`backend/app/main.py` before this slice — a from-a-different-origin
browser fetch to `/live`/`/ready` would have been blocked (no
`Access-Control-Allow-Origin` header at all). This required a backend
change; the smallest one made:

- New bounded `Settings.cors_allowed_origins: str = "http://localhost:3000"`
  (comma-separated; empty disables CORS entirely — every environment that
  doesn't explicitly set it keeps pre-Slice-1 behavior byte-for-byte).
- `backend/app/main.py` adds `CORSMiddleware` **only** when the parsed
  origin list is non-empty: `allow_origins=<parsed list>` (never `"*"`),
  `allow_credentials=False` (no cookie/session auth exists to protect),
  `allow_methods=["GET"]` (this slice only ever calls `GET`),
  `expose_headers=["X-Request-ID"]` (otherwise the browser hides that
  header from JS even though the server sends it).
- 6 new tests in `tests/test_cors.py`; full backend suite re-run:
  **816 passed, 0 failed, 166 skipped** (was 810 before this slice).

## Docker decision

**No frontend Dockerization added in this slice.** `docker-compose.yml`
was inspected; it currently orchestrates `backend`/`postgres`/`qdrant`/
`redis` only. Local `next dev` is sufficient for this foundation slice —
adding a frontend service (a distinct build/runtime story, a new exposed
port, a new `depends_on` edge) is a deliberate later decision, not
something this slice's own scope calls for. Documented here as an
explicit choice, not an oversight.

## Testing strategy

**Vitest + React Testing Library**, chosen as the smallest appropriate
setup — no Playwright/Cypress/other E2E framework (none was already
present, and Slice 1 has no user flow worth E2E-testing yet). 24 tests
across 4 files:

- `lib/config.test.ts` (6): valid URL, trailing-slash normalization,
  https, unset → clear error, malformed → clear error, non-http(s)
  protocol → clear error.
- `lib/api/client.test.ts` (7): typed success, base-URL usage, a non-2xx
  JSON body returned (not thrown), network failure → `ApiClientError`,
  unparseable body → `ApiClientError`, timeout → `ApiClientError` (via
  fake timers), confirms the thrown value is always `ApiClientError`.
- `lib/api/systemStatus.test.ts` (6): ready mapping, degraded-via-unready
  mapping, unavailable-via-network-failure mapping, degraded (not
  unavailable) when `/live` succeeds but `/ready` transport-fails,
  request-ID extraction, and the explicit Redis-optionality proof above.
- `components/SystemOverview.test.tsx` (5): honest checking state (no
  premature "Ready"), ready state renders all three dependency rows,
  unavailable state shows a calm message with no leaked exception text,
  the data disclaimer renders, and no request ID is shown prominently
  when healthy.

No test asserts only a snapshot; every test asserts specific rendered
text/state/behavior. No test requires a real running backend (all mock
`fetch`) — the one real-backend check is manual, described below, not
part of the automated suite.

## Accessibility approach

Semantic HTML (`<header>`, `<nav aria-label="Primary">`, `<main>`,
heading hierarchy `h1`→`h2`); every interactive element is a real `<a>`
(via `next/link`) or `<button>`, keyboard-reachable by default; a global
`:focus-visible` outline (2px solid, offset) so keyboard focus is always
visible; status is never color-only — every `StatusBadge` pairs a
distinct symbol (`…`/`●`/`▲`/`✕`) with its text label; the status region
uses `aria-live="polite"` so a screen reader announces state changes
without the developer needing to remember it per-component; disabled nav
items use `aria-disabled="true"` rather than being silently omitted from
the accessibility tree. No WCAG conformance level is claimed.

## Responsive behavior

Verified via `resize_window` at desktop (default), tablet (768px), and
mobile (375px) widths: the sidebar collapses from a fixed 240px left rail
to a full-width horizontal bar above the main content under 768px (a
plain CSS media query — no JS hamburger menu, per this slice's explicit
"don't build a complex mobile menu unless necessary"); no horizontal
overflow observed at any of the three widths.

## Security review

Searched the production build output (`frontend/.next/`) for: OpenAI key
patterns, Redis/Postgres/Qdrant credential patterns, any backend secret
value, and the literal contents of `.env.local`. None found — the only
environment value the frontend ever reads is
`NEXT_PUBLIC_API_BASE_URL` (a URL, explicitly documented as public, non-
secret configuration), and `lib/config.ts` is the sole module that touches
`process.env`, reading exactly that one variable and nothing else, so no
other server-side environment value has any path into a client bundle.

## Scope boundary for Slice 2+

Not built in this slice, on purpose: any question textarea/send button/
answer panel/citations UI (Ask CareFlow), patient or claims lookup,
multi-agent UI, human review UI, or analytics/dashboard screens. Those
nav items exist visually as inactive placeholders only. This document
will grow a new `## Slice N` section per future frontend slice, matching
`docs/phase13_reliability_observability_design.md`'s own convention.

## Slice 2: Ask CareFlow — policy RAG question + answer + citations

The first complete user-facing workflow: a question, `POST /query`, and a
rendered answer with citations or an honest abstention. Policy questions
only — no FHIR/SynPUF lookup, no `/orchestrate` or `/multi-agent` UI, no
review/analytics screens.

**`/query` contract (inspected directly from
`backend/app/api/query.py`/`backend/app/generation/models.py`/
`backend/app/generation/service.py`/`backend/app/generation/providers.py`
before writing any frontend type):**

- Request: `QueryRequest { question: string }`, `min_length=1,
  max_length=4000`, server-side trims and rejects whitespace-only.
- Response `200`, `RAGAnswer`: `answer: string`, `citations: Citation[]`,
  `insufficient_evidence: bool`, `retrieved_chunk_ids: string[]`,
  `model_provider`, `model_name`, `prompt_version: string`,
  `abstention_reason: string | null`.
- `Citation`: `document_id`, `document_version`, `chunk_id: string`;
  `title`, `section`, `source: string | null`. **No excerpt/quote field.**
  `RAGService.answer()` joins `"CMS evidence [chunk_id]:\n<quote>"` blocks
  directly into `answer` itself — the evidence text IS the answer text,
  for every provider (deterministic or OpenAI), since that assembly lives
  in `RAGService`, not per-provider code. The frontend therefore renders
  `answer` verbatim rather than inventing a per-citation excerpt field
  that does not exist in the schema.
- Abstention (200, not an error): `answer = "Insufficient evidence."`,
  `citations = []`, `insufficient_evidence = true`,
  `abstention_reason` ∈ `{ambiguous_question, no_retrieval_results,
  no_eligible_evidence, model_abstained, no_citations, invalid_citation,
  unsupported_quote}`.
- Non-2xx: `{"error": {"code": "..."}}` via `GenerationError` — codes
  observed in code: `rerank_query_too_long` (422), `malformed_model_output`/
  `invalid_evidence_output`/`provider_incomplete`/
  `malformed_provider_response`/`provider_unavailable` (502),
  `provider_not_configured`/`reranking_unavailable`/`retrieval_unavailable`
  (503), `provider_timeout` (504).
- `X-Request-ID`: present on every response (Slice 3's middleware,
  unchanged).

**Backend changes made (both to CORS only, nothing business-logic):**
1. `Settings.cors_allowed_origins` `allow_methods` extended from `["GET"]`
   to `["GET", "POST"]` — `POST /query` sends a JSON body, which triggers
   a browser CORS preflight regardless of origin; GET-only rejected it
   with a `400 Disallowed CORS method`. No other header/origin/credential
   change. One new test (`test_preflight_for_post_query_is_permitted...`);
   full backend suite re-run: 817 passed, 0 failed, 166 skipped.
2. No retrieval/generation/citation-validation/abstention/Qdrant/corpus
   code was touched at all.

**Ask CareFlow route:** `frontend/app/ask/page.tsx` (`/ask`), a real
Next.js route, not simulated with local state. `Sidebar` now resolves the
current path via `usePathname()` so exactly one nav item carries
`aria-current="page"` at a time (System Overview or Ask CareFlow).

**Question state machine** (`components/AskCareFlow.tsx`) — deliberately
separate from Slice 1's global `SystemStatusState` (checking/ready/
degraded/unavailable), per this slice's own instruction not to overload
one state machine for both:

```
idle -> submitting -> answered | abstained | error
```

A new submission always sets `submitting` immediately (clearing whatever
previous answered/abstained/error result was showing) before the request
resolves — a stale answer paired with a newer, different question is never
possible.

**Input validation:** blank/whitespace-only blocked client-side; max
length is exactly the backend's `4000` (`QUESTION_MAX_LENGTH`, re-exported
from `lib/api/types.ts` so the two can never drift), enforced both via the
textarea's own `maxLength` and a JS check (for defensive testability).

**Example questions:** four hardcoded strings, each **empirically
verified against the real running backend** before being hardcoded (not
inferred from the golden dataset's `answerable` label alone — one
`known_failure`-labeled golden question was tried and it actually
succeeds today; two different `answerable: true`-labeled walker questions
were tried and both actually abstain today; wording sensitivity is real
and confirmed, not theoretical). Clicking one populates the textarea only
— never auto-submits.

**API integration:** `lib/api/client.ts`'s `apiGet`/`apiPost` now share
one internal `request()` helper (no second fetch abstraction). New
`lib/api/policyQuery.ts::queryPolicy()` returns a bounded
`PolicyQueryOutcome` (`answered` | `abstained` | `error`), mapping
`GenerationError` codes to exactly the 5 categories this slice's own
instruction lists: `network`, `timeout`, `retrieval_unavailable`,
`generation_unavailable`, `unexpected` (an unrecognized code, or a body
that doesn't match the expected `{error:{code}}` shape, both map to
`unexpected` rather than guessing).

**Supported-answer UX:** "Answer" (the raw `answer` string, `white-space:
pre-wrap` so the backend's own paragraph breaks render correctly) then,
visually separated, "Evidence" (numbered `CitationCard`s: title, section,
`NCD <id> · Version <version>`, and a "View source document" link only
when `source` is present — never a fabricated page number, author, date,
or confidence).

**Abstention UX (the critical case):** a dedicated, visually neutral
(gray, not red/alarming) message — verbatim: "CareFlow couldn't find
enough evidence in the indexed Medicare policy documents to answer this
question reliably." / "Try asking a more specific Medicare policy
question." No "not covered" or "does not cover" language is ever shown
for an abstention — confirmed by test that this exact language never
appears in that state, and by the design itself never having a code path
that could produce it (the abstention branch renders one static message,
not backend-derived coverage language).

**Error UX:** 5 calm, distinct messages (network/timeout/
retrieval_unavailable/generation_unavailable/unexpected) — never a raw
exception, stack trace, or internal URL. A manual "Retry" re-submits the
exact last question (no automatic repeated retries). A request ID is
shown only in that error state, as a small monospace technical-detail
line — never for a successful answer, never as citation content.

**System readiness integration:** `lib/policyReadiness.ts` derives
submission-allowed purely from Slice 1's `SystemStatus`: blocked while
`checking`, blocked while `unavailable`, blocked when `degraded` **and**
`readiness.dependencies.qdrant.status === "unavailable"`, allowed
otherwise — including a Postgres-only or Redis-only degradation, since
neither backs the policy/RAG path. This is a pure function over data
Slice 1 already fetches; no new polling, no second status fetch.

**Redis optionality (live, not re-tested destructively):** the real
backend currently reports Redis `ok`, so ordinary integration already
demonstrates the normal case; the "Redis down alone keeps Ask CareFlow
enabled" claim is proven by a mocked-readiness unit test
(`lib/policyReadiness.test.ts`), reusing Phase 13's own established
principle rather than re-running Phase 13's destructive failure-injection
work.

**Request-ID handling:** confirmed live — a direct `fetch('/query')` from
the browser console could read `X-Request-ID` from the response
(`expose_headers` covers POST responses too, unchanged from Slice 1).
**Finding:** `backend/app/api/query.py` and `RAGService.answer()` call no
`log_event()` at all (unlike `/orchestrate`/`/multi-agent`/`/reviews`,
migrated in Phase 13 Slice 3) — a successful `/query` request produces
only Uvicorn's own access-log line, with no structured application event
carrying the request ID. Request correlation for `/query` specifically
could therefore not be verified via a matching structured log line; this
is a pre-existing Phase 1-9 architectural gap, not something this
policy-consuming, no-backend-business-logic-change slice introduced or is
positioned to fix. Correlation at the transport/response level (one ID,
threaded through `X-Request-ID`, readable cross-origin) is confirmed,
matching Slice 1's own middleware-level guarantee.

**Accessibility:** the textarea has a real `<label htmlFor>`; validation
text has `role="alert"`; the results region is `aria-live="polite"`;
abstention/error blocks use `role="status"`/`role="alert"` respectively;
citation cards are plain `<li>`s (never a clickable card without a real
destination — only the explicit "View source document" `<a>` is
interactive). Keyboard flow verified live: Tab from the question textarea
reaches only real controls (example buttons, submit) in order; Enter in
the textarea does not submit (textareas never submit forms on Enter,
matching normal multi-line-input expectations), the submit button does.

**Responsive behavior:** verified live at desktop, 768px, and 375px — the
question form, example chips, answer text, and citation cards all wrap
correctly (`overflow-wrap: anywhere` on free text and the chunk-ID-bearing
answer string); no horizontal overflow at any width.

**Security/privacy:** no `dangerouslySetInnerHTML` anywhere (`answer` is
plain backend text, rendered as a text child, never parsed as HTML/
Markdown — confirmed the backend does not claim a Markdown contract);
no `localStorage`/`sessionStorage`/cookie use; no `console.log` of any
question or answer; no analytics tracker; no fake confidence value ever
rendered (grepped and confirmed absent from both source and the live
rendered DOM in tests).

**Real integration verification (live, both directions):**
- Supported: *"Does Medicare cover hospital beds?"* → real answer
  quoting NCD 227 §A, one citation (`Hospital Beds`, NCD 227 v1, a real
  `cms.gov` source link) — rendered correctly end to end, verified via
  screenshot and `get_page_text` at desktop/tablet/mobile.
- Unsupported: *"What chemotherapy regimen treats pancreatic cancer?"* →
  dedicated abstention message, zero fabricated answer, zero citations.
- **Blocker found and fixed during this verification:** the real running
  `careflow-ai-backend-1` container still had Slice 1's `allow_methods:
  ["GET"]` image (predating this slice's `"POST"` addition) — the first
  live submission failed with a genuine browser CORS error
  (`OPTIONS /query → 400`). Rebuilt/recreated only the `backend` container
  (same safe, Postgres/Qdrant/Redis-untouched pattern as Phase 13 Slice 7
  and Phase 14 Slice 1); confirmed `access-control-allow-methods: GET,
  POST` afterward, then both live verifications above succeeded.

**Tests:** 38 new (11 `apiPost` additions to `client.test.ts`, 11
`policyQuery.test.ts`, 10 `policyReadiness.test.ts`, 13
`AskCareFlow.test.tsx` covering validation, submission/duplicate-
prevention, supported/abstained/error rendering, and readiness gating).
Full suite: 62 passed, 0 failed (was 24 before this slice).

**Known limitations:** example questions are hardcoded and must be
re-verified if the CMS corpus is ever re-ingested/changed. No Markdown
rendering (matches the backend's plain-text contract; would need explicit
backend confirmation to ever change). Request-ID correlation cannot be
shown via a structured log line for this specific endpoint (see above).
No caching/memoization of previous answers across questions in this
slice.

## Slice 3: structured healthcare data — Synthea FHIR + CMS DE-SynPUF UI

Exposes Phase 9's existing bounded structured-data tools (FHIR + SynPUF)
through two new pages. No new backend capability, no arbitrary SQL, no
combination with policy results — a query/inspection UI over what already
exists.

**Structured backend audit (inspected directly, not assumed):**
`POST /orchestrate` (`backend/app/api/orchestrate.py`,
`backend/app/orchestration/{models,graph,tools}.py`). `OrchestrationRequest
{question, route?, tool?, tool_arguments?}` — `route ∈ {policy, synpuf,
fhir, abstain}`; `route=policy` combined with a tool is rejected
(`inconsistent_request`); a tool/tool_arguments requires an explicit
route. `OrchestrationResponse {request_id, route, status: ok|abstained|
error, answer, citations, tool, source_dataset, record_count, data,
abstention_reason, error}`. Unlike `/query`, `/orchestrate` **does** call
`log_event()` (`orchestration_complete`) — request correlation via a
matching structured log line is fully verifiable here.

**FHIR tool inventory** (`backend/app/orchestration/tools.py::TOOL_REGISTRY`,
`route=fhir`, `source_dataset="synthea_fhir"`) — 10 total; this slice uses
only the 6 patient-ID-scoped ones (the 4 population-level aggregates —
`fhir_encounter_counts`, `fhir_condition_frequency`,
`fhir_procedure_frequency`, `fhir_medication_frequency` — take no patient
ID and are deliberately deferred to a future Analytics slice):

| Tool | Required args | Optional args | Output |
| --- | --- | --- | --- |
| `get_patient_summary` | `patient_id` | — | one `fhir_patients` row or `null` (→ `unknown_patient` abstention) |
| `get_patient_encounters` | `patient_id` | — | `fhir_encounters[]` |
| `get_patient_conditions` | `patient_id` | — | `fhir_conditions[]` (each with `codings[]`) |
| `get_patient_procedures` | `patient_id` | — | `fhir_procedures[]` (each with `codings[]`) |
| `get_patient_observations` | `patient_id` | `code` | `fhir_observations[]` (each with `value_type`-discriminated value fields, `components[]` when `value_type="component"`) |
| `get_patient_medication_requests` | `patient_id` | — | `fhir_medication_requests[]` |

**SynPUF tool inventory** (`route=synpuf`, `source_dataset="cms_desynpuf"`)
— 8 total; this slice uses the 3 per-beneficiary/per-claim ones (the 5
population-level aggregates — `synpuf_claim_counts`,
`synpuf_payment_totals`, `synpuf_diagnosis_frequency`,
`synpuf_procedure_frequency`, `synpuf_hcpcs_frequency` — are deferred for
the same reason as FHIR's aggregates):

| Tool | Required args | Output |
| --- | --- | --- |
| `get_beneficiary_summary` | `beneficiary_id` | one `synpuf_beneficiaries` row or `null` (→ `unknown_beneficiary`) |
| `get_claims_for_beneficiary` | `beneficiary_id` | `synpuf_claims[]` |
| `get_claim_details` | `claim_row_id` | one claim row + `diagnoses[]`/`procedures[]`/`lines[]` (ICD-9/HCPCS codes), or `null` (→ `unknown_claim`) |

There is no per-beneficiary "Diagnoses"/"Procedures" tool — those codes
exist only nested inside one claim's own detail (confirmed from
`backend/app/repository/synpuf.py::get_claim_details`), so the Claims page
surfaces them as a drill-down from a specific claim, not a separate
top-level view — a UX grouping decision driven by the actual data shape,
not invented.

**Dataset separation:** Synthea FHIR and CMS DE-SynPUF are independent
synthetic datasets with no foreign key or identity relationship between
them (confirmed in the migration files' own comments). Patient Data always
sends `route="fhir"`; Claims always sends `route="synpuf"`; neither page's
code path can construct a request naming both a `patient_id` and a
`beneficiary_id` — proven by 3 dedicated tests in
`components/datasetSeparation.test.tsx`, independent of each page's own
happy-path tests.

**Backend changes:** NONE. All Phase 9 tools, the graph, and the registry
are used exactly as they exist; only frontend code and tests were added.

**Routes:** `/patient-data`, `/claims` — real Next.js routes (`app/
patient-data/page.tsx`, `app/claims/page.tsx`), added to the shared
Sidebar/AppShell. Reviews and Analytics remain inactive placeholders.

**API integration:** `lib/api/orchestrationTypes.ts` (types derived
directly from the models/registry above) + `lib/api/structuredQuery.ts`'s
`queryFhirTool()`/`querySynpufTool()`, built on the *same* `apiPost` the
Ask CareFlow slice added — no second fetch layer. Every call sends an
explicit `route`+`tool`+`tool_arguments` — the free-text classifier is
never exercised by this UI, since the page already knows which dataset and
tool the user selected. `question` carries a fixed placeholder string
(`OrchestrationRequest.question` has `min_length=1` but is unused once
route/tool are explicit — matching the exact convention
`tests/test_orchestration_api.py` already uses for structured-only calls).

**Identifier strategy:** "Synthetic Patient ID" (FHIR) / "Synthetic
Beneficiary ID" (SynPUF) — never "Medicare number", "MRN", or "real patient
ID". Client-side validation blocks only blank/whitespace-only input; the
backend's own `StrictModel` length bounds (`patient_id`/`beneficiary_id`
≤64/32 chars) are authoritative and not duplicated as a second, possibly
conflicting frontend maximum.

**Demo synthetic IDs:** `31a2e8ec-69fc-8a71-3ab6-36cbdd508713` (FHIR) and
`00013D2EFD8E45D1` (SynPUF) — both queried directly from the live database
this session (`SELECT patient_id FROM fhir_patients ...` /
`SELECT beneficiary_id FROM synpuf_beneficiaries ...`) and confirmed
present before being hardcoded; not fabricated, not a large exposed list —
exactly one "Use example synthetic ID" link per page.

**Patient views implemented:** Summary, Encounters, Conditions,
Procedures, Observations (including multi-component values, e.g.
blood-pressure-style readings), Medications — selectable via tabs after
loading a patient; each tab issues its own explicit tool call with the
same ID (no client-side caching across tabs, matching Ask CareFlow's own
"refetch, don't cache" simplicity).

**Claims views implemented:** Beneficiary Overview (identity, coverage
months, chronic-condition indicators, payment amounts, grouped into
labeled sub-sections) and Claims (a list, each with an on-demand "View
details" drill-down calling `get_claim_details` for that one claim's
diagnoses/procedures/line-item codes).

**Structured rendering:** one shared, data-driven `RecordFields` component
(`components/structured/`) renders every resource type from a small
per-tool `FieldSpec[]` array — Encounters/Conditions/Procedures/etc. never
needed their own bespoke layout component. Results render as cards, not a
raw JSON dump; no technical-details/raw-JSON view exists in this slice
(not requested, and the card rendering already surfaces every returned
field).

**Code rendering:** `system`/`code`/`display` shown together via
`formatCoding()` (`"<display> (<system> <code>)"`, or just `"<system>
<code>"` when no display exists) — never an invented description. When
multiple `codings[]` exist for one concept (a real, observed case per the
FHIR migration's own comment, e.g. two LOINC codes for "temperature"),
every one is shown, not just the primary. SynPUF ICD-9/HCPCS codes (no
display text in this dataset) are shown as bare codes only — no external
terminology lookup.

**Date handling:** `formatDateOnly()` renders a `DATE`-column string
(`birth_date`, `from_date`, etc.) verbatim — never passed through a JS
`Date` object, which would risk a timezone-driven off-by-one-day bug for a
value that has no time component. `formatTimestamp()` is used only for
real `TIMESTAMPTZ` columns (`period_start`, `effective_datetime`, etc.),
which do carry real timezone information and are safe to format via
`Date`+`toLocaleString`. Both are directly unit-tested
(`lib/formatting.test.ts`) including the exact "never reinterpret a
DATE-only field" invariant.

**Money handling:** `formatCurrencyUsd()` (`Intl.NumberFormat`, USD) used
only for columns confirmed as genuine monetary `NUMERIC` fields in the
migrations (`claim_payment_amount`, `reimb_*`/`benres_*`/`pppymt_*`, etc.)
— never implying an audited billing total, just formatting a real returned
value. Chronic-condition indicator fields are rendered as their raw SP_*
numeric value, explicitly *not* reinterpreted as booleans, matching
`backend/app/db/migrations/0002_synpuf.sql`'s own documented caution that
the 1/2 codebook scale is not assumed.

**Empty-result UX:** a successful zero-record list (e.g. a real patient
with no medication requests) renders "No records found for this synthetic
identifier/query." — never phrased as a clinical conclusion, and never
confused with an abstention (which specifically means the *identifier
itself* was not found, a structurally different case the backend
distinguishes via `data: null` vs `data: []`).

**Abstention UX:** one dedicated message per `AbstentionReason` value
(`unknown_patient`/`unknown_beneficiary`/`unknown_claim` primarily
realistic for this slice's own pre-validated requests; the others handled
defensively). Never rendered as a server error.

**Error UX:** the same 4-category shape as Ask CareFlow
(network/timeout/backend_unavailable/unexpected), reusing the identical
calm-message-plus-Retry pattern (`components/structured/
StructuredResultStates.tsx`) — no SQL/database/Qdrant detail ever surfaces
(there is none to leak: the tool registry has no arbitrary-query path at
all).

**Readiness semantics (deliberately different from Ask CareFlow's):**
`lib/structuredReadiness.ts` blocks submission only when Postgres itself
is unavailable (or the backend is unreachable/still checking) —
confirmed from `backend/app/orchestration/graph.py::_run_structured_route`,
which calls `db/connection.py::connect()` directly and never touches
Qdrant. A Qdrant-only or Redis-only degradation never blocks Patient
Data/Claims, proven by dedicated tests
(`lib/structuredReadiness.test.ts`) distinct from `lib/policyReadiness.ts`'s
own Qdrant-gated tests.

**Request-ID handling:** verified live — a direct `fetch('/orchestrate')`
returned `X-Request-ID: f18b528e-...`, and the **same** ID appeared in the
real backend's structured log line: `{"event": "orchestration_complete",
"request_id": "f18b528e-...", "route": "fhir", "tool":
"get_patient_summary", "status": "ok", "record_count": 1, ...}` — no
patient data in the log line, only routing/tool metadata and a count,
exactly as Phase 13 Slice 3 designed.

**Synthetic-data labeling:** `DatasetBadge` always names the real dataset
plus "Synthetic" (`"Synthea FHIR · Synthetic"` / `"CMS DE-SynPUF ·
Synthetic"`) — never a vague "Patient Database" label. Each page also
carries its own prose notice (exact required wording for Patient Data;
Claims explains the data is synthetic/de-identified demonstration data).

**Accessibility:** real `<label htmlFor>` on both identifier inputs,
`role="alert"` validation and error messages, `aria-live="polite"` result
regions, `aria-current`/`aria-expanded` on view tabs and the claim-detail
toggle, semantic `<dl>`/`<dt>`/`<dd>` for every record's fields. Citation-
style cards are never clickable themselves — only the explicit "View
source document" link (FHIR) or "View details" button (SynPUF) is
interactive, each with a real destination/action.

**Responsive behavior:** verified live at desktop/768px/375px for both
pages (including a 78-condition list and a 2-claim drill-down) — the
field grid collapses to one column under 480px, no horizontal overflow,
long values (UUIDs, coding strings) wrap via `overflow-wrap: anywhere`.

**Privacy/security:** no `dangerouslySetInnerHTML`, no `localStorage`/
`sessionStorage`/cookie use, no console logging of any record content, no
SQL/query-builder UI of any kind (grepped and confirmed absent), no fraud/
risk/coverage-determination language or computation anywhere in this
slice's code.

**Real FHIR verification (live, patient `31a2e8ec-69fc-8a71-3ab6-
36cbdd508713`):**
tools: `get_patient_summary`, `get_patient_conditions`, `get_patient_observations`
record counts: 1 (summary), 78 (conditions), 175 (observations)
representative result: Summary — Adelaida985 DuBuque211, born 1917-05-15,
female, White/Not Hispanic or Latino. Conditions — e.g. "Alzheimer's
disease (disorder) (http://snomed.info/sct 26929004)", clinical_status
`active`, onset "Nov 21, 2000, 6:58 AM". Observations — e.g. "Body Height
(LOINC 8302-2)" = "158.5 cm".

**Real SynPUF verification (live, beneficiary `00013D2EFD8E45D1`):**
tools: `get_beneficiary_summary`, `get_claims_for_beneficiary`, `get_claim_details`
record counts: 1 (beneficiary), 2 (claims), 1 (claim detail drill-down)
representative result: Beneficiary — born 1923-05-01, state 26, county
950. Claims — one outpatient ($50.00 payment, 2008-09-04) and one
inpatient ($4,000.00 payment, DRG 217, 2010-03-12→2010-03-13). Claim
detail (outpatient claim) — diagnoses `["V5841"]`, no procedure codes,
line items `["85610", "84153"]`.

**Invalid FHIR ID verification:** a nonexistent patient ID → "No synthetic
patient was found for this ID." (not a server error).

**Invalid SynPUF ID verification:** a nonexistent beneficiary ID → "No
synthetic beneficiary was found for this ID." (not a server error).

**Request correlation verification:** confirmed exact match between the
`X-Request-ID` response header and the backend's `orchestration_complete`
structured log line's `request_id` field for a real live request (see
above) — no logging change was made to enable this; `/orchestrate` already
logged this way since Phase 13 Slice 3.

**Tests:** 44 new (11 `structuredQuery.test.ts`, 6
`structuredReadiness.test.ts`, 15 `formatting.test.ts`, 10
`PatientData.test.tsx`, 11 `Claims.test.tsx`, 3
`datasetSeparation.test.tsx` — some overlap in file boundaries reflects
logical grouping, not duplication). Full suite: 120 passed, 0 failed (was
96 before this slice).

**Known limitations:** the 9 population-level aggregate FHIR/SynPUF tools
(counts/frequency-by-code) are not exposed anywhere yet — deferred to a
future Analytics slice, matching the sidebar's existing placeholder.
Claim details are fetched one claim at a time on demand (no bulk
prefetch). No pagination for a beneficiary/patient with very many
records (this session's real data topped out at 175 observations,
rendered without issue, but a much larger list would currently render
in full rather than paging).

## Slice 4: intelligent router + orchestration UX — CareFlow Assistant

Exposes Phase 9's *existing* orchestration/router capability — the same
`POST /orchestrate` endpoint Slice 3 already calls, but this time letting
the backend's deterministic classifier pick the route instead of the
frontend specifying it explicitly. No new backend intelligence, no
multi-agent combination, no HITL, no analytics — a single page that shows
a user what CareFlow's router actually does with a natural-language
request.

**Router contract (re-audited, not assumed from Slice 3's notes):**
`backend/app/orchestration/classify.py`'s free-text classifier only runs
when a request omits an explicit `route`/`tool` — exactly what this page
sends. ID-shape detection runs first and takes priority over keywords: a
UUID (`FHIR_ID_PATTERN`) routes to `fhir`, a 16-hex-with-a-letter code
(`SYNPUF_ID_PATTERN`) routes to `synpuf`; both present at once →
`ABSTAIN`/`cross_dataset_linkage_request`. With no ID present, keyword
sets (`FHIR_KEYWORDS`, `SYNPUF_KEYWORDS`, `POLICY_KEYWORDS`) decide:
exactly one domain's keywords → that route (policy needs no identifier;
FHIR/SynPUF keywords with no ID → `missing_required_identifier`);
multiple domains → `ambiguous_route`; none → `unsupported_request`.

**Critical routing-tool finding:** `backend/app/orchestration/
graph.py::_run_structured_route` always resolves a classified FHIR/SynPUF
request to a fixed default tool per route
(`_DEFAULT_TOOL_BY_ROUTE = {fhir: get_patient_summary, synpuf:
get_beneficiary_summary}`) — natural-language routing through this page
can **never** reach any other registry tool (no
`get_patient_conditions`, no `get_claims_for_beneficiary`, etc.),
regardless of keywords in the question. This is why the page only needs
dedicated rendering for those two record shapes, plus one generic
fallback for defensive completeness.

**Backend changes:** NONE. `/orchestrate` is used exactly as it already
exists for Slice 3; only frontend code and tests were added.

**Route:** `/assistant` (`app/assistant/page.tsx` → `components/
Assistant.tsx`) — a new route alongside, not replacing, `/ask`,
`/patient-data`, and `/claims`. Sidebar label: "CareFlow Assistant" (never
"Autonomous Agent"/"Medical AI Doctor"/"Clinical Copilot").

**Request shape — the one rule this whole slice exists to demonstrate:**
`orchestrateQuestion()` (`lib/api/orchestrateQuery.ts`) sends
`{question}` only — never an explicit `route`, `tool`, or
`tool_arguments`. Unlike Slice 3's Patient Data/Claims pages (which
always specify both), this page's entire purpose is to show the router
actually deciding, so short-circuiting it would defeat the slice.
Enforced by a dedicated test asserting the exact request body.

**Frontend state vs. backend route — kept as two separate concepts:**
the component's own UI state machine is `idle | submitting | result |
abstained | error`; the backend's routing decision
(`OrchestrationResponse.route: policy | fhir | synpuf | abstain`) is a
value carried *inside* the `result`/`abstained` states, never conflated
with them — a `result` state can hold any of the three real routes, and
`abstained` is reached the same way regardless of which
`AbstentionReason` produced it.

**CareFlow Routing panel:** every successful or abstained response
renders a `RoutingSummary` block ("Source: <human route label>", "Tool:
<human tool label> (<raw tool name>)") via `lib/routingLabels.ts` — human
labels first, the raw backend value shown alongside only as a small
technical detail, never LangGraph/Python class names, database table
names, SQL, RRF, the embedding model, Qdrant, or any other tool-registry
internal.

**Shared rendering — no duplicate implementations:** the policy branch
renders through `components/policy/PolicyAnswer.tsx`'s
`PolicyAnswerResult`/`PolicyAbstainedResult` — extracted from Slice 2's
`AskCareFlow.tsx` in this slice (verified regression-safe: `AskCareFlow.
test.tsx`'s 13 tests still pass unchanged against the extracted
component). The FHIR/SynPUF branches render through the *same*
`RecordFields` + `FieldSpec[]` machinery Slice 3 built, via a new shared
`components/structured/fieldSpecs.ts` module (field definitions moved out
of `PatientData.tsx`/`Claims.tsx`, both pages' full test suites — 24
tests — still passing unchanged). A `GenericRecordFields` fallback
(`components/structured/GenericRecordFields.tsx`) renders any record this
page has no `FieldSpec[]` for as a key/value list — never a raw JSON
dump — kept only for defensive completeness, since real natural-language
routing can never actually produce anything but the two default-tool
shapes (see the routing-tool finding above).

**Abstention UX:** reuses Slice 3's `StructuredAbstention` component and
its full `AbstentionReason → message` map for every reason except two
that get dedicated handling: `policy_abstained` renders Slice 2's own
`PolicyAbstainedResult` (identical wording to `/ask`), and
`cross_dataset_linkage_request` renders a dedicated safety notice ("CareFlow
does not link identities across the synthetic FHIR and SynPUF datasets.")
— the backend's own abstention is shown as-is; no join, workaround, or
"best guess" is ever attempted client-side.

**Readiness policy (a third, distinct policy from Slices 2 and 3):**
`lib/assistantReadiness.ts` allows submission whenever the API process
itself is reachable — `ready` or *any* `degraded` state — and blocks only
on `checking`/`unavailable`. This is deliberately different from
`lib/policyReadiness.ts` (Qdrant-gated) and `lib/structuredReadiness.ts`
(Postgres-gated): this page's eventual route is not known until the
backend classifies the question, so gating on one dependency would
incorrectly block requests the *other* dependency could still serve.
Redis is never considered, consistent with the rest of the project. If
the classifier does pick a route whose one dependency is actually down,
the backend's existing bounded failure surfaces normally through
`orchestrateQuestion()`'s error categories — this function does not try
to predict that in advance. Proven by 8 dedicated tests
(`lib/assistantReadiness.test.ts`) plus component-level readiness-matrix
tests in `components/Assistant.test.tsx` confirming Redis-alone,
Postgres-alone, and Qdrant-alone degradation each still leave submission
enabled.

**Error UX:** `orchestrateQuestion()` maps backend failures into 5
categories — `network`, `timeout`, `orchestration_unavailable`,
`retrieval_unavailable`, `unexpected` — one more than Slice 3's 4-category
`structuredQuery.ts` (`retrieval_unavailable` is unique to this page,
since a classified request can land on the policy path and hit the same
`GenerationError` codes `/query` does). Visually reuses `components/
structured/StructuredResultStates.module.css`'s `.error`/`.retryButton`/
`.technicalDetail` classes directly rather than duplicating them, since
this page's category set doesn't match `StructuredErrorCategory` closely
enough to reuse the component itself.

**Example requests — verified against the real running router** (Docker
Desktop was unpaused in a follow-up session; all three confirmed via a
direct `POST /orchestrate` call and then re-confirmed end-to-end through
the real `/assistant` frontend before being left in the UI unchanged):

| Example | question | route | tool | source_dataset | record_count | status |
| --- | --- | --- | --- | --- | --- | --- |
| Medicare Policy | "What does Medicare say about hospital beds?" | `policy` | — | — | — | `ok` |
| Synthetic FHIR | "Show me FHIR patient 31a2e8ec-69fc-8a71-3ab6-36cbdd508713" | `fhir` | `get_patient_summary` | `synthea_fhir` | 1 | `ok` |
| Synthetic Claims | "Look up SynPUF beneficiary 00013D2EFD8E45D1" | `synpuf` | `get_beneficiary_summary` | `cms_desynpuf` | 1 | `ok` |

All three routed exactly as intended on the first try — no example text
needed to change, and the classifier was not touched.

**Accessibility:** real `<label htmlFor>` on the request textarea,
`role="alert"` for validation/error messages, `aria-live="polite"` result
region, keyboard-reachable example chips and submit button, semantic
headings, no color-only route communication (route/tool are always named
in text).

**Responsive behavior:** verified live at desktop, 768px (tablet), and
375px (mobile) — both for the empty form and for real rendered results
(a real policy answer + citation, a real FHIR structured record, and a
real abstention), against the actual running backend. No horizontal
overflow at any width for any of these
(`document.documentElement.scrollWidth === clientWidth` confirmed at
768px and 375px); example chips wrap onto multiple lines, the policy
citation card wraps its body text, and the FHIR record's UUID wraps
within its own field at 375px — the CareFlow Routing panel, dataset
badge, and synthetic-data notice all stay legible at every width tested.

**Real router verification (live, against the repo's own docker-compose
stack — `careflow-ai-backend-1` on `127.0.0.1:18000`, matching
`frontend/.env.local`):**

- **Policy** — `POST /orchestrate {"question": "What does Medicare say
  about hospital beds?"}` → `route=policy`, `status=ok`, the same NCD 227
  "Hospital Beds" answer/citation Slice 2 verified. Submitted through the
  real `/assistant` UI: routing panel showed "Source: Medicare Policy",
  the Answer/Evidence/Citation 1 sections rendered via the reused Slice 2
  component, no structured-data renderer appeared, no fake confidence
  score anywhere.
- **FHIR** — `POST /orchestrate {"question": "Show me FHIR patient
  31a2e8ec-69fc-8a71-3ab6-36cbdd508713"}` → `route=fhir`,
  `tool=get_patient_summary`, `source_dataset=synthea_fhir`,
  `record_count=1`, `status=ok` (Adelaida985 DuBuque211, born
  1917-05-15). Submitted through the real UI: routing panel showed
  "Source: Synthea FHIR · Synthetic" / "Tool: Patient Summary
  (get_patient_summary)", the structured card and synthetic-data notice
  rendered via the reused Slice 3 components. Question-only request
  confirmed by construction (`orchestrateQuestion()` sends `{question}`
  only, enforced by a passing unit test) and by matching routing
  behavior against the direct API call above.
- **SynPUF** — `POST /orchestrate {"question": "Look up SynPUF
  beneficiary 00013D2EFD8E45D1"}` → `route=synpuf`,
  `tool=get_beneficiary_summary`, `source_dataset=cms_desynpuf`,
  `record_count=1`, `status=ok`. Submitted through the real UI: routing
  panel showed "Source: CMS DE-SynPUF · Synthetic" / "Tool: Beneficiary
  Summary (get_beneficiary_summary)", structured card and synthetic-data
  notice rendered correctly.
- **Unsupported request** — `POST /orchestrate {"question": "What is the
  weather today?"}` → `route=abstain`, `status=abstained`,
  `abstention_reason=unsupported_request`. Submitted through the real UI:
  routing panel showed "Source: No supported route", and the bounded
  message "CareFlow could not process this structured data request."
  rendered — no fabricated result, no generic server error, no dataset
  silently chosen.
- **Cross-dataset linkage** — `POST /orchestrate {"question": "Link FHIR
  patient 31a2e8ec-69fc-8a71-3ab6-36cbdd508713 to SynPUF beneficiary
  00013D2EFD8E45D1"}` → `route=abstain`, `status=abstained`,
  `abstention_reason=cross_dataset_linkage_request`. Submitted through
  the real UI: the dedicated safety notice rendered verbatim — "CareFlow
  does not link identities across the synthetic FHIR and SynPUF
  datasets." — no join or workaround was attempted, and the backend was
  not modified.

**Request-ID correlation (live):** a real policy request's response
carried `X-Request-ID: 839d3f90-cdd2-483e-981d-a26f878f5261` (also
present in the response body as `request_id`), and the exact same ID
appeared in the backend's structured log: `{"event":
"orchestration_complete", "request_id":
"839d3f90-cdd2-483e-981d-a26f878f5261", "route": "policy", "tool": null,
"status": "ok", ...}` — confirmed via `docker logs`. No logging change
was needed or made.

**Privacy/security:** no `dangerouslySetInnerHTML`, no `localStorage`/
`sessionStorage`/cookie use, no console logging of the submitted question
or any returned record, no SQL/query-builder UI, no cross-dataset join or
identity-linking logic of any kind, no fabricated confidence score
(grepped and confirmed absent across all Slice 4 files).

**Tests:** 15 new `components/Assistant.test.tsx` tests (request-shape,
policy/FHIR/SynPUF routing and shared-component reuse, abstention
including missing-identifier/unsupported/cross-dataset/policy_abstained,
the 4-state readiness matrix, examples, validation, and error/retry), plus
11 `lib/api/orchestrateQuery.test.ts`, 8 `lib/assistantReadiness.test.ts`,
and 6 `lib/routingLabels.test.ts` — 40 new tests. Full suite: 156 passed,
0 failed (was 116 before this slice). `npm run typecheck` and `npm run
lint` both clean throughout.

**Production invariants (read-only, confirmed unchanged after all live
verification above):** Qdrant 39 points (all 3 collection names present
in the local instance); SynPUF `synpuf_beneficiaries`/`synpuf_claims`/
`synpuf_claim_diagnoses`/`synpuf_claim_procedures`/`synpuf_claim_lines` =
15/219/732/29/848; FHIR `fhir_patients`/`fhir_encounters`/
`fhir_conditions`/`fhir_procedures`/`fhir_observations`/
`fhir_observation_components`/`fhir_medication_requests` = 5/177/187/
234/1341/865/116; `review_cases`/`review_events` = 0/0. All `/orchestrate`
calls this session were read-only structured-data lookups or policy
retrieval, as expected.

**Known limitations / explicitly deferred (per this slice's own scope):**
no `/multi-agent` UI or combined policy+structured result rendering; no
human-in-the-loop review UI; no analytics dashboard or population-level
aggregate tool exposure; no change to the backend classifier or any
router intelligence — this slice only makes the *existing* router
visible. The 5-case live router verification, the request-ID correlation
check, and the responsive/production-invariant checks were completed in
a follow-up session once Docker Desktop was unpaused (see above) — no
example phrase needed to change, and the classifier was never modified.

## Slice 5: multi-agent policy + structured workflow UI — Evidence Workflow

Exposes Phase 10's *existing* bounded multi-agent workflow (`POST
/multi-agent`) — a small DAG (`supervisor -> {policy, structured (either
or both), abstain} -> validate -> END`) coordinating Phase 9's own policy
retrieval and structured tools, plus a new deterministic evidence
validator. No new backend intelligence, no autonomous planning/retry loop,
no HITL, no analytics. The architectural point of this slice, versus
Slice 4's `/orchestrate`: one request there always resolves to exactly one
supported route; here, one explicit, user-controlled request can gather
**both** a policy answer **and** a structured record in a single call, and
the result is passed through a validator before being shown.

**Contract (re-audited from current source, not assumed):**
`backend/app/agents/models.py`'s `MultiAgentRequest {question,
workflow?, policy_question?, structured_route?, tools?}` —
`WorkflowDecision` is exactly `policy_only | structured_only |
policy_and_structured | abstain` (confirmed directly from the enum, not
invented). When `workflow` is supplied explicitly, `backend/app/agents/
graph.py::supervisor_node` honors it directly and never re-classifies —
the deterministic free-text classifier
(`backend/app/agents/supervisor.py::classify_workflow`) only runs as a
fallback when no explicit workflow is given. `MultiAgentRequest`'s own
`model_validator` rejects (422) any contradictory combination outright:
`policy_only` with a `structured_route`/`tools`; `structured_only` with a
`policy_question`; `policy_and_structured` without a `structured_route`;
`abstain` with anything else; a `structured_route` that isn't `fhir`/
`synpuf`; or more than `MAX_STRUCTURED_TOOL_CALLS` (5) tool requests —
the backend rejects an over-limit request outright rather than silently
truncating it, and this slice never asks for more than one.

**`MultiAgentResponse` shape:** `{request_id, workflow, status, policy,
structured, validation, final_summary, abstention_reason, error}`.
`policy` (when present) is exactly Phase 9's `RAGAnswer` shape plus a
top-level `status` (`backend/app/agents/graph.py::policy_node`'s
`{"status": ..., "abstention_reason": ..., **policy_result}` merge) — so
Slice 2's `PolicyAnswerResult`/`PolicyAbstainedResult` work on it
unmodified. `structured` (when present) is `{route, results: [...]}`
where each result item is `{tool, success, source_dataset, data,
record_count, error, abstention_reason}` — a genuinely different shape
from Slice 3/4's flat `OrchestrationResponse` (an array of attempts, not
one flat record), since a combined or multi-tool structured request can
make more than one call. `validation` is `{passed: bool, issues:
[{code, detail}]}`.

**Multi-agent architecture (product language, not implementation
exposure):** described in the UI only as "CareFlow coordinated workflow"
— never "autonomous agent," "autonomous swarm," or any LangGraph/Python
class name, database table name, SQL, or tool-registry internal. The
underlying graph is a fixed, non-cyclic DAG: a deterministic supervisor
picks the workflow, the policy and/or structured specialist run (in
parallel for a combined workflow, writing only their own disjoint state
keys — verified directly from `graph.py`'s own module docstring and its
LangGraph `InvalidUpdateError` test), and a single deterministic
validator (never an LLM, never a second policy/structured call) decides
the final `status`/`abstention_reason`/`error`.

**Structured request limit:** `MAX_STRUCTURED_TOOL_CALLS = 5`
(`backend/app/agents/models.py`) — exceeding it is a 422 validation
error, not a silent truncation. This page only ever sends exactly one
tool request per submission, far under the limit; the limit itself is
documented here rather than built into the UI as a multi-tool picker,
since the mockup's "Structured information" control is a single bounded
operation, not a batch builder.

**Dataset boundary — the safety-critical design constraint:**
`CombinedWorkflowInput.structuredRoute` (`lib/api/multiAgentQuery.ts`) is
a single `Route` value (`"fhir"` or `"synpuf"`), never both — the type
system itself makes a combined FHIR+SynPUF request unconstructible from
this page, and `runCombinedWorkflow()` always sends exactly one
`structured_route` with exactly one tool request scoped to that same
domain. Switching the "Structured source" radio between FHIR and SynPUF
always clears the identifier field and resets the tool dropdown to that
domain's default tool (`handleDatasetChange` in `components/
Workflow.tsx`) — a FHIR patient ID is never silently reinterpreted as a
SynPUF beneficiary ID or carried across the switch. Proven by dedicated
tests (`components/Workflow.test.tsx`'s "no cross-dataset identity"
describe block) that inspect the actual request body sent to
`/multi-agent` and assert it contains only one dataset's identifier
field, never both.

**The actual, current safety boundary for cross-dataset identity —
confirmed by source inspection:** `ValidationIssueCode.
CROSS_DATASET_IDENTITY_VIOLATION` exists in `backend/app/agents/
models.py`'s enum but is grepped and confirmed to have **zero** other
references anywhere in the backend — no code path currently constructs
it. This is consistent with `MultiAgentRequest`'s own schema: a single
`structured_route` field structurally cannot name two datasets at once,
and there is no shared/combined identifier field. The real safety
boundary for this slice is therefore the request schema itself, not a
runtime check this page could trigger — see "Real safety verification"
below for the concrete attempt made to construct a violation and what it
actually returned.

**Backend changes:** NONE. `/multi-agent`, the supervisor, both
specialists, and the validator are used exactly as they already exist;
only frontend code and tests were added.

**Route:** `/workflow` (`app/workflow/page.tsx` → `components/
Workflow.tsx`). **Navigation label: "Evidence Workflow"** — chosen over
the alternative "Policy + Data" because it names the *activity* (running
a workflow) rather than only its inputs, and reads clearly next to
"CareFlow Assistant" without implying the page performs any kind of
determination. Never "Autonomous Agents," "Medical Decision Engine,"
"Coverage Decision," or "AI Doctor."

**Navigation order:** `System Overview, Ask CareFlow, Patient Data,
Claims, CareFlow Assistant, Evidence Workflow, Reviews (placeholder),
Analytics (placeholder)` — the existing Slice 1–4 order is left exactly
as it was; "Evidence Workflow" is appended after "CareFlow Assistant"
rather than the list being reordered, since reordering existing,
already-approved navigation was not asked for and is not necessary to
add one new item.

**Workflow UI — a controlled form, not a second chat box:** `Policy
question` (textarea) + `Structured source` (radio: Synthetic FHIR /
Synthetic Claims) + `<dataset>` identifier (text input, labeled
"Synthetic Patient ID" or "Synthetic Beneficiary ID" depending on the
selected source) + `Structured information` (a `<select>` of tools
scoped to the selected dataset) + "Run Evidence Workflow". Every control
is a real, explicit choice — there is no free-text box that gets
classified; see "Request construction" below.

**Tool selection (scoped, not the full registry):** FHIR: Patient
Summary / Encounters / Conditions / Procedures / Observations /
Medications (the same 6 patient-ID-scoped tools Slice 3's Patient Data
page offers). SynPUF: Beneficiary Summary / Beneficiary Claims (2 of
Slice 3's 3 beneficiary-scoped tools). `get_claim_details` is
deliberately excluded — it takes a `claim_row_id`, not a patient/
beneficiary identifier, so it has no place in this page's single
"Synthetic identifier" field; the population-level aggregate tools (9
total across both datasets) remain out of scope for the same reason
Slice 3 excluded them. Labels come from Slice 4's own `lib/
routingLabels.ts::toolLabel()` — reused directly, not a second mapping.

**Structured result rendering — reused, not reinvented:** `components/
structured/ToolResultView.tsx` is a new shared module built entirely
from Slice 3's own exported primitives (`RecordFields`, `RecordCard`,
the `fieldSpecs.ts` field lists, `formatCoding`/`formatCodingList` from
`lib/formatting.ts`) — the same per-tool field mapping Patient Data/
Claims already use, just assembled for this page's own bounded tool set
(8 of the 9 identifier-scoped tools; `get_claims_for_beneficiary` here
has no per-claim "View details" drill-down, since this page renders one
bounded result, not an exploratory surface). This is not a second,
independent rendering system — it is a third page's own tool-to-fields
switch built from the same shared building blocks, exactly as Patient
Data and Claims each already have their own. `DatasetBadge` and
`SyntheticDataNotice` are reused unmodified.

**Policy result rendering — reused, not reinvented:** the policy section
renders through Slice 2's own `PolicyAnswerResult`/`PolicyAbstainedResult`
(`components/policy/PolicyAnswer.tsx`, extracted in Slice 4 and reused
here for a third time) — answer, citations, and abstention are rendered
identically to `/ask` and `/assistant`; no third policy renderer exists.

**Combined result layout:** matches the slice's own preferred structure
— an "Evidence Workflow Result" heading with the workflow's human label,
then a "Medicare Policy Evidence" section, then a "Synthetic Healthcare
Data" section, then a "Validation" section, then (only for
`policy_and_structured`) an "Important" safety disclaimer. Each section
is visually distinct (its own heading, its own border) — never merged
into one paragraph, never cross-referencing the other section's content.

**Validator result rendering:** `ValidationResult {passed, issues}` is
rendered honestly — zero issues renders a calm "Evidence validation
passed with no issues." status line; any issues render each one's human
message (`lib/workflowLabels.ts::validationIssueMessage()`, covering all
7 real `ValidationIssueCode` values) with the raw code available
alongside as a technical detail, never hidden. When `passed=false` the
panel renders with `role="alert"` and distinct (warning-colored) styling
instead of the calm/notice treatment used when `passed=true` — a
validator failure is never presented as a fully successful result (the
combined result's other sections still render whatever data they
actually have, but the Validation section makes the failure visible, not
silently repaired or hidden). No AI/clinical/coverage confidence score
of any kind is invented — `ValidationResult` has no such field, and none
is displayed.

**Partial specialist failure — represented honestly:** because
`policy_node` and the structured specialist write disjoint state keys
and may run concurrently, `backend/app/agents/validator.py::validate_node`
can report overall `status=ok` even when one specialist succeeded and
the other only abstained (`Status.OK` takes precedence over
`Status.ABSTAINED` when combining the two halves) — so this page never
trusts the top-level `status` alone to decide what to render. The Policy
section and Structured section are each rendered from their own actual
sub-result independently: a successful policy answer still renders in
full even when the structured attempt failed (e.g. an unknown patient
ID), and vice versa — neither specialist's outcome is ever dropped,
disguised as the other's success, or silently removed. Proven by a
dedicated test asserting both a real policy citation and a real
"unknown patient" abstention message appear together in the same
result.

**Readiness (workflow-specific, not reused from Slice 4):** `lib/
workflowReadiness.ts` blocks submission when the API process is
unreachable/still checking, **or** when Qdrant is reported unavailable,
**or** when Postgres is reported unavailable — because every submission
from this page is always both a policy request (Qdrant-backed retrieval)
and a structured request (Postgres-backed) in the same call, so either
dependency being down would fail the whole combined request, not just
half of it. This is deliberately stricter than Slice 4's `lib/
assistantReadiness.ts` (which allows any degraded state, since its
eventual route is unknown until classified) and is its own distinct
policy from Slice 2's Qdrant-only and Slice 3's Postgres-only gating.
Redis is never considered. Proven by 9 dedicated tests covering every
combination in the readiness matrix (API down, Qdrant-alone,
Postgres-alone, both down, Redis-alone, all healthy).

**Error UX:** `runMultiAgentWorkflow()` maps transport/HTTP-level
failures into 5 categories — `network`, `timeout`, `retrieval_unavailable`
(the policy branch's `GenerationError` retrieval codes), `workflow_unavailable`
(the backend's own generic `multi_agent_unavailable` 503 fallback, e.g.
Postgres unreachable for the structured branch, plus the provider-layer
`GenerationError` codes), and `unexpected`. This is distinct from the
in-band `status="error"` (validator failure) case, which is not a
transport error at all and is rendered as a Validation-section warning
instead (see above) — the same category/in-band-status split Slice 2 and
Slice 4 already established for their own endpoints.

**Security/privacy:** no `dangerouslySetInnerHTML`, no `localStorage`/
`sessionStorage`/cookie use, no console logging of the policy question,
identifier, or any returned record, no SQL/query-builder UI, no
cross-dataset join or identity-linking logic, no fabricated confidence
score, no coverage/eligibility/medical-necessity conclusion anywhere in
this slice's own text (grepped and confirmed absent across all new
Slice 5 files).

**Accessibility:** every field has a real accessible label (`aria-label`
or `<label>`/`htmlFor`), the dataset choice and identifier/tool fields
are grouped in `<fieldset>`/`<legend>` elements, `role="alert"` for
validation/error messages, `aria-live="polite"` for the result region,
keyboard Tab order and visible focus confirmed live (see below), no
color-only communication (every state — routing, validation pass/fail,
abstention — is also named in text).

**Responsive behavior:** verified live at desktop, 768px, and 375px —
both for the empty form and for a real combined result (real policy
answer/citation, real structured record, real validation panel, real
safety disclaimer) rendered against the actual running backend. No
horizontal overflow at any width
(`document.documentElement.scrollWidth === clientWidth` confirmed at
768px and 375px for both); example chips, the safety-disclaimer prose,
and the structured record's long UUID field all wrap correctly at
mobile width, and the Validation/Important sections stay legible and
correctly bordered/colored at every width tested.

**Real live verification (against the repo's own docker-compose stack —
`careflow-ai-backend-1` on `127.0.0.1:18000`):**

- **Policy + FHIR** — `POST /multi-agent {question, workflow:
  "policy_and_structured", policy_question: "What does Medicare say
  about hospital beds?", structured_route: "fhir", tools:
  [{tool: "get_patient_summary", arguments: {patient_id:
  "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"}}]}` → `workflow=
  policy_and_structured`, `status=ok`; policy `status=ok`,
  `insufficient_evidence=false`, 1 citation (NCD 227 "Hospital Beds");
  structured `route=fhir`, `tool=get_patient_summary`, `success=true`,
  `source_dataset=synthea_fhir`, `record_count=1`; `validation=
  {passed: true, issues: []}`; `final_summary=null` (the backend
  intentionally always returns null here — not treated as a defect).
  Re-run through the real `/workflow` UI: the "Policy + Synthetic FHIR"
  example button populated all four fields, and submission rendered
  every section separately (Medicare Policy Evidence with Answer/
  Evidence/Citation 1, Synthetic Healthcare Data with the Synthea FHIR
  badge and full patient-summary record, Validation with "Evidence
  validation passed with no issues.", and the Important safety
  disclaimer) with no coverage conclusion anywhere in the rendered text.
- **Policy + SynPUF** — same policy question, `structured_route:
  "synpuf"`, tool `get_beneficiary_summary` with
  `beneficiary_id: "00013D2EFD8E45D1"` → `workflow=
  policy_and_structured`, `status=ok`; policy identical to above;
  structured `route=synpuf`, `success=true`,
  `source_dataset=cms_desynpuf`, `record_count=1`; `validation=
  {passed: true, issues: []}`. Re-run through the real UI via the
  "Policy + Synthetic Claims" example: identity/coverage/chronic-
  indicator/payment-amount field groups all rendered under the CMS
  DE-SynPUF badge, separately from the policy section, with the same
  Validation and safety-disclaimer sections.
- **Evidence Validator (real, not mocked):** both real combined
  workflows above returned `validation.passed=true` with `issues: []` —
  the validator ran and found nothing to flag, reported here exactly as
  observed (not manufactured).
- **Partial failure:** not intentionally induced against production
  data, per instruction — already covered by
  `components/Workflow.test.tsx`'s dedicated mocked test. However, the
  cross-dataset safety probe below incidentally produced a real (not
  mocked) partial-outcome response — see below.
- **Cross-dataset safety — the real boundary, confirmed two ways:**
  (1) `structured_route: ["fhir", "synpuf"]` (an array) was rejected by
  Pydantic itself with HTTP 422: `"Input should be an instance of
  Route"` — the request schema cannot represent two structured routes
  in one request at all. (2) A SynPUF tool (`get_beneficiary_summary`)
  sent under `structured_route: "fhir"` returned HTTP 200 with
  `structured.results[0] = {tool: "get_beneficiary_summary",
  success: false, source_dataset: null, error: "unsupported_tool",
  abstention_reason: null}` — the route-scoped tool registry rejected
  it without ever touching SynPUF data (policy still succeeded
  alongside it, giving a real, unmocked example of `status=ok` with a
  failed structured attempt — the "OK dominates ABSTAINED" partial-
  result behavior documented above). Neither attempt ever produced
  `cross_dataset_identity_violation` — confirming this session's earlier
  source-level finding that this code is currently unreachable, not
  merely untested. **The confirmed real safety boundary:** the public
  `/multi-agent` request contract structurally prevents one workflow
  from specifying both a FHIR and a SynPUF structured route.
- **Request-ID correlation (real, two separate requests):** a direct API
  call's `X-Request-ID` header, response body `request_id`, and the
  backend's `multi_agent_complete` structured log all matched exactly
  (`e84bf94b-08f1-401c-9566-a2bb4eee9c16`); the same three-way match was
  independently confirmed for a UI-driven submission
  (`4e381881-126b-47ad-abda-8df63da61599`), including the intermediate
  per-node `agent_node_complete` log lines (`supervisor`, `structured`,
  `policy`, `validate`) for the same request ID.
- **Browser/network:** both real UI submissions showed `OPTIONS
  /multi-agent → 200` (CORS preflight) followed by `POST /multi-agent →
  200`, no CORS errors, and no unexpected console errors — the only
  console entries were the dev server's own unrelated HMR WebSocket
  reconnect noise, identified and ignored as such.
- **Production invariants (read-only, confirmed unchanged after all of
  the above):** Qdrant 39 points; SynPUF 15/219/732/29/848; FHIR
  5/177/187/234/1341/865/116; **`review_cases`/`review_events` = 0/0** —
  confirmed `/multi-agent` created no review rows across every real
  request made this session.
- **Backend regression:** focused (`test_agents_*`, CORS, health/
  readiness) — 110 passed, 14 skipped, 0 failed. Full suite
  (`pytest tests/`) — 817 passed, 166 skipped, 0 failed. `ruff check .`
  — all checks passed. `ruff format --check .` — 155 files already
  formatted. `pip check` — no broken requirements. `git diff --check` —
  clean.

**Tests:** `lib/api/multiAgentQuery.test.ts` (13: policy_only/
structured_only/combined-FHIR/combined-SynPUF requests, exact request
body for a combined submission, abstain response, validator-issue
response, partial-failure response, network/timeout/retrieval_unavailable/
workflow_unavailable mapping, request-ID extraction), `lib/
workflowReadiness.test.ts` (9: the full readiness matrix), `lib/
workflowLabels.test.ts` (2: every WorkflowDecision and ValidationIssueCode
maps to a real, non-generic, confidence-free message), `components/
Workflow.test.tsx` (20: form validation, dataset-switch identifier
clearing, tool-list switching by dataset, duplicate-submission
prevention, exact no-cross-dataset-identity request bodies for both
datasets, combined-result section separation with no citation/structured
mixing, validator-failure warning rendering, honest partial-specialist-
failure rendering, the readiness matrix at the component level, error/
retry, and both example workflows populating without auto-submitting).
44 new tests. Full suite: 204 passed, 0 failed (was 156 before this
slice). `npm run typecheck`, `npm run lint`, and `npm run build` all
clean throughout (`/workflow` appears in the production build's route
list alongside the other 6 routes).

**Known limitations / explicitly deferred (per this slice's own scope):**
no `/multi-agent` UI beyond this one controlled combined-workflow form;
no HITL/review UI; no analytics dashboard or population-level aggregate
tool exposure; no new backend agent behavior, and no coverage/
eligibility/medical-necessity determination anywhere — this slice only
makes the *existing* Phase 10 workflow visible, with the two evidence
domains kept visually and semantically separate at all times. All live
verification (both combined workflows, the validator, the cross-dataset
safety boundary, request correlation, real-result responsiveness,
production invariants, and backend regression) was completed against
the repo's own running docker-compose stack once Docker Desktop was
available — see the "Real live verification" subsection above for the
full record.

## Slice 6: human review / HITL + audit UI — Reviews

Exposes Phase 11's *existing* human-in-the-loop review state machine —
`POST /reviewable-query`, `GET /reviews`, `GET /reviews/{review_id}`,
`POST /reviews/{review_id}/decision` — with no new review semantics, no
authentication, and no automatic revision/rerun behavior. A reviewer can
now see when CareFlow flags a request for review, inspect the exact
evidence that was captured, and record a decision.

**Review API contract (re-audited from current source):**
`backend/app/review/models.py`, `backend/db/migrations/
0004_review_workflow.sql`, `backend/app/review/{repository,service,
policy}.py`, `backend/app/api/reviews.py` — re-read directly, not assumed
from prior slices' documentation style. `ReviewableQueryRequest` extends
`MultiAgentRequest` with two fields: `explicit_review_requested: bool`
and `previous_review_id: str | None`. `ReviewableQueryResponse` extends
`MultiAgentResponse` with `review_required`, `review_reason_codes`,
`review_id`, `review_status` — a strict superset, confirmed by reading
the Pydantic class definition itself (`class ReviewableQueryResponse(
MultiAgentResponse)`).

**State machine:** `ReviewStatus = pending | approved | rejected |
revision_requested` (`backend/app/review/models.py`). Confirmed directly
from `is_valid_transition()`: valid exactly when `current_status ==
PENDING` — so **only `pending` is non-terminal**, and all three decision
targets (`approved`/`rejected`/`revision_requested`) are terminal; nothing
in Phase 11 ever transitions a case a second time. Optimistic
concurrency: `apply_decision()`'s `UPDATE ... WHERE review_id = %s AND
version = %s AND status = 'pending'` is the single compare-and-swap that
enforces both "correct version" and "still pending" atomically — a stale
version *or* an already-decided case both fail the same `WHERE` clause
and are indistinguishable at the SQL level, which is exactly why the API
layer returns the same `409 version_conflict` (carrying the row's actual
current state) for both cases rather than inventing a separate "already
decided" error.

**Review creation rule (confirmed, not changed):**
`backend/app/review/policy.py::determine_review_requirement()` —
`review_required = explicit_review_requested OR len(validation.issues) >
0`. A clean abstention is never a validation issue (Phase 10's
`validate_node` deliberately never records one), so it never triggers a
review on its own. An infrastructure failure (`GenerationError` or any
other exception) never reaches `run_reviewable_query()`'s review-creation
step at all — it propagates and the request never completes, so there is
nothing to snapshot and no review is ever created for it.

**Backend changes:** NONE. `/reviewable-query`, `/reviews`, `/reviews/
{review_id}`, `/reviews/{review_id}/decision`, the review repository, and
the trigger policy are all used exactly as they already exist.

**Routes:** `/reviews` (queue) and `/reviews/[reviewId]` (detail) — real
Next.js routes (`app/reviews/page.tsx`, `app/reviews/[reviewId]/
page.tsx`, the latter awaiting the async `params` per Next 16's App
Router convention). Sidebar's "Reviews" item is now functional
(`href="/reviews"`) instead of the Slice 1–5 disabled placeholder;
"Analytics" remains the only disabled placeholder left.

**Reviewable workflow integration — the endpoint-switch decision:**
Slice 5's `/workflow` page now always submits through `POST
/reviewable-query` instead of `POST /multi-agent`, with a new "Request
human review" checkbox controlling only `explicit_review_requested`.
This was a deliberate choice, not the only option considered: the
alternative (keep `/workflow` on `/multi-agent`, add a second, separate
review-submission surface) would have left the page permanently blind to
Phase 11's own always-on rule — a validation issue creates a review
*regardless* of any checkbox — so a user could trigger that real,
automatic behavior and never find out from this page. Since
`ReviewableQueryResponse` is a strict superset of `MultiAgentResponse`,
the switch is behavior-preserving for every existing field
`MultiAgentResultView` reads; only the request's own endpoint and body
changed. This did require updating a handful of Slice 5's own test
assertions (the literal `/multi-agent` endpoint string, and the mock
response shape needing the 4 new review fields) — a deliberate,
in-scope change tied directly to this slice's assigned integration work,
not an unrelated regression; the full previous-slice test suite (204
tests) still passes in substance, just against the corrected endpoint.

**Explicit human review:** the "Request human review" checkbox, labeled
exactly that — never "Send for medical approval" or similar. When a
review is created (whether by the checkbox or automatically via a
validation issue), a "Review required" panel appears above the normal
result: Review ID, State (human label), trigger reason(s), and a "View
review" link to `/reviews/{review_id}`. When no review is required, an
honest "No human review was required for this request." note appears
instead — never fabricated, always driven by the real
`review_required` field.

**Queue (`/reviews`):** calls the real `GET /reviews` with `status`,
`limit`, and `cursor` query parameters. Defaults to `status=pending`
(with an "All statuses" option), matching the page's primary purpose as
a work queue. Preserves the backend's own FIFO ordering (`created_at
ASC, review_id ASC` — oldest first, confirmed from
`repository.py::list_reviews`) — never re-sorted client-side. Each card
shows only bounded fields (state, workflow, trigger reason(s), created
time, version, review ID) — never the evidence snapshot. An empty queue
renders "No pending reviews." with no error styling — a genuinely
successful empty state, not a failure.

**Pagination:** implements the backend's real opaque-cursor keyset
pagination (`DEFAULT_REVIEW_QUEUE_LIMIT=20`, `MAX_REVIEW_QUEUE_LIMIT=
100`) — never a fabricated offset/page-number scheme, since the backend
doesn't have one. "Next" is enabled only when the response's own
`next_cursor` is present; "Previous" is implemented by retaining every
cursor visited so far in an in-memory stack (no second backend call
needed to go back), rather than the backend supporting reverse
pagination itself (it doesn't).

**Review detail (`/reviews/[reviewId]`):** calls the real `GET /reviews/
{review_id}`, rendering `ReviewDetail {case, events}` exactly as
returned. A 404 renders "No review was found for this ID." (not a
generic error); a 422 (malformed UUID) renders through the same calm
error/retry path used everywhere else in this frontend.

**Evidence snapshot — reused, never reconstructed:** `ReviewCase.
evidence_snapshot` is exactly a `MultiAgentResponse` JSON body
(`backend/app/review/models.py::build_evidence_snapshot()` is literally
`response.model_dump(mode="json")`), so it is rendered through the
*same* `MultiAgentResultView` component Slice 5's `/workflow` page
already uses for a live result — not a second, independent evidence
renderer. This also means the snapshot is guaranteed to render
identically to how that exact result looked the moment it was captured.
The page never re-runs the workflow, never re-queries Qdrant/Postgres,
and never replaces the snapshot with a current result — a small
disclosure toggle ("Show/Hide raw snapshot JSON") offers the literal
stored JSON as optional technical detail, never as the primary UX.

**Evidence fingerprint:** shown only as a labeled technical/audit detail
("Evidence fingerprint: <64-hex-char SHA-256>") — never described as a
tamper-proof or blockchain-backed audit ledger, matching
`backend/app/review/models.py::compute_evidence_fingerprint()`'s own
docstring, which explicitly disclaims exactly that: "This provides
snapshot-integrity comparison and reproducibility. It does NOT make the
database tamper-proof, cryptographically immutable, or blockchain-backed."

**Review events / audit history:** rendered chronologically (the
backend's own `created_at ASC, event_id ASC` order, never re-sorted).
Each of the 4 real `ReviewEventType` values (`review_created`,
`review_approved`, `review_rejected`, `revision_requested`) gets a human
label; `actor_type`/`actor_id` are shown exactly as returned (`system`
for the creation event, `reviewer "<id>"` for a decision) — no actor
identity is ever invented, and a decision's `previous_status → new_status`
transition and optional `reason` are shown verbatim when present.

**Reviewer identifier semantics:** the field is labeled "Reviewer
identifier" with the help text "Used for application audit history." —
never "Authenticated reviewer" or "Verified reviewer," since
`reviewer_id` is caller-supplied and non-authoritative
(`backend/app/review/models.py::ReviewDecisionRequest.reviewer_id`, a
plain 1–100 character string with no auth check anywhere in
`decide_review()`). This project implements no authentication in any
slice; the UI never implies otherwise.

**Decisions exposed — exactly the real three:** Approve, Reject, Request
Revision (`ReviewDecisionType.APPROVE/REJECT/REQUEST_REVISION`) — no
"Override," "Auto Approve," "Escalate to CMS," or "Approve Coverage."

**Approval semantics — the mandatory clarification:** every decision
panel (while the case is still pending) shows, directly above the
decision buttons: "Approval accepts this CareFlow output for the
application workflow. It is not a coverage, eligibility,
medical-necessity, claim, or clinical decision." Never labeled "Coverage
Approved," "Claim Approved," "Medically Approved," or "CMS Approved"
anywhere in the UI (grepped and asserted in tests).

**Reject / Request Revision semantics:** Reject records the reviewer's
non-acceptance with no inferred reason beyond the optional, bounded
(≤2000 char) `reason` field the backend itself accepts — nothing invented
beyond that. Request Revision is terminal for the *current* review case,
exactly matching the state machine above: the frontend never
automatically reruns the workflow, never creates a new AI answer, never
creates a second review, and never modifies the evidence snapshot —
confirmed by a live test asserting zero `/reviewable-query` or
`/multi-agent` calls happen as a side effect of a revision-request
decision. `previous_review_id` (for a deliberate *new* submission that
references this one) exists in the schema but has no UI in this slice —
building that flow is explicitly out of scope here (a "deliberate
future/new submission action," not automatic rerun).

**Optimistic versioning / 409 conflict UX:** every decision request sends
the case's actual current `version` as `expected_version`. On a 409, the
response body's own `review` field (the backend's authoritative current
state) is used to immediately correct the displayed case — never
overwritten with the rejected attempt, never silently retried. A calm
message appears: "This review changed before your decision was saved.
Refresh the review to see its current state," with a manual "Refresh"
button that re-fetches the full detail (including audit history) on
request — proven live (see below), not just in mocked tests.

**Terminal review UI:** once a case leaves `pending`, the Decision
section replaces the reviewer-identifier/reason form and the three
decision buttons with a single status line — "This review has already
been decided (<State>). No further decision can be made from this
page." — and no decision control remains in the DOM at all (not merely
visually disabled), confirmed by both mocked and live tests.

**Readiness — two distinct policies, neither reused verbatim from
Slice 5:** `lib/reviewReadiness.ts` (for `/reviews` and `/reviews/
[reviewId]`) blocks only on API-down/checking or Postgres-down — the
queue/detail/decision endpoints are pure Postgres reads/writes via
`db/connection.py`, confirmed from `backend/app/api/reviews.py`, and
never touch Qdrant, retrieval, or any generation provider. Qdrant-down
and Redis-down alone never block. The *submission* surface
(`/workflow`'s reviewable-query form) continues to reuse Slice 5's own
`lib/workflowReadiness.ts` unmodified, since a combined reviewable
request still needs both Qdrant (policy) and Postgres (structured) —
that dependency profile did not change in this slice.

**Request-ID handling:** `lib/api/reviewableQuery.ts` and `lib/api/
reviewsApi.ts` are both built on the existing `apiGet`/`apiPost`/
`ApiResponse` — no second fetch abstraction — and preserve `X-Request-ID`
through the same `requestId` field every other outcome type in this
project already carries. Verified live (see below) that `backend/app/
observability/logging.py::log_event()`'s own context-based auto-fill
means even `decide_review`'s log call (which passes no explicit
`request_id`) still correlates correctly to the HTTP request's ID.

**Error UX:** `reviewableQuery`'s 5 categories mirror
`multiAgentQuery.ts`'s exactly (network/timeout/retrieval_unavailable/
workflow_unavailable/unexpected, with `reviewable_query_unavailable`
replacing `multi_agent_unavailable` as the backend's generic-failure
code). `reviewsApi.ts`'s three endpoints distinguish `not_found` (404),
`conflict` (409, carrying the current case), `invalid` (422 malformed
ID), plus network/timeout/unexpected — never collapsing a normal
no-review or review-created result into an "error" outcome; those are
just two values of the same real `review_required` field.

**Security/privacy:** no `dangerouslySetInnerHTML`, no `localStorage`/
`sessionStorage`/cookie persistence of the reviewer identifier, review
contents, evidence snapshot, or notes, no console logging of evidence,
no analytics trackers (grepped and confirmed absent across all new
Slice 6 files).

**Accessibility:** real labels/`aria-label` on every field, `<fieldset>`/
`<legend>` grouping for the identifier/reason inputs, `role="alert"` for
validation/conflict/error messages, `aria-live="polite"` result regions,
semantic `h1`/`h2` structure confirmed live, state communicated in text
everywhere (never color-only), keyboard-reachable controls throughout.

**Responsive behavior:** verified live at desktop, 768px, and 375px for
both `/reviews` (including the real empty-queue state after all 4 test
reviews were decided) and `/reviews/[reviewId]` (a real loaded review
with its full evidence snapshot, validation notices, audit history, and
decision/terminal states) — no horizontal overflow at any width
(`scrollWidth === clientWidth` confirmed at 768px and 375px on both
pages).

**Tests:** `lib/api/reviewableQuery.test.ts` (8), `lib/api/
reviewsApi.test.ts` (15: queue success/empty/network/timeout, detail
success/404/422/request-ID, decision payload/success/404/409-conflict/
409-terminal/network/request-ID), `lib/reviewReadiness.test.ts` (9),
`lib/reviewLabels.test.ts` (8, including an explicit assertion that no
decision label ever contains "override/auto approve/escalate/coverage"),
`components/ReviewQueue.test.tsx` (9: empty state, bounded row fields, no
evidence dump, default status filter, filter switching, pagination
Next/Previous, error/retry, readiness), `components/ReviewDetail.test.tsx`
(15: full metadata/snapshot/events rendering, single-GET-per-mount,
JSON-disclosure toggle, 404 handling, approval-disclaimer presence and
placement, forbidden-phrase absence, reviewer-ID requirement, exact
decision payloads and resulting terminal states for all 3 decisions, no
automatic rerun/new-review side effects, real 409-conflict handling
including the Refresh re-fetch, reviewer-identifier non-authentication
language, readiness). Plus 4 new tests in `components/Workflow.test.tsx`
covering the endpoint switch, `explicit_review_requested` wiring, the
"Review required" panel, the honest no-review note, and automatic
review-on-validation-issue visibility without the checkbox. 67 new
tests. Full suite: 271 passed, 0 failed (was 204 before this slice).
`npm run typecheck`, `npm run lint`, and `npm run build` all clean
throughout (`/reviews` and `/reviews/[reviewId]` appear in the
production build's route list alongside the other 7 routes).

**Real live verification (against the repo's own docker-compose stack):**

- **Review creation:** a safe, real partial-specialist-failure request
  (SynPUF `get_beneficiary_summary` + a deliberately unsupported second
  tool name — the same pattern the backend's own `tests/
  test_review_api.py::PARTIAL_FAILURE_BODY` fixture uses) created a real
  review: `status=pending`, `version=1`, `trigger_reason_codes=
  ["specialist_failure"]`, a stored evidence snapshot and fingerprint,
  and exactly one `review_created` event. A second real request with
  `explicit_review_requested=true` on an otherwise-clean `policy_only`
  question confirmed `review_reason_codes=["explicit_review_requested"]`
  with no validation issues present. Three more real reviews were
  created the same way for the decision/conflict verification below (4
  total).
- **Real queue:** `/reviews` listed all pending reviews with the correct
  bounded fields, no evidence dump, and correct FIFO order; after all 4
  were decided, the default `status=pending` filter correctly showed
  "No pending reviews." — the genuine empty state, not an error.
- **Real detail:** each review's full detail rendered correctly —
  metadata, trigger reasons, evidence fingerprint, the complete evidence
  snapshot via `MultiAgentResultView` (including the second tool
  attempt's honest "Structured data could not be retrieved for this
  request." message), Validation notices, and the `review_created` audit
  event.
- **Real approval:** submitted through the real UI with reviewer
  identifier "alice" → `status: pending → approved`, `version: 1 → 2`,
  a `review_approved` event appended (`reviewer "alice" · Pending →
  Approved`), decision controls became inactive, and the evidence
  fingerprint in the decision response was byte-identical to the
  original — the snapshot was never touched.
- **Real rejection:** a second, separate real review, reviewer "bob" →
  `status: pending → rejected`, `version: 1 → 2`, event appended,
  fingerprint unchanged, controls inactive.
- **Real revision request:** a third, separate real review (the
  explicit-review-requested one), reviewer "carol" → `status: pending →
  revision_requested`, `version: 1 → 2`, event appended, fingerprint
  unchanged, controls inactive. Confirmed via network inspection: zero
  `/reviewable-query` or `/multi-agent` requests occurred as a result of
  this decision — no automatic rerun, no automatic new review.
- **Real 409 conflict:** a fourth review was loaded in the UI at
  version 1; it was then decided out-of-band directly against the API
  (`approve`, becoming version 2); the UI — still holding the stale
  version 1 — was then used to submit a `reject` decision. The backend
  correctly returned 409, and the UI immediately displayed the server's
  authoritative current state (`APPROVED`, version 2) rather than the
  attempted `rejected` value, with the calm conflict message and a
  working Refresh control. The audit history correctly showed no
  `review_rejected` event was ever appended — the conflicting write was
  genuinely rejected server-side, not partially applied.
- **Request-ID correlation:** confirmed for both a `reviewable-query`
  call and a decision call — the decision endpoint's `review_action_
  complete` log line correlated correctly via `log_event()`'s
  context-based auto-fill even though `decide_review()`'s own `_log()`
  call never passes `request_id` explicitly, exactly as the source
  code's own comment claims.
- **Browser/network:** every real UI action showed a clean `OPTIONS →
  200` / actual-method → `200`/`409` pair with no CORS errors; the only
  console entries were the dev server's own unrelated HMR WebSocket
  noise.
- **Backend regression:** focused (`test_review_*`, `test_agents_api`,
  CORS, health/readiness) — 90 passed, 60 skipped, 0 failed. Full suite
  — 817 passed, 166 skipped, 0 failed. `ruff check .` — all checks
  passed. `ruff format --check .` — 155 files already formatted. `pip
  check` — no broken requirements. `git diff --check` — clean.

**Production/data invariants:** Qdrant 39 points; SynPUF
15/219/732/29/848; FHIR 5/177/187/234/1341/865/116 — all unchanged.
**Review counts changed, as expected and intended by this slice's own
real verification:** `review_cases = 4` (2 approved, 1 rejected, 1
revision_requested), `review_events = 8` (4 `review_created` + 4 decision
events, one per case) — these rows are the real HITL verification
artifacts this slice exists to produce, not leftover test pollution, and
were intentionally not deleted (no repository test-data-cleanup policy
applies to manually-created verification data the way it does to the
backend's own automated test fixtures, which clean up after themselves
via their own dedicated pytest fixture).

**Known limitations / explicitly deferred (per this slice's own scope):**
no Analytics dashboard or population-aggregate UI; no authentication of
any kind (reviewer identity remains explicitly non-authoritative); no
coverage/eligibility/medical-necessity/claim-adjudication determination
anywhere; no automatic revision rerun or autonomous review decision; no
UI for `previous_review_id`-linked resubmission (schema supports it, this
slice does not build that flow); no FHIR/SynPUF identity linkage
anywhere in the review surfaces either.

## Slice 7: frontend integration hardening + product polish

A cross-cutting audit-and-fix slice — no new routes, no new backend
capability exposed, no Analytics/authentication. The goal was making the
7 existing surfaces (System Overview, Ask CareFlow, CareFlow Assistant,
Patient Data, Claims, Evidence Workflow, Reviews) behave like one
coherent application rather than 7 independently-built slices. Every
change below was a genuine inconsistency or gap found by re-reading the
actual current source across all slices — none were invented busywork.

**Route inventory (all 8 pages audited):** `/` (System Overview — no
backend action, just `/live`+`/ready`), `/ask` (policy RAG via
`POST /query`), `/assistant` (free-text routing via `POST /orchestrate`),
`/patient-data` (explicit FHIR lookups via `POST /orchestrate`),
`/claims` (explicit SynPUF lookups via `POST /orchestrate`), `/workflow`
(combined policy+structured via `POST /reviewable-query`), `/reviews`
(queue via `GET /reviews`), `/reviews/[reviewId]` (detail+decision via
`GET`/`POST /reviews/{id}`). Each already had a defined loading/success/
empty-or-abstention/error state and its own readiness policy from its
originating slice — the audit's job was checking these for *consistency*
with each other, not building them from scratch.

**Navigation fix (genuine bug):** `Sidebar.tsx`'s active-state check was
`pathname === item.href` — an exact match that worked for every route
through Slice 5, but silently failed to highlight "Reviews" while
viewing `/reviews/[reviewId]`, since Slice 6 was the first slice to add
a nested route. Fixed to also match any path starting with `"{href}/"`
(excluding `/` itself, which must never match every route) — proven by
a new `components/Sidebar.test.tsx` (6 tests) that didn't exist before
this slice.

**Terminology audit:** confirmed the existing split is intentional, not
inconsistent — `DatasetBadge`/`ROUTE_LABELS` use the precise technical
names ("Synthea FHIR", "CMS DE-SynPUF") plus "· Synthetic", while page
copy and form controls use the friendlier "Synthetic FHIR"/"Synthetic
Claims" — both forms already appear in the directive's own approved
vocabulary list for the same concept. No change made. A full-app grep
for every forbidden phrase ("AI Doctor," "Coverage Engine," "Autonomous
Agent," "Medical/Claim/CMS Approval," "Clinical Decision Engine,"
"coverage/eligibility/medical-necessity determination," "claim
adjudication," "authenticated reviewer") found zero genuine matches —
the only hits were legitimate disclaimer text explicitly saying the
system does *not* do these things.

**Loading-state audit:** confirmed already consistent and appropriately
domain-specific across pages ("Searching Medicare policy…", "Loading
synthetic patient data…", "Running evidence workflow…", "Loading
reviews…") — never a generic "AI thinking." One genuine gap found and
fixed: `ReviewDetail.tsx` disabled its decision buttons while a decision
was submitting but showed no loading text at all, unlike every other
submitting state in the app. Added "Saving review decision…" (the exact
phrase this slice's own directive suggested), rendered in the same
`aria-live="polite"` region as the conflict/error notices.

**Error-state audit:** confirmed the `network`/`timeout`/`unexpected`
message text is already byte-for-byte identical across `AskCareFlow`,
`Assistant`, `Workflow`, `ReviewQueue`, and `ReviewDetail` — a real,
pre-existing consistency, not something this slice needed to create.
Meaningful distinctions (abstention vs. validation issue vs. review
conflict vs. not-found) are preserved everywhere, never collapsed into
one generic message.

**Request-ID audit (genuine gap found and fixed):** every other page's
error state already showed "Request ID: `<id>`" as optional technical
detail when available (`AskCareFlow`, `Assistant`, `Workflow`,
`SystemOverview`, the shared `StructuredResultStates`). `lib/api/
reviewsApi.ts`'s outcome types already captured `requestId` on every
path, but `ReviewQueue.tsx`'s `QueueState` and `ReviewDetail.tsx`'s
`LoadState`/`DecisionUiState` silently discarded it when converting the
API outcome into component state — so Reviews' two pages could never
show a request ID on an unexpected error, unlike the rest of the app.
Fixed by threading `requestId` through both state types and rendering it
in the existing error blocks, exactly matching the established pattern.
Two new tests confirm it (one per page).

**Readiness matrix (audited, not changed):** confirmed each policy still
blocks only on what it actually needs — `policyReadiness` (Qdrant),
`structuredReadiness` (Postgres), `assistantReadiness` (permissive: any
degraded state, since its route isn't known until classified),
`workflowReadiness` (Qdrant + Postgres, since every combined request
needs both), `reviewReadiness` (Postgres only, since queue/detail/
decision never touch Qdrant or retrieval). Redis is never authoritative
anywhere. No single global readiness rule exists or was introduced — five
distinct, independently-justified policies remain, which is correct
given the five genuinely different dependency profiles.

**System Overview fix (genuine gap found and fixed):** Redis was listed
as an equal-looking dependency row next to Postgres/Qdrant with no
indication that a Redis outage never affects overall readiness (backend
confirms this: `/ready`'s `status` field is never influenced by Redis).
Added an inline "(optional)" qualifier on the Redis row and a caption —
"Postgres and Qdrant are required for readiness. Redis backs an optional
performance cache only and never affects overall system status." — with
a dedicated new test. No fake uptime/history charts or unsupported
monitoring claims were added.

**Shared-component consolidation (genuine duplication found and fixed):**
`AskCareFlow.module.css`'s `.errorResult`/`.retryButton`/
`.technicalDetail` were confirmed byte-for-byte identical to
`StructuredResultStates.module.css`'s `.error`/`.retryButton`/
`.technicalDetail` (already reused by `Assistant`/`Workflow`/
`ReviewQueue`/`ReviewDetail`) — a leftover from `AskCareFlow` predating
that shared module (Slice 2, before Slice 3 introduced it).
`AskCareFlow.tsx`'s error panel now imports and uses the shared classes
directly; the duplicate CSS was deleted. Verified regression-safe by the
existing 13 `AskCareFlow.test.tsx` tests passing unchanged. A smaller
candidate (`.validationError`'s identical 3-line rule, duplicated across
4 files) was deliberately left alone — not worth a shared CSS module for
3 lines, and over-abstracting a trivial utility class was judged against
the directive's own "do not over-abstract domain-specific UI" guidance.

**Form-validation audit (genuine cross-cutting gap found and fixed):**
every form already validated blankness via `.trim().length === 0`, but
none of them actually trimmed the value they *sent* — `AskCareFlow`,
`Assistant`, `PatientData`, `Claims`, `Workflow`, and `ReviewDetail` all
sent the raw, untrimmed string to the backend. Confirmed this is a real
functional risk, not cosmetic: `backend/app/orchestration/models.py::
StrictModel` uses `strict=True` with no `str_strip_whitespace` — the
backend does not normalize whitespace itself, so a stray leading/
trailing space (e.g. from a pasted synthetic ID) would silently turn a
valid patient/beneficiary ID into an "unknown" abstention purely due to
whitespace. Fixed by trimming each value at the point of submission (not
on every keystroke, so the visible input is untouched while typing) in
all 6 forms, including `ReviewDetail`'s `reason` field. Verified live
against the real backend: typing `"  31a2e8ec-...-508713  "` (with
spaces) into Patient Data's identifier field still returned the correct
real patient record — proof the trim actually reaches the request, since
an untrimmed value would have produced a hard "no synthetic patient was
found" abstention (exact-match SQL lookup). New tests added for
`Workflow`, `PatientData`, and `ReviewDetail` as representative coverage
of the fix (not duplicated across all 6 forms, since the same one-line
fix pattern repeats identically).

**Empty states (audited, confirmed correct):** "No pending reviews.",
"No records found for this synthetic identifier/query.", "No human
review was required for this request.", and a zero-issue "Evidence
validation passed with no issues." are all rendered as calm, non-alert
text/status — never styled or announced as an error. No changes needed.

**API client audit (confirmed, no changes):** every network call in the
frontend still goes through the single `apiGet`/`apiPost` pair in
`lib/api/client.ts` — grepped and confirmed zero raw `fetch()` calls
anywhere else. Timeout (5000ms default), JSON-parse guarding, and
`X-Request-ID` extraction remain centralized and consistent. No
credentials or secrets appear anywhere in the frontend (grepped).

**Security audit (full app, clean):** no `dangerouslySetInnerHTML`, no
`eval`/`.innerHTML`, no `localStorage`/`sessionStorage`/cookie usage
anywhere, no console logging of questions/identifiers/evidence/results,
no embedded secrets or API keys, and every dynamic URL path segment
(review IDs) is `encodeURIComponent`-escaped before interpolation.

**Content/overclaim audit (full app, clean):** a comprehensive grep for
every prohibited phrase found only two matches, both legitimate: the
Evidence Workflow/Review safety disclaimer itself saying evidence
presence "does not establish... claim approval," and a code comment in
`policyQuery.ts` explaining an abstention must never be read as "a
negative coverage determination." Both are explanatory disclaimers using
the forbidden terms to rule them out, exactly the kind of context this
audit was instructed to preserve, not remove.

**Responsive full-app pass:** every one of the 8 routes was loaded fresh
and checked at 375px (`scrollWidth === clientWidth` confirmed on all 8,
including the nested `/reviews/[reviewId]`) and spot-checked at 768px
(desktop→tablet transition confirmed clean on System Overview; the other
7 pages' own originating slices already performed full desktop/768/375
verification with real rendered results, and no structural CSS changed
this slice — only short text additions, none wide enough to introduce
new overflow risk).

**Accessibility (confirmed, no new issues):** every interactive control
across all 8 pages remains a native HTML element (`<input>`, `<textarea>`,
`<select>`, `<button>`, `<a>`) — never a custom div-based widget — so
keyboard operability, focus visibility, and Enter/Space activation are
guaranteed by browser default behavior, not custom JS. Semantic heading
hierarchy, `<fieldset>`/`<legend>` grouping, `role="alert"`/
`aria-live="polite"`, and never-color-only status communication were all
previously verified per-slice and reconfirmed live this slice (System
Overview, Ask CareFlow, CareFlow Assistant, Reviews).

**Real smoke tests (against the repo's own docker-compose stack):**
- **System:** `/live`+`/ready` both healthy; System Overview correctly
  showed "Ready" with all 4 rows (API/Postgres/Qdrant/Redis) and the new
  Redis-optional note.
- **Policy:** a real `/ask` submission ("Does Medicare cover hospital
  beds?") rendered the NCD 227 answer and citation correctly through the
  refactored (shared-CSS) error-panel component.
- **Assistant:** a real FHIR-routing request ("Show me FHIR patient
  31a2e8ec-...") correctly returned `route=fhir`,
  `tool=get_patient_summary`, and rendered the structured card — prior
  behavior confirmed intact after the question-trim fix.
- **Structured:** a real Patient Data lookup with a deliberately
  space-padded ID returned the correct real patient (proving the trim
  fix); a real Claims/SynPUF lookup returned the correct real
  beneficiary.
- **Workflow:** a real Policy + Synthetic FHIR combined run showed
  "No human review was required for this request.", full policy/
  structured separation, "Evidence validation passed with no issues.",
  and the safety disclaimer — confirmed **no** review row was created
  (`review_cases` stayed at 4), matching the directive's "avoid creating
  review unless intentionally requested."
- **Reviews:** the queue's "All statuses" view showed all 4 existing
  Slice 6 rows in correct FIFO order with bounded fields only; a
  terminal `REJECTED` case's detail page rendered full metadata,
  evidence snapshot, and 2-event audit history correctly, with decision
  controls absent (not merely disabled) and the Sidebar's "Reviews" item
  correctly highlighted via the nested-route fix above.
- **Browser/network:** no CORS errors, no unexpected console errors
  across the entire smoke-test session (the only console entries were
  benign, self-resolving `AbortController`-driven `/live` aborts from
  `useSystemStatus.ts`'s own deliberate cancel-and-refetch pattern).

**Production invariants:** confirmed unchanged before and after every
live action this slice performed — Qdrant 39; SynPUF 15/219/732/29/848;
FHIR 5/177/187/234/1341/865/116; Review 4 cases / 8 events (Slice 6's
own verification rows, intentionally never touched or added to this
slice, since the Evidence Workflow smoke test deliberately used a clean
request that does not trigger review creation).

**Tests:** 13 new (`Sidebar.test.tsx` ×6, `SystemOverview.test.tsx` +1,
`ReviewQueue.test.tsx` +1, `ReviewDetail.test.tsx` +3, `Workflow.test.tsx`
+1, `PatientData.test.tsx` +1) — each added only for a genuine gap this
audit actually found, not for count's sake. Full suite: 284 passed, 0
failed (was 271 before this slice). `npm run typecheck`, `npm run lint`,
and `npm run build` all clean; backend full suite unaffected (817
passed, 0 failed, zero backend files touched); `ruff check .`/`ruff
format --check .`/`pip check`/`git diff --check` all clean.

**Roadmap boundary (explicit):** the Analytics/Evaluation dashboard is
**NOT implemented in this slice** — it remains Phase 15, per this
slice's own directive. The 9 population-level aggregate FHIR/SynPUF
tools remain unexposed anywhere in the frontend until that phase.
Authentication remains entirely outside this project's current scope —
`reviewer_id` continues to be an explicitly non-authoritative,
caller-supplied string, and no login/session/credential system of any
kind exists or was added.

**Known remaining frontend gaps (not fixed in this slice, none blocking):**
the `.validationError` 3-line CSS rule remains duplicated across 4 files
(deliberately left as-is — see "Shared-component consolidation" above);
no automated end-to-end/E2E test runner exists in this project — all
frontend tests are component-level (Vitest + RTL), and all cross-page/
real-backend verification in every slice has been manual/live rather than
scripted. (Slice 7's note that tablet-width verification for pre-existing
pages relied only on each originating slice's own prior check was closed
by Slice 8's fresh full 3-breakpoint re-verification with live data across
all 8 routes — see the Phase 14 Final Checkpoint below.)

## Slice 8 — Final Frontend Checkpoint

Slice 8 added no product features. It performed a final, no-scope-creep
audit of the completed 8-route frontend and closed the one open item
Slice 7 had flagged, then produced the single Phase 14 checkpoint commit.

**Re-confirmed audits (no changes required):** safety/terminology
boundaries across all pages (synthetic-data notices, the
human-review-is-not-clinical/coverage-approval disclaimers, the
cross-dataset non-linkage statement on the Assistant page); no page
performs or requests financial, credential, or account actions; every
network call still routes through `lib/api/client.ts`'s single `request()`
helper (re-confirmed zero raw `fetch()` calls outside it); each page's
readiness policy continues to gate submission according to the dependency
it actually needs (Qdrant for Ask CareFlow/Workflow policy leg, Postgres
for Patient Data/Claims/Workflow structured leg/Reviews, the Assistant
page remaining permissive except while checking or fully unavailable).

**Fresh verification performed in this slice:** a bounded live smoke test
across all 8 routes against a running backend (policy question, FHIR
patient lookup, SynPUF beneficiary lookup, an unsupported/abstained
question, a combined workflow request with and without explicit review
requested, the review queue and a review detail approve/reject/revision
flow); a full responsive re-check at desktop, 768px tablet, and 375px
mobile widths for all 8 routes using real backend data — this is the
fresh, direct re-verification that closes the gap Slice 7 had explicitly
noted (tablet-width checks for the 7 pre-existing pages previously relied
on each originating slice's own earlier verification rather than a fresh
cross-page pass); a spot-check of keyboard focus order and `aria-live`
region announcements on the Assistant, Workflow, and Review Detail pages,
including confirming the 64-character SHA-256 evidence fingerprint and
multi-line audit-event entries wrap correctly without horizontal overflow
at 375px.

### Phase 14 Final Checkpoint

**Routes shipped (8):** `/` (System Overview), `/ask` (Ask CareFlow —
policy Q&A), `/patients` (Patient Data — Synthea FHIR), `/claims`
(Claims — CMS SynPUF), `/assistant` (CareFlow Assistant — intelligent
router), `/workflow` (Multi-Agent Policy + Structured Workflow, with
optional human-review request), `/reviews` (Review Queue), and
`/reviews/[reviewId]` (Review Detail — approve/reject/revision-requested).

**Major capabilities:** live/ready dependency status with an
optional-vs-required distinction (Postgres and Qdrant required, Redis
optional and never affecting overall status); direct policy Q&A over the
synthetic Medicare policy corpus with citations; direct structured lookups
against the synthetic Synthea FHIR and CMS SynPUF datasets, each rendered
through shared record/field/empty-state primitives; a natural-language
router that classifies a free-text question to a route/tool without the
caller choosing one, while explicitly refusing cross-dataset identity
linkage; a bounded multi-agent workflow that can combine a policy answer
and a structured lookup behind one deterministic validator, never implying
coverage/eligibility/medical-necessity/claim-approval; an optional
human-review request on any workflow submission, backed by a real
pending/approved/rejected/revision-requested state machine with
optimistic-concurrency conflict handling and a durable evidence
snapshot/fingerprint per review.

**Test results:**
- Frontend (Vitest + RTL): 284 passed, 0 failed.
- Backend regression (pytest): 817 passed, 166 skipped (Docker-dependent
  integration tests skipped when their service isn't running locally),
  0 failed.
- Production build (`next build`): succeeded, 0 errors, 0 warnings.

**Data invariants (unchanged by this slice, re-confirmed, not mutated):**
Qdrant policy corpus — 39 chunks. CMS SynPUF — 15 beneficiaries, 219
carrier claims, 732 carrier claim lines, 29 outpatient claims, 848
outpatient claim lines. Synthea FHIR — 5 patients, 177 encounters, 187
conditions, 234 observations, 1341 observation components, 865 procedures,
116 medication requests. Review store — 4 review cases, 8 audit events.

**Safety boundary (unchanged, re-confirmed):** FHIR and SynPUF data are
never joined or cross-referenced by patient/beneficiary identity in any
UI surface, request payload, or backend route; the actual enforcement
point remains the request schema itself (a route accepts only its own
dataset's identifier shape and tool registry), not a runtime
cross-dataset check. Human review approval/rejection is scoped
exclusively to "accepted for the CareFlow application workflow" and is
never rendered or worded as a coverage, claim, medical-necessity, or CMS
determination. No authentication exists anywhere in the frontend;
`reviewer_id` is an explicitly non-authoritative, caller-supplied string.

**Known limitations carried forward:** no authentication or authorization
of any kind; no automated end-to-end/E2E test runner (all automated
coverage is component-level); the small `.validationError` CSS rule
remains intentionally duplicated across 4 files rather than extracted;
Redis is present only as an optional performance cache and is never
exercised by any frontend flow.

**PHASE 14 COMPLETE.**
**NEXT: Phase 15 — Evaluation / Analytics Dashboard.**
**Phase 15 has NOT started.**
