# Phase 8 — structured healthcare data engineering

CMS DE-SynPUF synthetic claims and Synthea synthetic FHIR R4 patient records,
ingested into PostgreSQL as a structured layer that sits alongside the
existing CMS NCD retrieval pipeline. This phase does **not** connect
structured data to the RAG pipeline, does not add routing or agents, and does
not add LangGraph — those are Phase 9+ concerns.

## Synthetic-data statement

Both sources are official, publicly published **synthetic** datasets. No real
patient PHI is used anywhere in this phase:

- **CMS DE-SynPUF** ("Data Entrepreneurs' Synthetic Public Use File") is a CMS
  publication explicitly built to look statistically like Medicare claims
  while containing no real beneficiaries.
- **Synthea** is an open-source population simulator; every patient, encounter,
  condition, procedure, observation and medication in the ingested data is
  algorithmically generated, not drawn from a real person's record.

Using synthetic data is not, and does not imply, HIPAA certification,
clinical validation, or production clinical readiness. No such claim is made
anywhere in this phase.

## Architecture

```
                       CAREFlow AI

   ┌──────────────────────────┐        ┌───────────────────────────┐
   │ UNSTRUCTURED POLICY DATA │        │  STRUCTURED HEALTH DATA    │
   │        (Phases 1-7)      │        │        (Phase 8)          │
   └────────────┬─────────────┘        └─────────────┬──────────────┘
                │                                     │
             CMS NCD                       ┌──────────┴──────────┐
                │                          │                     │
     Dense + BM25 + RRF              DE-SynPUF Claims       Synthea FHIR
                │                     (Beneficiary,          (Patient,
          Cross-Encoder               Inpatient,              Encounter,
                │                     Outpatient)              Condition,
             Evidence                      │                   Procedure,
                                            │                   Observation,
                                            │                   MedicationRequest)
                                            │                     │
                                       checksum-gate         checksum-gate
                                            │                     │
                                        validate +           validate +
                                        quarantine           quarantine
                                            │                     │
                                       normalize             normalize +
                                       (wide -> long)         resolve urn:uuid
                                            │                     │
                                            └──────────┬──────────┘
                                                       │
                                              idempotent PostgreSQL load
                                              (ON CONFLICT DO NOTHING on
                                               natural/deterministic keys)
                                                       │
                                          repository / analytics layer
                                          (parameterized SQL only)
```

These two structured paths remain **independent synthetic populations** —
`synpuf_beneficiaries` and `fhir_patients` share no foreign key and no
identity mapping is invented between them.

## Data sources

| Source | Files used | Origin |
| --- | --- | --- |
| CMS DE-SynPUF Sample 1, 2008 Beneficiary Summary | `DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv` | cms.gov |
| CMS DE-SynPUF Sample 1, Inpatient Claims | `DE1_0_2008_to_2010_Inpatient_Claims_Sample_1.csv` | cms.gov |
| CMS DE-SynPUF Sample 1, Outpatient Claims | `DE1_0_2008_to_2010_Outpatient_Claims_Sample_1.csv` | cms.gov |
| Synthea sample data, FHIR R4, Nov 2021 release | 557 per-patient `Bundle` JSON files | `synthetichealth/synthea-sample-data` |

**Explicitly out of scope for Phase 8:** DE-SynPUF Carrier Claims and
Prescription Drug Events (not ingested — a deliberate, bounded subset, not an
oversight). See "Supported FHIR resources" below for the FHIR side of this
same decision.

Checksums, exact column headers, and row counts for the reviewed source
snapshots are recorded, not hand-typed, in
[docs/cms_inspection/desynpuf_profile.json](cms_inspection/desynpuf_profile.json)
and
[docs/cms_inspection/synthea_profile.json](cms_inspection/synthea_profile.json).
Raw source files are large (up to ~275MB combined) and are **not committed**
— they live in gitignored `data/raw/cms_synpuf/` and `data/raw/synthea/` and
must be downloaded before ingestion (see Reproduction below).

## Development/test subset selection

Full sources are far larger than appropriate for a development corpus
(116,352 beneficiaries; 557 Synthea patients averaging ~1.7MB of FHIR JSON
each). Both subsets are small, deterministic, and their selection method is
recorded alongside the data itself, not only in this document:

