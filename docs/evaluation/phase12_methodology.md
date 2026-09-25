# Phase 12 — advanced evaluation methodology

This document establishes Phase 12's evaluation infrastructure and dataset
methodology. It is **not** a results/conclusions report — Slice 2 only
proves the infrastructure works and records two factual baseline
measurements. No comparative configuration experiment (chunking, threshold,
reranker on/off) has been run yet, and no production configuration has
changed.

## Two datasets, two different purposes

### `docs/evaluation/golden_retrieval_v1.json` — development / regression

The original Phase 7 dataset (32 cases: 25 positive, 7 unanswerable). As of
Phase 12, this is formally classified as **development/regression data, not
independent held-out evaluation data**. Its own `label_method` field already
discloses why: 8 of the 32 cases reuse Phase 3–6 development questions, and
the complete 32-case artifact has been repeatedly inspected while building
the retrieval pipeline — meaning the existing chunking/threshold/RRF
configuration may have been influenced, even informally, by familiarity with
these specific cases. It remains valuable as a regression check (does a
change break something previously working?), just not as an independent
measurement of generalization.

### `docs/evaluation/golden_retrieval_heldout_v1.json` — frozen held-out set

A second, smaller dataset (12 cases: 10 positive, 2 negative), constructed
in Phase 12 Slice 1 **after** the development set was declared frozen data,
and **before** any comparative experiment was run against it. Built
exclusively from the 20 of 39 indexed chunks never used as expected evidence
in the development set — zero evidence-chunk overlap, independently
verified. Deliberately includes 2 cases drawing evidence from long
(>700-token) sections, so the Slice 3 chunking comparison has genuine
held-out sensitivity to chunk-boundary changes.

**Authorship**: this is a **Phase 12 project-authored held-out engineering
evaluation set**. It is explicitly **not** an independently annotated,
externally validated, or clinician-validated benchmark — no such claim is
made anywhere in this project. Labels were constructed the same
programmatic-provenance-validated way as the development set (exact quote
and SHA-256 verified against the live corpus), just by the same author,
without independent review.

**Frozen state**: approved and frozen at Slice 1. Its validated dataset
SHA-256 (`digest()` over the full validated `GoldenDataset` model) is:

```
a144fc2e1611b41dca66dff0dc5a3415f3b1a11476de2d19555a2a3bacfe0158
```

Corpus fingerprint (shared with, and independently confirmed identical to,
the development set — both are grounded against the same unmutated
39-chunk index):

```
1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2
```

`evaluation/run_experiment.py` checks this exact hash before every run
against the held-out set and refuses to proceed — not repair, not
warn-and-continue — if it ever differs. After freeze: no edited questions,
labels, evidence, expected_chunk_ids, or categories; no added or removed
cases; no changed positive/negative status; none of this may ever be done
in response to an observed experiment result. A genuine labeling defect
discovered later must be reported, not silently corrected.

## Experiment identity and reproducibility

Every experiment run produces a deterministic `experiment_id`:

```
<git-commit-short-sha>_<config-hash>
```

`config-hash` is a canonical-JSON SHA-256 (reusing `ingestion.models.digest`,
the same helper used everywhere else in this codebase for content-addressed
identity) over the experiment's *behavioral* parameters only — dataset,
embedding/reranker identity, chunk size/overlap, retrieval/rerank
configuration, evidence threshold, generation provider. `git_commit` and
`timestamp` are deliberately excluded from that hash: two runs of the
identical configuration must hash identically regardless of when or on
which commit they ran, so they can be recognized as the same experiment.

### Dirty-working-tree disclosure

Phase 12 code is intentionally uncommitted while slices are developed and
reviewed. `git_commit` alone does not prove which exact code produced a
given artifact under these conditions. Every `config.json` therefore also
records `working_tree_clean` (bool) and, when dirty, the exact repo-relative
`modified_files`/`untracked_files` lists (never file contents, never
absolute paths — git already reports paths relative to the repository
root). This is a bounded, deterministic disclosure, not a full source
fingerprint, and is itself excluded from the config hash (it describes
*execution provenance*, not *experiment parameters*).

## Artifact structure

