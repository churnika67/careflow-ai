# CMS basic RAG — Phase 4

Phase 4 connects the existing semantic search to a constrained answer-generation
interface, Pydantic validation, and exact CMS citations. No embeddings, chunks,
collections, retrieval ranking, or source selections were redesigned.

The verified generator is `deterministic / first-evidence-v1`, an offline test
double, **not an LLM**. It quotes the first eligible chunk. No OpenAI credential
was present, so no external model quality, billing, or live API success is claimed.
The real OpenAI adapter is implemented and tested through simulated HTTP responses.

## Architecture

```mermaid
flowchart LR
    Input[POST /query or rag CLI] --> Gate[Question validation]
    Gate --> Search[Existing NCDIndex.search / MiniLM / Qdrant]
    Search --> Context[Score floor / substantive chunks / bounded JSONL]
    Context --> Provider[OpenAI or deterministic provider]
    Provider --> Parse[Strict Pydantic draft]
    Parse --> Validate[Context membership and exact paragraph validation]
    Validate --> Answer[Cited excerpts or Insufficient evidence.]
```

`generation/runtime.py` lazily loads the existing embedding provider. A process
lock protects its mutable tokenizer during search; this is not query caching.
Qdrant clients are closed per request. The sync FastAPI route executes in the
framework's worker thread pool. Generation and retrieval remain separate modules.

The API now needs the existing ingestion dependencies to embed queries. Docker
installs the CPU PyTorch wheel plus the ingestion lock and mounts the native model
cache read-only. Health checks still concern infrastructure, not index readiness.
An empty index or missing offline model returns structured HTTP 503 from `/query`.

A real portability bug surfaced: Linux CPU PyTorch reports `2.8.0+cpu` while macOS
reports `2.8.0`. The embedding identity normalizes only the `+cpu` suffix. All other
configuration comparisons remain exact; indexed payloads and IDs are unchanged.
The Docker CPU runtime was tested against the existing macOS-produced vectors.
This is not a guarantee of bitwise numerical parity across platforms.

## Context and prompt

Prompt version: **`cms-extractive-v1`**, in `generation/prompts.py`.
The user question is JSON-escaped after `QUESTION_JSON`. Evidence is one JSON
object per line after `EVIDENCE_JSONL`; embedded newlines are escaped. The stable
whitelist includes actual NCD ID/version, title, manual section, source field and
section, effective/termination dates when present, snapshot date, text and chunk ID.
Continuation and section offsets/counts describe chunk boundaries. Keywords,
revision-history HTML, page numbers, scores and unrelated raw metadata are omitted.
A missing termination date is not interpreted as current coverage.

Context preserves search order, deduplicates IDs, drops scores below the configured
floor and excludes empty/`N/A`/`Not applicable` bodies after removing the exact
section heading. The 24,000-character budget includes serialized JSON lines;
chunks are omitted whole instead of truncating conditions. This is a character
budget, not a provider-token count. It can reduce evidence recall.

The prompt treats both evidence and questions as data, forbids outside knowledge,
medical advice, individual coverage decisions, unsupported interpretation, invented
metadata and similarity-as-confidence. This phase deliberately supports direct
excerpts rather than free-form policy interpretation. The real model must select
whole contiguous paragraphs, preserving relevant conditions and exceptions, or
abstain if it cannot answer the question. This conservative restriction makes
literal support testable; it does not prove semantic relevance or completeness.

## Providers and configuration

`GenerationProvider.generate(question, context)` returns JSON. Providers expose
`name` and `model`, recorded in every answer, including pre-generation abstentions.
Those fields identify the configured provider, not proof that it was invoked.
`abstention_reason` indicates the gate used.

- `RAG_PROVIDER=deterministic`: offline, stable first-eligible-chunk test double.
  Its model name is fixed to `first-evidence-v1` and cannot masquerade as OpenAI.
- `RAG_PROVIDER=openai`: `RAG_MODEL=gpt-4.1-mini` by default and `OPENAI_API_KEY`
  from environment or ignored `.env`. Uses HTTPX and the Responses API with strict
  JSON Schema, `store=false`, and a 30-second HTTP timeout. No extra SDK dependency.
  It has no tools, web search, conversation memory or retries. Explicitly selecting
  OpenAI without a key fails with 503; it never silently switches to a mock.