- **DE-SynPUF** ([desynpuf_dev_subset.json](cms_inspection/desynpuf_dev_subset.json)):
  `DESYNPUF_ID` sorted lexicographically ascending, filtered to beneficiaries
  present in the 2008 Beneficiary Summary file **and** with at least one
  claim in **both** the Inpatient and Outpatient Sample 1 files (36,314 such
  beneficiaries exist in the full sample); first 15 taken. This guarantees
  the subset exercises all three selected source tables.
- **Synthea** ([synthea_dev_subset.json](cms_inspection/synthea_dev_subset.json)):
  patient bundle filenames sorted lexicographically ascending across the
  557-bundle release; first 5 taken.

Both are development selections for exercising the ETL pipeline, not
representative population samples.

## Supported FHIR resources

Inspecting 30 real bundles before writing any schema (not assuming) found 19
distinct resource types across the sample. Phase 8 supports a deliberately
bounded subset:

**Supported:** `Patient`, `Encounter`, `Condition`, `Procedure`,
`Observation`, `MedicationRequest`.

**Explicitly out of scope, counted but not ingested:** `DiagnosticReport`,
`Claim`, `ExplanationOfBenefit`, `DocumentReference`, `Immunization`,
`SupplyDelivery`, `CareTeam`, `CarePlan`, `Medication`,
`MedicationAdministration`, `ImagingStudy`, `AllergyIntolerance`, `Device`,
`Provenance`. Every ingestion run reports counts of unsupported resource
types encountered (`unsupported_resource_counts` in the ingestion result) —
they are not silently dropped without a trace.

### Real data-modeling findings that shaped the schema

- **`Observation.value[x]` is not uniform.** Across a 30-bundle check: 5,287
  `valueQuantity`, 805 `valueCodeableConcept`, 438 multi-component (no
  top-level value — blood-pressure-style, e.g. separate systolic/diastolic
  sub-observations), and 5 `valueString`. All four are modeled explicitly
  (`fhir_observations.value_type` plus a `fhir_observation_components` child
  table for the component shape). Any value[x] representation not in this
  list (`valueBoolean`, `valuePeriod`, `valueRatio`, ...) — or an Observation
  with neither a value[x] nor a `component` array — is inserted with
  `value_type='unsupported'` and null value columns, not silently dropped
  and not rejected outright, since the code/status/patient/encounter
  linkage is still real and useful even without a parseable value.
- **Multiple `Coding` entries per concept are real, not hypothetical.** One
  Observation in the sample carries both LOINC 8310-5 ("Body temperature")
  and 8331-1 ("Oral temperature") for the same reading. The **first** coding
  becomes the indexed `code`/`code_system`/`code_display`; the **full**
  `coding` array is preserved verbatim in a `codings` JSONB column, so the
  fact that multiple codings existed is never lost. 1,055 of ~6,700 checked
  resources (Condition/Procedure/Observation/MedicationRequest) had more
  than one coding.
- **`MedicationRequest.medication[x]` has two real shapes**:
  `medicationCodeableConcept` (698 of 787 checked) and `medicationReference`
  (89). Since `Medication` is out of scope, `medicationReference`-shaped
  requests cannot be resolved to a code and are **quarantined**
  (rejected with a clear reason), not silently skipped or filled with a
  placeholder. This is a direct, documented consequence of the resource
  boundary above, not a bug: it was observed for real in the actual 5-bundle
  ingestion (3 of 119 MedicationRequests).
- **Coding systems observed: SNOMED CT, LOINC, RxNorm, CVX** — never ICD-10.
  `code_system` is always stored alongside `code`; nothing infers ICD-10.
- **`Procedure.performed[x]`**: only `performedPeriod` was observed in-sample
  (1,477 of 1,477 checked). `performedDateTime` is also supported (a trivial,
  common alternative — mapped to `performed_start == performed_end`); any
  other shape (`performedString`, `performedAge`, `performedRange`) is
  rejected with a clear reason.
