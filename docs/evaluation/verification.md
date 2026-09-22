# Phase 7 verification and handoff

## Status and scope

**Status: implementation and evaluation complete; final full live regression verification pending because Docker Desktop is manually paused.**

Phase 7 implements development retrieval evaluation only. No Phase 8 work,
retrieval tuning, corpus mutation, threshold reduction, commit, push or PR was
performed. The canonical corpus remains eight NCD versions, 32 sections and 39
chunks. The evaluator uses the existing pinned CPU models, RRF k=60, ten
candidates, top five, BM25 k1=1.2/b=0.75, a 0.6 cosine threshold and 24,000-character
context. Serving defaults remain unchanged.

## Actual results

The golden dataset has 32 cases: 25 positive and seven unanswerable. Categories
are mixed (8), exact/lexical (6), semantic (5), known failure (3), hard negative (3),
ambiguous (3), and out of corpus (4). The first eight queries reuse prior development
cases. Labels are agent-authored against inspected indexed text, not independently
clinically reviewed. The multiple-label scooter case accepts either of two chunks.

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR@5 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 22/25 | 24/25 | 25/25 | 0.928 |
| BM25 | 24/25 | 25/25 | 25/25 | 0.980 |
| Hybrid | 24/25 | 25/25 | 25/25 | 0.980 |
| Hybrid + reranker | 24/25 | 25/25 | 25/25 | 0.980 |

All modes reached Hit@1=1.0 on the six lexical and three hard-negative cases.
On five semantic cases, BM25/hybrid reached 1.0; dense/reranked hybrid reached 0.8.
On eight mixed cases, BM25 reached 0.875; the other modes reached 1.0.
On three known-failure cases, dense reached 0.333, hybrid 0.667, and BM25/reranked
hybrid 1.0. Full category Hit@1/3/5 and MRR@5 appear in the generated report.
These small groups do not establish general superiority of any approach.

Reranking improved one case, left 23 unchanged and degraded one, with mean observed
rank change zero across all 25 positives. Mobility evidence improved 2→1;
cane/walker evidence degraded 1→2. Substantive seat-elevation evidence remained
first in hybrid and reranked hybrid. Dense still placed its N/A chunk first.

Four positive cases retrieve expected evidence rejected by the unchanged cosine
gate in every mode:

| Case | Expected evidence cosine | Reranked behavior |
| --- | ---: | --- |
| 003: mobility activities of daily living | 0.5457982 | Expected rank 1 excluded; cites seat elevation |
| 013: cane/walker assessment | 0.42512673 | Expected rank 2 excluded; abstains |
| 017: baclofen pump trials | 0.5969231 | Expected rank 1 excluded; abstains |
| 018: insulin-pump follow-up frequency | 0.5656053 | Expected rank 1 excluded; abstains |

All four modes abstained on six of seven unanswerable cases, and abstained on
three positive cases. Abstention precision is 6/(6+3)=0.667; recall is 6/7=0.857.
The unsupported insulin-pump brand/basal-dose question prompted an answer attempt
in all modes. The deterministic provider quoted authentic policy evidence that
does not supply the requested brand/dose. It did not generate a clinical dosage;
the error is attempting to answer despite the absence of the requested information.

The failure report automatically identifies component Hit@1 disagreements,
hybrid rank losses, reranking degradation, expected evidence below the gate,
non-substantive top-three hits, wrong-evidence citations and retrieved nonanswer
evidence on negative questions. There were no positive top-five misses in this
run; that detector is still covered by tests.

| Stage | Calls | Median ms | p95 ms |
| --- | ---: | ---: | ---: |
| Dense retrieval | 96 | 15.96 | 28.59 |
| BM25 retrieval | 96 | 14.46 | 30.74 |
| Hybrid retrieval | 96 | 28.08 | 50.99 |
| Hybrid candidates with gate lookup | 96 | 28.78 | 43.19 |
| Reranking only | 96 | 427.80 | 668.22 |

Timings are sequential, warm local CPU observations. Reranking excludes retrieval
and generation; these medians are not a measured end-to-end time.

Two independent full evaluation processes produced identical stable observations:
`0d257e61550f4209ff25ac15025ffbbec55378603cea14b1f7e7c2f762d60016`.
Rankings, scores, eligibility and citations matched, excluding latency/timestamps.
The first run's timings are retained. Both also checked the unchanged corpus.

