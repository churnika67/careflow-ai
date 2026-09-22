# CMS BM25 and hybrid retrieval — Phase 5

I added lexical retrieval alongside the existing MiniLM/Qdrant search because CMS
policies contain exact equipment names, abbreviations and policy phrases. The
implementation supports `dense`, `bm25` and `hybrid` modes. **Dense remains the
default**: the small development comparison is encouraging, but not enough to
establish a general retrieval-quality improvement.

Phase 5 does not add a cross-encoder, agents, structured claims, Redis caching,
frontend work, cloud deployment or full evaluation. Generation, prompts, citations
and document ingestion retain their Phase 4 designs.

## Corpus and index construction

BM25 reads the actual published Qdrant payloads, not a separately maintained text
collection. Verification found **8 document versions, 32 sections and 39 chunks**
in `careflow_cms_ncd__5ce29cd4691dc56423f2__279ea98f`. The snapshot hash remains
`735619558de8759427d5fe71989d06b48e5625376594fe94efa7a60f7e152ca3`.
No source was downloaded again, no vectors were regenerated and no alias changed.

A retrieval request resolves the alias once. Both search branches then use that
physical collection. The only extension to `NCDIndex.search` is an optional pinned
collection argument; ordinary dense calls retain their previous behavior. This
prevents an alias switch between the two branches from mixing generations.

`load_corpus` scrolls every payload, checks point/chunk-ID agreement, exact count,
uniqueness and a common index fingerprint. It sorts by deterministic chunk ID.
`BM25Index` copies this corpus and builds explicit term-frequency dictionaries,
document frequencies, lengths and an ID-to-row mapping. Identical inputs produce
identical results; a duplicate ID is rejected. Search results retain source
metadata, including native NCD ID/version, exact section, text and source hashes.

The lexical input is the same logical input used for Phase 3 document embeddings:

```text
title + newline + section + newline + evidence_text
```

There are no field boosts. A heading already present in the evidence text is thus
included twice, matching the existing embedding input. Metadata-only keywords,
revision history and invented codes are not indexed. `N/A` chunks remain in the
39-chunk corpus and in the unfiltered comparison results.

The tiny in-memory lexical index is rebuilt on each BM25/hybrid request. It has no
pickle, separate disk format, stale index file or Redis cache. This is simple and
reproducible for 39 chunks; repeatedly scrolling and copying the corpus will not
scale to a large export. The comparison artifact records all 39 IDs and a hash of
the exact sorted payloads used.

## BM25 and tokenization

BM25 is implemented directly with Python's standard library, without a new
runtime dependency. It uses term frequency saturation, document-length normalization
and positive inverse document frequency:

```text
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
BM25(q,d) = sum over distinct query terms t:
    idf(t) * tf(t,d) * (k1 + 1)
    / (tf(t,d) + k1 * (1 - b + b * length(d) / average_length))
```