- **References use `urn:uuid:<uuid>`**, matching each resource's own
  `fullUrl` within the bundle. References are resolved by building a
  `fullUrl -> resource` index per bundle and looking up the reference string
  directly — never by assuming any relationship between a resource's `.id`
  and its `fullUrl`.

### Deterministic handling of edge cases

| Case | Behavior |
| --- | --- |
| Missing/unresolved `subject` (Patient) reference | **Reject** the resource — patient identity is a required relationship. |
| Missing or unresolved `encounter` reference | Stored as `NULL` — encounter is optional; not an error. Verified with a fixture that omits the reference entirely and one that references an encounter that failed its own validation. |
| Unsupported resource type | Counted per bundle in `unsupported_resource_counts`, never inserted, never silently ignored without a trace. |
| Unsupported `value[x]` / `performed[x]` / `medication[x]` shape | Observation: inserted with `value_type='unsupported'`. Procedure/MedicationRequest: rejected with a specific reason (see above — these types require an identity-bearing field to store at all). |
| Malformed or tampered source bytes | Checksum gate at the whole-archive level and, for Synthea, at the individual bundle-file level, raises before any JSON is parsed. |

## Relational schema

Normalized domain tables, not one giant table. See
[backend/app/db/migrations/0002_synpuf.sql](../backend/app/db/migrations/0002_synpuf.sql)
and
[0003_fhir.sql](../backend/app/db/migrations/0003_fhir.sql)
for full DDL with comments.

**Provenance (shared):** `ingestion_runs`, `source_files`, `schema_migrations`.

**DE-SynPUF:** `synpuf_beneficiaries` (PK = `DESYNPUF_ID`), `synpuf_claims`
(PK = deterministic `uuid5(claim_type, claim_id, segment)` — see below),
`synpuf_claim_diagnoses`, `synpuf_claim_procedures`, `synpuf_claim_lines`
(each normalizing a wide, repeated-column group from the source CSV into a
long/normalized table).

**Synthea FHIR:** `fhir_patients` (PK = `Patient.id`), `fhir_encounters`,
`fhir_conditions`, `fhir_procedures`, `fhir_observations`,
`fhir_observation_components`, `fhir_medication_requests`. All primary keys
are the FHIR resource's own `id`.

**No foreign key exists between the `synpuf_*` and `fhir_*` table groups.**
This is deliberate: DE-SynPUF beneficiaries and Synthea patients are
independent synthetic populations, and Phase 8 does not invent a
cross-dataset identity mapping.

### Claim identity: an empirical finding, not an assumption

Before finalizing the claims primary key, `CLM_ID` uniqueness was checked
directly against the real Sample 1 files (not assumed):

- 68 inpatient and 10,975 outpatient claims have **more than one `SEGMENT`
  row** sharing the same `CLM_ID` — so `CLM_ID` alone is not unique even
  within one claim type.
- `CLM_ID` never overlaps between the inpatient and outpatient files.
- `(claim_type, claim_id, segment)` **is** unique within each file (verified:
  66,773 inpatient rows → 66,773 unique triples; 790,790 outpatient rows →
  790,790 unique triples).

`synpuf_claims.claim_row_id` is therefore a deterministic
`uuid5(NAMESPACE_URL, "careflow:synpuf:{claim_type}:{claim_id}:{segment}")`
— matching the existing `chunk_id` convention from Phase 3 — with
`UNIQUE(claim_type, claim_id, segment)` enforcing and documenting the real
natural key. Child tables reference the single-column `claim_row_id`.

### Indexes

Added where an anticipated query needs them: beneficiary/patient IDs on
every child table, encounter references, claim date ranges, and
`(code, code_system)` on every clinical coding table. Not added
speculatively beyond that.

## ETL stages: raw → validated → normalized → PostgreSQL

1. **Raw**: the reviewed source archive/bundle files, checksum-gated against
   `docs/cms_inspection/*_profile.json` before anything is parsed. A changed
   archive, changed headers, changed row/bundle count, or tampered bundle
   content fails here — nothing malformed reaches the next stage.
