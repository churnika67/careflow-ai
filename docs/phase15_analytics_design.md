# Phase 15 — Evaluation / Analytics Dashboard design

## Slice 1 — Foundation + backend contract audit

Slice 1 built the smallest possible backend contract for two independent,
read-only evidence domains, a foundation frontend shell that proves that
contract end to end against real data, and this document. It added no new
production capability beyond that: no charting, no new tuning surface, no
patient-level analytics.

### 1. Phase 12 artifact audit

Phase 12 (`evaluation/` package, `artifacts/evaluation/`,
`docs/evaluation/`) already built reproducible, artifact-backed evaluation
infrastructure covering retrieval, chunking, threshold/abstention,
deterministic citation wiring, latency, and an isolated reranker
comparison. Slice 1 read every relevant module and artifact directly
(never from memory) before writing any code. Key structural facts:

- `evaluation/run_retrieval_eval.py::evaluate()` is the shared low-level
  engine reused unmodified by `run_experiment.py` (Slice 2),
  `chunking_experiment.py` (Slice 3), and `threshold_experiment.py`
  (Slice 4); `latency_experiment.py` (Slice 5) and
  `reranker_comparison.py` (Slice 6) measure directly instead.
- Every experiment artifact lives at
  `artifacts/evaluation/<experiment_id>/`, written atomically by
  `evaluation/artifacts.py::write_experiment_artifacts()` — a run that
  fails partway leaves no directory at all, and an existing
  `experiment_id` is never overwritten, appended to, or deleted.
- `experiment_id = f"{git_commit[:8]}_{config_hash}"` for config-hash-
  driven experiment types, or a fixed descriptive name for aggregates
  (`eb59bc90_chunking_grid`, `eb59bc90_reranker_comparison`,
  `eb59bc90_threshold_sweep_development`/`_held_out`) and a
  timestamp-suffixed name for latency runs (latency is explicitly not
  meant to be byte-for-byte reproducible).
- `config.json` records dataset identity, embedding/reranker model +
  revision, chunk size/overlap, retrieval/rerank configuration, evidence
  threshold, generation provider, git commit, and an explicit
  `working_tree_clean`/`modified_files`/`untracked_files` disclosure
  (Phase 12 was developed with a dirty working tree throughout — every
  artifact says so honestly rather than implying a clean-checkout
  reproduction). There is no `random_seed` field: the pipeline
  (BM25/cosine/RRF) is fully deterministic, so a seed would carry no
  meaning.
- `evaluation/claim_governance.py` provides `parse_markdown_table` and
  `validate_claim_matrix`/`validate_gap_registry` — pure, dependency-free
  functions Slice 1's backend reuses directly (see §17) rather than
  re-implementing markdown parsing or hardcoding numbers that could drift
  from the source doc.

### 2. Evaluation datasets

Two datasets, grounded against the identical 39-chunk production corpus
(fingerprint `1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2`):

- **Development/regression** (`docs/evaluation/golden_retrieval_v1.json`):
  32 cases (25 positive, 7 negative). **Not independent** — 8 of 32 cases
  reuse Phase 3–6 development questions, and the set has been repeatedly
  inspected while building the retrieval pipeline.
- **Held-out** (`docs/evaluation/golden_retrieval_heldout_v1.json`): 12
  cases (10 positive, 2 negative), frozen at Phase 12 Slice 1 with a
  checked SHA-256, built exclusively from the 20 of 39 chunks never used
  as development evidence, **before** any comparative experiment ran
  against it.

Required wording: **"project-authored held-out engineering evaluation."**
Never "independent benchmark," "external benchmark," or "clinical
benchmark," for either dataset. The Analytics dashboard displays each
dataset's own `limitation` string verbatim in its card — see
`DatasetSummary.limitation` in `backend/app/analytics/models.py`.

### 3. Canonical snapshot selection

No single global "latest" artifact pointer exists anywhere in the
repository. Canonicity is instead established **per conclusion area** by
the "Artifact provenance" table in `docs/evaluation/phase12_claim_matrix.md`
(built by Phase 12 Slices 6–8), which this slice treats as authoritative
rather than inventing a new rule:

| Conclusion area | Canonical experiment_id |
|---|---|
| Development retrieval baseline | `eb59bc90_774ea9a697a1` |
| Held-out retrieval baseline | `eb59bc90_a223469082ce` |
| Chunking comparison | `eb59bc90_chunking_grid` |
| Threshold/abstention/citation sweep | `eb59bc90_threshold_sweep_development` / `_held_out` |
| Latency (all boundaries) | `eb59bc90_latency_1790202561` (named explicitly in `phase12_final_report.md` §8, even though two later re-runs of the same live suite, `_1790347472` and `_1790348527`, also exist on disk) |
| Causal reranker quality/latency trade-off | `eb59bc90_reranker_comparison` — supersedes the Slice 2 baseline artifacts for this specific question (depth-5 vs depth-10 candidate-pool confound) |

These IDs are hardcoded as named module-level constants in
`backend/app/analytics/snapshot.py` — never accepted as a request
parameter (see §7).

### 4. Metric definitions surfaced

- **Hit@1/3/5, MRR@5**: positive cases only; `Hit@k = hits/total` at rank
  k; `MRR@5` treats a miss/rank>5 as 0. Every rate ships with its raw
  numerator/denominator alongside it in the underlying artifact.
- **Citation metric** (`CITATION_REFERENCES_EXPECTED_EVIDENCE`): among
  positive cases that were actually answered (not abstained), does at
  least one validated citation's `chunk_id` fall within the case's
  expected evidence? A deterministic exact-membership check — **never**
  "citation accuracy," entailment, or completeness. Exact source:
  `evaluation/threshold_experiment.py::citation_expected_evidence()`.
- **Threshold sweep**: frozen grid `[0.40, 0.45, 0.50, 0.55, 0.60]`.
  Production threshold is `0.60` (`backend/app/core/config.py`'s
  `rag_min_score`). 27 case-level transitions observed across the 4
  adjacent threshold pairs, all monotonic answered→abstained, zero
  reversals. `cms-v1-032` (out-of-corpus, unsupported) still answers at
  every tested threshold including production's own (gate score
  ≈0.613495 at hybrid_reranked) — this is surfaced verbatim in the
  snapshot's `threshold.known_issue` field, sourced live from
  `per_query.jsonl`, not hardcoded.
- **Reranker comparison** (Slice 6 same-pool paired comparison, the
  authoritative causal source per §3): development 1 improved / 23
  unchanged / 1 degraded (aggregate metrics unchanged — masks an
  offsetting pair); held-out 2 improved / 8 unchanged / 0 degraded
  (Hit@3/Hit@5/MRR@5 improved, Hit@1 unchanged). Reranker latency
  ≈426–474ms median, ≈15.9–17.3x the hybrid candidate-retrieval stage
  median. **No winner or recommendation was selected; production
  reranker configuration is unchanged.**
- **Cost/token usage**: genuinely absent from the entire evaluation
  package — every artifact's `generation_provider` is `deterministic`,
  and the `OpenAIProvider` path (the only place a token could ever be
  spent) is never exercised by any Phase 12 evaluation run. The dashboard
  reports this as `cost_tokens.status = "not_evaluated"`, never a
  fabricated `0`.
