# Phase 12 claim matrix

This document exists so the final Phase 12 report — and anything built on
top of it later — cannot accidentally overclaim what CareFlow's evaluation
evidence actually supports. It is an audit of Slices 1–6's actual artifacts
and current source code, not a restatement of chat summaries. Every "Status"
below is one of exactly four values: `SUPPORTED`, `PARTIALLY_SUPPORTED`,
`NOT_EVALUATED`, `OUT_OF_SCOPE`. No numeric confidence score is attached to
any claim area — a claim either has evidence bounding it, or it does not.

Table cells in the "Disallowed wording" column are **examples of prohibited
phrasing**, listed there deliberately so a reader can recognize it — their
presence in that column is expected and is not itself a violation. The
`evaluation.claim_governance` scanner (Slice 7) is structure-aware of this:
it only flags a prohibited phrase found **outside** a `Disallowed wording`
table column or an explicit `## Avoid` section.

## Claim matrix

| Claim | Status | Evidence | Population / scope | Metric | Important limitation | Allowed wording | Disallowed wording |
|---|---|---|---|---|---|---|---|
| Retrieval quality (development set) | PARTIALLY_SUPPORTED | Slice 2 baseline artifact `eb59bc90_774ea9a697a1` | 32-case development/regression set, 8 reused Phase 3-6 questions | Hit@1/3/5, MRR@5 | Development set is not independent — repeatedly inspected while building the pipeline | "measured retrieval performance on the development/regression evaluation set" | "independent benchmark performance", "state-of-the-art retrieval" |
| Retrieval quality (held-out set) | PARTIALLY_SUPPORTED | Slice 2 baseline artifact `eb59bc90_a223469082ce` | 12-case project-authored held-out set (10 positive) | Hit@1/3/5, MRR@5 | Small sample; project-authored, not independently annotated | "measured retrieval performance on this project-authored held-out evaluation set" | "independent benchmark", "clinically validated retrieval accuracy" |
| Hybrid retrieval (dense+BM25+RRF) | SUPPORTED | Slice 2/6 artifacts | Same 39-chunk production corpus | Hit@k/MRR@5 by mode | Supported as measured behavior only, on this corpus/dataset | "hybrid retrieval measured Hit@1=X on this evaluation set" | "hybrid retrieval is superior to production alternatives" |
| Reranking (quality effect) | PARTIALLY_SUPPORTED | Slice 6 same-depth paired comparison, `eb59bc90_reranker_comparison` | Same-pool paired cases, dev (25 positive) + held-out (10 positive) | ΔHit@k, ΔMRR@5, rank-change counts | Aggregate-neutral on dev, small-sample improvement on held-out; created one false abstention | "reranking's measured effect on this evaluation set was..." | "reranking improves answer quality", "reranking is proven beneficial" |
| Chunking (700/120 vs alternatives) | PARTIALLY_SUPPORTED | Slice 3, 6-point grid | Same corpus, 2 datasets | Hit@k/MRR@5 per config | Did not justify changing production 700/120; small held-out sample | "the chunking experiment did not provide sufficient evidence to justify changing 700/120" | "700/120 is the optimal chunk size" |
| Threshold / abstention behavior | PARTIALLY_SUPPORTED | Slice 4 threshold sweep, `eb59bc90_threshold_sweep_*` | Same corpus, frozen 0.40-0.60 grid | Explicit abstention labels, derived rates | Trade-off only — no threshold was selected or recommended | "the sweep characterizes the measured trade-off; production threshold is unchanged" | "0.60 is the optimal threshold" |
| Citation-references-expected-evidence | SUPPORTED | Slice 4/6 `CITATION_REFERENCES_EXPECTED_EVIDENCE` | Answered+supported cases only | numerator/denominator/rate | Narrow and deterministic-provider-only; pipeline-wiring validation, not semantic quality | "citation references expected evidence in X of Y answered cases (deterministic check)" | "citations are accurate", "citation accuracy is X%" |
| Answer correctness | NOT_EVALUATED | — | — | — | See "Answer-correctness boundary" below | "retrieval/abstention/citation-wiring behavior was measured" | "answer correctness", "answers are correct" |
| Answer entailment | NOT_EVALUATED | — | — | — | No entailment/NLI check exists anywhere in this codebase | (none available) | "the answer is entailed by the evidence" |
| Citation completeness | NOT_EVALUATED | — | — | — | Only "references at least one expected chunk" is checked, never full coverage | "at least one validated citation references expected evidence" | "citations are complete" |
| Clinical correctness | OUT_OF_SCOPE | — | — | — | No clinician was involved anywhere in this project | (none available) | "clinically correct", "clinically validated" |
| Coverage-determination correctness | NOT_EVALUATED | — | — | — | No ground-truth coverage-determination dataset exists | (none available) | "correctly determines coverage" |
| Medical necessity determination | OUT_OF_SCOPE | — | — | — | Out of scope for a policy-retrieval RAG system without clinical review | (none available) | "determines medical necessity" |
| Structured-tool correctness (schema/behavior) | SUPPORTED | Phase 8 repository/constraint tests (`tests/test_structured_*`) | All 18 registered tools, deterministic unit tests | pass/fail test assertions | Narrow: established by unit tests, not an external accuracy benchmark | "structured tools are covered by deterministic Phase 8 tests" | "structured-tool accuracy is X%" |
| Structured-tool latency (representative) | PARTIALLY_SUPPORTED | Slice 5 `eb59bc90_latency_*` | 5 of 18 tools, synthetic dataset | median/p95/min/max ms | Small synthetic dataset, local machine, 5 of 18 tools only | "measured latency for 5 representative structured tools on this synthetic dataset" | "structured-tool performance at scale" |
| Structured data quality (pipeline) | PARTIALLY_SUPPORTED | Phase 8 schema constraints, quarantine, idempotency tests | Synthetic DE-SynPUF/Synthea subsets | constraint/quarantine test outcomes | Synthetic data; "quality" here means pipeline integrity, not real-world accuracy | "Phase 8 established schema/idempotency/quarantine behavior" | "structured data quality validated against real claims" |
| Routing accuracy | NOT_EVALUATED | Phase 9 unit/integration tests exist for deterministic classifier behavior | — | — | No representative routing-accuracy benchmark/dataset exists | "the deterministic router's behavior is unit/integration tested" | "routing accuracy is X%" |
| Multi-agent workflow correctness (state machine) | SUPPORTED | Phase 10 graph/validator tests, Slice 5 zero-failure benchmark | 4 fixed representative workflows | pass/fail, structural validation | Narrow: means state-machine/invariant correctness, not answer quality | "multi-agent workflow structural correctness is tested" | "multi-agent reasoning is correct" |
| Multi-agent answer quality | NOT_EVALUATED | — | — | — | No accuracy/quality dataset for combined workflows exists | (none available) | "multi-agent answers are accurate", "agents outperform single-agent baseline" |
| Human-review workflow correctness | SUPPORTED | Phase 11 repository/service tests, CAS/transaction tests | review_cases/review_events state machine | pass/fail | Narrow: means the state machine/persistence layer, not reviewer judgment | "the human-review state machine and persistence layer are tested" | "human review improves accuracy" |
| Human-review effectiveness | NOT_EVALUATED | — | — | — | No human reviewers, no reviewer-agreement, no measured HITL impact anywhere | (none available) | "HITL improves answer correctness", "reviewer agreement is X%" |
| Latency (service-level, local) | PARTIALLY_SUPPORTED | Slice 5 `eb59bc90_latency_*` | Local dev machine, this synthetic dataset | median/p95/min/max ms, cold/warm | Local machine only; no load test | "measured local development-machine service-level latency" | "production SLA", "cloud latency" |
| Scalability | NOT_EVALUATED | — | — | — | No scale test of any kind was performed | (none available) | "scales to production", "scalable" |
| Throughput / RPS | NOT_EVALUATED | — | — | — | No concurrency/load test occurred; never inferred from 1/median latency | (none available) | "requests per second", "throughput" |
| Production readiness (as a single binary claim) | OUT_OF_SCOPE | See "Production readiness" below for the itemized, separately-supported properties | — | — | Collapsing many separately-scoped properties into one readiness label would overclaim | "the following specific properties are implemented: ..." | "production ready" |
| Security | PARTIALLY_SUPPORTED | `orchestration/tools.py` bounded registry, typed StrictModel validation, artifact secret/path scanning (Slices 1-5) | Code-level properties, not a security audit | pass/fail | Narrow: not a penetration test; not a security audit | "the tool registry is bounded (no arbitrary SQL); inputs are typed-validated" | "secure system", "penetration tested", "production hardened" |
| Privacy / PHI safety | PARTIALLY_SUPPORTED | Dataset provenance: CMS policy text, DE-SynPUF synthetic claims, Synthea synthetic FHIR | Evaluation-time data only | — | Narrow: no real PHI was required for evaluation; says nothing about a future real-data deployment | "no real patient PHI was required for this evaluation" | "HIPAA compliant", "HIPAA certified", "PHI-safe in production" |
| Cross-dataset identity linkage (prevention) | SUPPORTED | Phase 10 validator's `CROSS_DATASET_IDENTITY_VIOLATION`/`SOURCE_MISMATCH` issue codes, tested | Structural validation only | pass/fail | Narrow: detects a specific structural mismatch class, not a general linkage audit | "cross-dataset source/identity mismatches are structurally detected and tested" | "no possibility of identity linkage" |
| Generalization (to other corpora/domains) | NOT_EVALUATED | — | — | — | Single 39-chunk CMS NCD corpus only | (none available) | "generalizes to other healthcare domains" |
| External validity | NOT_EVALUATED | — | — | — | No comparison to an external system or dataset was performed | (none available) | "outperforms external systems", "validated against industry benchmark" |

