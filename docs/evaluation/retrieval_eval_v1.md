# CMS retrieval development evaluation v1

This is a development evaluation over a small curated CMS NCD corpus and is not a clinical or production benchmark.

Observed: 2026-09-22T15:56:15.313556+00:00. Dataset: `cms-retrieval-v1`.
Corpus: 8 NCD versions, 32 sections, 39 chunks.
Corpus fingerprint: `1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2`.
Dataset fingerprint: `4c5901ac105f06e6b4e285bf1a10c3c25a7f18629a0253fc43f0996ab479c169`.
Stable observations: `0d257e61550f4209ff25ac15025ffbbec55378603cea14b1f7e7c2f762d60016`.

## Dataset and configuration

Cases: 32; positive: 25; negative/ambiguous: 7.
Category counts: {'mixed': 8, 'known_failure': 3, 'exact_lexical': 6, 'semantic': 5, 'hard_negative': 3, 'ambiguous': 3, 'out_of_corpus': 4}.

Pinned MiniLM embedding and cross-encoder identities, packages and device are recorded in the JSON configuration. RRF k=60; candidate pool=10; final top-k=5; cosine gate=0.6; context=24,000 characters. No ranking tuning.

## Retrieval metrics

Only positive cases contribute. MRR@5 uses the first acceptable chunk rank; misses contribute zero. Multiple acceptable IDs are alternatives, not a requirement to retrieve all of them.

| Mode | Cases | Hit@1 | Hit@3 | Hit@5 | MRR@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| dense | 25 | 0.880 | 0.960 | 1.000 | 0.928 |
| bm25 | 25 | 0.960 | 1.000 | 1.000 | 0.980 |
| hybrid | 25 | 0.960 | 1.000 | 1.000 | 0.980 |
| hybrid_reranked | 25 | 0.960 | 1.000 | 1.000 | 0.980 |

## Category results

| Category | Mode | Positive cases | Hit@1 | Hit@3 | Hit@5 | MRR@5 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ambiguous | dense | 0 | — | — | — | — |
| ambiguous | bm25 | 0 | — | — | — | — |
| ambiguous | hybrid | 0 | — | — | — | — |
| ambiguous | hybrid_reranked | 0 | — | — | — | — |
| exact_lexical | dense | 6 | 1.000 | 1.000 | 1.000 | 1.000 |
| exact_lexical | bm25 | 6 | 1.000 | 1.000 | 1.000 | 1.000 |
| exact_lexical | hybrid | 6 | 1.000 | 1.000 | 1.000 | 1.000 |
| exact_lexical | hybrid_reranked | 6 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard_negative | dense | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard_negative | bm25 | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard_negative | hybrid | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard_negative | hybrid_reranked | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| known_failure | dense | 3 | 0.333 | 0.667 | 1.000 | 0.567 |
| known_failure | bm25 | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| known_failure | hybrid | 3 | 0.667 | 1.000 | 1.000 | 0.833 |
| known_failure | hybrid_reranked | 3 | 1.000 | 1.000 | 1.000 | 1.000 |
| mixed | dense | 8 | 1.000 | 1.000 | 1.000 | 1.000 |
| mixed | bm25 | 8 | 0.875 | 1.000 | 1.000 | 0.938 |
| mixed | hybrid | 8 | 1.000 | 1.000 | 1.000 | 1.000 |
| mixed | hybrid_reranked | 8 | 1.000 | 1.000 | 1.000 | 1.000 |
| out_of_corpus | dense | 0 | — | — | — | — |
| out_of_corpus | bm25 | 0 | — | — | — | — |
| out_of_corpus | hybrid | 0 | — | — | — | — |
| out_of_corpus | hybrid_reranked | 0 | — | — | — | — |
| semantic | dense | 5 | 0.800 | 1.000 | 1.000 | 0.900 |
| semantic | bm25 | 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| semantic | hybrid | 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| semantic | hybrid_reranked | 5 | 0.800 | 1.000 | 1.000 | 0.900 |