- **Claim matrix**: exactly 4 statuses (`SUPPORTED`,
  `PARTIALLY_SUPPORTED`, `NOT_EVALUATED`, `OUT_OF_SCOPE`). Recomputed live
  at request time from `docs/evaluation/phase12_claim_matrix.md`'s actual
  markdown table via `evaluation.claim_governance.parse_markdown_table`,
  not hardcoded — confirmed 6/10/11/3 (total 30), matching
  `phase12_final_report.md`'s own corrected summary.
- **Gap registry**: 13 entries, loaded and validated live from
  `docs/evaluation/phase12_gap_registry.json` via
  `evaluation.claim_governance.validate_gap_registry` — confirmed 5
  `OPEN` / 4 `DOCUMENTED_LIMITATION` / 4 `OUT_OF_SCOPE_PHASE12`.

### 5. Runtime vs evaluation configuration drift (`EVAL-RUNTIME-CONFIG-DRIFT`)

The single most important caveat in the entire snapshot: the live
multi-agent runtime resolves to `retrieval_mode=dense`,
`rerank_enabled=false` in this environment, while every retrieval-quality
result in the snapshot was measured against hybrid retrieval with
reranking enabled. This gap is `OPEN`, not resolved by Phase 12, and not
resolved by this slice — the dashboard surfaces the exact warning text in
`EvaluationSnapshotResponse.provenance.runtime_config_drift_warning`
rather than letting a reader assume the two configurations match.

### 6. Population aggregate tool inventory

Phase 9's `TOOL_REGISTRY` (`backend/app/orchestration/tools.py`) already
contains 9 population-level aggregate tools (4 FHIR, 5 SynPUF) — no new
tool was created by this slice:

**FHIR** (`backend/app/repository/analytics.py`, reused unchanged):
`fhir_encounter_counts` (no args → `{class_code: count}` across all
patients), `fhir_condition_frequency`, `fhir_procedure_frequency`,
`fhir_medication_frequency` (each `top_n: 1..100` → a frequency table
across all patients).

**SynPUF**: `synpuf_claim_counts` (no args → `{claim_type: count}` across
all beneficiaries), `synpuf_payment_totals` (no args → per-type sum +
count), `synpuf_diagnosis_frequency`, `synpuf_procedure_frequency`,
`synpuf_hcpcs_frequency` (each `top_n`-bounded).

All 9 are plain, fixed, parameterized `GROUP BY`/`COUNT`/`SUM` SQL over
the entire structured table — no `WHERE patient_id=...` or
`WHERE beneficiary_id=...` filter anywhere in them, and no
`execute_sql`/dynamic-query path exists or will exist in this module (see
its own docstring). Safe for aggregate analytics as-is; Slice 1's new
`backend/app/analytics/structured.py` calls these same repository
functions directly (bypassing the orchestration classifier/tool registry,
since a bounded dashboard endpoint has no need for natural-language
routing).

### 7. Dataset boundary

FHIR and SynPUF are queried entirely independently in
`backend/app/analytics/structured.py`: `_load_fhir_overview` and
`_load_synpuf_overview` are separate functions, each touching only its
own dataset's tables, and neither function ever receives the other
dataset's data before the final response is assembled. No shared
identifier, no join, no cross-dataset longitudinal profile — verified by
`tests/test_analytics_api.py::test_structured_overview_returns_real_fhir_and_synpuf_aggregates_without_linkage`
(asserts neither block's JSON serialization contains a `patient_id` or
`beneficiary_id` field).

### 8. No patient-level analytics

Every aggregate this slice exposes is population-level (a count, a sum,
or a top-N frequency table) — never a single patient's or beneficiary's
own data. Individual-record lookups remain exclusively the job of the
existing Patient Data and Claims pages.

### 9. Backend API contract

Two endpoints, both `GET`, both read-only, neither accepting any request
body, path parameter, or query parameter that selects a file, table, or
experiment:

- `GET /analytics/evaluation/snapshot` → `EvaluationSnapshotResponse`
  (`backend/app/analytics/models.py`). Reads only the fixed canonical
  artifact files listed in §3, from disk. 503
  (`evaluation_snapshot_unavailable`) if any of them is missing or
  malformed.
- `GET /analytics/structured/overview` → `StructuredAnalyticsOverview`.
  Live Postgres aggregate queries via `app.repository.analytics`,
  unchanged. 503 (`structured_overview_unavailable`) if the database is
  unreachable.

This is deliberately the smallest coherent contract for a foundation
slice with no charts yet — not the 6+ granular
`/analytics/evaluation/{retrieval,reranker,thresholds,latency,claims}`
endpoints sketched as one option in the originating directive. Once a
later slice needs per-metric charting with independent loading/caching,
splitting `evaluation/snapshot` into narrower endpoints is a
straightforward, additive change; Slice 1 intentionally does not do that
work before it is needed.

### 10. Security model — no client-supplied paths

`backend/app/analytics/snapshot.py` has exactly one public function,
`load_evaluation_snapshot()`, which takes **no arguments**. Every artifact
path it reads is built from a literal, named module-level constant (an
`experiment_id` string hardcoded in source) — there is no
`experiment_id`/`path` request parameter anywhere in this module's public
surface, so there is no path-traversal surface to defend: the simplest
way to make `../` or an absolute-path override impossible is to never
parse a path from a request at all. `tests/test_analytics_snapshot.py`
asserts this structurally (enumerates the module's public functions and
asserts there is exactly one, with an empty parameter list) rather than
only testing specific malicious inputs. `backend/app/repository/analytics.py`
(reused for the structured endpoint) was already bounded before this
slice — no `execute_sql`/dynamic table/column name path exists there
either.

Environment metadata inside artifact `environment.json` files was
reviewed and contains only Python/OS/CPU facts and pinned package
versions — no absolute paths, usernames, or secrets; nothing needed
sanitizing before being served.

### 11. Snapshot vs live provenance

Every response names its own provenance explicitly:
`EvaluationSnapshotResponse.source = "phase12_artifact_snapshot"` (a
curated read of pre-existing, already-persisted files — nothing
re-executes) vs. `StructuredAnalyticsOverview`'s `fhir.source` /
`synpuf.source = "live_structured_query"` (a fresh SQL query against the
current Postgres data on every request). The frontend never blends the
two without this label being visible in the underlying contract.

### 12. Docker/deployment fix

`backend/Dockerfile` previously copied only `backend/` and `ingestion/`
into the image — the analytics endpoints could not have worked in the
deployed container at all without `artifacts/evaluation/`,
`docs/evaluation/`, and `evaluation/` (for its dependency-free
`claim_governance` module) also being copied. Two real bugs were found
and fixed while verifying this end to end against the actual running
Docker stack (not just local pytest):