## Answer-correctness boundary

This is the single most important boundary in Phase 12. The evaluation
package's deterministic pipeline (`DeterministicProvider`, `evaluate()`,
Slices 2-6) establishes three things and **only** three things about
generation-adjacent behavior:

1. **Retrieval behavior** — which chunk ranks where, under which
   configuration (Hit@k/MRR@5).
2. **Abstention behavior** — whether the evidence gate causes the system to
   answer or abstain, and the resulting false-answer/false-abstention rates.
3. **Citation/evidence wiring** — whether at least one validated citation's
   `chunk_id` matches the case's expected evidence
   (`CITATION_REFERENCES_EXPECTED_EVIDENCE`).

None of these is answer correctness, factual correctness, clinical
correctness, or medical correctness. `DeterministicProvider` mechanically
quotes the first eligible (in-context) evidence chunk — it does not reason
about the question, does not generate free text, and is not a proxy for how
an LLM-backed provider (e.g. OpenAI) would answer. A citation match proves
the *pipeline* correctly wired an eligible chunk into the response; it says
nothing about whether that chunk's content, if read by a person, correctly
and completely answers the clinical question asked. Establishing answer
correctness would require either a clinician-reviewed answer-correctness
dataset or a validated LLM-judge methodology — neither exists in this
project, and neither is in scope for Phase 12.

