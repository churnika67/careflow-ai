import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from ingestion.cms_coverage.cleaning import clean_sections
from ingestion.models import Document, digest

SOURCE_URL = "https://downloads.cms.gov/medicare-coverage-database/downloads/exports/ncd.zip"
FIELDS = ("itm_srvc_desc", "indctn_lmtn", "xref_txt", "othr_txt")
DATES = (
    "NCD_efctv_dt",
    "NCD_impltn_dt",
    "NCD_trmntn_dt",
    "trnsmtl_issnc_dt",
    "creatd_tmstmp",
    "last_updt_tmstmp",
    "last_clrnc_tmstmp",
)
BOOLEAN_FIELDS = ("natl_cvrg_type", "under_rvw", "NCD_lab", "NCD_AMA")
COVERAGE = {"1": "full", "2": "restricted", "3": "none"}


def validate_tables(tables: dict, schema: dict) -> list[dict]:
    if set(tables) != set(schema):
        raise ValueError("Unexpected source table inventory")
    for name, rows in tables.items():
        if not rows:
            raise ValueError(f"Empty source table: {name}")
        keys = []
        for row in rows:
            if list(row) != schema[name]["columns"] or any(v is None for v in row.values()):
                raise ValueError(f"Schema/row width mismatch: {name}")
            required = (
                (
                    "NCD_id",
                    "NCD_vrsn_num",
                    "natl_cvrg_type",
                    "cvrg_lvl_cd",
                    "NCD_mnl_sect",
                    "NCD_mnl_sect_title",
                    "NCD_efctv_dt",
                    "pblctn_cd",
                    "under_rvw",
                    "creatd_tmstmp",
                    "last_updt_tmstmp",
                    "last_clrnc_tmstmp",
                    "NCD_lab",
                    "NCD_AMA",
                )
                if name == "ncd_trkg.csv"
                else tuple(row)
            )
            if any(not row[column].strip() for column in required):
                raise ValueError(f"Missing required source value: {name}")
            key = tuple(row[k] for k in schema[name]["primary_key"])
            if any(not k.strip() for k in key):
                raise ValueError(f"Empty primary key: {name}")
            keys.append(key)
            for column in DATES:
                if row.get(column):
                    datetime.fromisoformat(row[column])
        if len(set(keys)) != len(keys):
            raise ValueError(f"Duplicate primary key: {name}")
    policies = tables["ncd_trkg.csv"]
    policy_keys = {(r["NCD_id"], r["NCD_vrsn_num"]) for r in policies}
    benefits = {r["bnft_ctgry_cd"] for r in tables["ncd_bnft_ctgry_ref.csv"]}
    publications = {r["pblctn_cd"] for r in tables["ncd_pblctn_ref.csv"]}
    for row in tables["ncd_trkg_bnft_xref.csv"]:
        if (row["NCD_id"], row["NCD_vrsn_num"]) not in policy_keys:
            raise ValueError("Orphan policy crosswalk")
        if row["bnft_ctgry_cd"] not in benefits:
            raise ValueError("Orphan benefit category")
    observations = []
    for row in policies:
        if row["pblctn_cd"] not in publications:
            raise ValueError("Orphan publication")
        if any(row[f] not in {"True", "False"} for f in BOOLEAN_FIELDS):
            raise ValueError("Invalid boolean domain")
        if not row["NCD_mnl_sect_title"].strip() or not row["NCD_mnl_sect"].strip():
            raise ValueError("Missing title or manual section")
        if not row["NCD_efctv_dt"]:
            raise ValueError("Missing effective date")
        flags = []
        if row["cvrg_lvl_cd"] not in COVERAGE:
            flags.append("unknown_coverage_code")
        if "RETIRED" in row["NCD_mnl_sect_title"] or row["NCD_trmntn_dt"]:
            flags.append("retirement_evidence")
        if not row["indctn_lmtn"].strip():
            flags.append("blank_indications")
        if row["NCD_trmntn_dt"] and row["NCD_trmntn_dt"] < row["NCD_efctv_dt"]:
            flags.append("termination_before_effective")
        if flags:
            observations.append(
                {"NCD_id": row["NCD_id"], "version": row["NCD_vrsn_num"], "flags": flags}
            )
    return observations