2. **Validated / quarantined**: each row (DE-SynPUF) or resource (FHIR) is
   individually validated. Malformed rows are **not** silently discarded —
   they are collected as `RejectedRecord(file/resource_type, natural_key,
   reason)` and reported in the ingestion result and in `ingestion_runs`,
   while valid rows continue through the pipeline. This is deliberately
   *not* an all-or-nothing validation (unlike the Phase 2 CMS NCD pipeline)
   — DE-SynPUF and FHIR are large, heterogeneous real-world sources where
   per-record quarantine is the honest approach.
3. **Normalized**: wide DE-SynPUF columns (`ICD9_DGNS_CD_1..N`,
   `ICD9_PRCDR_CD_1..N`, `HCPCS_CD_1..N`) become long rows in the diagnosis/
   procedure/line child tables, preserving the source column position as
   `sequence`/`line_number` (not compacted — a blank `ICD9_DGNS_CD_2` with a
   populated `_3` yields sequences `(1, 3)`, not `(1, 2)`). FHIR references
   are resolved to internal IDs; coding is split into a primary
   `code`/`code_system`/`code_display` plus a full `codings` JSONB array.
4. **PostgreSQL**: one transaction per ingestion run. `ON CONFLICT DO
   NOTHING` on natural or deterministic primary keys — see Idempotency.

## Provenance

Every ingestion run creates one `ingestion_runs` row (source, start/end
time, status, records read/accepted/rejected, a source fingerprint) and one
`source_files` row per source file actually read (origin URL, SHA-256,
byte size). DE-SynPUF rows carry their own `source_row_sha256`
(canonical-JSON hash of the raw CSV row); FHIR patient rows carry
`source_bundle_sha256`; every other FHIR row is traceable to its bundle via
`run_id -> source_files`.

## Idempotency

Every write uses `ON CONFLICT (<natural or deterministic key>) DO NOTHING`.
A second run of the same ingestion against the same subset inserts zero new
domain rows — verified directly against the live database, not only
asserted by a test:

| Table | Before 2nd run | After 2nd run |
| --- | ---: | ---: |
| `synpuf_beneficiaries` | 15 | 15 |
| `synpuf_claims` | 219 | 219 |
| `synpuf_claim_diagnoses` | 732 | 732 |
| `synpuf_claim_procedures` | 29 | 29 |
| `synpuf_claim_lines` | 848 | 848 |
| `fhir_patients` | 5 | 5 |
| `fhir_encounters` | 177 | 177 |
| `fhir_conditions` | 187 | 187 |
| `fhir_procedures` | 234 | 234 |
| `fhir_observations` | 1,341 | 1,341 |
| `fhir_observation_components` | 865 | 865 |
| `fhir_medication_requests` | 116 | 116 |

Existing rows are never updated on a rerun — if source content changes for
an already-loaded natural key, the **first** load wins and the change is
silently ignored by design (a documented limitation, not a bug: this phase
does not implement upsert/versioning semantics).

## Data quality

`python -m ingestion.cli quality-check` reports, against what is actually
loaded: duplicate natural IDs (0, enforced by primary key and re-verified
explicitly), orphan claims/references via `LEFT JOIN` (0, enforced by
foreign key and re-verified explicitly), negative payment amounts (0,
enforced by `CHECK`), and — what constraints alone cannot express — the
`Observation.value_type` distribution and how many clinical resources have
no encounter link. Constraint enforcement is also verified independently of
the application layer in `tests/test_structured_db_constraints.py`, which
attempts raw invalid inserts directly and confirms PostgreSQL itself refuses
them (`ForeignKeyViolation`, `CheckViolation`, `UniqueViolation`).

### Real rejections observed on the actual dev subset (not synthetic examples)

- **2 outpatient claim segments** with blank `CLM_FROM_DT`/`CLM_THRU_DT`
  (continuation-segment rows where dates were only populated on segment 1).
- **1 outpatient claim** with a genuinely negative `CLM_PMT_AMT` (-$10.00).
- **3 `MedicationRequest`s** using the unsupported `medicationReference`
  shape.

All three data sets reproduced identically on rerun — quarantine is
deterministic, not incidental.

## Structured query / repository layer