## Citation boundary

**SUPPORTED**: citation structure/provenance validation where mechanically
enforced (Phase 4's own citation-shape validation, unchanged); the
`CITATION_REFERENCES_EXPECTED_EVIDENCE` deterministic expected-evidence
match (Slices 4 and 6).

**NOT ESTABLISHED**: semantic entailment (does the cited text actually
support the claim made), citation completeness (does the answer cite
*every* relevant piece of evidence), citation sufficiency, or clinical
validity of what is cited. `DeterministicProvider`'s citation behavior is a
pipeline/evidence-wiring validation mechanism, not a proxy for general LLM
citation quality — this was established during Slice 4's audit and is
restated here as a standing boundary.

## Routing boundary

Phase 9's deterministic router (`app.orchestration.classify`) is covered by
unit and integration tests (`tests/test_orchestration_classify.py`,
`tests/test_orchestration_graph.py`) that assert specific input->route
mappings behave as coded. This is **"deterministic router behavior is
tested,"** not **"routing accuracy is X%."** No representative,
independently-labeled routing dataset exists to compute an accuracy rate
against. A future representative routing-accuracy benchmark would need a
labeled dataset of realistic queries with ground-truth intended routes,
which Phase 12 does not construct.

## Multi-agent boundary

Phase 10's graph/validator invariants (no cycles, exactly-once `validate`,
disjoint state-key writes, structural response validation) are tested, and
Slice 5 measured representative workflow latency with zero call failures.
Phase 12 has **not** established: multi-agent answer-quality accuracy,
agent-vs-single-agent superiority, autonomous reasoning quality, or a broad
workflow success rate on representative external tasks. "Bounded multi-agent
orchestration" (structurally correct, testable, latency-measured) is not the
same claim as "multi-agent answers are accurate."

