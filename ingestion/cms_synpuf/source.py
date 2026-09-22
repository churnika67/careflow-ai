import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

FILES = ("beneficiary_2008", "inpatient_sample1", "outpatient_sample1")


@dataclass(frozen=True)
class RejectedRecord:
    file: str
    natural_key: str
    reason: str


def _load_zip_csv(archive: Path, spec: dict) -> list[dict]:
    raw = archive.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != spec["zip_sha256"]:
        raise ValueError(f"{archive.name}: checksum does not match the reviewed profile")
    if len(raw) != spec["zip_bytes"]:
        raise ValueError(f"{archive.name}: size does not match the reviewed profile")
    with ZipFile(io.BytesIO(raw)) as z:
        if z.testzip():
            raise ValueError(f"{archive.name}: corrupt ZIP")
        with z.open(spec["inner_csv"]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), strict=True)
            if reader.fieldnames != spec["columns"]:
                raise ValueError(f"{archive.name}: unexpected column headers")
            rows = list(reader)
    if len(rows) != spec["row_count"]:
        raise ValueError(f"{archive.name}: row count does not match the reviewed profile")
    return rows


def load_source_tables(raw_dir: Path, profile_path: Path, subset_path: Path) -> dict:
    """Checksum-gate and structurally validate the three DE-SynPUF Sample 1 files
    referenced by the reviewed profile, then return their full parsed rows. This
    validates the WHOLE file against its pinned checksum/headers/row count before
    any row is used — a changed CMS file fails here, not silently mid-pipeline.
    Row-level acceptance/rejection for the selected dev subset happens separately
    in normalize.py, since CMS DE-SynPUF fields may legitimately vary in ways a
    whole-file structural check should not reject (e.g. blank optional dates)."""
    profile = json.loads(profile_path.read_text())
    subset = json.loads(subset_path.read_text())
    if profile["data_as_of"] != subset["data_as_of"]:
        raise ValueError("Profile and dev subset were built from different snapshots")
    tables = {}
    for name in FILES:
        spec = profile["files"][name]
        if spec["zip_sha256"] != subset["zip_sha256"][name]:
            raise ValueError(f"{name}: profile and dev subset checksums disagree")
        tables[name] = _load_zip_csv(raw_dir / spec["zip_filename"], spec)
    return tables