## Files created or changed

- `evaluation/__init__.py`: evaluation package.
- `evaluation/dataset.py`: strict versioned labels and live provenance validation.
- `evaluation/metrics.py`: Hit@K, MRR@5, censored rank change and latency schema.
- `evaluation/analysis.py`: context eligibility, aggregation, abstention and failures.
- `evaluation/run_retrieval_eval.py`: single-command repeatable four-mode runner.
- `evaluation/report.py`: Markdown generated from machine-readable results.
- `tests/test_retrieval_evaluation.py`: schema, labels, metrics, behavior and live checks.
- `docs/evaluation/golden_retrieval_v1.json`: frozen 32-case labels.
- `docs/evaluation/retrieval_eval_v1.json`: actual machine-readable results.
- `docs/evaluation/retrieval_eval_v1.md`: generated results and failure analysis.
- `docs/evaluation/README.md`: construction, definitions and reproduction.
- `docs/evaluation/verification.md`: this handoff.
- `README.md`: Phase 7 scope and results.
- `pyproject.toml`: include the evaluation package in existing package discovery.

No Phase 1–6 test, production retrieval/RAG module, dependency lock or Compose
setting was modified. The initial direct pytest invocation could not import the
new package; adding it to package discovery and refreshing the editable install
resolved that packaging issue.

## Commands executed and reproduction

The audit read existing code, documentation, Phase 6 artifacts and all 39 live
CMS chunks. The dataset was built from those inspected chunks and validated
before any new rankings were run. The evaluation was executed twice:

```bash
.venv/bin/python -m evaluation.run_retrieval_eval
.venv/bin/python -m evaluation.run_retrieval_eval --output-dir /tmp/careflow-phase7-repeat
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/ruff format evaluation tests/test_retrieval_evaluation.py
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q tests/test_retrieval_evaluation.py
.venv/bin/pytest -q
CAREFLOW_API_URL=http://localhost:18000 CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 CAREFLOW_RAG_INTEGRATION=1 CAREFLOW_HYBRID_INTEGRATION=1 CAREFLOW_RERANK_INTEGRATION=1 .venv/bin/pytest -q
.venv/bin/python -m pip check
git diff --check
```

Lint and formatting passed (60 Python files). Dependency validation reported no
broken requirements. `git diff --check` passed but cannot inspect an untracked
baseline. Actual test totals:

- Phase 7 targeted suite: 30 passed, 1 skipped (live label validation).
- Full default suite: 159 passed, 31 skipped, two existing warnings.
- Full live suite attempted with all flags: interrupted after 7 failed and 38
  passed in 163.96 seconds. Failures were Qdrant timeouts in existing RAG tests;
  `docker compose ps` confirmed Docker Desktop was manually paused. This run is
  not a passing Phase 7 integration result and must be repeated after resuming it.
- Both completed evaluation processes had already validated every golden reference
  against the actual canonical corpus and produced identical stable observations.

The previously verified Phase 6 total of 159 live tests is historical evidence,
not a substitute for the pending Phase 7 live regression run.

## Git handoff

The repository still has no committed/tracked baseline. A Phase 7-only PR requires
an actual Phase 1–6 baseline; do not invent historical commits from this mixed
untracked working tree. No Git mutation was performed.

After that baseline is established and the Phase 7 changes are present:

```bash
git switch -c codex/phase-7-retrieval-evaluation
git add evaluation tests/test_retrieval_evaluation.py docs/evaluation README.md pyproject.toml
git diff --cached --check
git diff --cached
git commit -m "feat(evaluation): add CMS golden retrieval dataset and evaluation"
```

Suggested PR title: **Phase 7: Add Corpus-Grounded Retrieval Evaluation**.
The PR should describe frozen labels/provenance, stage-separated metrics, honest
regressions and abstention failures, reproducible commands and actual verification.
No push or PR creation is included in this handoff.

## Interview explanation and limitations

The goal is measurement rather than tuning. Explain chunk-level relevance labels,
alternative acceptable evidence, truncated reciprocal rank and explicit negative
denominators. Explain why a relevance hit can fail the evidence gate and why
an exact citation can still fail to answer the question. The unchanged aggregate
reranking score hides one improvement and one regression, demonstrating why
per-query analysis matters. Independent label review and a larger held-out corpus
are needed before broader claims. No clinical correctness, current coverage
certification or production reliability is established by this development set.