## Human-review boundary

Phase 11 established workflow/state-machine correctness: review creation,
decision transitions, compare-and-swap concurrency behavior, append-only
audit events, and transaction-safety (the ambient-transaction bug found and
fixed during Phase 11, and re-verified not reintroduced during Slice 5's
persistence benchmark). Phase 12 has **not** measured: human reviewer
accuracy, reviewer agreement, real reviewer time-to-decision, whether
human-in-the-loop review actually improves answer correctness, or clinical
reviewer effectiveness. No human reviewer has ever used this system.

## Latency boundary

### Supported

Local development-machine, service-level, boundary-specific measurements
(Slice 5), with explicit warm/cold separation, on this project's specific
small synthetic dataset sizes.

### Disallowed wording

production SLA, cloud latency, hospital-deployment latency, throughput/RPS
(never inferred from `1/median`), autoscaling behavior, concurrent-load
behavior, or large-dataset performance claims. No load test of any kind has
been performed in this project.

## Held-out limitations

12 total cases, 10 positive, 2 negative. At this size, **one** positive case
flipping status changes positive-only Hit@1 by 10 percentage points, and
**one** negative case flipping changes a negative-case rate (false-answer
rate, correct-abstention rate) by 50 percentage points. Every held-out rate
reported anywhere in Phase 12 is a descriptive engineering signal at this
granularity, not a statistically robust estimate. No confidence interval is
attached to any held-out rate anywhere in this project, because no
confidence-interval methodology was pre-specified before observing results
— attaching one after the fact would itself be a form of overclaiming.

## Corpus limitations

The evaluated policy corpus is 8 NCD document versions, 32 sections, 39
production chunks. Chunking and reranking results measured against this
corpus may not generalize to large policy corpora (thousands to millions of
chunks) or to different healthcare policy domains (e.g., non-CMS payer
policies, non-NCD document types). No claim in this project asserts
otherwise.

## Synthetic-data limitations

Structured-data benchmarks (Slice 5) ran against exactly: DE-SynPUF subset
(15 beneficiaries, 219 claims, 732 diagnoses, 29 procedures, 848 lines) and
Synthea subset (5 patients, 177 encounters, 187 conditions, 234 procedures,
1341 observations, 865 components, 116 medication requests). Both are
synthetic, sampled evaluation datasets. No claim in this project generalizes
these results to hospital-scale production data volumes.

## Privacy / security claim boundaries

### Allowed

