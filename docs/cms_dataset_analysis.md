# CMS Medicare Coverage Database: Phase 2 inspection

Inspected September 8, 2026, America/New_York (September 9 UTC).

**Decision:** use eight explicitly selected NCD document versions for the first
development ingestion. The full, small NCD export was profiled to establish its
schema and identify data-quality hazards. LCDs and Articles have separate future
adapters; their official dictionaries were inspected, but their data exports were
not downloaded. No ingestion, cleaning pipeline, embeddings, indexing, retrieval,
RAG, or agents were implemented in this phase.

## 1. Sources, exact files, and scope

The master prompt's [official CMS download URL](https://www.cms.gov/medicare-coverage-database/downloads/downloadable-databases.aspx)
redirects to [MCD Downloads](https://www.cms.gov/medicare-coverage-database/downloads/downloads.aspx).
The saved listing identifies the NCD snapshot as **data as of August 30, 2026,
released September 3, 2026**. The download URL is mutable, so the archive's hash,
not its filename alone, identifies the inspected bytes.

| Artifact | Actual size | Inspection performed |
| --- | ---: | --- |
| [Current NCD Data: `ncd.zip`](https://downloads.cms.gov/medicare-coverage-database/downloads/exports/ncd.zip) | 1,281,194 bytes | Outer and inner archive integrity; all four CSV tables; selected policy narratives |
| Included `ncd data dictionary.pdf` | 252,324 bytes; 8 pages | All pages extracted/read; main schema page visually checked; dated July 31, 2025 |
| [LCD data dictionary](https://www.cms.gov/medicare-coverage-database/downloads/lcd%20data%20dictionary.pdf) | 339,819 bytes; 38 pages | Base schema, lifecycle, crosswalk and relationship sections; main schema page visually checked; dated April 29, 2025 |
| [Article data dictionary](https://www.cms.gov/medicare-coverage-database/downloads/article%20data%20dictionary.pdf) | 423,538 bytes; 49 pages | Base schema, subtype lookup, lifecycle and relationship sections; main schema page visually checked; dated April 8, 2026 |
| Saved download listing, `downloads-page.html` | 114,117 bytes | Source links and snapshot/release dates |

NCD ZIP SHA-256:

```text
735619558de8759427d5fe71989d06b48e5625376594fe94efa7a60f7e152ca3
```

The original archive is at `data/raw/cms_coverage/ncd.zip`. Its contents:

| Outer ZIP member | Uncompressed bytes |
| --- | ---: |
| `ncd data dictionary.pdf` | 252,324 |
| `ncd.mdb` | 4,960,256 |
| `ncd_csv.zip` | 421,836 |
| `readme_first.txt` | 1,789 |

The MDB was inventoried and hashed, **not opened or compared against the CSVs**.
Consequently, this report does not claim verified Access column types or MDB/CSV
equivalence. CSV inspection avoids requiring Microsoft Access for development.
The nested ZIP contains four CSVs plus another `readme_first.txt`.

The committed [source manifest](cms_inspection/source_manifest.json) records URLs,
file sizes, hashes and local write times. The [measured profile](cms_inspection/ncd_profile.json)
also records every archive member's hash. Raw downloads and extracted dictionary
text stay ignored by Git; no policy narratives are added to the repository.

## 2. Actual CSV format and relational schema

All four files decoded strictly as **UTF-8 without a BOM**. They use comma
delimiters and double-quote qualification. Records contain quoted commas,
embedded HTML and embedded newlines. Record separators include CRLF; narrative
cells also contain LF. A line count is therefore not a document count. Python's
standard `csv` reader parsed every row with the expected width.

CSV has no intrinsic SQL types: identifiers, booleans and dates initially arrive
as strings. The types below describe inspected values and proposed conversions,
not inferred Access DDL.

| CSV | Rows | Columns | Key verified unique/nonempty |
| --- | ---: | ---: | --- |
| `ncd_trkg.csv` | 357 | 26 | (`NCD_id`, `NCD_vrsn_num`) |
| `ncd_bnft_ctgry_ref.csv` | 78 | 2 | `bnft_ctgry_cd` |
| `ncd_pblctn_ref.csv` | 42 | 3 | `pblctn_cd` |
| `ncd_trkg_bnft_xref.csv` | 599 | 5 | (`NCD_id`, `NCD_vrsn_num`, `bnft_ctgry_cd`) |

### Main table: every actual column

“Empty” counts cells equal to `""` across 357 rows. It does not mean that Access
NULL semantics were inspected. “Required” reflects the dictionary's Not Null
designation, not a rule invented from this snapshot. Proposed use: **T** =
retrievable narrative, **M** = metadata, **A** = audit/history, **S** = search aid.

| Exact CSV column | Value shape / dictionary meaning | Required | Empty | Proposed use |
| --- | --- | --- | ---: | --- |
| `NCD_id` | Integer-shaped system identifier | Yes | 0 | M: native ID, retained as string |
| `NCD_vrsn_num` | Integer-shaped version, observed 1–11 with gaps | Yes | 0 | M: versioned identity |
| `natl_cvrg_type` | `True` = NCD; `False` = coverage provision in dictionary | Yes | 0 | M: native document-kind flag |
| `cvrg_lvl_cd` | Coverage code; 1, 2, 3 defined; 4 also observed | Yes | 0 | M: raw code and explicit mapping status |
| `NCD_mnl_sect` | Manual section identifier, e.g. `240.4.1` | Yes | 0 | M + S: string, never floating point |
| `NCD_mnl_sect_title` | Policy title | Yes | 0 | M + S: title context |
| `NCD_efctv_dt` | Version effective date | Yes | 0 | M: effective date |
| `NCD_impltn_dt` | Implementation date | No | 139 | M: separate from effective date |
| `NCD_trmntn_dt` | Termination date | No | 345 | M: lifecycle evidence |
| `itm_srvc_desc` | Item/service narrative with HTML | No | 112 | T: background/general section |
| `indctn_lmtn` | Indications and limitations narrative | No | 0 | T: primary policy evidence; one whitespace-only value |
| `xref_txt` | Manual/topic cross-reference narrative | No | 242 | T: separately labeled references; retain link targets |
| `othr_txt` | Other narrative | No | 334 | T: separately labeled supplementary evidence |
| `trnsmtl_num` | Transmittal identifier | No | 96 | M: keep as string |
| `trnsmtl_issnc_dt` | Transmittal issue date | No | 95 | M: distinct date role |
| `trnsmtl_url` | Transmittal URL | No | 147 | M: related source link, not the NCD page URL |
| `chg_rqst_num` | Change request identifier | No | 146 | M: keep as string |
| `pblctn_cd` | Publication reference-table key | Yes | 0 | M: join to number/title |
| `rev_hstry` | Revision-history narrative | No | 102 | A: retain separately; exclude from default current-policy context |
| `under_rvw` | Boolean review flag | Yes | 0 | M: workflow flag, not confidence or retirement |
| `creatd_tmstmp` | Creation timestamp | Yes | 0 | A |
| `last_updt_tmstmp` | Update timestamp | Yes | 0 | A: refresh/change tracking |
| `last_clrnc_tmstmp` | Approval/publication-clearance timestamp | Yes | 0 | A: refresh/change tracking |
| `NCD_lab` | Boolean lab-NCD flag | Yes | 0 | M |
| `ncd_keyword` | Additional search words | No | 195 | S: search aid only, not evidence for an answer |
| `NCD_AMA` | Boolean copyright-notice display flag | Yes | 0 | M: preserve; not a license grant |

Other tables' **complete** headers:

```text
ncd_bnft_ctgry_ref.csv:
  bnft_ctgry_cd, bnft_ctgry_desc

ncd_pblctn_ref.csv:
  pblctn_cd, pblctn_num, pblctn_title

ncd_trkg_bnft_xref.csv:
  NCD_id, NCD_vrsn_num, bnft_ctgry_cd, creatd_tmstmp, last_updt_tmstmp
```

All fields in these three tables had zero empty or whitespace-only cells. Codes
and native IDs should remain strings; publication numbers include values such as
`13-1` and `100-3`. Crosswalk timestamps use the same date parsing rules as the
main table. The dictionary marks every field in these three tables Not Null.

Verified joins:

```text
ncd_trkg.(NCD_id, NCD_vrsn_num)
  -> ncd_trkg_bnft_xref.(NCD_id, NCD_vrsn_num)
  -> ncd_bnft_ctgry_ref.bnft_ctgry_cd

ncd_trkg.pblctn_cd -> ncd_pblctn_ref.pblctn_cd
```

There are **zero orphan references** on these joins. Every policy has at least
one benefit association; the range is 1–72. Joining the main table directly to
all benefit rows expands 357 policies into 599 rows. Aggregate benefit categories
per document version before producing documents, or the index will duplicate
policy evidence.

Two dictionary details demonstrate why the actual files matter: the PDF spells
the final field `NCD_ama`, while the CSV spells it `NCD_AMA`; the benefit-table
usage prose says `benefit_category_cd`, but both actual CSV headers use
`bnft_ctgry_cd`. Use verified headers, with any aliases explicitly documented.

## 3. Observed types, dates, missingness, and hazards

### Domains

| Field | Actual value counts |
| --- | --- |
| `natl_cvrg_type` | `True`: 357; no coverage-provision rows observed |
| `cvrg_lvl_cd` | `1`: 82; `2`: 209; `3`: 64; **`4`: 2** |
| `under_rvw` | `True`: 171; `False`: 186 |
| `NCD_lab` | `True`: 23; `False`: 334 |
| `NCD_AMA` | `False`: 357 |
| `pblctn_cd` | `25`: 355; `26`: 1; `9`: 1 |

The dictionary defines coverage codes 1 = full, 2 = restricted, 3 = none. It does
**not** define 4. Code 4 occurs in document versions **73/3** and **368/1**.
Their narratives were inspected, but they do not establish an authoritative
codebook definition. Preserve `4` and flag it as unmapped; do not silently map it
to denial, approval, or “not applicable.” These records are outside the initial
development subset.

### Date handling

All nonempty values in the seven date/timestamp fields parsed using
`datetime.fromisoformat`. The CSV strings do not carry timezone offsets; the
dictionary specifies UTC for time information. Preserve raw values as well as
typed values, and retain date-only business semantics where appropriate.

| Field | Minimum observed | Maximum observed |
| --- | --- | --- |
| `NCD_efctv_dt` | 1966-01-01 | 2026-06-08 |
| `NCD_impltn_dt` | 1983-03-11 | 2027-01-04 |
| `NCD_trmntn_dt` | 2014-12-18 | 2021-01-01 |
| `trnsmtl_issnc_dt` | 1985-11-01 | 2026-08-27 |
| `creatd_tmstmp` | 2002-11-27 12:10:46 | 2026-08-27 17:35:25 |
| `last_updt_tmstmp` | 2002-12-02 14:14:31 | 2026-08-28 11:49:28 |
| `last_clrnc_tmstmp` | 2002-11-27 12:11:00 | 2026-08-28 11:49:28.133000 |

142 clearance timestamps include fractional seconds. A parser requiring exactly
`%Y-%m-%d %H:%M:%S` would fail on them. Two implementation dates are after the
snapshot date: ID 281 has 2027-01-04, and ID 291 has 2026-10-05. Do not substitute
implementation, transmittal, publication, or crawl dates for policy effective dates.
The dictionary identifies the later of update and clearance timestamps as the
latest document change; future refresh logic should consider both plus a content hash.

### Quality findings and proposed handling

| Finding | Measured evidence | Future handling |
| --- | --- | --- |
| “Current” package contains retired documents | 41 titles contain `RETIRED` | Preserve lifecycle evidence; exclude flagged records from default current-policy retrieval |
| Blank termination does not establish active status | 29 of those 41 have no termination date | Never use `termination IS NULL` as the sole active-policy test |
| Termination precedes version effective date | All 12 populated termination dates precede their record's effective date | Preserve both dates; flag ambiguity, do not “repair” source values |
| Empty evidence can look nonempty | ID 5/version 1 has whitespace-only `indctn_lmtn` | Check visible text after cleanup; do not embed whitespace |
| Optional sections are sparse | E.g. 334/357 empty `othr_txt` values | Omit absent sections; do not manufacture content |
| HTML and multiline evidence | 355 indication cells contain an HTML tag; 283 contain newlines; 5 contain a table tag | Parse CSV first, then HTML; preserve tables, lists, conditions and negation |
| Long narrative fields | Maximum raw indication length 32,758 characters | Use section-aware chunking later; these are character counts, not token counts |
| Versioned identity | 357 distinct IDs in this snapshot, but dictionary key includes version | Keep version in document identity despite this snapshot containing one row per ID |

No literal cell equal to `NULL`, `NONE`, `N/A`, or `NA` was observed (case-insensitive).
This does not mean those strings cannot occur inside a narrative. Blank strings
may become null in the normalized model; valid `False`, `0`, and old dates must
not become null. Parse booleans explicitly: `bool("False")` is incorrect.

Example anomaly: ID 20/version 3 is titled “Electrosleep Therapy - RETIRED,” with
effective date 2023-04-10 and termination date 2021-01-01. Its narrative discusses
retirement. This illustrates source lifecycle complexity, not permission to
overwrite one date with the other. Title matching is a conservative review flag,
not a complete CMS status model.

## 4. Selected development subset and sample records

The full download is already manageable, so no large LCD/Article archive or
combined export was needed. The proposed first ingestion narrows the NCD data to
these **eight exact ID/version pairs**, stored in [dev_subset.json](cms_inspection/dev_subset.json).
Titles and values below come from the CSV, not generated examples.

| Native ID / version | Manual section | Actual title | Effective date | Coverage code | Raw text characters* |
| --- | --- | --- | --- | --- | ---: |
| 43 / 1 | 50.5 | Oxygen Treatment of Inner Ear/Carbon Therapy | 1978-08-01 | 3 | 272 |
| 169 / 2 | 240.2 | Home Use of Oxygen | 2021-09-27 | 2 | 6,557 |
| 219 / 2 | 280.3 | Mobility Assistive Equipment (MAE) | 2005-05-05 | 2 | 10,685 |
| 223 / 2 | 280.14 | Infusion Pumps | 2004-12-17 | 2 | 11,883 |
| 226 / 3 | 240.4 | Continuous Positive Airway Pressure (CPAP) Therapy For Obstructive Sleep Apnea (OSA) | 2008-03-13 | 2 | 9,178 |
| 227 / 1 | 280.7 | Hospital Beds | 1966-01-01 | 2 | 3,444 |
| 330 / 1 | 240.4.1 | Sleep Testing for Obstructive Sleep Apnea (OSA) | 2009-03-03 | 1 | 4,100 |
| 376 / 1 | 280.16 | Seat Elevation Equipment (Power Operated) on Power Wheelchairs | 2023-05-16 | 1 | 2,957 |

\* Sum of the raw `itm_srvc_desc`, `indctn_lmtn`, `xref_txt`, and `othr_txt`
character lengths, including markup: **49,076 characters** across the eight records.
This is not cleaned text size, token count, or an indexing result.

These records were manually read. They provide varied document lengths, positive
and negative indications, nested requirements, cross-references, and documentation
language relevant to operations questions. Oxygen ID 43 intentionally provides
a different policy with overlapping vocabulary; it is useful for later testing
whether retrieval distinguishes a negative policy from a different oxygen use.
This is a development corpus, not a representative evaluation sample or a complete
prior-authorization policy collection.

Concrete structural examples from the inspected records:

- **169/2:** `itm_srvc_desc` contains a general section; `indctn_lmtn` contains
  covered indications, noncovered indications, and other provisions within one
  cell. A CSV field boundary alone is not a sufficient chunk boundary.
- **226/3:** indications include nested numbered criteria and a separate evidence-
  development subsection. A future parser must retain which conditions belong
  together and preserve the scope of each subsection.
- **227/1:** `itm_srvc_desc` and `trnsmtl_url` are empty, but `indctn_lmtn` contains
  substantive sections including prescription/documentation requirements.
  Missing background or a transmittal URL must not discard the whole policy.
- **219/2:** the narrative refers to a flow chart through a link. The linked
  chart was not downloaded. Do not invent its contents or assume all evidence is
  inline in the CSV.

The [official NCD viewer for 169/version 2](https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDId=169&NCDver=2)
was also located to verify an example citation-link pattern. Viewer URLs are not
columns in the export; any generated link is derived provenance, and the saved
archive remains the source for the measured snapshot.

## 5. Proposed text and metadata mapping

This is a design proposal for Phase 3, not implemented ingestion output.

**Retrievable text:** clean HTML from `itm_srvc_desc`, `indctn_lmtn`, `xref_txt`,
and `othr_txt` into distinct, labeled sections. Attach title and manual section
as search context while retaining the original evidence spans. Subdivide actual
headings inside a field when present; do not assume every policy uses A/B/C/D.
Decode entities without dropping inequality symbols, percentages, or units.
Keep lists/table relationships and exceptions; avoid a regex-only tag stripper.

**Search aids:** title, manual section, `ncd_keyword`, and resolved benefit-category
labels may help retrieval. Keywords are explicitly allowed to include terms not
in the policy; they cannot substantiate generated claims. Revision history should
be retained as a separately typed historical section, excluded from ordinary
current-policy context unless the user is asking about changes.

**Metadata:** native ID/version, native kind flag, manual section/title, raw
coverage code and mapping status, date fields, review/lab/copyright flags,
publication reference, benefit-category arrays, transmittal/change request
identifiers, and source timestamps. Keep original values alongside normalized
values where interpretation is involved.

Application-created provenance must be clearly distinguished from CMS columns:

| Proposed application field | How it would be obtained |
| --- | --- |
| `document_id` | Namespaced native ID, e.g. `cms:ncd:169`; an application convention |
| `document_version_id` | Native ID plus version, e.g. `cms:ncd:169:v2` |
| `policy_type` | NCD for the inspected `natl_cvrg_type=True` rows; preserve the native flag; separately model a coverage provision if later observed |
| `source` / `source_url` | Official archive URL plus captured snapshot provenance; optional validated viewer URL |
| `source_file` | `ncd.zip!ncd_csv.zip!ncd_trkg.csv` plus native row key |
| `section` | Original source field and any actually observed heading path |
| `page` | Null/omitted for CSV evidence; dictionary page numbers are not policy page numbers |
| `effective_date` | Parsed `NCD_efctv_dt`, with raw source value retained |
| `chunk_id` | Deterministic ID derived later from version, section, chunk position/content, and chunker version |
| `snapshot_sha256` / `content_sha256` | Computed archive/record content hashes |
| `quality_flags` | Measured anomalies with reasons, not inferred CMS fields |

There is no generic `document_id`, `chunk_id`, `page`, `source`, or unified `status`
column in the NCD CSV. Do not pretend the planned application schema is the source
schema. Keep manual section number distinct from narrative subsection path.

## 6. How NCDs, LCDs, and Articles should differ

Only NCD rows were empirically profiled. Everything about LCD/Article columns
below is **dictionary-derived design**, not a claim about actual CSV headers,
row counts, populated values, or null rates in an uninspected export. Before
implementing either adapter, download its official current export and verify
headers, records, lookup values, dates, and joins as done here.

| Family | Identity and representation | Narrative fields identified in dictionary | Metadata/lifecycle |
| --- | --- | --- | --- |
| NCD | National document version keyed by `NCD_id`, `NCD_vrsn_num` | Four narrative fields listed above | Native coverage code, effective/implementation/termination dates, publication and benefits |
| LCD | Separate local determination keyed by `lcd_id`, `lcd_version`; final display uses `L` plus native ID | `indication`, `doc_reqs`, `coding_guidelines`, `util_guide`, `cms_cov_policy`, `associated_info`, `summary_of_evidence`, `analysis_of_evidence`, `bibliography` when actually populated | Contractor/jurisdiction crosswalks, `status`, `orig_det_eff_date`, `rev_eff_date`, `rev_end_date`, `ent_det_end_date`, `date_retired`, future-retire table |
| Article | Separate supporting document keyed by `article_id`, `article_version`; final display uses `A` plus native ID | `description`, `other_comments`, `cms_cov_policy`, and relevant narrative fields around coding groups | `article_type` joined to `ARTICLE_TYPE_LOOKUP.article_type_id`; publication/effective/end/revision-end/retirement dates; contractor/jurisdiction crosswalks |

Dictionary details that affect the future adapters:

- LCD pages 4–9 distinguish final and proposed documents through `display_id`;
  proposed display identifiers use `DL`. Article pages 4–7 similarly distinguish
  drafts with `display_id` and `DA`. Keep system identity distinct from display
  identity. Proposed/draft material must not be treated as effective coverage.
- The LCD dictionary describes `A` as approved for final documents and `P` as
  approved for display for proposed documents. Article `status` includes `A`
  and `R`. These are not a universal shared enum. Approval alone does not establish
  applicability for a service date, contractor, or jurisdiction.
- These are relational exports, not one giant document table. Use
  `LCD_X_CONTRACTOR` / `ARTICLE_X_CONTRACTOR` and jurisdiction tables as structured
  relationships. Missing crosswalk rows mean absence of supplied association,
  not permission to invent a jurisdiction.
- `LCD_RELATED_DOCUMENTS` includes related LCD/Article IDs and versions;
  `ARTICLE_RELATED_DOCUMENTS` links back to LCDs. Keep document evidence separate
  and connect it with typed relationships instead of merging narratives into one
  undifferentiated document.
- LCD dictionary page 28 says related Article links point to the latest version
  and `r_article_version` may be ignored for that navigation. Preserve the raw
  declared edge **and** the version actually resolved from a snapshot. Do not
  present a latest-version link as an exact historical citation.
- `LCD_RELATED_NCD_DOCUMENTS` / `ARTICLE_RELATED_NCD_DOCUMENTS` provide national
  links. Their dictionaries specify `r_ncd_id=0` as N/A; it must not produce a
  relationship to a fictional NCD 0.
- Article coding tables include covered/noncovered ICD-10 groups and CPT/HCPCS
  groups. Keep code systems, polarity, grouping and qualifiers structured. Do not
  flatten unrelated code rows into narrative claims or assume their values before
  inspecting the actual files.

An Article is not automatically an LCD or a denial rule. Preserve its resolved
subtype and its role as supporting evidence. The NCD-only subset cannot support
claims that depend on uncollected local policies, payer rules, patient records,
or actual prior-authorization outcomes.

## 7. Proposed future ingestion sequence

1. **Acquire and pin:** retain original official archives, download provenance,
   dictionary versions, and checksums. Refuse silent replacement of a reviewed
   snapshot. Inspect schema changes before accepting refreshed files.
2. **Validate source tables:** strict encoding/CSV parsing, exact headers,
   nonempty unique composite keys, domain checks, dates, and reference integrity.
   Emit a quality report and quarantine ambiguous records; never fabricate fixes.
3. **Select:** load the eight reviewed ID/version pairs. Preserve excluded
   records in raw storage. This selection does not certify present-day coverage;
   later applicability must consider the query's service date and policy context.
4. **Resolve relationships:** aggregate benefit categories and publication labels
   per NCD version. Add LCD/Article adapters only after their export inspection.
5. **Clean and section:** process HTML with a parser, retain headings, lists,
   tables, links and original-to-cleaned provenance. Detect empty visible text;
   retain missing sections as missing. Do not fetch referenced URLs indiscriminately.
6. **Chunk:** begin with a configurable target of 700 tokens and 120-token overlap,
   respecting section boundaries and preserving conditions/exceptions together.
   Measure using the selected tokenizer; do not estimate tokens from this report's
   raw character counts. Record chunker configuration for later experiments.
7. **Embed/index in Phase 3:** use the approved embedding provider and Qdrant,
   versioned IDs, idempotent writes, and explicit metadata filters. These steps
   are only described here; no model was downloaded and no collection was created.
8. **Verify in Phase 3:** trace sample search results back to exact source records
   and evidence sections; check missing-evidence behavior and data-quality gates.
   Basic RAG, hybrid retrieval, reranking and evaluation follow their later phases.

No SQL migrations, parsed document outputs, or model dependency changes are needed
for this inspection phase. The inspector writes schema/provenance diagnostics,
not cleaned policy documents or ingestion artifacts.

## 8. Reproduce the inspection

From the repository root, using the Phase 1 environment:

```bash
mkdir -p data/raw/cms_coverage
curl --fail --location --retry 2 --max-time 90 \
  'https://downloads.cms.gov/medicare-coverage-database/downloads/exports/ncd.zip' \
  --output data/raw/cms_coverage/ncd.zip
shasum -a 256 data/raw/cms_coverage/ncd.zip
.venv/bin/python scripts/inspect_cms_ncd.py \
  --check docs/cms_inspection/ncd_profile.json
```

**The CMS URL changes over time.** Download into a separate location if preserving
an existing snapshot. The inspector checks the archive against the selected
snapshot hash and intentionally rejects changed bytes. CMS historical availability
of this exact ZIP has not been verified; a future fresh download may need a new
inspection rather than reproduce this snapshot. Do not edit the manifest hash just
to silence a mismatch.

To write a fresh diagnostic report for the same verified archive:

```bash
.venv/bin/python scripts/inspect_cms_ncd.py --output /tmp/careflow-ncd-profile.json
```

This command does not ingest or extract policy files. Both ZIP layers are read in
memory, avoiding filesystem extraction of archive member paths.

Dictionary downloads used:

```bash
curl --fail --location --retry 2 --max-time 90 \
  'https://www.cms.gov/medicare-coverage-database/downloads/lcd%20data%20dictionary.pdf' \
  --output data/raw/cms_coverage/lcd-data-dictionary.pdf
curl --fail --location --retry 2 --max-time 90 \
  'https://www.cms.gov/medicare-coverage-database/downloads/article%20data%20dictionary.pdf' \
  --output data/raw/cms_coverage/article-data-dictionary.pdf
curl --fail --location --retry 2 --max-time 90 \
  'https://www.cms.gov/medicare-coverage-database/downloads/downloadable-databases.aspx' \
  --output data/raw/cms_coverage/downloads-page.html
```

The NCD dictionary was read from the outer ZIP's `ncd data dictionary.pdf` member.
Bundled `pypdf` extracted dictionary text. Bundled `pdftoppm` rendered NCD page 5,
LCD page 4 and Article page 4 for visual inspection. No project dependencies were
added. PDF extraction is inspection tooling, not the future CMS ingestion parser.

CMS downloads include notices concerning third-party code content. The repository's
MIT license applies to our code, not upstream data. Retain notices and use the
official download workflow; `NCD_AMA=False` is not proof of redistribution rights.
Only public policy material was used, with no patient records or real PHI.

## 9. Files and verification

Created for version control:

- `docs/cms_dataset_analysis.md` — findings and ingestion proposal.
- `docs/cms_inspection/source_manifest.json` — actual source provenance.
- `docs/cms_inspection/ncd_profile.json` — measured full-export diagnostics.
- `docs/cms_inspection/dev_subset.json` — eight exact document versions.
- `scripts/inspect_cms_ncd.py` — reproducible inspection/check command; standard library only.

Updated `README.md` to reflect Phase 2 and point to these instructions. Raw
archives, dictionary PDFs/text, and the saved listing remain under the ignored
`data/raw/cms_coverage/` directory. Temporary PDF preview images are outside the
repository. The backend and infrastructure implementation were not changed.

Commands executed for verification:

```bash
.venv/bin/ruff check scripts/inspect_cms_ncd.py --fix
.venv/bin/ruff format scripts/inspect_cms_ncd.py
.venv/bin/python scripts/inspect_cms_ncd.py --output docs/cms_inspection/ncd_profile.json
.venv/bin/python scripts/inspect_cms_ncd.py --check docs/cms_inspection/ncd_profile.json
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
CAREFLOW_INTEGRATION=1 .venv/bin/pytest -q
git status --short --untracked-files=all
```

Additional Python inspection commands read ZIP inventories, computed hashes,
profiled null/domain/date values, inspected selected narratives, extracted PDF
text with `pypdf.PdfReader`, and generated the source/selection manifests from
actual files. A temporary-directory validation harness ran the inspector against
an altered report, a wrong archive checksum and a nonexistent selected version;
each was required to fail with its specific diagnostic. It also verified all
source-manifest hashes/sizes and called `git check-ignore -q` for every raw file.

| Validation | Final observed result |
| --- | --- |
| Outer and nested ZIP CRC | Pass |
| All CSVs: UTF-8, row widths, unique/nonempty primary keys | Pass |
| All nonempty inspected date fields parse | Pass |
| All three foreign-key joins | Zero orphans |
| Eight selected ID/version/title/section records match source | Pass |
| Recomputed diagnostic report matches saved JSON | Pass |
| All five source artifacts match manifest SHA-256 and sizes | Pass |
| Altered report / wrong hash / nonexistent selected version | All three correctly rejected |
| Raw files excluded by Git | Pass |
| Ruff lint | All checks passed |
| Ruff formatting | 12 files already formatted |
| Default pytest | 11 passed, 2 integration tests skipped, 1 warning |
| Integration-enabled pytest | 13 passed, 1 warning |

No remaining Phase 2 blocker. Source anomalies remain explicitly recorded; a
passing inspection does not mean those policies are safe to treat as current.
The existing Starlette/AnyIO `BlockingPortal` deprecation warning persists.
Network downloads and live integration tests needed approved sandbox escalation.
The bundled runtime lacked `pymupdf`; available `pypdf` handled extraction instead.
Poppler emitted font-cache warnings for the LCD page, but the generated page was
visually inspected and its table was readable. These inspection-tool issues did
not require changes to application dependencies.

## 10. What to understand for an interview

Explain the engineering decision with evidence: “I inspected the real CMS export
before choosing the ingestion schema. It contained four related CSV tables with
357 policy records. I found undocumented coverage code values, retired policies
in the current download, and a blank evidence field, so I designed explicit
quality gates instead of assuming the feed was clean.”

Be prepared to explain why:

- **Source contracts come before parsers.** A dictionary explains meaning; actual
  bytes establish headers, missingness, encoding and data-quality exceptions.
- **Identity is versioned.** Manual section numbers are display/search values;
  native ID plus version identifies the evidence record.
- **Metadata is part of retrieval correctness.** The right topic from the wrong
  date, jurisdiction, document family or lifecycle state can be misleading.
- **Relational joins can duplicate evidence.** Benefit crosswalks must become
  arrays or relationships, not repeated policy documents.
- **Search hints are not evidence.** A keyword match or coverage-level label is
  not sufficient support for a specific operational conclusion.
- **A small corpus needs honest boundaries.** Eight NCDs support development and
  later grounded questions; they cannot resolve every authorization denial.
- **Reproducibility requires provenance.** A URL alone is insufficient when the
  publisher replaces a ZIP. Preserve its checksum, selection and measured profile.

Do not claim this phase built a RAG system, improved retrieval metrics, established
current medical coverage, or ingested LCD/Article data. Those claims are not supported.

Suggested commit message: `docs: inspect CMS NCD snapshot and define ingestion design`

**Phase 3 requires explicit approval: “Continue to Phase 3.”**