## Reranking changes

{'counts': {'unchanged': 23, 'improved': 1, 'degraded': 1}, 'mean_observed_rank_delta': 0, 'both_found_count': 25}

Improved/degraded compares the first acceptable rank in top five; a miss is censored after rank five. Two misses are unchanged. Mean rank delta is before minus after only where both are observed; positive means improvement.

## Negative and abstention behavior

Abstention is the positive prediction for these metrics. TP = abstention on an unanswerable case; FP = abstention on an answerable case; FN = an answer attempt on an unanswerable case. Precision = TP/(TP+FP); recall = TP/(TP+FN). Undefined ratios are null. This evaluates the deterministic provider, not clinical answer quality.

| Mode | Negatives | Correct abstentions | Incorrect attempts | Positive abstentions | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 7 | 6 | 1 | 3 | 0.667 | 0.857 |
| bm25 | 7 | 6 | 1 | 3 | 0.667 | 0.857 |
| hybrid | 7 | 6 | 1 | 3 | 0.667 | 0.857 |
| hybrid_reranked | 7 | 6 | 1 | 3 | 0.667 | 0.857 |

## Latency

Sequential warm calls; all cases repeated as configured. Retrieval includes Qdrant I/O and BM25 rebuilding where applicable, excludes model loading and generation. Candidate timing additionally includes the existing dense evidence-gate lookup at depth 20. Rerank-only timing scores the ten retrieved candidates, excludes their retrieval and generation. p95 uses nearest-rank ceil(0.95*n). These are not end-to-end or concurrent-load timings.

| Stage | Calls | Median ms | p95 ms |
| --- | ---: | ---: | ---: |
| dense | 96 | 15.96 | 28.59 |
| bm25 | 96 | 14.46 | 30.74 |
| hybrid | 96 | 28.08 | 50.99 |
| hybrid_candidates_with_gate | 96 | 28.78 | 43.19 |
| rerank_only | 96 | 427.80 | 668.22 |

## Per-query ranks and eligibility

Ranks are top-five retrieval ranks. Rejected entries below are expected hits present in the list but below the cosine gate or missing its dense lookup. Full per-hit cosine, threshold, placeholder status, context membership, actual generation context and citation IDs are in JSON.

| Case | Category | Dense | BM25 | Hybrid | Reranked | Change |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| cms-v1-001 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-002 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-003 | known_failure | 5 | 1 | 2 | 1 | improved |
| cms-v1-004 | mixed | 1 | 2 | 1 | 1 | unchanged |
| cms-v1-005 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-006 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-007 | known_failure | 2 | 1 | 1 | 1 | unchanged |
| cms-v1-008 | known_failure | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-009 | exact_lexical | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-010 | semantic | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-011 | exact_lexical | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-012 | hard_negative | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-013 | semantic | 2 | 1 | 1 | 2 | degraded |
| cms-v1-014 | exact_lexical | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-015 | hard_negative | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-016 | hard_negative | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-017 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-018 | semantic | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-019 | exact_lexical | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-020 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-021 | semantic | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-022 | exact_lexical | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-023 | mixed | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-024 | exact_lexical | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-025 | semantic | 1 | 1 | 1 | 1 | unchanged |
| cms-v1-026 | ambiguous | — | — | — | — | not applicable |
| cms-v1-027 | ambiguous | — | — | — | — | not applicable |
| cms-v1-028 | ambiguous | — | — | — | — | not applicable |
| cms-v1-029 | out_of_corpus | — | — | — | — | not applicable |
| cms-v1-030 | out_of_corpus | — | — | — | — | not applicable |
| cms-v1-031 | out_of_corpus | — | — | — | — | not applicable |
| cms-v1-032 | out_of_corpus | — | — | — | — | not applicable |

### Expected evidence rejected by cosine gate