"This project's evaluation uses CMS policy documents, DE-SynPUF synthetic
claims, and Synthea synthetic FHIR data. No real patient PHI was required
for the evaluation." "The structured-tool registry is bounded — there is no
arbitrary-SQL execution path, no dynamic tool creation, and every tool
argument passes strict typed validation before any database call."
"Cross-dataset source/identity mismatches are structurally detected (Phase
10 validator) and covered by tests." "Generated evaluation artifacts are
scanned to exclude secrets and absolute personal paths."

### Disallowed wording

Unless separately established with real evidence: "HIPAA compliant," "HIPAA
certified," "PHI-safe in production," "secure for real hospital
deployment," "secure system," "penetration tested," "production hardened,"
"zero vulnerabilities."

## Production readiness

This report does not collapse readiness into a single binary label — doing
so would itself overclaim in one direction or the other. Instead, the
concrete, separately-supported properties are:

- Reproducible evaluation infrastructure with deterministic experiment
  identity (Slices 1-6)
- A bounded, typed structured-tool registry with no arbitrary-SQL path
  (Phase 8/9)
- Deterministic citation/evidence-wiring validation (Phase 4, Slice 4/6)
- An evidence-threshold-gated abstention mechanism, characterized but not
  tuned (Slice 4)
- A tested human-review-in-the-loop state machine with audit events (Phase
  11)
- Structured JSON logging and latency instrumentation at named boundaries
  (Phase 9-11, Slice 5)
- An extensive automated test suite (517+ tests at Slice 6, non-live)
- Containerized services (Postgres, Qdrant) via docker-compose

Remaining gaps that a genuine production-readiness assessment would need to
close are listed in the gap registry (`phase12_gap_registry.json`) —
answer-correctness evaluation, load/scale testing, a security audit, human
reviewer effectiveness measurement, and resolving the runtime/evaluation
configuration drift, at minimum. This project does not attach a readiness
score to that list.

### Disallowed wording

"production ready" (as a standalone binary claim, positive or negative).

## Artifact provenance

Later reports must cite the **authoritative** artifact for each conclusion,
not an earlier superseded one:

| Conclusion area | Authoritative artifact/slice |
|---|---|
| Development/held-out retrieval baseline | Slice 2 (`eb59bc90_774ea9a697a1`, `eb59bc90_a223469082ce`) |
| Chunking comparison | Slice 3 (`eb59bc90_chunking_grid`) |
| Threshold/abstention/citation sweep | Slice 4 (`eb59bc90_threshold_sweep_development`, `eb59bc90_threshold_sweep_held_out`) |
| Latency (all boundaries) | Slice 5 (`eb59bc90_latency_*`) |
| **Causal reranker quality/latency trade-off** | **Slice 6** (`eb59bc90_reranker_comparison`) — supersedes Slice 2 for this specific question |

**Slice 6 explicitly supersedes Slice 2 for the isolated reranker causal
comparison.** Slice 2's `hybrid` vs `hybrid_reranked` per-query rows remain
valid as a record of each *operational mode's own* end-to-end result (what a
caller actually receives from that mode) — they are not deleted or
rewritten — but they must not be read as a clean reranker ablation, because
they compare a depth-5 pool against a depth-10 pool (see the "Slice 2
candidate-depth confound" gap below). Any future document making a causal
claim about reranking's effect must cite Slice 6, not Slice 2.

## Approved vocabulary

### Use

"project-authored held-out engineering evaluation," "deterministic
citation-to-expected-evidence match," "local development-machine latency,"
"synthetic structured data," "observed / measured," "bounded multi-agent
orchestration," "human-review workflow," "measured trade-off," "did not
provide sufficient evidence to justify a change."

### Avoid

Unless later evidence explicitly supports it: "independent benchmark,"
"clinical accuracy," "clinically validated," "production SLA," "autonomous
agents," "HIPAA compliant," "production ready," "statistically
significant," "external benchmark."