The request structure follows the official
[OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).
A valid schema does not itself establish factual support. Account/model availability
and live behavior still require a credentialed run.

Other settings: `RAG_TOP_K=5`, `RAG_MIN_SCORE=0.6`, `RAG_CONTEXT_CHARS=24000`,
`RAG_PROVIDER_TIMEOUT_SECONDS=30`, `RAG_MODEL_CACHE=.cache/models`,
`RAG_EMBEDDING_OFFLINE=true`, `RAG_QDRANT_ALIAS=careflow_cms_ncd`.
Provider timeout is an HTTP network timeout, not a total request deadline; first
model loading, the retrieval lock, and CPU inference have no wall-clock deadline.

## Responses and citations

The internal strict `GenerationDraft` contains `insufficient_evidence: bool` and
`quotes: [{chunk_id: str, quote: str}]`. Extra fields and incorrect types fail.
The server renders accepted quotes with a `CMS evidence [chunk_id]:` prefix;
there is no model-generated uncited prose in the public answer.

`RAGAnswer` contains:

| Field | Meaning |
| --- | --- |
| `answer` | Validated evidence excerpts or exactly `Insufficient evidence.` |
| `citations` | Exact source references for quoted chunks |
| `insufficient_evidence` | Explicit abstention flag |
| `retrieved_chunk_ids` | Original retrieval IDs, including chunks excluded from context |
| `model_provider`, `model_name` | Configured generation provider identity |
| `prompt_version` | Version of the prompt contract |
| `abstention_reason` | Nullable, machine-readable gate reason |

Each citation contains the native `NCD_id` as `document_id`, `NCD_vrsn_num` as
`document_version`, title, exact indexed section, chunk ID, and indexed CMS viewer
URL (falling back to the indexed source URL). The model supplies only chunk IDs;
the server supplies all citation metadata. No page or confidence field is emitted.

Every quote must reference a chunk actually supplied to the provider, not merely
one in the original retrieval set. It must exactly match contiguous whole
paragraphs within that chunk and contain more than a heading/placeholder. Invalid
citations or quotes cause the **entire answer** to abstain; a partially valid answer
is not returned. Duplicates are removed. More than eight excerpts is rejected.
Malformed JSON/schema is HTTP 502, not a false claim of insufficient CMS evidence.

Exact quotes can still be selectively misleading, irrelevant, or incomplete.
Paragraph boundaries at a chunk edge are not necessarily boundaries of the full
source section. This remains a documented limitation, especially for the mock.

## Insufficient evidence and errors

Deterministic pre-checks reject a question containing only generic question/coverage
words (for example `Is it covered?`), no search results, or no eligible context.
Post-checks handle model abstention, missing citations, invalid IDs and unsupported
quotes. These are risk-reduction measures, not a comprehensive intent classifier
or an entailment model. A specific but ambiguous question may pass the first gate.

The cosine floor of 0.6 is a **development heuristic**, chosen below the lowest
positive smoke-query top score (~0.651). Observed dental, chemotherapy and unrelated
technical negatives had top scores ~0.299, ~0.457 and ~0.166. This tiny, selected
set does not calibrate a universal threshold. Related but unanswerable questions
can score above it; valid paraphrases can score below it. The deterministic provider
cannot reason about that distinction. Never equate cosine with answer confidence.

`POST /query` accepts one stripped nonblank question of at most 4,000 characters.
HTTP 200 covers answers and evidence abstentions; request-schema errors are 422.
Errors use `{"error":{"code":"..."}}`: malformed output/provider failure 502,
missing credential/model/index or retrieval failure 503, provider timeout 504.
Upstream exception bodies and secrets are not returned. No request IDs existed in
the earlier architecture; broader reliability instrumentation remains Phase 13.

## Actual smoke observations

Full unabridged answers, citations, top-five scores and cited text are saved in
[phase4_rag_results.json](phase4_rag_results.json). Source-by-source review notes
are in [phase4_rag_review.json](phase4_rag_review.json). These are observations from
real MiniLM/Qdrant retrieval with a deterministic generator, not full RAG evaluation.

Four compact cases provide directly relevant excerpts with exact citations:

| Question topic | NCD/version | Exact chunk ID | Section |
| --- | --- | --- | --- |
| Hospital-bed prescription | 227/1 | `0364e913-f508-5d9e-a928-d9266d5b7741` | B. Physician's Prescription |
| Unattended sleep tests | 330/1 | `beae40ce-4792-5578-80c8-afd649db96aa` | B. Nationally Covered Indications |
| Seat-elevation evaluation | 376/1 | `d760711e-bf95-5e64-9d58-31510aba392e` | B. Nationally Covered Indications |
| Inner-ear oxygen/carbon therapy | 43/1 | `dc2a342a-5448-50b4-b087-836666a5fa08` | indctn_lmtn |

For the actual question “What must a physician prescription document to justify a
hospital bed?”, the returned text is:

```text
CMS evidence [0364e913-f508-5d9e-a928-d9266d5b7741]:
B. Physician's Prescription

The physician's prescription, which must accompany the initial claim, and supplementing documentation when required, must establish that a hospital bed is medically necessary. If the stated reason for the need for a hospital bed is the patient's condition requires positioning, the prescription or other documentation must describe the medical condition, e.g., cardiac disease, chronic obstructive pulmonary disease, quadriplegia or paraplegia, and also the severity and frequency of the symptoms of the condition that necessitates a hospital bed for positioning.

If the stated reason for requiring a hospital bed is the patient's condition requires special attachments, the prescription must describe the patient's condition and specify the attachments that require a hospital bed.
```

Dental implants, a pancreatic-cancer chemotherapy regimen, and Kubernetes ingress
returned `Insufficient evidence.` with `no_eligible_evidence`. “Is it covered?”
returned the same answer with `ambiguous_question`. The inspection script separately
retrieves that ambiguous query to expose scores; the service itself skips retrieval.

Oxygen and CPAP answers include the requested facts but extend into incomplete
neighboring criteria. The infusion-pump excerpt is overinclusive. The mobility
answer is only partial: its top chunk omits the preceding mobility-limitation
definition. These are quality limitations, not counted as successful full answers.

### Seat elevation

The existing top hit remains the `C. Nationally Non-Covered Indications / N/A`
chunk `d099d33f-7cb8-5474-814e-60f7bdc5f76a`, score ~0.832. The substantive B section
is rank 2. General placeholder filtering removes rank 1 from provider context;
the deterministic answer quotes rank 2, including specialty evaluation and evaluator
qualifications. The original rank-1 ID remains in `retrieved_chunk_ids`.
With top-k=1 the system abstains; filtering cannot recover evidence not retrieved.
No query-specific rule or rank manipulation was introduced.

This phase is vector-only. Phase 5 will add BM25 and hybrid retrieval so exact
policy terminology can complement semantic matching. Reranking belongs to Phase 6;
none was implemented here. Future generation work must also assess relevance and
completeness independently of literal citation validity.

## Reproduce

Install the existing development lock and run Phase 3 ingestion first if the
reviewed index/model cache is absent. No new native dependencies were needed.

```bash
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m ingestion.cli ingest --offline
.venv/bin/python -m ingestion.cli rag --offline \
  "What must a physician prescription document to justify a hospital bed?"
curl --fail http://localhost:8000/query -H 'Content-Type: application/json' \
  -d '{"question":"What specialty evaluation is required for power wheelchair seat elevation equipment?"}'
.venv/bin/python scripts/verify_basic_rag.py --output /tmp/phase4-rag-results.json
```

Without a cached model, run the initial ingestion without `--offline` as documented
in Phase 3. The CLI prints the complete JSON response, including answer, citations,
retrieved IDs and abstention status. API and CLI use the same service and provider
settings. CLI provider failures return a JSON error on stderr and nonzero exit.

For an actual OpenAI run, set `RAG_PROVIDER=openai`, `RAG_MODEL` and `OPENAI_API_KEY`
in `.env` (never commit it), then run the same CLI. Recreate the backend container
for changed Compose environment settings. There is no fabricated external fallback.

### Verification environment and commands

Another local project occupied ports 8000, 6333 and 6379. Its containers were left
running. This repository uses its retained `careflow-ai_*` volumes and alternate
ports during verification:

```bash
BACKEND_PORT=18000 QDRANT_PORT=16333 REDIS_PORT=16379 \
  docker compose up --build -d --wait --wait-timeout 180
export QDRANT_URL=http://localhost:16333
export REDIS_URL=redis://localhost:16379/0
export CAREFLOW_API_URL=http://localhost:18000
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 CAREFLOW_RAG_INTEGRATION=1 \
  .venv/bin/pytest -q
.venv/bin/python scripts/inspect_cms_ncd.py --check docs/cms_inspection/ncd_profile.json
.venv/bin/python scripts/verify_basic_rag.py --output docs/phase4_rag_results.json
.venv/bin/python -m ingestion.cli rag --offline \
  "What must a physician prescription document to justify a hospital bed?"
.venv/bin/python -m pip check
```

Port defaults are unchanged. To keep alternate ports across Compose runs, put
`BACKEND_PORT=18000`, `QDRANT_PORT=16333`, `REDIS_PORT=16379`, and corresponding
native service URLs in the ignored `.env`. `CAREFLOW_API_URL` only configures live
tests. Existing test assertions were retained; the old hardcoded API base URL was
made configurable to avoid accidentally testing the other application.

See the final validation record below for executed results. Initial failures were
an incorrect Qdrant endpoint and the CPU suffix mismatch; the first full integration
run reached the old container while its replacement was still building. Those
failures were corrected before the final run. The source archive was not downloaded
again and the collection was not rebuilt.

### Final validation record

- Default suite: **74 passed, 13 skipped** (opt-in live checks), 3.15 seconds.
- All Phase 1–4 flags enabled: **87 passed**, 9.30 seconds.
- Ruff lint passed; all **40 Python files** passed formatting checks.
- Phase 2 archive/profile validation passed unchanged.
- Native and Docker `pip check`: no broken requirements.
- Docker build and Compose wait completed successfully; backend health is OK.
- Four direct container API cases returned 200. The hospital-bed response exactly
  matched native CLI JSON. Top-k=1 seat elevation abstained as expected.
- [phase4_api_results.json](phase4_api_results.json) records exact API responses,
  CLI parity, the retained collection and snapshot hash.
- Collection remains `careflow_cms_ncd__5ce29cd4691dc56423f2__279ea98f`, **39 points**.
- `.env`, model cache and raw archive remain Git-ignored. No Git commit was made;
  the repository was already entirely untracked on entry.

The only pytest warning is the existing Starlette/AnyIO `BlockingPortal`
deprecation. The tokenizer emits a non-failing performance advisory. Native pip
reported an unavailable optional cache and completed normally. No live OpenAI
verification was possible without a credential. These timings are test-run durations,
not API latency benchmarks.

Local alternate port settings were saved to the ignored `.env`, preserving other
settings. On this machine, use `http://localhost:18000/query` and set
`CAREFLOW_API_URL=http://localhost:18000` for live tests.

## Files changed in Phase 4

| Files | Change |
| --- | --- |
| `backend/app/generation/{__init__,models,context,prompts,providers,service,runtime}.py` | New generation package, models, prompt, providers, context, validation and retrieval wiring |
| `backend/app/api/query.py` | New query endpoint |
| `backend/app/main.py`, `backend/app/core/config.py` | Route registration and environment settings |
| `ingestion/cli.py` | RAG subcommand and validated options |
| `ingestion/embeddings/providers.py` | CPU build suffix normalization for package identity |
| `backend/Dockerfile`, `docker-compose.yml` | CPU inference dependencies, model mount, provider settings and optional host ports |
| `.env.example` | Document generation settings and port defaults |
| `.env` (ignored) | This machine's alternate service ports and native URLs |
| `tests/test_basic_rag.py`, `tests/test_basic_rag_live.py` | Unit/API/provider/error and opt-in live RAG checks |
| `tests/test_integration.py` | Configurable API test base URL; existing assertions retained |
| `scripts/verify_basic_rag.py` | Repeatable live smoke artifact generation |
| `docs/cms_basic_rag.md` | Phase 4 design, examples, limits, commands and results |
| `docs/phase4_rag_results.json`, `docs/phase4_rag_review.json`, `docs/phase4_api_results.json` | Actual outputs, source comparison notes and API observations |
| `README.md` | Implemented scope, usage, configuration and current verification ports |

Phase 5 has not started.
