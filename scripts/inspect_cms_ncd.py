"""Profile the downloaded CMS NCD CSVs without cleaning or ingesting policy content.

Standard library only. Reports contain schema and diagnostics, not policy narratives.
The field names and keys below were checked against the actual Phase 2 CSV headers
and the included NCD data dictionary (2025-07-31).
"""

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

KEYS = {
    "ncd_bnft_ctgry_ref.csv": ("bnft_ctgry_cd",),
    "ncd_pblctn_ref.csv": ("pblctn_cd",),
    "ncd_trkg.csv": ("NCD_id", "NCD_vrsn_num"),
    "ncd_trkg_bnft_xref.csv": ("NCD_id", "NCD_vrsn_num", "bnft_ctgry_cd"),
}
DATE_FIELDS = {
    "NCD_efctv_dt",
    "NCD_impltn_dt",
    "NCD_trmntn_dt",
    "trnsmtl_issnc_dt",
    "creatd_tmstmp",
    "last_updt_tmstmp",
    "last_clrnc_tmstmp",
}
TEXT_FIELDS = ("itm_srvc_desc", "indctn_lmtn", "xref_txt", "othr_txt")
SAMPLE_FIELDS = (
    "NCD_id",
    "NCD_vrsn_num",
    "NCD_mnl_sect",
    "NCD_mnl_sect_title",
    "NCD_efctv_dt",
    "NCD_trmntn_dt",
    "cvrg_lvl_cd",
)


def members(archive: ZipFile) -> list[dict]:
    return [
        {
            "name": member.filename,
            "bytes": member.file_size,
            "compressed_bytes": member.compress_size,
            "sha256": hashlib.sha256(archive.read(member)).hexdigest(),
        }
        for member in archive.infolist()
    ]


def profile_column(name: str, values: list[str]) -> dict:
    result = {
        "empty": sum(value == "" for value in values),
        "whitespace_only": sum(bool(value) and not value.strip() for value in values),
        "distinct_including_empty": len(set(values)),
        "max_characters": max(map(len, values), default=0),
    }
    if name in DATE_FIELDS:
        # CSV values carry no timezone; the dictionary specifies UTC.
        dates = [datetime.fromisoformat(value) for value in values if value]
        result["dates"] = {
            "nonempty_parsed": len(dates),
            "min": min(dates).isoformat() if dates else None,
            "max": max(dates).isoformat() if dates else None,
            "fractional_second_values": sum("." in value for value in values if value),
        }
    if name in (*TEXT_FIELDS, "rev_hstry"):
        result["contains_html_tag"] = sum(
            bool(re.search(r"<[A-Za-z][^>]*>", value)) for value in values
        )
        result["contains_newline"] = sum("\n" in value for value in values)
        result["contains_table_tag"] = sum("<table" in value.lower() for value in values)
    return result