- cms-v1-003 / dense: rank 5, cosine 0.5457982, chunk `c5266e78-a4d3-55c9-9fa9-64ef7fc57d37`. Actual generation context: ['266a9002-e18a-5b6b-950e-0705824077ee', '050d0c24-fb74-5004-94aa-b66ed0faec60', '83d8a48c-77da-5c86-9cd4-c70e42cead80', 'd760711e-bf95-5e64-9d58-31510aba392e']; citations: ['266a9002-e18a-5b6b-950e-0705824077ee'].
- cms-v1-003 / bm25: rank 1, cosine 0.5457982, chunk `c5266e78-a4d3-55c9-9fa9-64ef7fc57d37`. Actual generation context: ['d760711e-bf95-5e64-9d58-31510aba392e', '266a9002-e18a-5b6b-950e-0705824077ee', '050d0c24-fb74-5004-94aa-b66ed0faec60', '83d8a48c-77da-5c86-9cd4-c70e42cead80']; citations: ['d760711e-bf95-5e64-9d58-31510aba392e'].
- cms-v1-003 / hybrid: rank 2, cosine 0.5457982, chunk `c5266e78-a4d3-55c9-9fa9-64ef7fc57d37`. Actual generation context: ['266a9002-e18a-5b6b-950e-0705824077ee', '050d0c24-fb74-5004-94aa-b66ed0faec60', 'd760711e-bf95-5e64-9d58-31510aba392e', '83d8a48c-77da-5c86-9cd4-c70e42cead80']; citations: ['266a9002-e18a-5b6b-950e-0705824077ee'].
- cms-v1-003 / hybrid_reranked: rank 1, cosine 0.5457982, chunk `c5266e78-a4d3-55c9-9fa9-64ef7fc57d37`. Actual generation context: ['d760711e-bf95-5e64-9d58-31510aba392e', '266a9002-e18a-5b6b-950e-0705824077ee', '050d0c24-fb74-5004-94aa-b66ed0faec60', '83d8a48c-77da-5c86-9cd4-c70e42cead80']; citations: ['d760711e-bf95-5e64-9d58-31510aba392e'].
- cms-v1-013 / dense: rank 2, cosine 0.42512673, chunk `266a9002-e18a-5b6b-950e-0705824077ee`. Actual generation context: []; citations: [].
- cms-v1-013 / bm25: rank 1, cosine 0.42512673, chunk `266a9002-e18a-5b6b-950e-0705824077ee`. Actual generation context: []; citations: [].
- cms-v1-013 / hybrid: rank 1, cosine 0.42512673, chunk `266a9002-e18a-5b6b-950e-0705824077ee`. Actual generation context: []; citations: [].
- cms-v1-013 / hybrid_reranked: rank 2, cosine 0.42512673, chunk `266a9002-e18a-5b6b-950e-0705824077ee`. Actual generation context: []; citations: [].
- cms-v1-017 / dense: rank 1, cosine 0.5969231, chunk `21a43ec3-703b-5491-99a2-8732528de421`. Actual generation context: []; citations: [].
- cms-v1-017 / bm25: rank 1, cosine 0.5969231, chunk `21a43ec3-703b-5491-99a2-8732528de421`. Actual generation context: []; citations: [].
- cms-v1-017 / hybrid: rank 1, cosine 0.5969231, chunk `21a43ec3-703b-5491-99a2-8732528de421`. Actual generation context: []; citations: [].
- cms-v1-017 / hybrid_reranked: rank 1, cosine 0.5969231, chunk `21a43ec3-703b-5491-99a2-8732528de421`. Actual generation context: []; citations: [].
- cms-v1-018 / dense: rank 1, cosine 0.5656053, chunk `8b3af28a-4941-5cab-a5a5-a0b4bbbf6a6a`. Actual generation context: []; citations: [].
- cms-v1-018 / bm25: rank 1, cosine 0.5656053, chunk `8b3af28a-4941-5cab-a5a5-a0b4bbbf6a6a`. Actual generation context: []; citations: [].
- cms-v1-018 / hybrid: rank 1, cosine 0.5656053, chunk `8b3af28a-4941-5cab-a5a5-a0b4bbbf6a6a`. Actual generation context: []; citations: [].
- cms-v1-018 / hybrid_reranked: rank 1, cosine 0.5656053, chunk `8b3af28a-4941-5cab-a5a5-a0b4bbbf6a6a`. Actual generation context: []; citations: [].

