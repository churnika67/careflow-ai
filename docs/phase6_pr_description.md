# Phase 6: Add Cross-Encoder Reranking to Hybrid Retrieval

## Summary

Hybrid retrieval previously ranked the expected mobility-assistive-equipment
passage second in the eight-question development set. Optional cross-encoder
reranking now scores a larger candidate pool before final top-k selection while
preserving evidence eligibility, provenance and the existing RAG response contract.

## Architecture

Dense + BM25 → RRF → 10 candidates → optional cross-encoder → top 5 → bounded
context and cosine gate → generation → exact citation validation → answer/abstention.
The model implements a reusable scoring protocol; ordering is independent of
FastAPI and generation. Existing dense, BM25 and hybrid evaluation paths remain.

## Implementation

- Pin `cross-encoder/ms-marco-MiniLM-L6-v2` at
  `233902d25c440f23af6f7d6e94d2946bac0bee0a` using existing ML dependencies.
- CPU inference; 512-token pairs, queries up to 128 tokens, 64-token evidence
  overlap, batches of eight, maximum raw window-logit aggregation.
- Preserve all original payload/ranking fields and add score, rank, model and
  window diagnostics. Logs include IDs and timing, without question/evidence text.
- Configure optional reranking, candidate depth and cache using existing settings;
  reuse `RAG_TOP_K` for final depth. Defaults preserve dense retrieval without reranking.
- Fail explicitly with 503 on model failure or 422 on overlong queries; no fallback.
- Reuse the existing Docker model-cache mount. No new dependencies or infrastructure.

## Testing

159 tests passed with all integration flags, including all 132 Phase 1–5 tests.
Targeted reranker tests: 19 passed. Default suite: 129 passed, 30 intentionally
skipped. Two existing warnings concern an AnyIO deprecated alias and local Qdrant
payload indexes. Ruff lint/format, native/container dependency checks and CMS
source-profile validation passed. Docker build and final service health passed.

Actual Docker API checks verified expected citations for hospital beds, seat
elevation and noncoverage, three negative abstentions and the long-query error.
Disabled/restored default output exactly matched the saved Phase 4 hospital-bed
response. The mobility citation limitation below was observed in both native and
Docker paths. Initial integration failures occurred while Docker Desktop was
paused; checks passed after it resumed.

## Evaluation

Development retrieval evaluation only: the same eight positive questions, three
negatives and 39 unchanged chunks. Expected evidence requires document/version,
section and phrase, not merely policy identity.

| Mode | Hit@1 | Hit@3 | Hit@5 |
| --- | --- | --- | --- |
| Dense | 6/8 | 7/8 | 8/8 |
| BM25 | 8/8 | 8/8 | 8/8 |
| Hybrid | 7/8 | 8/8 | 8/8 |
| Hybrid + reranker | 8/8 | 8/8 | 8/8 |

Mobility evidence moved from hybrid rank 2 to 1. Substantive seat-elevation evidence
was already first in hybrid and remains first after reranking. All three negatives
still abstained. Warm CPU reranking median was 449.3 ms for 10 candidates → five results (33 calls, excluding retrieval/generation). Exact rankings and timings are in
`phase6_reranking_comparison.json` and the Phase 6 design report.

## Known limitations

These questions are a small development set, not production accuracy evidence.
The mobility passage's cosine score is about 0.546, below the preserved 0.6 gate:
RAG excludes it and the deterministic provider cites seat-elevation evidence.
Perfect retrieval Hit@1 therefore does not imply correct answer selection. No live
LLM quality result is claimed. Cross-encoder logits are relevance, not confidence.
Maximum-window scoring can favor longer chunks; CPU adds latency and the API
serializes inference. No inference deadline/cache was added. Temporal filtering
was absent in the audited baseline; dates are only preserved metadata. Phase 7
and later features remain unimplemented.

## Git handoff (not part of the proposed PR body)

The current repository has no commits or tracked files. A Phase 6-only diff cannot
be produced against a Phase 5 baseline that does not exist in Git. Do not use
`git add .` expecting a Phase 6-only change. Preserve this completed working tree
and establish/recover the actual Phase 1–5 baseline separately before using the
following intended workflow. Do not invent historical phase commits from the
current mixed tree.

```bash
# Only after an actual Phase 1–5 baseline exists and Phase 6 changes are present:
git switch -c phase-6-cross-encoder-reranking
git status --short
git diff --check
git add .env.example docker-compose.yml README.md \
  backend/app/core/config.py backend/app/generation/runtime.py \
  backend/app/reranking ingestion/cli.py \
  tests/test_reranking.py tests/test_reranking_live.py \
  scripts/compare_reranking.py docs/cms_cross_encoder_reranking.md \
  docs/phase6_reranking_comparison.json docs/phase6_api_verification.json \
  docs/phase6_pr_description.md
git diff --cached --stat
git diff --cached
git commit -m "feat(retrieval): add cross-encoder reranking"
```

Suggested PR title: **Phase 6: Add Cross-Encoder Reranking to Hybrid Retrieval**.
No branch, staging, commit, push, merge or PR creation was performed in Phase 6.