def inspect(archive_path: Path, subset_path: Path) -> dict:
    archive_bytes = archive_path.read_bytes()
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    subset = json.loads(subset_path.read_text())
    if archive_hash != subset["archive_sha256"]:
        raise ValueError("Archive differs from the inspected development subset snapshot")

    csv.field_size_limit(10_000_000)
    tables, table_profiles = {}, {}
    with ZipFile(io.BytesIO(archive_bytes)) as outer:
        if outer.testzip() is not None:
            raise ValueError("Outer archive CRC failed")
        outer_members = members(outer)
        with ZipFile(io.BytesIO(outer.read("ncd_csv.zip"))) as inner:
            if inner.testzip() is not None:
                raise ValueError("Inner archive CRC failed")
            inner_members = members(inner)
            csv_names = {name for name in inner.namelist() if name.endswith(".csv")}
            if csv_names != set(KEYS):
                raise ValueError(f"Unexpected CSV inventory: {sorted(csv_names)}")
            for name in sorted(csv_names):
                raw = inner.read(name)
                reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
                columns = reader.fieldnames
                if not columns or len(set(columns)) != len(columns):
                    raise ValueError(f"Missing or duplicate column names in {name}")
                rows = list(reader)
                if not rows or any(None in row or None in row.values() for row in rows):
                    raise ValueError(f"Empty table or malformed row width in {name}")
                keys = [tuple(row[column] for column in KEYS[name]) for row in rows]
                if any("" in key for key in keys) or len(set(keys)) != len(keys):
                    raise ValueError(f"Missing or duplicate primary key in {name}")
                tables[name] = rows
                table_profiles[name] = {
                    "rows": len(rows),
                    "columns": columns,
                    "encoding_verified": "utf-8",
                    "utf8_bom": raw.startswith(b"\xef\xbb\xbf"),
                    "primary_key": list(KEYS[name]),
                    "duplicate_primary_keys": len(keys) - len(set(keys)),
                    "fields": {
                        column: profile_column(column, [row[column] for row in rows])
                        for column in columns
                    },
                }

    policies = tables["ncd_trkg.csv"]
    crosswalk = tables["ncd_trkg_bnft_xref.csv"]
    policy_keys = {(row["NCD_id"], row["NCD_vrsn_num"]) for row in policies}
    benefit_keys = {row["bnft_ctgry_cd"] for row in tables["ncd_bnft_ctgry_ref.csv"]}
    publication_keys = {row["pblctn_cd"] for row in tables["ncd_pblctn_ref.csv"]}
    joins = {
        "orphan_policy_crosswalks": sum(
            (row["NCD_id"], row["NCD_vrsn_num"]) not in policy_keys for row in crosswalk
        ),
        "orphan_benefit_crosswalks": sum(
            row["bnft_ctgry_cd"] not in benefit_keys for row in crosswalk
        ),
        "orphan_publication_references": sum(
            row["pblctn_cd"] not in publication_keys for row in policies
        ),
    }
    if any(joins.values()):
        raise ValueError(f"Broken references: {joins}")
    associations = Counter((row["NCD_id"], row["NCD_vrsn_num"]) for row in crosswalk)
    joins["policies_without_benefits"] = sum(key not in associations for key in policy_keys)
    joins["min_benefits_per_policy"] = min(associations.get(key, 0) for key in policy_keys)
    joins["max_benefits_per_policy"] = max(associations.values())

    def sample(row: dict) -> dict:
        return {field: row[field] for field in SAMPLE_FIELDS}

    unknown = [row for row in policies if row["cvrg_lvl_cd"] not in {"1", "2", "3"}]
    retired = [row for row in policies if "RETIRED" in row["NCD_mnl_sect_title"]]
    conflicts = [
        row
        for row in policies
        if row["NCD_trmntn_dt"]
        and datetime.fromisoformat(row["NCD_trmntn_dt"])
        < datetime.fromisoformat(row["NCD_efctv_dt"])
    ]
    selected = []
    for expected in subset["records"]:
        matches = [
            row
            for row in policies
            if (row["NCD_id"], row["NCD_vrsn_num"])
            == (expected["NCD_id"], expected["NCD_vrsn_num"])
        ]
        if len(matches) != 1 or any(matches[0][key] != value for key, value in expected.items()):
            raise ValueError(f"Subset record mismatch: {expected}")
        row = matches[0]
        if (
            row in retired
            or row in unknown
            or row["NCD_trmntn_dt"]
            or not row["indctn_lmtn"].strip()
        ):
            raise ValueError(f"Selected record needs review: {row['NCD_id']}")
        selected.append(
            sample(row) | {"raw_text_characters": sum(len(row[c]) for c in TEXT_FIELDS)}
        )

    return {
        "archive_sha256": archive_hash,
        "archive_bytes": len(archive_bytes),
        "outer_crc_valid": True,
        "inner_crc_valid": True,
        "outer_members": outer_members,
        "inner_members": inner_members,
        "tables": table_profiles,
        "relationships": joins,
        "value_counts": {
            column: dict(sorted(Counter(row[column] for row in policies).items()))
            for column in (
                "natl_cvrg_type",
                "cvrg_lvl_cd",
                "under_rvw",
                "NCD_lab",
                "NCD_AMA",
                "pblctn_cd",
            )
        },
        "quality_observations": {
            "undefined_coverage_level_records": [sample(row) for row in unknown],
            "retired_title_count": len(retired),
            "retired_title_without_termination_count": sum(not r["NCD_trmntn_dt"] for r in retired),
            "termination_before_effective_records": [sample(row) for row in conflicts],
            "blank_indication_records": [
                sample(row) for row in policies if not row["indctn_lmtn"].strip()
            ],
            "implementation_after_snapshot": [
                sample(row) | {"NCD_impltn_dt": row["NCD_impltn_dt"]}
                for row in policies
                if row["NCD_impltn_dt"]
                and datetime.fromisoformat(row["NCD_impltn_dt"]).date()
                > datetime.fromisoformat(subset["data_as_of"]).date()
            ],
        },
        "selected_records": selected,
        "selected_raw_text_characters": sum(row["raw_text_characters"] for row in selected),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("data/raw/cms_coverage/ncd.zip"))
    parser.add_argument("--subset", type=Path, default=Path("docs/cms_inspection/dev_subset.json"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="Write a measured inspection report")
    mode.add_argument("--check", type=Path, help="Recompute and compare with a saved report")
    args = parser.parse_args()
    report = inspect(args.archive, args.subset)
    if args.check:
        if report != json.loads(args.check.read_text()):
            raise SystemExit("FAIL: inspection report differs; review source/schema changes")
        print(
            "PASS: archive integrity, CSV structure, keys, joins, dates, subset, and report match"
        )
    else:
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote measured profile to {args.output}")
    print("Source anomalies are recorded in quality_observations; they are not corrected.")


if __name__ == "__main__":
    main()
