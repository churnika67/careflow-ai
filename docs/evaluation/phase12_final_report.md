# Phase 12 final report — advanced RAG evaluation

This is the single authoritative synthesis of Phase 12 (Slices 1–7). It
summarizes what each slice established without duplicating every raw
number — the per-slice artifacts remain the source of truth for exact
figures (see "Reproducibility" below for exact paths/IDs). Nothing in this
document overrides a measured artifact; where this document's prose and an
artifact could ever disagree, the artifact is correct and this document
should be fixed, not the other way around.

## 1. Scope

Phase 12 built reproducible evaluation infrastructure for CareFlow's
retrieval, chunking, threshold/abstention, citation-wiring, latency, and
reranker behavior, and produced an explicit inventory of what that evidence
does and does not support. It did not change any production configuration,
did not add new production capabilities, and did not evaluate answer
correctness, clinical correctness, routing accuracy, multi-agent answer
quality, or human-reviewer effectiveness — see "Known evaluation gaps"
below.

## 2. Dataset methodology

Two datasets, two different purposes, both grounded against the identical
39-chunk production corpus (`corpus_sha256`/fingerprint
`1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2`):

- **Development/regression dataset** (`docs/evaluation/golden_retrieval_v1.json`):
  32 cases (25 positive, 7 negative). Predates Phase 12; 8 of the 32 reuse
  Phase 3–6 development questions and the set has been repeatedly inspected
  while building the pipeline — it is not independent.
- **Held-out engineering dataset** (`docs/evaluation/golden_retrieval_heldout_v1.json`):
  12 cases (10 positive, 2 negative), frozen at Slice 1 with SHA-256
  `a144fc2e1611b41dca66dff0dc5a3415f3b1a11476de2d19555a2a3bacfe0158`,
  **before** any comparative experiment was run against it. Built from the
  20 of 39 chunks never used as development evidence.

## 3. Development vs held-out distinction

Use exactly: **"project-authored held-out engineering evaluation."** The
held-out set is project-authored, frozen before comparative experiments,
constructed from previously unused evidence, and is **not** independently
authored, not externally annotated, and not clinician validated.

### Disallowed wording

For either dataset: "independent benchmark," "external benchmark," or
"clinical benchmark."

## 4. Baseline retrieval

Authoritative artifacts: Slice 2, `eb59bc90_774ea9a697a1` (development),
`eb59bc90_a223469082ce` (held-out). Measured at the production
configuration (700/120 chunking, hybrid retrieval, reranking enabled,
threshold 0.60, deterministic generation) — see "Reproducibility" for the
exact configuration identity. These are operational baseline metrics for
each mode (dense/bm25/hybrid/hybrid_reranked); they are not a causal
reranker ablation (see §9 and §14 below) and are not evidence of broad
retrieval generalization beyond this specific 39-chunk corpus.

## 5. Chunking experiment

Authoritative artifact: Slice 3, `eb59bc90_chunking_grid`. A predetermined,
non-post-hoc-adjusted 6-point grid: (400,0), (400,120), (700,0), (700,120),
(1200,0), (1200,120), evaluated on both datasets via deterministic,
provenance-based evidence remapping (never retrieval rank/embedding/reranker
score). Production 700/120's chunk_id set and text were proven byte-identical
to a local rebuild from the frozen source before any comparison was drawn.

**Conclusion, verbatim, not to be strengthened:** *"The six-configuration
chunking experiment did not provide sufficient evidence to justify changing
the existing 700/120 production configuration."* Supporting measured
findings: overlap=120 showed no measured benefit at target 700 or 1200;
overlap=120 degraded retrieval at target 400 on both datasets; long-section
cases showed no systematic chunk-size pattern; the held-out sample is small;
no production setting was changed.

## 6. Threshold/abstention experiment

