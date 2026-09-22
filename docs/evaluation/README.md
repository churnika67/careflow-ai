# Phase 7 — retrieval evaluation and golden dataset

This is a development evaluation over a small curated CMS NCD corpus and is not
a clinical or production benchmark.

## Audit and scope

The existing Phase 5 script compared dense, BM25 and hybrid using eight positive
questions plus three negatives. The Phase 6 script added pinned cross-encoder
reranking and recorded before/after evidence, timings and deterministic RAG
responses. Both use the production retriever. Their limitations were unversioned
case labels, no MRR/category aggregation, no comprehensive label validation and
limited automated failure reporting. The mobility example already demonstrated
that a retrieved hit can fail the cosine gate and lead to a different citation.

Phase 7 reuses `Retriever`, `load_corpus`, `rerank`, `build_context`, `RAGService`,
`DeterministicProvider` and the existing model providers. It adds evaluation code,
labels, tests and reports only. The 0.6 gate, default API configuration, retrieval
algorithms, model revisions, CMS data, sections and chunking were not changed.
No Phase 8 work or new dependency was introduced. The package discovery list now
includes `evaluation` so the existing pytest entry point and editable installation
can import the new modules.

## Dataset construction and provenance

`golden_retrieval_v1.json` is a versioned JSON document with 32 cases: 25 positives
and seven unanswerable cases. The corpus supports distinct questions about oxygen,
mobility, infusion pumps, CPAP, beds, sleep diagnostics and seat elevation without
padding the dataset with many near-identical paraphrases.

| Category | Cases | Meaning |
| --- | ---: | --- |
| Exact/lexical | 6 | Close to policy terminology |
| Semantic | 5 | Paraphrased intent |
| Mixed | 8 | Policy terms with natural-language intent |
| Hard negative/near match | 3 | Answerable noncoverage provisions competing with covered uses |
| Known failure | 3 | Mobility, seat elevation and oxygen/carbon dioxide inner-ear therapy |
| Ambiguous | 3 | Missing service, pump type or context |
| Out of corpus | 4 | Requested information absent from the reviewed subset |

Categories describe query construction, not which retriever is expected to win.
The first eight questions preserve the prior development queries. The remaining
17 positive questions target distinct inspected provisions. There is no held-out
test split or claim of independent evaluation. Questions and evidence references
were authored by the coding agent after inspecting all 39 indexed chunks, before
running the new evaluation. No clinician or second annotator reviewed the labels.
The labels were not changed in response to retrieval results.

Each positive case stores exact acceptable chunk IDs plus a reference for each:
NCD ID/version, section, excerpt, CMS viewer URL, text hash and source-record hash.
The schema supports multiple alternatives: the POV/scooter stability case accepts
two overlapping chunks because each contains the relevant provision. It does not
require both chunks to be returned. `answerable=true` means the corpus contains
the requested evidence; it does not mean coverage is approved or the evidence
will pass the cosine gate. A policy stating noncoverage is still positive evidence.

Negative cases have empty expected IDs/references and `answerable=false`; their
notes record the missing context or scope of the corpus inspection. Absence from
this small subset is not a claim that Medicare has no relevant policy elsewhere.
Every run validates schema, unique IDs/queries, reference consistency, chunk
existence, NCD/version/section, exact excerpt, source URL, record/text hashes and
canonical corpus fingerprint before loading models. It rejects a missing or
changed chunk. It checks the unchanged 8 NCD versions / 32 sections / 39 chunks
and rechecks the entire corpus after evaluation. Exact quotation validation proves
traceability, not semantic label correctness; the latter still needs independent
review.

## Metrics and stage separation

Hit@K asks whether any acceptable expected chunk appears within K. MRR@5 averages
`1 / first_acceptable_rank`, with zero for a top-five miss. This is explicitly
truncated MRR, not a claim about unseen ranks. Only the 25 positives contribute.
Categories without positives have count zero and null retrieval metrics.