## Automatically identified failure cases

- **cms-v1-003** — How are mobility limitations in activities of daily living at home assessed for a wheelchair? bm25 Hit@1 succeeds where dense does not; hybrid worse than at least one component; dense: retrieved expected evidence rejected by cosine gate; dense: answer cites no expected evidence; bm25: retrieved expected evidence rejected by cosine gate; bm25: answer cites no expected evidence; hybrid: retrieved expected evidence rejected by cosine gate; hybrid: answer cites no expected evidence; hybrid_reranked: retrieved expected evidence rejected by cosine gate; hybrid_reranked: answer cites no expected evidence.
- **cms-v1-004** — What fasting C-peptide and glucose testing is required for an insulin infusion pump? dense Hit@1 succeeds where bm25 does not; bm25: answer cites no expected evidence.
- **cms-v1-007** — What specialty evaluation is required for power wheelchair seat elevation equipment? bm25 Hit@1 succeeds where dense does not; dense: non-substantive evidence in top3; hybrid: non-substantive evidence in top3.
- **cms-v1-013** — What should be checked before deciding whether a walking stick or walking frame sufficiently resolves the mobility deficit? bm25 Hit@1 succeeds where dense does not; reranker degraded first acceptable rank; dense: retrieved expected evidence rejected by cosine gate; bm25: retrieved expected evidence rejected by cosine gate; hybrid: retrieved expected evidence rejected by cosine gate; hybrid_reranked: retrieved expected evidence rejected by cosine gate.
- **cms-v1-017** — What trials must precede an implanted baclofen pump for chronic intractable spasticity? dense: retrieved expected evidence rejected by cosine gate; bm25: retrieved expected evidence rejected by cosine gate; hybrid: retrieved expected evidence rejected by cosine gate; hybrid_reranked: retrieved expected evidence rejected by cosine gate.
- **cms-v1-018** — How often must a patient return to the treating physician to keep insulin pump coverage? dense: retrieved expected evidence rejected by cosine gate; bm25: retrieved expected evidence rejected by cosine gate; hybrid: retrieved expected evidence rejected by cosine gate; hybrid_reranked: retrieved expected evidence rejected by cosine gate.
- **cms-v1-025** — Does the equipment that lifts a seated power wheelchair user also tilt the seat? dense: non-substantive evidence in top3; hybrid_reranked: non-substantive evidence in top3.
- **cms-v1-026** — Is it covered? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.
- **cms-v1-027** — What documentation is required? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.
- **cms-v1-028** — Does the pump qualify? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.
- **cms-v1-029** — What dental implant documentation is required? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.
- **cms-v1-030** — What chemotherapy regimen treats pancreatic cancer? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.
- **cms-v1-031** — How do I configure a Kubernetes ingress controller? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.
- **cms-v1-032** — Which insulin pump brand and exact basal dose should a newly diagnosed patient use? dense: negative question retrieves nonanswer evidence; bm25: negative question retrieves nonanswer evidence; hybrid: negative question retrieves nonanswer evidence; hybrid_reranked: negative question retrieves nonanswer evidence.

## Limitations

- Development corpus, not a clinical or production benchmark.
- Agent-authored labels, no independent clinical review; eight reused cases.
- MRR@5 truncates unobserved ranks; missing is zero reciprocal rank.
- Deterministic provider quotes first eligible evidence; citation match is not answer correctness.
- Wall-clock latency and timestamps vary; comparisons assert stable scores and payloads.
- No threshold tuning, corpus changes or retrieval algorithm changes.

Reproduce from the repository root:

```bash
.venv/bin/python -m evaluation.run_retrieval_eval
```