```
artifacts/evaluation/<experiment_id>/
    config.json        # the full resolved ExperimentConfig actually used
    per_query.jsonl     # one row per (case, retrieval_mode) pair
    summary.json         # dataset identity, case counts, per-mode metrics,
                          # abstention confusion + derived rates, reranking
                          # rank-change counts, failure category counts
    latency.json          # retrieval-stage Latency summaries (median/p95/min/max)
    environment.json       # bounded, non-identifying reproducibility metadata
```

Written atomically: content is built entirely in memory, then moved into
place with a single filesystem rename. A run that fails partway leaves
**no** artifact directory at all — never a partially-written one. Because
`experiment_id` excludes timestamp, re-running an identical configuration
produces the same id; the runner refuses to overwrite, append to, or delete
an existing experiment directory — historical artifacts are never silently
lost. `per_query.jsonl` rows never contain full CMS document text — only
chunk identifiers, ranks, scores, and small provenance fields.

`docs/evaluation/retrieval_eval_v1.json`/`.md` (the historical Phase 7
artifacts) and `evaluation/run_retrieval_eval.py` (the historical Phase 7
runner) are unchanged and remain independently reproducible.

## Metrics

Reused/extended exactly as approved — no new metric families:

- `Hit@1`/`Hit@3`/`Hit@5`/`MRR@5`, now reported with explicit raw numerator
  and denominator alongside each rate (e.g. `Hit@1_hits: 7`, `Hit@1_total:
  10`, `Hit@1: 0.7`) — never a bare percentage.
- Abstention confusion counts (precision/recall, framed as "abstention is
  the positive prediction") plus two Phase 12 additions: `false_answer_rate`
  (= FN / negative_cases) and `false_abstention_rate` (= FP / positive_cases),
  both independently computed with explicit denominators, `null` when a
  denominator is zero.
- `FailureCategory` — exactly 4 values with real, existing detectors:
  `NO_RELEVANT_IN_TOP_K`, `BELOW_EVIDENCE_THRESHOLD`, `RERANK_REGRESSION`,
  `INCORRECT_ABSTENTION`. No `LEXICAL_MISMATCH`/`SEMANTIC_MISMATCH`/
  `UNSUPPORTED_ANSWER`/etc. — those would need labels this project doesn't
  have.

No `Recall@k`/`Precision@k`/`nDCG@k` — with a single acceptable chunk for
31 of 32 development cases and 10 of 10 held-out cases, those would be
redundant restatements of `Hit@k`, not new information.

## Production configuration (measured, not assumed)

Verified directly from `backend/app/core/config.py` and
`ingestion/chunking/sections.py` before Slice 2 work began, not carried
forward from memory:

| Parameter | Value |
|---|---|
| Chunk target size | 700 tokens |
| Chunk overlap | 120 tokens |
| Dense/BM25 candidate depth | 10 |
| RRF constant | 60 |
| BM25 k1 / b | 1.2 / 0.75 |
| Rerank candidates | 10 |
| Final top-k | 5 |
| Evidence (cosine) threshold | 0.60 |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` @ `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| Reranker model | `cross-encoder/ms-marco-MiniLM-L6-v2` @ `233902d25c440f23af6f7d6e94d2946bac0bee0a` |
| Generation provider | `deterministic` |

All match historical expectations exactly. **None of these values were
changed during Slice 2, and none will be changed by any Phase 12 slice
without an explicit before/after comparison, trade-off explanation,
regression verification, and your explicit approval.**

## Limitations

- Neither dataset is independently annotated, externally validated, or
  clinician-validated. Both are project-authored engineering evaluation
  sets over synthetic/public CMS text, not a clinical or production
  benchmark.
- The held-out set is small (12 cases, 10 positive) — a real constraint of
  this corpus (only 39 chunks, 20 never used as development evidence, and 6
  of those 20 are non-substantive boilerplate). Any comparison drawn from it
  should be read as a small-sample engineering signal, not a statistically
  robust claim.
- `false_answer_rate`/`false_abstention_rate` inherit the same small
  denominators as the underlying abstention counts (2–7 negative cases
  depending on dataset) — a single case flipping changes these rates by a
  large percentage.
- No comparative experiment (chunking grid, threshold sweep, reranker
  on/off comparison) has been run yet — Slice 2 measured only the existing,
  unmodified production configuration.