Authoritative artifact: Slice 4, `eb59bc90_threshold_sweep_development` /
`eb59bc90_threshold_sweep_held_out`. Frozen grid: 0.40 / 0.45 / 0.50 / 0.55
/ 0.60, at production 700/120 chunking, both datasets, using the same
provenance-based evidence remapping validated in Slice 3. Retrieval rank was
verified structurally invariant across all 5 thresholds (threshold is never
passed into `search.search()`). 27 case-level transitions were observed
across the 4 adjacent threshold pairs, **all** answered→abstained as
threshold increased, **zero** reverse/non-monotonic transitions. Historical
low-score development cases (mobility, cane/walker, baclofen pump, insulin
pump follow-up) were re-verified against actual current gate scores, not
assumed.

**`cms-v1-032`** (unsupported/out-of-corpus) still answers at every tested
threshold including production's 0.60 (gate score ≈0.613495) — documented as
`EVAL-UNSUPPORTED-HIGH-SIMILARITY`, not fixed, no special-case rule added.
Production threshold remains 0.60; **no threshold change is recommended.**

## 7. Deterministic citation evaluation

`CITATION_REFERENCES_EXPECTED_EVIDENCE` (Slice 4, reused in Slice 6) is the
sole deterministic metric: does at least one validated citation's chunk_id
fall within the case's expected evidence? Use **"deterministic
citation-to-expected-evidence match"** — never "citation accuracy" unqualified.
Phase 12 explicitly did **not** establish semantic entailment, citation
completeness, answer correctness, or clinical correctness.
`DeterministicProvider` mechanically quotes the first eligible evidence
chunk; it is a pipeline/evidence-wiring validation mechanism, not a proxy
for general (e.g. LLM-backed) citation quality.

## 8. Latency evaluation

Authoritative artifact: Slice 5, `eb59bc90_latency_1790202561`. Local
development-machine, service-level measurements only, with explicit
warm/cold separation. Representative boundaries measured: retrieval stages
(dense/bm25/hybrid, reused from Slice 2), rerank-only, 5 representative
structured tools, 4 multi-agent workflows, pure review-policy decision, and
isolated review-persistence (create + decision, cleaned up, counts verified
restored to 0/0). No throughput/RPS claim is made or inferred from
`1/median`. Multi-agent `POLICY_AND_STRUCTURED` combined latency (25.87ms)
sits close to `max(policy_only, structured_only)` (25.63ms) rather than
their sum (33.37ms) — described precisely as: *the LangGraph implementation
uses policy/structured fan-out within the same superstep, and the observed
combined latency is consistent with concurrent branch execution* — timing
similarity is evidence consistent with concurrency, not standalone proof.

## 9. Reranker same-pool comparison

Authoritative artifact: **Slice 6**, `eb59bc90_reranker_comparison` — **not**
Slice 2 (see §14). Isolated the reranker as the sole experimental
difference by holding the pre-rerank depth-10 hybrid candidate pool
identical for both arms.

- Development: improved 1, unchanged 23, degraded 1; aggregate Hit@1/3/5,
  MRR@5 unchanged (masks one offsetting improvement/degradation pair).
- Held-out: improved 2, unchanged 8, degraded 0; Hit@1 0.700→0.700, Hit@3
  0.900→1.000, Hit@5 0.900→1.000, MRR@5 0.783→0.833 (10 positive cases —
  small sample, no significance claim).
- `cms-v1-h003` (held-out): reranking creates one additional false
  abstention even though expected-evidence rank stays at 1 — documented as
  `EVAL-RERANKER-FALSE-ABSTENTION`, an observed interaction between
  reranked top-k composition and downstream evidence gating, not asserted
  as a code defect.
- Reranker latency: ≈426–474ms median, ≈15.9–17.3x the hybrid
  candidate-retrieval stage median.

**No winner or recommendation was selected; production reranker
configuration is unchanged.**

## 10. Runtime vs evaluation configuration distinction