Defaults are `k1=1.2`, `b=0.75`. The positive IDF convention and defaults follow
[Lucene's BM25 documentation](https://lucene.apache.org/core/10_2_2/core/org/apache/lucene/search/similarities/BM25Similarity.html).
This is an explicit floating-point implementation, not a claim of byte-for-byte
Lucene parity. There is no query-term-frequency weighting; repeated query terms
contribute once. Filtered search retains whole-corpus IDF and average length.

Tokenizer version: **`cms-lexical-v1`**.

| Decision | Behavior |
| --- | --- |
| Unicode and case | NFKC normalization followed by Unicode case folding |
| Whitespace | Separates tokens; repeated spaces/newlines have no extra meaning |
| Punctuation | Separates tokens except internal dots |
| Hyphens | `C-peptide` → `c`, `peptide`; `12-week` → `12`, `week` |
| Numbers | Preserved, including decimal/dotted forms such as `280.16` |
| Abbreviations | `CPAP` → `cpap`, `U.S.` → `u.s`; no expansion or synonym dictionary |
| Apostrophes | Curly apostrophes normalized; terminal possessive `'s` removed; other apostrophes split tokens |
| Stopwords | None removed; policy negation words such as `not` remain searchable |
| Stemming | None; `evaluation` and `evaluations` remain different tokens |

Removing stopwords, normalizing dotted abbreviations to undotted equivalents,
phrase matching, stemming and synonyms are not implemented. Without stopword
removal, a query outside the corpus can still match common words. That limitation
is visible in the negative-query results and is not hidden with special-case rules.
No tokenization experiments are claimed.

Empty or punctuation-only queries and wholly unknown vocabulary return no BM25
results. Zero-score rows are omitted. Equal BM25 scores sort by chunk ID. Search
limits are 1–20 and questions are limited to 4,000 characters. Metadata filters
match the existing dense whitelist: `NCD_id`, `NCD_vrsn_num`, `source_field`,
`coverage_code`, `document_version_id`. Unsupported or empty filter values fail.

## Hybrid fusion and result shape

The two branches execute sequentially in the current implementation. Hybrid
retrieval takes up to `max(top_k, RETRIEVAL_CANDIDATE_K)` results per branch, then
combines their ranks using Reciprocal Rank Fusion:

```text
RRF(chunk) = sum over branches containing the chunk: 1 / (constant + rank)
```

Ranks are one-based. Defaults are **10 candidates per branch** and **constant 60**.
The constant moderates the effect of a single very high rank. This uses the formula
from [Cormack, Clarke and Büttcher's RRF paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf);
the paper's results are not claimed as this project's results.

Cosine and BM25 have different scales; summing their raw scores would require a
separate calibration decision. RRF avoids that by combining rank contributions.
A document in both lists receives two contributions. A result in only one branch
can still enter the fused result, but agreement between branches often dominates.
RRF scores are neither probabilities nor answer confidence.

Deduplication uses `chunk_id`. Each branch contributes at most once per ID. Dense
rank, BM25 rank and raw scores are retained; conflicting provenance for a shared
ID raises an error instead of silently selecting one version. Fusion ties sort by
chunk ID. Final results receive a one-based `fusion_rank`.

A small dictionary adapter extends the existing payload result; a separate nested
enterprise model was unnecessary:

| Field | Meaning |
| --- | --- |
| Existing payload fields | Chunk ID, native NCD ID/version, title, section, text and complete provenance |
| `collection` | Physical Qdrant generation used |
| `score` | Backward-compatible mode-specific rank score: cosine, BM25 or RRF |
| `dense_score`, `bm25_score`, `fusion_score` | Separate raw values, null when the branch did not contribute |
| `dense_rank`, `bm25_rank`, `fusion_rank` | Branch/final ranks when applicable |
| `retrieval_method` | `dense`, `bm25` or `hybrid` |
| `retrieval_sources` | Branches that contributed this candidate |
| `evidence_gate_score` | RAG-only cosine support check, separate from ranking |

**Cosine ≠ confidence. BM25 ≠ confidence. RRF ≠ confidence.** None is a probability.

## RAG integration and abstention

The existing context builder, prompt `cms-extractive-v1`, generation providers and
citation checks are preserved. New raw lexical and fusion scores never enter the
prompt and are never compared directly to the Phase 4 cosine floor of 0.6.

For BM25/hybrid RAG, the retriever additionally obtains the dense top 20 from the
same physical collection. It attaches the matching cosine as `evidence_gate_score`
without changing the selected mode's ranking. Candidates outside that list have
no support score and are excluded from context. The context builder rejects a
BM25/hybrid hit without this separate gate score. A large raw BM25 score cannot
bypass abstention.

This deliberately conservative choice retains the verified Phase 4 negative-case
behavior. **BM25 search alone does not load an embedding model; BM25 RAG does**, for
this evidence check. The RAG gate can reject a useful lexical-only result and thus
limits recall gains. It is not a calibrated relevance detector. Related but
unanswerable evidence may still pass the cosine floor. This tradeoff is explicit;
Phase 5 does not claim to solve semantic answerability.

General empty/placeholder filtering remains in context construction. It is not
applied before retrieval comparison or fusion. Existing citation validation still
checks exact IDs and whole-paragraph evidence. No free-form synthesis or new
confidence calculation was introduced.

## Phase 5 development retrieval comparison

The complete machine-readable record is
[phase5_retrieval_comparison.json](phase5_retrieval_comparison.json).
It contains each mode's top five chunks, raw scores and ranks, exact expected
evidence/document ranks, hit flags, source text, latency samples, negatives and
seat-elevation RAG outputs. It is **not a production benchmark or Phase 7 evaluation**.

Expected evidence means the original Phase 3 ID/version, `indctn_lmtn` field, exact
section and expected evidence phrase all match. Document rank requires only the
expected ID/version. This distinction matters: a correct policy can rank first
while the chunk containing the needed passage ranks lower.

| Question topic | Dense evidence rank | BM25 evidence rank | Hybrid evidence rank |
| --- | ---: | ---: | ---: |
| Home oxygen clinical testing | 1 | 1 | 1 |
| CPAP documentation | 1 | 1 | 1 |
| Wheelchair mobility assessment | 5 | 1 | 2 |
| Insulin pump / C-peptide testing | 1 | 1 | 1 |
| Hospital-bed prescription | 1 | 1 | 1 |
| Unattended sleep testing | 1 | 1 | 1 |
| Seat elevation | 2 | 1 | 1 |
| Inner-ear oxygen therapy | 1 | 1 | 1 |

The expected **document** ranked first in all eight queries in all three modes.
For the stricter evidence criterion:

| Mode | Hit@1 | Hit@3 | Hit@5 |
| --- | ---: | ---: | ---: |
| Dense | 6/8 (75%) | 7/8 (87.5%) | 8/8 (100%) |
| BM25 | 8/8 (100%) | 8/8 (100%) | 8/8 (100%) |
| Hybrid | 7/8 (87.5%) | 8/8 (100%) | 8/8 (100%) |

These fixed, development-selected questions cannot establish broad quality or
statistical significance. BM25 beating hybrid here is a real observation: fusion
can dilute a better branch. Dense remains the default to preserve the established
baseline while broader queries, paraphrases and failure cases remain unmeasured.

### Seat elevation

Question: “What specialty evaluation is required for power wheelchair seat elevation
equipment?” The substantive chunk is
`d760711e-bf95-5e64-9d58-31510aba392e`, NCD **376/version 1**, section
**B. Nationally Covered Indications**.

| Mode | Substantive rank | N/A rank | Substantive score |
| --- | ---: | ---: | ---: |
| Dense | 2 | 1 | cosine 0.751485 |
| BM25 | 1 | 5 | BM25 20.085695 |
| Hybrid | 1 | 3 | RRF 0.032522 |

The N/A chunk (`d099d33f-7cb8-5474-814e-60f7bdc5f76a`) remains in all three top-five
lists. The improvement therefore comes from the lexical evidence and rank fusion,
not deleting the difficult candidate. At top-k=1, dense RAG still abstains;
BM25 and hybrid return the substantive specialty-evaluation evidence. At top-k=5,
all three modes return that evidence after general context filtering.

### Queries outside the corpus

All three negative questions returned `Insufficient evidence.` in every RAG mode:

| Query | Dense top score | BM25 top score | Hybrid top score |
| --- | ---: | ---: | ---: |
| Dental implant documentation | 0.299220 | 7.916813 | 0.032522 |
| Pancreatic-cancer chemotherapy regimen | 0.457425 | 8.023878 | 0.032787 |
| Kubernetes ingress | 0.165959 | 4.617795 | 0.016393 |

Lexical overlap still retrieves irrelevant policies. The chemotherapy negative
has a higher top fusion score than the successful seat-elevation example. That
is direct evidence that an RRF threshold cannot be treated as answer confidence.
The separate cosine gate rejects these cases; no dental, cancer or Kubernetes
special-case rules exist. Live tests also retain the ambiguous Phase 4 question.

## Latency observations

Measured on this machine against local Qdrant, three repetitions of each of the
eight positive queries: **24 calls per mode** after a warm-up per mode.

| Mode | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Dense | 13.68 ms | 10.86 ms | 29.70 ms |
| BM25 | 12.85 ms | 10.99 ms | 22.32 ms |
| Hybrid | 28.12 ms | 23.58 ms | 45.62 ms |

These timings include alias lookup, Qdrant I/O, and rebuilding BM25 when applicable.
They exclude model loading, process startup, RAG-only cosine checking and generation.
Separately observed model loading was 3,599.01 ms; initial corpus read/build was
73.58 ms. Branches are sequential. This is not a concurrency, throughput, production
latency or large-corpus measurement. Raw samples are in the comparison artifact.

## Run and configure

No new dependencies are required. The existing environment and CPU Docker image
already contain the retrieval dependencies. With the reviewed index available:

```bash
.venv/bin/python -m ingestion.cli search --offline --mode dense \
  "What specialty evaluation is required for power wheelchair seat elevation equipment?"
.venv/bin/python -m ingestion.cli search --mode bm25 \
  "What specialty evaluation is required for power wheelchair seat elevation equipment?"
.venv/bin/python -m ingestion.cli search --offline --mode hybrid \
  "What specialty evaluation is required for power wheelchair seat elevation equipment?"
.venv/bin/python -m ingestion.cli rag --offline --mode hybrid --top-k 1 \
  "What specialty evaluation is required for power wheelchair seat elevation equipment?"
.venv/bin/python scripts/compare_retrieval.py \
  --output /tmp/phase5-retrieval-comparison.json --repeats 3
```

Existing search filters work in all modes. The comparison script provides the
three-way view; no separate comparison CLI mode was necessary.

| Environment setting | Default |
| --- | --- |
| `RETRIEVAL_MODE` | `dense` |
| `RETRIEVAL_CANDIDATE_K` | `10` |
| `RETRIEVAL_RRF_CONSTANT` | `60` |
| `BM25_K1` | `1.2` |
| `BM25_B` | `0.75` |

`--mode` overrides the configured mode for CLI search/RAG. The API reads
`RETRIEVAL_MODE` at process startup; recreate the backend for configuration changes.
Its request and response schemas remain unchanged. For example:

```bash
RETRIEVAL_MODE=hybrid docker compose up -d --no-deps --wait backend
curl --fail http://localhost:18000/query -H 'Content-Type: application/json' \
  -d '{"question":"What specialty evaluation is required for power wheelchair seat elevation equipment?"}'
# Restore the configured default:
docker compose up -d --no-deps --wait backend
```

This machine retains the ignored `.env` port settings from Phase 4: API 18000,
Qdrant 16333, Redis 16379, PostgreSQL 55432. Other projects' containers were left
untouched. The default `.env.example` still uses standard host ports.

## Limitations and Phase 6

Lexical search does not understand synonyms, clinical relationships or whether a
policy answers an entire question. Dense retrieval can prefer a semantically close
heading over substantive content. RRF combines these imperfect lists but does not
read the query and passage together to judge relevance. It still ranks the partial
mobility passage ahead of the expected one in this development set.

Phase 6 will investigate cross-encoder reranking of the candidate set. It may
improve ordering, but that must be measured; it cannot restore evidence absent from
both candidate lists or guarantee a complete generated answer. The Phase 4 mock
remains extractive and can return incomplete or overinclusive policy excerpts.
No real LLM performance claim is made in Phase 5.

## Verification and changed files

Executed checks:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
CAREFLOW_API_URL=http://localhost:18000 \
  CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 \
  CAREFLOW_RAG_INTEGRATION=1 CAREFLOW_HYBRID_INTEGRATION=1 .venv/bin/pytest -q
.venv/bin/python scripts/inspect_cms_ncd.py --check docs/cms_inspection/ncd_profile.json
.venv/bin/python scripts/compare_retrieval.py --output docs/phase5_retrieval_comparison.json
.venv/bin/python -m pip check
docker compose up --build -d --wait --wait-timeout 180
```

Actual CLI runs also checked BM25/hybrid seat-elevation search and hybrid RAG with
`--top-k 1`. Container verification temporarily selected `RETRIEVAL_MODE=bm25`,
then `hybrid`, both with `RAG_TOP_K=1`, and sent real `POST /query` requests.
Responses are recorded in [phase5_api_verification.json](phase5_api_verification.json).
The backend was restored to dense/top-five afterward.

Results:

- Full suite with all live flags: **132 passed**, two warnings, 8.17 seconds.
- Default suite: **110 passed, 22 skipped** (opt-in live tests), two warnings,
  2.79 seconds.
- Lint passed; formatting check passed for **47 Python files**.
- Original archive/profile validation passed, including joins, dates and subset.
- Native and container dependency checks found no broken requirements. No new package was added.
- Docker build/startup and live health checks succeeded. After restoring dense/top-five,
  the hospital-bed API response matched the saved Phase 4 response exactly and the
  original collection still contained 39 points.
- Ranking repeated identically across three trials per query/mode in the comparison.
- Unit tests cover hand-calculated BM25/RRF values, tokenization, filters, ID mapping,
  duplicate/conflicting provenance, empty/unknown queries, mode validation, CLI/API
  wiring and rejection of ungated lexical/fusion scores.
- Live tests check all eight questions in all modes, exact source payloads, unchanged
  corpus identity, seat-elevation top-one citations, and negative-query abstention.
- Existing Phase 1–4 test files and assertions were not changed in this phase.

The two warnings are the existing Starlette/AnyIO deprecation and Qdrant's notice
that payload indexes have no effect in its in-memory test implementation. Real
Qdrant filtering is separately covered by live tests. The tokenizer emits its
existing performance advisory; native pip may disable its unavailable optional
cache. None failed verification.

Two issues found while adding tests were fixed: an unnecessary expectation that
Qdrant's once-per-process warning would repeat, and importing an unpackaged script
from live tests. The tests now use their own assertions and saved query cases.
No application feature or existing test was weakened to resolve these failures.

| File | Change |
| --- | --- |
| `backend/app/retrieval/__init__.py` | Retrieval package |
| `backend/app/retrieval/lexical.py` | Deterministic tokenizer, explicit BM25 index and metadata filtering |
| `backend/app/retrieval/fusion.py` | Common score fields, RRF, deduplication and provenance conflict checks |
| `backend/app/retrieval/search.py` | Published-corpus loading, mode selection, pinned generation and RAG cosine checks |
| `ingestion/indexing/qdrant.py` | Optional physical collection argument, preserving ordinary dense search |
| `ingestion/cli.py` | `--mode` for search/RAG; BM25 search avoids model loading |
| `backend/app/core/config.py` | Validated retrieval settings |
| `backend/app/generation/runtime.py` | Retrieval-mode wiring |
| `backend/app/generation/context.py` | Separate cosine gating for lexical/fusion results |
| `.env.example`, `docker-compose.yml` | Document and pass retrieval settings |
| `tests/test_hybrid_retrieval.py`, `tests/test_hybrid_live.py` | Unit, CLI, API and live checks |
| `scripts/compare_retrieval.py` | Reproducible development comparison and timing collection |
| `docs/phase5_retrieval_comparison.json` | Actual rankings, evidence, scores, timings and abstentions |
| `docs/phase5_api_verification.json` | Actual container API observations |
| `docs/cms_hybrid_retrieval.md`, `README.md` | Implemented design, usage, measured results and limits |

The repository was entirely untracked at the start of the phase; no commit was
made. Raw data, model caches and local `.env` remain ignored. Phase 6 has not started.