1. **Missing directories** — fixed by adding the three `COPY` lines.
2. **Permission denied** — `evaluation/artifacts.py` writes each
   experiment directory via `tempfile.mkdtemp()`, which is mode `0700`
   on the host (correct there — only the developer who ran the
   experiment needs access). `COPY` preserves that mode verbatim, and
   the container runs as the unprivileged `careflow` user, not root, so
   every artifact read failed with `PermissionError` until a
   `RUN chmod -R a+rX ./artifacts/evaluation ./docs/evaluation` was added
   — relaxing only the container's own copy, never touching the host
   repository's file modes.
3. **Path resolution** — `snapshot.py` originally derived its artifact
   root from `Path(__file__).resolve().parents[3]`, which is correct
   under an *editable* install (this repo's own local dev setup, see
   README.md's "Native backend development") but resolves to somewhere
   under `/usr/local/lib/python3.12/site-packages/` under the
   Dockerfile's real (non-editable) `pip install --no-deps .` — silently
   pointing at the wrong directory. Fixed by switching to CWD-relative
   paths (`Path("artifacts/evaluation")`), matching the exact convention
   `evaluation/run_experiment.py` already established; this resolves
   correctly under the container's `WORKDIR /app`, under local `pytest`
   run from the repository root, and under native `uvicorn` run from the
   repository root per the documented local dev command.

All three were caught only by testing against the actual rebuilt Docker
container (`docker compose build backend && docker compose up -d backend`)
and re-verifying `GET /analytics/evaluation/snapshot` returned real data
over `http://localhost:18000`, not merely by the local pytest suite
(which used an editable install and therefore never exercised bug #3, and
ran as the host user and therefore never exercised bug #2).

### 13. Readiness

Two independent readiness policies, matching the actual dependency each
endpoint has:

- `lib/evaluationSnapshotReadiness.ts`: permissive — allowed whenever the
  API process itself is reachable (`ready` or `degraded`, regardless of
  which dependency is degraded), blocked only while `checking` or fully
  `unavailable`. The snapshot endpoint reads static files; it never
  touches Qdrant, Postgres, or Redis, so gating it on either would hide
  evidence that has nothing to do with that dependency.
- `lib/structuredAnalyticsReadiness.ts`: Postgres-only, identical rule to
  `lib/reviewReadiness.ts` — blocked only when Postgres is reported
  unavailable. Qdrant and Redis are never considered.

### 14. Not-evaluated semantics

`components/analytics/MetricValue.tsx` is the single shared rendering
rule: a `null`/`undefined` metric value renders as an explicit, styled
"Not evaluated" (or a caller-supplied explanatory label, e.g. the
cost/token panel's own note), never as `0%`, `0 ms`, or a bare `N/A`. The
backend enforces the same discipline one layer down — every passthrough
metric block (`ArtifactMetricBlock.metrics`, `CitationMetric`,
`ThresholdInfo.known_issue`) is typed `dict[str, Any]` specifically so a
genuine JSON `null` in the source artifact is never coerced to a Python
`0` or an empty string while being reshaped into the response.

### 15. Accessibility

`/analytics` uses real semantic headings (`<h1>`/`<h2>`/`<h3>`), a real
`<nav aria-label="Primary">` (unchanged, shared with every other page),
native `<table>`/`<caption>`/`<th scope="col">` for every frequency
table, `<dl>`/`<dt>`/`<dd>` for the claim-matrix/gap-registry counts, and
`aria-live="polite"` regions around both panels' loading/error/content
states — matching every existing page's established pattern. No status
is color-only: every badge/error state pairs a color with explicit text.
This is a requirement for every future Phase 15 slice too — when charts
are added, each must ship a textual/table equivalent alongside it, not
instead of the pattern established here.

### 16. Responsive behavior

Verified at desktop, 768px, and 375px against the live backend (real
data, not a mock) with zero horizontal overflow (`document.documentElement
.scrollWidth === document.documentElement.clientWidth` at both narrower
widths). Frequency tables are wrapped in their own `overflow-x: auto`
container (`.tableScroll`) so a wide table scrolls internally rather than
the page scrolling horizontally.

### 17. Tests

Backend (`tests/test_analytics_snapshot.py`, `tests/test_analytics_api.py`):
canonical snapshot load against the real repository artifacts (not a
mock — proves the hardcoded experiment IDs actually exist and parse),
not-evaluated-stays-null for a zero-count category, the "no
`experiment_id` parameter exists" structural security check, missing
artifact → `EvaluationArtifactMissingError`/503, malformed JSON →
`EvaluationArtifactMalformedError`/503, a required field missing →
malformed error, resolved-path-never-escapes-root, GET-only (405 on
POST), and (behind `CAREFLOW_ANALYTICS_INTEGRATION=1`, matching this
repo's existing live-test gating convention) a real structured-overview
fetch with a dataset-linkage assertion and a before/after invariant-count
assertion proving zero mutation. All pre-existing Phase 1–14 backend
tests remain unmodified and passing.

Frontend (`components/Analytics.test.tsx`, plus `Sidebar.test.tsx`
updates): both panel headings render, a loading state renders before the
backend responds, real claim-matrix/gap counts render from a mocked
snapshot, a calm error+retry renders when either endpoint returns 503,
a not-evaluated citation rate renders as text (never `0%`), FHIR and
SynPUF render as two visibly separate sections, and a frequency table
uses real `<table>` semantics. `Sidebar.test.tsx` was updated to reflect
that Analytics is now a real, active link (its old
"disabled-placeholder" test is gone, replaced with an active-state test
matching every other functional page).

### 18. Scope confirmation

No production threshold change. No retrieval tuning. No new evaluation
dataset. No LLM-as-judge or clinical-correctness scoring of any kind. No
FHIR/SynPUF patient linkage. No arbitrary SQL or arbitrary artifact path
acceptance anywhere. No experiment-execution endpoint. No authentication
work. No deployment work beyond the Dockerfile fix required to make the
already-scoped feature function at all. No Phase 16 work.

### 19. Known limitations carried forward

Everything Phase 12 already documented as a limitation remains a
limitation — this slice did not resolve any of it, only made it visible:
small held-out sample, small policy corpus, synthetic structured data at
small scale, local-machine-only latency, the Slice 2 candidate-depth
confound (superseded by Slice 6 for the reranker question), and the
open runtime/evaluation configuration drift. Additionally, specific to
this slice: no chart library or visualization exists yet (deliberately —
see the originating directive's explicit instruction not to add one
before the contract, provenance, and accessibility foundation was
proven); the two endpoints are not yet split into narrower per-metric
routes (see §9); and structured aggregate `top_n` is fixed at 5 in the
frontend (the backend repository functions support up to 100 — a future
slice can expose this as a control once charting exists to make it
useful).

### 20. Recommended Slice 2

Build the actual charts (retrieval Hit@k/MRR@5 by mode and category,
reranker rank-change visualization, threshold curve, latency
distributions) reading from this same snapshot contract, splitting
`/analytics/evaluation/snapshot` into narrower endpoints only if a
specific chart's data volume or independent-loading need justifies it —
not before.

## Slice 2 — Evaluation visualizations + evidence exploration

Slice 2 turned Slice 1's foundation shell into a full evaluation
dashboard, reading the same `/analytics/evaluation/snapshot` contract
Slice 1 already proved end to end, with two small, justified extensions
to that contract (below). No new evaluation was run; no production
configuration changed; no metric was recalculated for presentation.

### 21. Documentation correction (Slice 1)

Slice 1's report and this doc previously said "8 population-level
aggregate tools." The correct count, re-verified directly against
`backend/app/orchestration/tools.py`, is **9**: 4 FHIR
(`fhir_encounter_counts`, `fhir_condition_frequency`,
`fhir_procedure_frequency`, `fhir_medication_frequency`) and 5 SynPUF
(`synpuf_claim_counts`, `synpuf_payment_totals`,
`synpuf_diagnosis_frequency`, `synpuf_procedure_frequency`,
`synpuf_hcpcs_frequency`). §6 above is corrected accordingly. The tool
registry itself was not modified for this correction — it was always 9;
only the prose miscounted.

### 22. Backend contract audit and the two extensions made

Before writing any frontend code, the real `GET
/analytics/evaluation/snapshot` response was fetched from the live
Docker backend and inspected field by field (not assumed from Slice 1's
own models). It already contained everything needed for retrieval
quality (exact Hit@k/MRR@5 with numerator/denominator per mode per
dataset), reranker rank-change counts and quality deltas, the full
threshold sweep grid and known-issue detail, the full latency artifact
(retrieval/reranker stages, structured tools, multi-agent workflows,
review policy/persistence), citation rates for both `hybrid` and
`hybrid_reranked` per dataset, and claim-matrix counts.

Two fields were genuinely missing and were added — both minimal,
sourced from data the backend was already reading (never a new file
read, never new I/O):

1. **`GapRegistrySummary.entries: list[GapEntry]`** — Slice 1 only
   returned per-status *counts* for the 13-entry gap registry. The
   directive's "Evaluation Gaps" section requires naming individual gaps
   (routing accuracy, production-load latency, reranker false-abstention,
   the unsupported-high-similarity case) — impossible from counts alone.
   `_load_gaps()` already parsed and validated the full registry via
   `evaluation.claim_governance.validate_gap_registry()`; it previously
   discarded everything but the status tally. Each `GapEntry` carries
   `gap_id`, `title`, `category`, `status`, `evidence`,
   `impact_on_claims` — the same fields already present in
   `docs/evaluation/phase12_gap_registry.json`, nothing invented.
2. **`Provenance.generation_provider: str`** — the Evaluation Overview
   section needs to state the generation provider (`deterministic`).
   `_load_provenance()` already reads the reranker-comparison
   `config.json`, which already has this field; it was simply not copied
   into the response before.

No other endpoint was added or changed. `GET
/analytics/structured/overview` is byte-for-byte the Slice 1 contract —
no new aggregate query, no new field, per the directive's explicit
instruction not to expand structured analytics in this slice.

### 23. Charting decision

No chart dependency was added. Per the directive's preference order,
this dashboard needed exactly two visual shapes — a small labeled
comparison across a handful of categories (retrieval modes, reranker
outcomes) and a small table of measurements — both of which a few dozen
lines of semantic HTML/CSS render correctly, accessibly, and without a
runtime dependency:

- **`AccessibleBarChart`**: a `<div>`-based horizontal bar row per
  category. The numeric value is always rendered as ordinary DOM text
  next to the bar (`<span className={styles.value}>{row.displayText}</span>`)
  — never conveyed by bar length or color alone, and never a separate
  hidden table a screen reader has to find. A `null`/`undefined` value
  renders a flat, explicitly muted, zero-width bar labeled "Not
  evaluated," never a bar that could be misread as a measured zero.
- **`ComparisonTable`** / **`LatencyTable`**: real `<table>` elements
  (`<caption>`, `<th scope="col">`/`<th scope="row">`) for the
  mode-by-metric and stage-by-latency comparisons — the natural, already
  fully accessible shape for this data, no chart needed at all.

A real charting library (Recharts, Chart.js, D3, etc.) would have added
a runtime dependency, bundle weight, and an SVG/canvas accessibility
burden (needing its own textual fallback) to render four bars and a few
tables — not justified at this scale. If a future slice adds a genuinely
continuous visualization (e.g. the 5-point threshold curve plotted as a
line, or a distribution plot), that specific need should be re-evaluated
against this same preference order then, not preemptively solved now.

### 24. Dashboard information architecture

`/analytics`'s Evaluation Snapshot panel is now organized as, in order:
Evaluation Overview, Dataset Limitations, Retrieval Quality, Reranker
Analysis, Reranker Quality/Latency Tradeoff, Threshold Behavior, Latency,
Citation Expected-Evidence Match, Claim Matrix, Open Evaluation Gaps,
Cost/Token Usage, Evaluation Provenance, Known Limitations — matching the
directive's suggested order exactly. Structured Analytics remains its
own separate panel below, unchanged from Slice 1, with its own
independent readiness/loading/error state — evaluation metrics and
synthetic population counts are never mixed into one section.

### 25. Evaluation Overview

Shows exactly the fields the directive asked for and nothing invented:
development/held-out case counts, positive/negative splits, production
threshold, and generation provider — all read directly from the real
snapshot response, not hardcoded. Explicitly states "No overall accuracy,
safety, or readiness score is computed anywhere in this project" next to
the figures, and the two datasets are never combined into a single row.

### 26. Dataset limitations

Rendered as its own two-card row directly under the overview (not behind
a tooltip): development set's non-independence and reused questions;
held-out set's project-authored/frozen/small-sample nature — both
sourced verbatim from `DatasetSummary.description`/`.limitation`, the
same fields Slice 1 already returned.

### 27. Retrieval quality

For development and held-out separately: a headline Hit@1-by-mode bar
chart (dense/BM25/hybrid/hybrid+reranker) plus a full comparison table
with all four metrics (Hit@1/3/5, MRR@5) and exact numerator/denominator
where the artifact provides one (MRR@5 has none, by design — see Slice 1
§4). Metric definitions are stated inline, verified against
`evaluation/metrics.py`/`evaluation/threshold_experiment.py` during the
Slice 1 audit and re-confirmed unchanged this slice, and explicitly
never called answer correctness. The two datasets' tables are visually
and structurally separate (`RetrievalQualitySection` never merges their
rows or averages a metric across them), with an explicit sentence stating
why.

### 28. Reranker visualization

`RerankerAnalysisSection` shows the authoritative Slice 6 same-pool
comparison's `rank_change_counts` (development 1/23/1, held-out 2/8/0 —
read live from the snapshot, not hardcoded) as a plain comparison table,
with an explicit "no winner is declared" sentence. `RerankerLatencyTradeoffSection`
places the quality summary directly next to the measured latency cost
(hybrid-candidates-with-gate vs. reranker-only median, plus the computed
ratio) — quality is never shown without its latency cost alongside it,
and the wording never says reranking "is better" or "should be enabled."

### 29. Threshold visualization

Shows the frozen 5-point grid, the production threshold, and the
observed transition count as plain text/table content — deliberately no
slider, no "apply" control, and no interactive element that could be
mistaken for a live production setting. The known `cms-v1-032` issue is
its own visually distinct card (a left-border accent paired with the
heading text "Known issue," never color alone) with the exact gate score
read from `per_query.jsonl` at request time (`0.613495`, matching the
audited value) and an explicit "not a clinical failure" sentence.

### 30. Latency

Six separate `LatencyTable`s (retrieval/reranker stages × 2 datasets,
structured tools, multi-agent workflows, review policy, review
persistence) — deliberately not merged into one table, since they measure
different boundaries. Every cell renders through `MetricValue`, so a
missing stage would show "Not evaluated," never a blank or a 0. The
section states the local-machine/service-level limitation once, up
front, rather than repeating it per table.

### 31. Citation expected-evidence match

A single comparison table (rows: development/held-out; columns:
hybrid/hybrid+reranker) built from the exact rates re-read from the live
snapshot during this slice's audit (development 95.5%/95.5%, held-out
70.0%/77.8%) — the held-out `hybrid_reranked` rate is not the same as
Slice 1's `77.8%` was for `hybrid`; both are shown because Slice 1's
report had only surfaced one arm. The definition and its explicit "does
not establish entailment/completeness/correctness" boundary are restated
directly in this section, and a test
(`never labels the citation metric as accuracy, correctness, or an
entailment score`) asserts none of those words appear here.

### 32. Claim matrix

The four counts (6/10/11/3, total 30) render as a plain `<dl>`, exactly
as Slice 1 already showed them — Slice 2 did not add a percentage, a
score, or a "pass rate." Per the directive's explicit fallback (§22 of
the Slice 2 directive), individual claim rows are **not** exposed by this
snapshot (see §9 above — extending `claim_matrix` with all 30 rows'
worth of columns was judged not worth the response-size and endpoint-
surface cost for a foundation dashboard), and the UI says so directly
rather than inventing per-claim detail.

### 33. Evaluation gaps

`GapList` groups the now-exposed 13 entries by status (Open/Documented
limitation/Out of scope for Phase 12), each entry showing its title, ID,
category, and evidence text verbatim from the registry. Status is
conveyed by a left-border accent plus an explicit text heading — never
color alone. `EVAL-RUNTIME-CONFIG-DRIFT` gets its own highlighted,
non-collapsible card directly above the grouped list (not merely one row
among the other four `OPEN` entries), restating the exact warning that
the live runtime (`dense`/no-rerank) differs from every retrieval-quality
result in this snapshot (`hybrid`+rerank) — so a reader cannot miss it or
mistake historical evaluation evidence for a description of the current
runtime.

### 34. Cost/token usage

Unchanged in substance from Slice 1: `MetricValue` renders an explicit
"Not evaluated," paired with the exact note explaining why
(`DeterministicProvider`, no LLM ever exercised) — never an empty chart,
never a fabricated `$0.00`.

### 35. Evaluation provenance

A `<details>`/`<summary>` block (native, keyboard-operable, no JS
disclosure widget) listing exactly the fields the response actually
returns: the four canonical experiment IDs, corpus fingerprint, chunk
size/overlap, evidence threshold, retrieval candidate k / RRF k,
embedding model+revision, reranker model+revision, and generation
provider. Verified directly in the real browser (`details.textContent`
after programmatically opening it) to contain no local filesystem path
and no API-key-shaped string — consistent with `Provenance`'s Pydantic
model never including `environment.json`'s contents or any
`git_commit`/`timestamp`/`modified_files` disclosure fields in the first
place.

### 36. Structured Analytics regression

Not expanded in this slice, as instructed. Re-verified end to end against
the real rebuilt Docker backend: real FHIR encounter/condition/procedure/
medication aggregates and real SynPUF claim/diagnosis/procedure/HCPCS
aggregates render, visually and structurally separate from each other and
from the Evaluation Snapshot panel, with independent
loading/error/readiness state (an evaluation-snapshot failure never hides
structured analytics and vice versa — both panels' `useEffect`s and
`SnapshotState`/`StructuredState` unions remain fully independent,
unchanged from Slice 1's architecture).

### 37. Accessibility

Every new visual element ships a textual/table equivalent by
construction, not as an afterthought: bar chart values are DOM text,
comparison/latency tables are real `<table>`s, gap/claim counts are
`<dl>`s, provenance is a native `<details>`. Status is never color-only
(gap entries and the threshold known-issue card pair a left-border accent
with an explicit text heading). All new headings (`<h3>`/`<h4>`) nest
correctly under the existing `<h2>` panel headings.

### 38. Responsive behavior

Verified at desktop, 768px, and 375px against the live backend with real
data: `document.documentElement.scrollWidth === document.documentElement
.clientWidth` at both narrower widths (zero page-level horizontal
overflow), including with the full set of new content — long experiment
IDs, the 64-character corpus fingerprint, gap evidence paragraphs, and
every comparison/latency table. Wide tables scroll internally via their
existing `.tableScroll`/`ComparisonTable`'s own `overflow-x: auto`
wrapper, never the page.

### 39. Real verification

Against the rebuilt Docker backend (`http://localhost:18000`), every
section's rendered numbers were cross-checked against the live JSON
response: Hit@1 by mode, reranker rank-change counts (1/23/1,
2/8/0), reranker latency (426.34ms vs. 26.77ms development, ≈15.9x),
threshold known-issue gate score (`0.613495`), citation rates (95.5% /
95.5% development, 70.0% / 77.8% held-out), claim matrix (6/10/11/3),
gap counts and all 13 individual entries (including routing accuracy,
production-load latency, and the reranker false-abstention case),
corpus fingerprint, and generation provider — all matched exactly. Bar
fill widths and colors were additionally confirmed via computed style
inspection (`getComputedStyle`) after a screenshot rendering artifact
made them visually ambiguous at small scale — the underlying DOM/CSS was
correct (88%/96%/etc. widths, the theme's primary blue).

### 40. Known limitations

No chart library (deliberate, see §23) — a future slice revisiting this
decision should re-run the same preference-order analysis against the
specific new visualization need, not assume the answer carries over.
Claim-matrix detail remains aggregate-only (see §32). Structured
Analytics remains a Slice-1-scope foundation overview, unchanged. All
Phase 12 evaluation limitations remain open and undiminished by this
slice's work — visualizing evidence does not resolve any of it.

## Slice 3 — Population-level structured healthcare analytics

Slice 3 turned Slice 1-2's Structured Analytics foundation panel into a
full population-level analytics surface for both synthetic datasets,
using the same 9 aggregate tools (4 FHIR, 5 SynPUF — see §21) that
already existed. No patient- or beneficiary-level data is shown anywhere,
and FHIR/SynPUF remain fully unlinked.

### 41. Structured contract audit

Before writing any frontend code, `GET /analytics/structured/overview`
was fetched from the live Docker backend and inspected field by field.
Findings, verified against `backend/app/repository/analytics.py`'s
actual SQL, not assumed:

- `encounter_counts_by_class` groups by `fhir_encounters.class_code`
  (FHIR's `Encounter.class` — the setting of the encounter, e.g.
  ambulatory/emergency/inpatient) — **a complete distribution**, no
  `LIMIT`. Its 3 observed values (`AMB`, `EMER`, `IMP`) sum to the full
  177-encounter sample. The UI keeps the exact class-code strings as the
  label (never expanding them to invented English words) and states the
  grouping field by name ("by encounter class code").
- `claim_counts_by_type` / `payment_totals_by_type` likewise group by
  `synpuf_claims.claim_type` with no `LIMIT` — **complete distributions**
  (2 values: `outpatient`, `inpatient`), summing to the full 219-claim
  sample.
- `top_conditions`/`top_procedures`/`top_medications` (FHIR) each row
  carries `code`, `code_system`, `code_display`, `occurrences` — all four
  fields are genuinely present (Slice 1-2's UI had been dropping `code`
  and `code_system`; Slice 3 restores them).
- `top_diagnoses`/`top_procedures`/`top_hcpcs` (SynPUF) each row carries
  **only** the code column (`icd9_code`/`icd9_procedure_code`/
  `hcpcs_code`) and `occurrences` — genuinely **no description field
  exists** in these three tables' schemas. The UI shows the bare code and
  states explicitly that the backend provides no description, rather than
  omitting that fact silently or inventing one.
- `payment_totals_by_type[*].total_payment` is a real dollar amount
  (`synpuf_claims.claim_payment_amount`, `numeric(12,2)`, `SUM`'d),
  serialized as a JSON string (e.g. `"46010.00"`) because it is a Python
  `Decimal`. Genuinely a currency value — safe to format as USD.
- All 5 FHIR/SynPUF top-N queries are capped at `top_n=5`
  (`backend/app/analytics/structured.py`'s `_TOP_N`), confirmed **not**
  configurable by the client anywhere in this API.
- Nothing in the response before this slice stated the dataset's own
  size (patient/beneficiary count) — see §42.

### 42. Backend contract changes

One small, justified extension, matching the same pattern established in
Slice 2 (§22): two fields were genuinely unavailable and needed for the
directive's required "Dataset Overview" / "sample size context"
sections.

- **`FhirAggregateOverview.patient_count: int`** and
  **`SynpufAggregateOverview.beneficiary_count: int`** — a plain
  `SELECT count(*) FROM fhir_patients` / `synpuf_beneficiaries`, no
  parameters, no identifier column selected. Added as two small private
  functions (`_fhir_patient_count`, `_synpuf_beneficiary_count`)
  **local to `backend/app/analytics/structured.py`**, deliberately **not**
  added to `backend/app/repository/analytics.py` (the Phase 9 module
  backing the orchestration `TOOL_REGISTRY`) or to that registry itself —
  doing so would have made the documented "9 aggregate tools" count
  inaccurate. This keeps that count exactly true while still giving the
  dashboard the context it needs.
- **`FhirAggregateOverview.top_n: int`** / **`SynpufAggregateOverview.top_n: int`**
  — the actual `_TOP_N` constant the backend used for that response, so
  the frontend's "Top 5" wording is read from the response, never
  hardcoded/assumed.

`GET /analytics/evaluation/snapshot` is completely unchanged by this
slice.

### 43. Aggregate inventory (corrected count, re-confirmed)

**FHIR (4):** `fhir_encounter_counts`, `fhir_condition_frequency`,
`fhir_procedure_frequency`, `fhir_medication_frequency`.
**SynPUF (5):** `synpuf_claim_counts`, `synpuf_payment_totals`,
`synpuf_diagnosis_frequency`, `synpuf_procedure_frequency`,
`synpuf_hcpcs_frequency`. Total **9** — matching Slice 2's §21
correction exactly; the registry itself was not touched by this slice
either.

### 44. Information architecture

Structured Analytics now contains two large, clearly separate sections
(`FhirAnalyticsSection`, `SynpufAnalyticsSection`), each its own `<h3>`
inside its own card, in the directive's suggested order: Dataset
Overview, then each aggregate in turn (FHIR: Encounter Distribution,
Condition/Procedure/Medication Frequency; SynPUF: Claim Distribution,
Payment Totals, Diagnosis/Procedure/HCPCS Frequency), followed by one
shared Structured Analytics Limitations card. No chart ever combines
data from both datasets.

### 45. FHIR visualizations

- **Dataset Overview**: patient count (live, `patient_count`) and total
  encounters (derived client-side as the sum of
  `encounter_counts_by_class`'s own values — not a new backend field,
  since it's exactly recoverable from data already returned).
- **Encounter Distribution**: a bar chart plus an exact-count table,
  labeled "by encounter class code" and using the raw class-code strings
  — no invented full-word expansion of `AMB`/`EMER`/`IMP`.
- **Condition/Procedure/Medication Frequency**: each gets a bar chart
  (local-max-scaled, see §48) plus a 4-column table (code, code system,
  display, occurrences) — restoring the two columns Slice 1-2 had
  dropped. Every heading states "Top 5" and each has its own disclaimer
  sentence explicitly declining to interpret frequency as risk,
  prevalence, necessity, success, outcome, prescribing guidance, or a
  treatment recommendation, per the directive's explicit wording
  requirements for §11-13.

### 46. SynPUF visualizations

- **Dataset Overview**: beneficiary count (live, `beneficiary_count`)
  and total claims (derived client-side as the sum of
  `claim_counts_by_type`'s values).
- **Claim Distribution**: bar chart + table, by claim type, explicitly
  not framed as an approval rate or a utilization rate (neither concept
  exists in this data).
- **Payment Totals**: see §47.
- **Diagnosis/Procedure/HCPCS Frequency**: bar chart + 2-column table
  (code, occurrences only) — no description column, since none exists in
  the source data (see §41). The Diagnosis Frequency card states this
  explicitly. HCPCS Frequency's disclaimer explicitly declines to
  reframe a code count as a cost, medical-necessity, or coverage claim,
  per the directive's explicit §19 wording requirement.

### 47. Payment semantics

`payment_totals_by_type[*].total_payment` (a `Decimal`-as-string from
`SUM(claim_payment_amount)`) is formatted via a small `formatUsd()`
helper using `Number.toLocaleString('en-US', {style: 'currency', ...})`
at exactly 2 decimal places — the same precision the backend already
returns, never truncated, never given invented sub-cent precision. A
`null`/missing `total_payment` renders through the existing `MetricValue`
"Not evaluated" pattern, **never** silently becomes `$0.00` — verified by
a dedicated test that supplies `total_payment: null` and asserts
`$0.00` is absent while `Not evaluated` is present. A genuine numeric
`0` (not exercised by the current sample, since neither claim type has
zero total payment) would correctly render as `$0.00` under this same
logic, per the directive's explicit distinction between "missing" and
"genuinely zero."

### 48. Top-N semantics and chart scale

`top_n` stayed fixed at 5, per the directive's explicit instruction not
to add a 1–100 control just because the repository supports one. Every
frequency heading/table caption says "Top 5 <thing> codes" verbatim, and
the two genuinely complete distributions (encounter class, claim type)
are never conflated with the five genuinely-partial top-N lists in
wording or visual treatment. `AccessibleBarChart` is always called with
an explicit `maxValue` scoped to that specific chart's own values
(`countBarRows`/`occurrenceBarRows` compute a local max) — never a
fixed 0–1 scale (which was Slice 2's rate-only default) and never
compared against any other chart's scale.

### 49. Dataset separation

`FhirAnalyticsSection` and `SynpufAnalyticsSection` are two sibling
`<div>`s with no shared component, no shared state, and no data passed
between them — each receives only its own half of
`StructuredAnalyticsOverview`. A test
(`keeps the two dataset sections visually and structurally separate`)
asserts neither section's DOM node contains the other. The backend
property this depends on (`app/analytics/structured.py`'s two
independent `_load_*_overview` functions) was unchanged by this slice.

### 50. Synthetic/sample labeling

Every section states its provenance in its own first sentence: FHIR —
"Synthea-generated synthetic FHIR data... not a real hospital
population"; SynPUF — "CMS DE-SynPUF synthetic/sample claims data... not
Medicare spending or a national sample." Dataset-size figures are
explicitly called "in sample" (e.g. "Patients in sample," "Beneficiaries
in sample"), never "population of Medicare" or any national/hospital
framing the source data does not support.

### 51. Empty-state semantics

Every one of the 9 aggregates has its own specific empty-state sentence
(e.g. "No procedure-frequency rows available.") rendered via a shared
`EmptyAggregateNotice` component with `role="status"` — a successful
query returning zero rows is explicitly not styled or worded as an
error. This is kept distinct from two other states that remain
unchanged from Slice 1-2: "Not evaluated" (a measurement genuinely never
performed, e.g. a missing payment figure) and "temporarily unavailable"
(the structured-analytics panel's existing 503/network error path) — the
three are never collapsed into one generic message.

### 52. Structured analytics limitations

A dedicated card lists: the small live sample sizes (read from the
response, not hardcoded — "5 FHIR patients, 15 SynPUF beneficiaries" at
the time of writing, but sourced from `patient_count`/
`beneficiary_count` so it stays accurate as the sample changes), both
datasets being synthetic/sample data, the top-5-only nature of the
frequency tables, no cross-dataset identity linkage, and that aggregate
counts are descriptive only — never a clinical, coverage, or eligibility
conclusion.

### 53. Evaluation dashboard regression

Unchanged in substance. Re-verified against the live rebuilt backend
that every Slice 2 section still renders its exact real numbers:
retrieval Hit@k by mode, reranker rank-change counts (1/23/1, 2/8/0),
reranker latency (426.34ms / 26.77ms), threshold known-issue gate score
(0.613495), citation rates (95.5%/95.5% dev, 70.0%/77.8% held-out), claim
matrix (6/10/11/3), all 13 gap entries, and provenance fields — no metric
changed, and only the page's own top-level intro paragraph text changed
(removing a now-stale "structured analytics remains foundation-only, more
coming later" sentence that this slice's own work made inaccurate).

### 54. Accessibility

Every new element follows the same rule as Slice 2: bar chart values are
DOM text (never color/length-only), every frequency/distribution table is
a real `<table>` with `<caption>` and `scope="col"` headers, dataset
overview counts use `<dl>`, and every new heading (`<h3>`/`<h4>`) nests
correctly under the existing panel `<h2>`. Long codes (SNOMED/RxNorm
numeric codes, ICD-9 codes, HCPCS codes) remain plain text inside table
cells that wrap normally; no code is ever truncated or clipped.

### 55. Responsive verification

Verified at desktop, 768px, and 375px against the live backend with the
**complete** `/analytics` page rendered (all Evaluation Snapshot sections
plus both structured sections): `document.documentElement.scrollWidth
=== document.documentElement.clientWidth` at both narrower widths (zero
page-level horizontal overflow). At 375px, the Payment Totals table was
confirmed to scroll internally via its own `.tableScroll` wrapper (visibly
cropping its third column with an internal scrollbar) rather than the
page scrolling horizontally, and every code/currency value remained fully
legible.

### 56. Real FHIR/SynPUF verification

Cross-checked live against `GET /analytics/structured/overview` on the
rebuilt Docker backend (representative values only, never hardcoded into
frontend source): 5 patients, 177 encounters (AMB 169 / EMER 6 / IMP 2);
top condition "Full-time employment (finding)" (SNOMED `160903007`) at 83
occurrences; 15 beneficiaries, 219 claims (outpatient 191 / inpatient 28);
payment totals $46,010.00 (outpatient, 191 claims) and $300,000.00
(inpatient, 28 claims); top diagnosis ICD-9 `4019` at 37 occurrences; top
HCPCS `36415` at 64 occurrences. All matched the rendered page exactly.

### 57. Security

Confirmed: no arbitrary SQL anywhere in this slice's code (both new
count queries are fixed strings with zero interpolation); no
client-supplied `top_n` or aggregate selector exists in the API surface;
no `patient_id`/`beneficiary_id` rendered anywhere (grep-verified across
the live page's full text content); no FHIR/SynPUF join; no LLM call or
generated interpretation of any kind; no secret, local path, or
`dangerouslySetInnerHTML` in any new file; no sensitive data in any
`console.log`/`console.error` call (none were added).

### 58. Known limitations

Same limitations as the data itself states (§52) — small sample, top-5
only, synthetic data. Additionally specific to this slice: the two
complete distributions (encounter class, claim type) are shown with the
same bar-chart-plus-table treatment as the five genuinely-partial top-5
lists, which is accurate (a bar chart doesn't imply completeness either
way) but a future slice could make the "this is the complete picture"
property more visually distinct if that turns out to matter to users.

## Phase 15 Final Checkpoint

Slice 4 performed the final Phase 15 audit and checkpoint. It added no
new product features — only re-verification, a documentation pass, and
one commit.

### Route

`/analytics`, a real active Sidebar link (its former disabled/"Coming
soon" placeholder was removed in Slice 1). All 9 frontend routes are
present and build cleanly: `/`, `/ask`, `/assistant`, `/patient-data`,
`/claims`, `/workflow`, `/reviews`, `/reviews/[reviewId]`, `/analytics`.

### Evaluation capabilities (final)

Evaluation Overview; Dataset Limitations (development vs. held-out, kept
visually and semantically separate, never averaged); Retrieval Quality
(Hit@1/3/5, MRR@5, per mode, per dataset, with exact numerator/
denominator); Reranker Analysis (the authoritative Slice 6 same-pool
rank-change comparison — development 1 improved/23 unchanged/1 degraded,
held-out 2 improved/8 unchanged/0 degraded); Reranker Quality/Latency
Tradeoff (quality never shown without its latency cost alongside it, no
winner/recommendation language); Threshold Behavior (the frozen 0.40-0.60
grid, observational only, no control that mutates production); the known
`cms-v1-032` high-similarity issue (real gate score `0.613495`, framed as
a retrieval/abstention-pipeline behavior, never a "clinical failure");
Latency (six separate category tables, ms throughout, local/service-level
limitation stated); Citation Expected-Evidence Match
(`CITATION_REFERENCES_EXPECTED_EVIDENCE`, with an explicit
not-entailment/not-completeness/not-correctness boundary restated
in-page); Claim Matrix (6/10/11/3, aggregate counts only, no percentage
score); Evaluation Gaps (all 13 real registry entries, grouped by status,
`EVAL-RUNTIME-CONFIG-DRIFT` given its own prominent, highlighted card);
Cost/Token state (`Not evaluated`, with the deterministic-provider
reason, never `$0`); Evaluation Provenance (an expandable native
`<details>` with experiment IDs, corpus fingerprint, chunk/retrieval
config, model+revisions, and generation provider — confirmed to contain
no local path, username, or API key).

### Structured analytics capabilities (final)

**Synthetic FHIR**: dataset overview (live `patient_count`, derived total
encounters); encounter distribution (complete grouping by encounter class
code, not top-N); Top 5 condition/procedure/medication frequency, each
preserving code/code_system/code_display/occurrences, each with an
explicit disclaimer against risk/prevalence/necessity/outcome/prescribing
claims. **Synthetic SynPUF**: dataset overview (live `beneficiary_count`,
derived total claims); claim distribution (complete grouping by claim
type); payment totals (exact USD formatting, `null` preserved as "Not
evaluated," never a fabricated `$0.00`); Top 5 diagnosis/procedure/HCPCS
frequency, code-and-occurrences only since no description field exists in
that source data, each with an explicit disclaimer against cost/
medical-necessity/coverage/approval-rate claims. A shared Structured
Analytics Limitations card states the live sample sizes, synthetic-data
status, top-5-only scope, and no-cross-dataset-linkage property.

### Canonical snapshot semantics

`GET /analytics/evaluation/snapshot` reads a fixed, hardcoded set of
canonical Phase 12 artifact files (no `experiment_id` parameter exists
anywhere in its public API — verified structurally by a dedicated test,
re-confirmed by this slice's grep-based security audit) — see §3 for the
full per-conclusion-area canonical-artifact table, sourced from Phase
12's own "Artifact provenance" table, not invented by Phase 15. Nothing
in this endpoint re-runs an experiment, re-scores a metric, or mutates
any artifact. `GET /analytics/structured/overview` runs fixed,
parameterized, read-only SQL (the same 9 tools already registered in
Phase 9's `TOOL_REGISTRY`, plus two small local `count(*)` queries added
in Slice 3 for dataset-size context) with a fixed `top_n=5` — no
client-supplied path, experiment ID, table name, or `top_n` value is ever
accepted.

### Dataset boundaries

FHIR and SynPUF are queried by fully independent backend functions and
rendered by fully independent frontend components at every layer of this
feature — no join, no shared identifier, no patient-to-beneficiary
mapping, no cross-dataset profile, anywhere in Phase 15's code. Verified
directly: a live-page grep for `patient_id`/`beneficiary_id` returns
zero matches, and a dedicated test asserts neither analytics section's
DOM tree contains the other's.

### Tests

Frontend: 309 passed, 0 failed (284 Phase 14 baseline + 25 Phase 15
Analytics-specific tests, covering both dashboards' rendering, real
numerator/denominator preservation, not-evaluated semantics, dataset
separation, payment formatting, top-N wording, empty states, and
security-relevant assertions like the absence of patient/beneficiary
identifiers). Backend: 830 passed, 169 skipped (mostly pre-existing
Docker-dependent integration tests plus Phase 15's own two
`CAREFLOW_ANALYTICS_INTEGRATION=1`-gated live tests), 0 failed.

### Build

`next build`: succeeded, 0 errors, 0 warnings, all 9 routes generated.
Backend: `ruff check` clean, `ruff format --check` clean (162 files),
`pip check` clean, `git diff --check` clean.

### Data invariants

Verified identical before Slice 1 and after Slice 4, across every slice's
own Docker rebuild and every round of real-browser verification: Qdrant
39 points; SynPUF 15 beneficiaries / 219 claims / 732 diagnoses / 29
procedures / 848 lines; FHIR 5 patients / 177 encounters / 187 conditions
/ 234 procedures / 1341 observations / 865 components / 116 medication
requests; Review 4 cases / 8 events. Phase 15's own live-gated tests
additionally assert zero mutation via an explicit before/after count
comparison.

### Security boundary

No arbitrary SQL anywhere in Phase 15's code (grep-confirmed). No
client-supplied artifact path, experiment ID, table/repository-function
selector, or `top_n` value exists in either endpoint's public surface
(grep- and test-confirmed). No patient or beneficiary identifier is ever
returned or rendered (grep-confirmed against the live page). No FHIR/
SynPUF join. No LLM call, generated summary, or "AI insight" anywhere in
this feature — every number is either read verbatim from an existing
artifact file or computed by a fixed, deterministic SQL aggregate. No
`dangerouslySetInnerHTML`, no `eval`, no sensitive data in any console
call, no hardcoded secret or credential, anywhere in Phase 15's code
(grep-confirmed). The one Dockerfile change this phase required (copying
`artifacts/evaluation/`, `docs/evaluation/`, and `evaluation/` into the
backend image, plus a permission fix for their host-inherited `0700`
directory modes) copies only already-public, already-committed project
files — no `.env`, no credential, no machine-local path.

### Known limitations (still true)

- The development/regression evaluation set (32 cases) is **not
  independent** — 8 of 32 reuse earlier development questions, and the
  set was repeatedly inspected while building the retrieval pipeline.
- The held-out set (12 cases) is **project-authored**, not externally or
  clinician-validated, and small — a single flipped case moves
  positive-only Hit@1 by 10 percentage points.
- The evaluated CMS policy corpus is small (8 NCD document versions, 32
  sections, 39 chunks).
- Latency figures are local-machine, service-level measurements only — no
  load test, no SLA, no throughput claim exists anywhere in this project.
- `EVAL-RUNTIME-CONFIG-DRIFT` remains **open**: the live multi-agent
  runtime resolves to `dense`/no-rerank, while every retrieval-quality
  result in the snapshot was measured against hybrid+rerank. Phase 15
  surfaces this prominently; it does not resolve it.
- Cost/token usage remains genuinely **not evaluated** — no LLM provider
  has ever been exercised by any evaluation run in this project.
- Both structured datasets are synthetic/sample data at small scale (5
  FHIR patients, 15 SynPUF beneficiaries) — never described as a hospital
  population, Medicare spending, or a national sample.
- Structured frequency views are **top-5 only**, never presented as a
  complete distribution; the two genuinely complete groupings (FHIR
  encounter class, SynPUF claim type) receive the same visual treatment
  as the partial ones (see §58) — accurate but not maximally distinct.
- No authenticated reviewer identity exists anywhere in the project — the
  review workflow's `reviewer_id` remains a caller-supplied,
  non-authoritative string (unchanged by Phase 15, and out of this
  phase's scope).
- No automated browser end-to-end test suite exists; all cross-page/
  real-backend verification in every Phase 15 slice, including this
  checkpoint, was manual/live against a real Docker backend rather than
  scripted.

### Next phase

**PHASE 15 COMPLETE.**
**NEXT: Phase 16 — Comprehensive Testing + CI/CD.**
**Phase 16 has NOT started.**