**`EVAL-RUNTIME-CONFIG-DRIFT`, status OPEN, not resolved in Phase 12.** The
live multi-agent runtime (`app.core.config.get_settings()`, audited
directly in Slice 5) resolves to `retrieval_mode=dense`,
`rerank_enabled=false` in this environment. Phase 12's retrieval-quality
experiments (Slices 2, 3, 4, 6) evaluate a different, frozen configuration:
hybrid retrieval with reranking enabled (`PRODUCTION_SETTINGS` in
`evaluation/run_experiment.py`). **Therefore retrieval-quality results in
this report cannot be cited as direct measurements of the currently
resolved multi-agent API request path.** Neither configuration was changed
by Phase 12; a future engineering decision should explicitly resolve
whether they should be aligned.

## 11. Known evaluation gaps

Full registry: `docs/evaluation/phase12_gap_registry.json` (13 entries, all
schema-validated — see Slice 7/8 verification). Summary by status: 5
`OPEN` (runtime/eval config drift, routing accuracy not evaluated,
production/load latency not evaluated, `cms-v1-032`, `cms-v1-h003`), 4
`OUT_OF_SCOPE_PHASE12` (answer correctness, citation entailment/completeness,
multi-agent answer quality, HITL effectiveness — all deliberately outside
this phase's scope), 4 `DOCUMENTED_LIMITATION` (small held-out sample, small
policy corpus, synthetic structured-data scale, Slice 2 candidate-depth
confound). Every gap's `production_change_required_now` is `false` — Slice
7/8 are documentation, not remediation.

## 12. Claim boundaries

Full matrix: `docs/evaluation/phase12_claim_matrix.md` (30 claim-area rows).
**Recomputed programmatically at Slice 8** via
`evaluation.claim_governance.parse_markdown_table`/`validate_claim_matrix`
(zero violations — every status is one of the 4 approved enum values):

| Status | Count |
|---|---|
| SUPPORTED | 6 |
| PARTIALLY_SUPPORTED | 10 |
| NOT_EVALUATED | 11 |
| OUT_OF_SCOPE | 3 |
| **Total** | **30** |

**Correction to Slice 7's chat-report prose:** Slice 7's chat summary stated
"SUPPORTED (8 rows...)" and "NOT_EVALUATED (9 rows...)" while its own
enumeration actually named 11 NOT_EVALUATED concepts. This was a genuine
arithmetic error in that chat summary, not a row-status inconsistency —
every individual row's status was already correct (`validate_claim_matrix`
returns zero violations both then and now), and no row's status was changed
to fix this. The error was never persisted to `phase12_claim_matrix.md`
itself (confirmed by grep before writing this section) — only this
document's corrected summary numbers (6/10/11/3) are authoritative.

The single most load-bearing boundary: current evaluation establishes
retrieval, abstention, and citation-wiring behavior — **never** answer,
factual, or clinical correctness.

## 13. Production invariants