def load_documents(
    archive: Path, subset_path: Path, profile_path: Path
) -> tuple[list[Document], dict]:
    subset = json.loads(subset_path.read_text())
    profile = json.loads(profile_path.read_text())
    raw = archive.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != subset["archive_sha256"] or sha != profile["archive_sha256"]:
        raise ValueError("Archive checksum does not match the reviewed Phase 2 snapshot")
    expected = [{k: r[k] for k in subset["records"][0]} for r in profile["selected_records"]]
    if subset["records"] != expected or len(expected) != 8:
        raise ValueError("Selection differs from the eight Phase 2 document versions")
    csv.field_size_limit(10_000_000)
    with ZipFile(io.BytesIO(raw)) as outer:
        if outer.testzip():
            raise ValueError("Corrupt outer ZIP")
        with ZipFile(io.BytesIO(outer.read("ncd_csv.zip"))) as inner:
            if inner.testzip():
                raise ValueError("Corrupt nested ZIP")
            tables = {}
            for name in inner.namelist():
                if name.endswith(".csv"):
                    reader = csv.DictReader(
                        io.StringIO(inner.read(name).decode("utf-8"), newline=""), strict=True
                    )
                    if reader.fieldnames != profile["tables"].get(name, {}).get("columns"):
                        raise ValueError(f"Unexpected headers: {name}")
                    tables[name] = list(reader)
    observations = validate_tables(tables, profile["tables"])
    by_key = {(r["NCD_id"], r["NCD_vrsn_num"]): r for r in tables["ncd_trkg.csv"]}
    benefit_ref = {r["bnft_ctgry_cd"]: r for r in tables["ncd_bnft_ctgry_ref.csv"]}
    publication_ref = {r["pblctn_cd"]: r for r in tables["ncd_pblctn_ref.csv"]}
    flagged = {(r["NCD_id"], r["version"]) for r in observations}
    documents = []
    for selected in subset["records"]:
        key = (selected["NCD_id"], selected["NCD_vrsn_num"])
        row = by_key.get(key)
        if row is None or any(row[k] != v for k, v in selected.items()):
            raise ValueError(f"Selected record mismatch: {key}")
        if key in flagged or row["natl_cvrg_type"] != "True":
            raise ValueError(f"Selected policy requires review: {key}")
        categories = [
            benefit_ref[r["bnft_ctgry_cd"]]
            for r in tables["ncd_trkg_bnft_xref.csv"]
            if (r["NCD_id"], r["NCD_vrsn_num"]) == key
        ]
        metadata = {
            "document_id": f"cms:ncd:{key[0]}",
            "document_version_id": f"cms:ncd:{key[0]}:v{key[1]}",
            "NCD_id": key[0],
            "NCD_vrsn_num": key[1],
            "policy_type": "NCD",
            "title": row["NCD_mnl_sect_title"],
            "manual_section": row["NCD_mnl_sect"],
            "coverage_code": row["cvrg_lvl_cd"],
            "coverage_label": COVERAGE[row["cvrg_lvl_cd"]],
            "effective_date": datetime.fromisoformat(row["NCD_efctv_dt"]).date().isoformat(),
            "termination_date": row["NCD_trmntn_dt"] or None,
            "source_dates": {k: row[k] or None for k in DATES},
            "flags": {k: row[k] == "True" for k in BOOLEAN_FIELDS},
            "benefit_categories": categories,
            "publication": publication_ref[row["pblctn_cd"]],
            "transmittal": {
                k: row[k] or None
                for k in ("trnsmtl_num", "trnsmtl_issnc_dt", "trnsmtl_url", "chg_rqst_num")
            },
            "search_keywords": row["ncd_keyword"] or None,
            "revision_history": row["rev_hstry"] or None,
            "source_url": SOURCE_URL,
            "viewer_url": f"https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDId={key[0]}&NCDver={key[1]}",
            "source_file": "ncd.zip!ncd_csv.zip!ncd_trkg.csv",
            "snapshot_sha256": sha,
            "source_record_sha256": digest(row),
            "snapshot_data_as_of": subset["data_as_of"],
            "quality_flags": [],
            "applicability": "reviewed_development_subset_not_current_coverage_certification",
            "page": None,
        }
        sections = tuple(s for field in FIELDS for s in clean_sections(row[field], field))
        if not any(s.field == "indctn_lmtn" and s.text.strip() for s in sections):
            raise ValueError(f"No visible policy evidence: {key}")
        documents.append(Document(metadata, sections))
    return documents, {
        "source_records": len(by_key),
        "selected_documents": len(documents),
        "unselected_records": len(by_key) - len(documents),
        "source_observations": observations,
        "selected_failures": 0,
    }