[backend/app/repository/synpuf.py](../backend/app/repository/synpuf.py),
[fhir.py](../backend/app/repository/fhir.py), and
[analytics.py](../backend/app/repository/analytics.py) expose deterministic,
parameterized-SQL-only methods: beneficiary/claim lookups with attached
diagnoses/procedures/lines, patient summaries with encounters/conditions/
procedures/observations/medications, and count/sum/frequency analytics
(claim counts and payment totals by type, diagnosis/procedure/HCPCS
frequency, FHIR encounter counts by class, condition/procedure/medication
frequency). No SQL is built from user or LLM input anywhere in this layer.
No risk scoring or "high-risk" labeling is implemented — plain counts and
sums only, since no validated risk model exists in this phase.

## CLI

Added to the existing `ingestion/cli.py` (`python -m ingestion.cli <command>`):

```bash
python -m ingestion.cli ingest-synpuf
python -m ingestion.cli ingest-fhir
python -m ingestion.cli validate-sources
python -m ingestion.cli ingestion-summary --limit 10
python -m ingestion.cli quality-check
```

## Testing

- `tests/test_db_migrations.py` — migration ordering, idempotency, tamper
  detection (6 tests).
- `tests/test_synpuf_ingestion.py` — DE-SynPUF parsing/validation/quarantine,
  claim identity, live source loading and idempotent ingestion (16 tests).
- `tests/test_fhir_ingestion.py` — FHIR parsing, reference resolution, all
  four `Observation` value shapes, multi-coding preservation, unsupported
  resource/value/medication handling, malformed-source rejection, live
  loading and idempotent ingestion (23 tests).
- `tests/test_structured_repository.py` — repository/analytics layer against
  real ingested data (14 tests).
- `tests/test_structured_reports.py` — source validation, ingestion summary,
  quality checks, and the CLI itself as a subprocess (5 tests).
- `tests/test_structured_db_constraints.py` — the database's own constraints,
  independent of application validation (5 tests).

## Known limitations

- Development-scale subsets (15 beneficiaries, 5 patients) — not a claim
  about performance or correctness at full DE-SynPUF/Synthea scale.
- No upsert/versioning: a changed source row for an already-loaded natural
  key is ignored on rerun, not merged or updated.
- DE-SynPUF is scoped to Beneficiary Summary, Inpatient, and Outpatient
  Claims only; Carrier Claims and Prescription Drug Events are not ingested.
- Synthea is scoped to 6 resource types; 14 others observed in the real data
  are explicitly out of scope (counted, not ingested).
- `Observation` resources using a `value[x]` shape not yet observed in the
  inspected corpus (e.g. `valueBoolean`, `valuePeriod`) are marked
  `value_type='unsupported'` rather than modeled — none occurred in the
  actual 5-bundle ingestion, so this path is unit-tested but not yet
  exercised by real data.
- No structured-data-to-RAG integration, routing, or agent layer — by design,
  reserved for Phase 9.

## Reproduction

```bash
# Download the reviewed sources (large; not committed — see checksums in
# docs/cms_inspection/desynpuf_profile.json and synthea_profile.json).
mkdir -p data/raw/cms_synpuf data/raw/synthea
curl -sL -o data/raw/cms_synpuf/beneficiary_2008_sample1.zip \
  "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_beneficiary_summary_file_sample_1.zip"
curl -sL -o data/raw/cms_synpuf/inpatient_sample1.zip \
  "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_1.zip"
curl -sL -o data/raw/cms_synpuf/outpatient_sample1.zip \
  "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_outpatient_claims_sample_1.zip"
curl -sSfL -o data/raw/synthea/fhir_r4_nov2021.zip \
  "https://github.com/synthetichealth/synthea-sample-data/raw/main/downloads/synthea_sample_data_fhir_r4_nov2021.zip"

# Apply migrations, then ingest (idempotent — safe to rerun).
.venv/bin/python -m app.db.migrate
.venv/bin/python -m ingestion.cli ingest-synpuf
.venv/bin/python -m ingestion.cli ingest-fhir
.venv/bin/python -m ingestion.cli quality-check

# Tests (default suite skips DB-backed tests; set the flag to run them).
.venv/bin/ruff check . && .venv/bin/ruff format --check .
CAREFLOW_STRUCTURED_INTEGRATION=1 .venv/bin/pytest -q
```
