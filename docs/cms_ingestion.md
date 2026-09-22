# CMS NCD ingestion: Phase 3

The implemented pipeline ingests only the eight reviewed NCD document versions
from Phase 2. It produces **32 sections and 39 chunks**, embeds them locally, and
stores vectors and traceable payloads in Qdrant. It does not generate answers.

## Inputs and reproducibility

Use Python 3.12 and run commands from the repository root. Required inputs:

- `data/raw/cms_coverage/ncd.zip` from the [official CMS download listing](https://www.cms.gov/medicare-coverage-database/downloads/downloadable-databases.aspx).
- `docs/cms_inspection/dev_subset.json` with the eight selected versions.
- `docs/cms_inspection/ncd_profile.json` with the verified snapshot/schema.

The inspected archive is [CMS Current NCD Data](https://downloads.cms.gov/medicare-coverage-database/downloads/exports/ncd.zip),
data as of **2026-08-30**, released **2026-09-03**. SHA-256:

```text
735619558de8759427d5fe71989d06b48e5625376594fe94efa7a60f7e152ca3
```

The parser reads `ncd.zip!ncd_csv.zip!ncd_trkg.csv`,
`ncd_trkg_bnft_xref.csv`, `ncd_bnft_ctgry_ref.csv`, and `ncd_pblctn_ref.csv`.
It does not parse the included MDB or use LCDs/Articles. Original downloads remain
ignored by Git. CMS can replace the ZIP at this URL: a changed checksum fails
before model loading or database writes. Do not change the reviewed checksum to
force a new snapshot through. Availability of the exact old archive from a future
clean checkout is an upstream limitation; preserve your original download.

For a clean Python environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
# Copy .env.example to .env only if you do not already have a configured .env.
docker compose up --build -d --wait --wait-timeout 180
.venv/bin/python scripts/inspect_cms_ncd.py --check docs/cms_inspection/ncd_profile.json
.venv/bin/python -m ingestion.cli ingest
```

The first ingestion downloads the model. Subsequent runs can add `--offline`.
Model files use `.cache/models/`; `.cache/` is excluded from Git and Docker build
contexts. No API key, patient information, or LLM service is used. The installed
development lock includes ingestion and test dependencies. For ingestion without
test tools, use `requirements-ingestion.lock`. `.[dev,ingestion]` is also available
for development; the lock files pin the resolved versions.

The native pipeline was verified on macOS arm64/CPU. The API Docker image was
built and run on Linux arm64. Ingestion itself was not tested inside that image;
it intentionally does not install the large ML dependency set. Other operating
systems may resolve additional platform-specific PyTorch dependencies.

## Construction, cleaning and provenance

Source validation checks the reviewed archive, exact table/header inventory,
row widths, nonempty unique composite keys, dates, boolean values and foreign-key
references. Unknown coverage codes remain explicit quality observations. The
selected corpus fails closed if a selected record has retirement evidence,
unknown coverage, missing visible indications or a mismatched identity.

The whole export has **357 policy records**. This run deliberately selects eight
and leaves **349 unselected**; these are not ingestion failures. **Zero selected
documents failed.** The original source anomalies remain in the run report.
No status correction or general current-coverage certification is performed.

`NCD_id` plus `NCD_vrsn_num` defines the document version. Benefit associations
are aggregated per version rather than multiplying documents through a one-to-many
join. Publication codes resolve to the actual reference table. Effective,
implementation, termination and source timestamps retain their distinct meanings.

Only `itm_srvc_desc`, `indctn_lmtn`, `xref_txt`, and `othr_txt` become evidence.
BeautifulSoup's HTML parser handles the inspected malformed HTML, entities and
inline markup. The renderer preserves block boundaries, list labels, table cells,
negation, inequalities and link references. It removes script/style/comment content.
It does not fetch links. The inspected top-level lettered headings become sections;
numbered and lower-level criteria remain in the section text. Missing fields do
not create synthetic sections.

Chunk payload metadata includes:

- Native ID/version, application document/version IDs, title and manual section.
- Raw coverage code plus its known label, effective date, nullable termination
  date, original source dates, flags, publication, benefits and transmittal details.
- Keywords and revision history as explicitly separate metadata. They are **not
  embedded** and must not be treated as current-policy evidence by future generation.
- Official archive URL, nested CSV path, archive checksum, snapshot date, canonical
  source-row hash, and derived version-specific CMS viewer link.
- Source field, actual heading, section ordinal/ID, raw-field hash, cleaned-section
  hash, exact character/token span within the cleaned section, continuation flag,
  field-level link references, tokenizer hash and chunking/cleaner configuration.
- Embedding specification and index fingerprint. `page` is always **null**.

Application IDs, hashes, section spans and viewer links are derived fields, not
invented CMS columns. Character offsets refer to the saved **cleaned section**,
not raw HTML offsets. `raw_field_sha256` hashes the original field's UTF-8 bytes;
source-row and cleaned-section hashes use the project's canonical JSON hash
function. `section_links` contains references from its source field, not a claim
that each link occurred inside each chunk.

To trace a result: take its native ID/version and `source_file`, verify the archive
checksum, locate that row and field, verify the raw-field hash, then compare the
chunk's character slice with the saved cleaned section. The raw CMS content remains
the authority; the viewer may have changed since the downloaded snapshot.

## Chunking and embeddings

Defaults are **700 tokens** per chunk and **120 tokens** of overlap, measured by
the embedding model's tokenizer. Chunks never cross source-field/top-level-section
boundaries. Within a long section, the splitter prefers paragraph boundaries in
the latter half of the window and avoids splitting a word when possible. Overlap
is local to a section and can grow slightly to preserve a word boundary.

Small sections remain small: the target is a ceiling, not a padding requirement.
The largest observed chunk has **699 tokens**. Long clauses may still cross a
chunk boundary; section IDs, spans, continuation flags and saved section text
allow later context expansion. A retrieved chunk alone is not necessarily the
complete policy condition.

```bash
.venv/bin/python -m ingestion.cli ingest --offline \
  --chunk-tokens 700 --overlap-tokens 120
```

Chunk IDs are UUIDs derived from the document version/provenance, evidence text,
section spans, tokenizer identity and configuration. Identical inputs/configuration
produce identical IDs. Configuration/content changes create a different index
fingerprint so stale chunks are not mixed into the new active corpus.

Embedding configuration:

| Setting | Verified value |
| --- | --- |
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Revision | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| Sentence Transformers / Transformers / PyTorch | 5.1.0 / 4.55.4 / 2.8.0 |
| Vector dimensions | 384 |
| Device | CPU, two PyTorch threads |
| Normalization | L2 |
| Document input | Title, section label, evidence text |
| Query input | Original query |
| Encoder maximum | 256 tokens including special tokens |
| Long-text strategy | Nonoverlapping 254-token windows, token-count-weighted mean of window embeddings, final L2 normalization |

This window strategy covers every token without silently truncating a 700-token
chunk. It is a design tradeoff, not a claim of optimal long-document retrieval:
averaging can dilute a particular requirement. Queries use the same provider.
The provider protocol lets storage/search use a replacement implementation without
depending on Sentence Transformers internals. A mismatched model specification
is rejected at search time even if its vector dimension happens to match.

The model limit is also described by the
[Sentence Transformers documentation](https://www.sbert.net/examples/sentence_transformer/applications/computing-embeddings/README.html).
Short-input embeddings are tested against native `SentenceTransformer.encode`;
long-input tests verify that changing content beyond the first window changes the vector.

## Qdrant and safe reindexing

Search alias: **`careflow_cms_ncd`**. Collections use **384-dimensional cosine
vectors**, deterministic point IDs and keyword payload indexes on document ID,
version, source field, coverage code and application version ID.

The initial physical name includes a content/configuration fingerprint. Repeated
ingestion uses that generation and upserts the same IDs. Before publication the
writer validates vector dimensions, finite normalized values, exact point count,
and every stored payload/vector through read-back.

```bash
.venv/bin/python -m ingestion.cli ingest --offline
.venv/bin/python -m ingestion.cli ingest --offline --reindex
```

`--reindex` builds a fresh physical collection, verifies it, then atomically moves
the alias. Old collections remain available; failed builds are not published.
The implementation uses [Qdrant aliases](https://qdrant.tech/documentation/manage-data/collections/)
and never deletes the existing generation as part of ingestion. Search resolves
the alias once per call so a generation cannot change halfway through that call.

The CLI uses a local writer lock. This is a single-host development workflow,
not a distributed concurrent-writer protocol. Old/failed generations are retained
and require deliberate later cleanup. Payload indexes improve filtering; no
temporal applicability filter is claimed yet.

Measured verification: first run, repeat and fresh reindex each had **39 points**.
The first/repeat used the same collection and fingerprint. Old/new generations
had identical chunk IDs and payloads, and the old collection remained readable.
The active verified generation is recorded in [phase3_ingestion_results.json](phase3_ingestion_results.json).

## Search and measured results

```bash
.venv/bin/python -m ingestion.cli search --offline --top-k 5 \
  "What must a physician prescription document to justify a hospital bed?"
.venv/bin/python -m ingestion.cli search --offline --document-id 226 --version 3 \
  --source-field indctn_lmtn --coverage-code 2 "CPAP sleep testing documentation"
.venv/bin/python scripts/verify_ncd_search.py --output /tmp/careflow-search-results.json
```

The CLI returns scores, evidence and provenance. Cosine similarity is **not** a
coverage decision or calibrated confidence. The eight smoke cases check exact
document/version, source section and a phrase grounded in the inspected policy.
They also verify returned payloads against source construction, null pages and
metadata filters. This small development check is not the Phase 7 golden dataset.

All **8/8** expected evidence cases appeared in the top five. Seven had the
expected evidence first; the seat-elevation case had it second. Its first result
was a short subsection containing N/A. It is retained as a measured limitation,
not described as a correct answer. Title similarity can dominate short sections.

| Query | Actual first result (ID/version) | Section | Cosine score | Expected evidence rank |
| --- | --- | --- | ---: | ---: |
| What clinical testing must support an initial claim for oxygen therapy at home? | 169/2 | B. Nationally Covered Indications | 0.703698 | 1 |
| What diagnosis and sleep test documentation supports an initial 12-week CPAP trial? | 226/3 | B. Nationally Covered Indications | 0.770839 | 1 |
| How are mobility limitations in activities of daily living at home assessed for a wheelchair? | 219/2 | B. Nationally Covered Indications | 0.650762 | 5 |
| What fasting C-peptide and glucose testing is required for an insulin infusion pump? | 223/2 | B. Nationally Covered Indications | 0.739425 | 1 |
| What must a physician prescription document to justify a hospital bed? | 227/1 | B. Physician's Prescription | 0.792353 | 1 |
| Which unattended home sleep testing devices are covered to diagnose obstructive sleep apnea? | 330/1 | B. Nationally Covered Indications | 0.656319 | 1 |
| What specialty evaluation is required for power wheelchair seat elevation equipment? | 376/1 | C. Nationally Non-Covered Indications | 0.832171 | 2 |
| Is oxygen and carbon dioxide inhalation therapy for inner ear disease reasonable and necessary? | 43/1 | indctn_lmtn | 0.817872 | 1 |

The exact queries, top-five results, scores, spans and ranks are in
[phase3_search_cases.json](phase3_search_cases.json) and
[phase3_search_results.json](phase3_search_results.json).

## Local artifacts and changed files

Each generation writes `documents.jsonl`, `chunks.jsonl`, and `manifest.json`
under `data/processed/cms_ncd/<physical-collection>/`. These files remain Git-ignored.
The manifest records document/section/chunk counts, per-document counts, selected
failures, unselected records, source anomalies, model configuration and publication
details. Ingestion is not an HTTP upload endpoint in this phase.

Created: the `ingestion` package (source, cleaning, chunking, model/provider,
indexing, pipeline, CLI and verification modules); `scripts/verify_ncd_search.py`;
two new ingestion test files; `requirements-ingestion.lock`; this guide and three
Phase 3 case/result JSON files. Updated `pyproject.toml`, `requirements-dev.lock`,
`backend/Dockerfile`, `.gitignore`, `.dockerignore`, and `README.md`.
Existing Phase 1 tests and the Phase 2 inspector/profile were retained.

## Verification commands

Dependencies were installed with `pip install -e '.[dev,ingestion]'`. The package
was refreshed with `pip install --no-deps --no-build-isolation -e .` after adding
the package directories. Model metadata was read from the official Hugging Face
API, and the pinned model was downloaded and exercised locally.

Executed commands include:

```bash
.venv/bin/python -m ingestion.cli ingest --offline
.venv/bin/python -m ingestion.cli ingest --offline          # idempotency run
.venv/bin/python -m ingestion.cli ingest --offline --reindex
.venv/bin/python scripts/verify_ncd_search.py --output docs/phase3_search_results.json
.venv/bin/python scripts/inspect_cms_ncd.py --check docs/cms_inspection/ncd_profile.json
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
CAREFLOW_INTEGRATION=1 CAREFLOW_INGESTION_INTEGRATION=1 .venv/bin/pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m pip install --dry-run -r requirements-dev.lock
docker compose up --build -d --wait --wait-timeout 180
```

Additional read-only checks compared the old/new collections' point counts,
IDs and payloads and confirmed the alias target. Malformed-table, checksum,
selection, invalid-vector and simulated failed-reindex cases exercise safe failure.
The test suite uses synthetic vectors only for storage tests; the live tests use
real model weights and the reviewed CMS archive.

Final verification results:

| Check | Result |
| --- | --- |
| Default tests | 36 passed, 5 opted-out live tests skipped |
| Full suite with both integration flags | 41 passed |
| Ruff lint and formatting | Passed; 29 Python files formatted |
| Existing Phase 2 inspector/profile | Passed unchanged |
| Real semantic checks | 8/8 expected document/version/section/phrase matches in top 5 |
| Repeat ingestion | 39 points; same IDs, fingerprint and collection |
| Fresh reindex | 39 points; identical payloads; previous collection retained |
| Invalid input and simulated failed reindex | Rejected without replacing the published generation |
| Dependency consistency and lock dry run | Passed |
| Docker backend build and Compose readiness | Passed |

One existing Starlette/AnyIO deprecation warning remains in pytest.

Known limitations: eight-policy scope, no current-applicability certification,
mutable upstream archive availability, nonoptimal placeholder-section ranking,
window averaging, and single-host indexing coordination. No production readiness
or formal retrieval quality claim is made. The existing Starlette/AnyIO warning
and a tokenizer padding-performance advisory are nonfatal. No remaining external blocker was identified.

## What to understand

- An **embedding** is a numeric representation of text that places related meanings
  near each other. Here each representation contains 384 numbers.
- We **chunk** because a full policy contains several topics and conditions. A
  focused passage is easier to retrieve and trace than an entire long document.
- **Chunk size and overlap** balance context, precision, repeated storage and
  computation. Overlap helps at boundaries but does not guarantee a complete rule.
- **Qdrant** stores vectors plus point IDs and metadata/evidence payloads. Search
  embeds the query and finds vectors with high cosine similarity, subject to filters.
- **ID plus version** prevents a revised policy from being confused with an older
  one. An ID alone is insufficient for an auditable citation.
- **Provenance** connects a chunk to the exact archive, CSV row, field and cleaned
  section span, making a result inspectable rather than merely plausible.
- This is **not RAG yet**: there is no LLM composing an answer from retrieved text.
  Phase 4 will add evidence-grounded generation, structured responses, citations,
  and insufficient-evidence behavior after approval.

## Five interview questions

1. **How did you make ingestion idempotent?** Deterministic chunk IDs plus a
   corpus/configuration fingerprint and Qdrant upserts; repeated runs kept 39 points.
2. **How do you update an index safely?** Build and verify a new collection before
   atomically switching its alias, retaining the previous generation.
3. **How did you handle MiniLM's short input limit?** I embedded bounded token
   windows and combined them, recording that strategy and testing against truncation.
4. **What source-data problems did you handle?** Undefined coverage codes, retired
   records, sparse fields, malformed HTML, versioned joins and fractional timestamps.
5. **How did you verify retrieval without an LLM judge?** Eight grounded cases
   assert document/version, section and evidence phrase, with exact provenance and
   filter checks. I also reported the seat-elevation ranking failure at rank one.

Suggested commit: `feat: ingest versioned CMS NCD evidence into Qdrant`

Phase 4 requires explicit approval: **“Continue to Phase 4.”**