Verified unchanged throughout Phase 12 (Slices 1–8, re-verified after Slice
8's remediation pass): production alias `careflow_cms_ncd` → physical
collection `careflow_cms_ncd__5ce29cd4691dc56423f2__279ea98f`, 39 points.
**Temporary Phase-12 experiment Qdrant collections remaining: 0** (searched
by the `careflow_exp_*` naming convention `chunking_experiment.py` uses for
its isolated indexes — none found). Separately, **2 pre-existing unaliased
physical collections** remain untouched:
`careflow_cms_ncd__5ce29cd4691dc56423f2` and
`careflow_cms_ncd__38d120ac69f9bcf6d63c` (39 points each) — these predate
Phase 12 (present, identical, and unaliased as far back as Slice 4's first
inventory check) and were never created, aliased, or modified by any Phase
12 code; they are not called "Phase 12 leftovers" without that provenance
evidence. Corpus fingerprint recomputed via the established
`ingestion.models.digest(load_corpus(...))` function (not merely asserted
unchanged): `1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2`
— exact match. Chunking 700/120. Evidence threshold 0.60. SynPUF 15
beneficiaries / 219 claims / 732 diagnoses / 29 procedures / 848 lines. FHIR
5 patients / 177 encounters / 187 conditions / 234 procedures / 1341
observations / 865 components / 116 medication requests. Review 0
review_cases / 0 review_events. No Phase 4–11 API was modified.

**Artifact-identity test isolation (added in Slice 8 remediation):**
`run_threshold_sweep()` and `run_reranker_comparison()` now accept an
optional `artifact_root` parameter (default: the real repository
`artifacts/evaluation/` directory — production/CLI behavior unchanged).
Live tests pass a pytest `tmp_path` instead, so they exercise the real
production Qdrant/corpus/reranker for retrieval while writing artifacts
into an isolated directory — proving both that the isolated write succeeds
and that `ExperimentAlreadyExistsError`/no-overwrite still holds inside
that isolated root, without ever touching, archiving, or deleting the real
repository's historical Slice 2–6 artifacts. `evaluation.artifacts.write_experiment_artifacts()`
itself was not modified. One expected, harmless side effect of re-running
the full live suite: `evaluation/latency_experiment.py`'s
`run_latency_evaluation()` retains its pre-existing Slice 5 design (a
timestamp-included experiment_id, since latency is not meant to be
byte-for-byte reproducible) and was out of this remediation's scope — each
live rerun of its test therefore adds one new, correctly-schemaed,
artifact-safe latency directory to the real repository. This was verified
precisely: a before/after SHA-256 of every file under
`artifacts/evaluation/` showed exactly one new directory
(`eb59bc90_latency_<timestamp>`) and zero other differences after Slice 8's
full live-suite rerun.

## 14. Limitations

- **Small held-out sample** (12 cases, 10 positive, 2 negative): 1 flipped
  positive case changes positive-only Hit@1 by 10 percentage points; 1
  flipped negative case changes a negative-case rate by 50 percentage
  points. No confidence interval is attached anywhere — none was
  pre-specified.
- **Small policy corpus**: 8 NCD document versions, 32 sections, 39 chunks —
  results may not generalize to larger/different policy corpora.
- **Synthetic structured data only**: DE-SynPUF (15/219/732/29/848) and
  Synthea (5/177/187/234/1341/865/116) subsets — not hospital-scale.
- **Local-machine latency only** — no load test, no SLA/throughput claim.
- **Slice 2's `hybrid` vs `hybrid_reranked` rows are not a clean reranker
  ablation** (depth-5 vs depth-10 candidate-pool confound) — superseded by
  Slice 6 for that specific causal question; Slice 2 artifacts unchanged.
- **Runtime/evaluation configuration drift** (§10) — unresolved by design.
- No statistical-significance test was performed or is claimed anywhere in
  Phase 12.

## 15. Reproducibility

Every artifact records: dataset version + SHA-256, corpus fingerprint,
embedding model + revision (`sentence-transformers/all-MiniLM-L6-v2` @
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`), reranker model + revision
(`cross-encoder/ms-marco-MiniLM-L6-v2` @
`233902d25c440f23af6f7d6e94d2946bac0bee0a`, device `cpu`), chunking
(700/120), evidence threshold (0.60), retrieval candidate_k (10), RRF k
(60), final_top_k (5), generation provider (`deterministic`), git commit,
and explicit source-state disclosure.

**Phase 12 was developed entirely with a dirty working tree on HEAD
`eb59bc9`** — every artifact's `config.json` records `working_tree_clean:
false` plus the exact repo-relative `modified_files`/`untracked_files` lists
at the time of that run, precisely because `git_commit` alone does not prove
which code produced a given artifact under these conditions. No claim in
this report implies experiment code was run from a pristine `eb59bc9`
checkout. Exact latency reproducibility across different hardware is not
claimed or implied anywhere.

## 16. Phase 12 conclusion

Phase 12 built reproducible, artifact-backed evaluation infrastructure
covering retrieval, chunking, threshold/abstention, deterministic citation
wiring, latency, and an isolated reranker comparison, and it built an
explicit, programmatically-validated inventory of what that evidence does
and does not support. No production configuration was changed at any point.
The most significant open items carried forward are the runtime/evaluation
configuration drift (`EVAL-RUNTIME-CONFIG-DRIFT`) and the absence of any
answer-correctness evaluation — both are documented, neither is resolved
here, and neither requires an immediate production change.