Reranking compares the first acceptable rank before and after. A miss is ordered
after rank five for improved/unchanged/degraded classification. Mean rank change
uses only cases where both ranks were observed, avoiding invented missing ranks.
Positive delta means improvement. Rankings, candidate IDs and scores remain in
per-query JSON for inspection, including degradation cases.

Eligibility is analyzed separately for every final hit: expected label, rank,
cosine, threshold, substantive text and context inclusion. Hybrid/BM25 use the
existing dense top-20 lookup; a missing lookup is ineligible. A high RRF or
cross-encoder score never replaces cosine eligibility. The evaluator calls the
existing context builder and records the actual context supplied after the RAG
ambiguity guard. A separately computed candidate context is not necessarily
supplied to generation: a generic question can abstain before retrieval.

The deterministic provider quotes the first eligible chunk. The evaluator records
abstention reason, citation IDs and whether a citation is among the expected IDs.
That match is a diagnostic, not a full measure of answer correctness. In particular,
quoting authentic coverage text can still fail to answer a brand/dose question.

For abstention, TP is abstention on an unanswerable case; FP is abstention on an
answerable case; FN is an answer attempt on an unanswerable case. Precision is
TP/(TP+FP); recall is TP/(TP+FN); undefined denominators produce null. Ambiguous
and out-of-corpus cases both belong to the unanswerable class. No retrieval Hit@K
is assigned to them.

## Reproduction and artifacts

Run from the repository root with the existing Python 3.12 environment, pinned
models cached, and the reviewed Qdrant index available. The local `.env` already
points to this project's Qdrant port; preserve it.

```bash
# Refresh editable package discovery after adding evaluation/ (no new dependencies).
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m evaluation.run_retrieval_eval
# Optional separate run; default is three repetitions per query.
.venv/bin/python -m evaluation.run_retrieval_eval --output-dir /tmp/careflow-eval
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q tests/test_retrieval_evaluation.py
CAREFLOW_API_URL=http://localhost:18000 CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 CAREFLOW_RAG_INTEGRATION=1 CAREFLOW_HYBRID_INTEGRATION=1 CAREFLOW_RERANK_INTEGRATION=1 .venv/bin/pytest -q
```

The runner explicitly freezes Phase 6 settings: BM25 k1=1.2/b=0.75, RRF k=60,
10 candidates, top five, cosine 0.6 and 24,000 context characters. It evaluates
all four modes independently of API defaults. It records dataset/corpus hashes,
source snapshot, model names/revisions/packages/device, configuration and UTC time.
No serving configuration or Qdrant writes are required.

All branches are warmed once and executed three times per question. Results,
scores and payloads must agree exactly within repeats or evaluation fails.
`stable_observations_sha256` excludes timing samples and timestamps, allowing
comparison across processes. Timings use `perf_counter`: retrieval includes
Qdrant and BM25 rebuilding; rerank-only excludes candidate retrieval and generation.
Candidate retrieval with the evidence lookup is reported as a separate stage.
p95 is the nearest-rank percentile. No model-loading or end-to-end claim is made.

- `golden_retrieval_v1.json`: frozen labels and provenance.
- `retrieval_eval_v1.json`: configuration, metrics, per-query scores/context,
  failures, latency samples and stable fingerprint.
- `retrieval_eval_v1.md`: generated human-readable report from the same JSON.
- `verification.md`: actual checks, interpretation and Git handoff.

## Limits and interview explanation

All queries are development cases from a small corpus, with eight already used
in earlier phases. A perfect Hit@5 does not establish clinical or production
quality. Category counts are too small to infer broad model superiority. No
confidence intervals, significance claim, live LLM evaluation or independent
clinical label review is provided. Exact corpus fingerprints intentionally reject
new index generations until the labels are reviewed and versioned.

For an interview, explain why labels reference evidence chunks rather than only
policy titles, why multiple acceptable chunks matter, and why negatives require
separate denominators. Explain MRR's sensitivity to ordering and the difference
between retrieving evidence, admitting it to context and answering correctly.
Use the observed reranking degradation and brand/dose answer attempt to explain
why aggregate scores alone conceal important failures. Future evaluation expansion
must retain this separation; Phase 8 ingestion is not implemented here.
