import os
import subprocess
import sys

import pytest
from app.core.config import get_settings

from ingestion.structured_reports import (
    SYNPUF_RAW_DIR,
    SYNTHEA_ZIP,
    ingestion_summary,
    quality_check,
    validate_sources,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running, real sources downloaded, "
    "and the Phase 8 dev-subset ingestion already applied to run this module's tests",
)


def _sources_present() -> bool:
    return SYNPUF_RAW_DIR.exists() and any(SYNPUF_RAW_DIR.glob("*.zip")) and SYNTHEA_ZIP.exists()


def test_validate_sources_reports_ok_for_both_when_present():
    if not _sources_present():
        pytest.skip("Download the reviewed DE-SynPUF and Synthea sources to run this test")
    report = validate_sources()
    assert report["cms_synpuf"]["status"] == "ok"
    assert report["cms_synpuf"]["row_counts"]["beneficiary_2008"] > 100_000
    assert report["synthea_fhir"]["status"] == "ok"
    assert report["synthea_fhir"]["bundle_count"] == 5


async def test_ingestion_summary_reflects_completed_runs():
    summary = await ingestion_summary(get_settings(), limit=20)
    sources = {run["source"] for run in summary["recent_runs"]}
    assert {"cms_synpuf", "synthea_fhir"} <= sources
    assert all(run["status"] == "completed" for run in summary["recent_runs"])
    assert {row["source"] for row in summary["source_files_by_source"]} >= {
        "cms_synpuf:beneficiary_2008",
        "cms_synpuf:inpatient_sample1",
        "cms_synpuf:outpatient_sample1",
    }


async def test_quality_check_reports_zero_violations_on_the_loaded_dev_subset():
    checks = await quality_check(get_settings())
    assert checks["synpuf_duplicate_beneficiary_ids"] == 0
    assert checks["synpuf_orphan_claims"] == 0
    assert checks["synpuf_negative_payment_amounts"] == 0
    assert all(v == 0 for v in checks["fhir_orphan_patient_references"].values())
    assert checks["synpuf_claim_counts_by_type"]["inpatient"] > 0
    assert checks["synpuf_claim_counts_by_type"]["outpatient"] > 0
    assert sum(checks["fhir_observation_value_type_distribution"].values()) > 0
    sources = {row["source"] for row in checks["latest_run_per_source"]}
    assert {"cms_synpuf", "synthea_fhir"} <= sources


def test_cli_ingestion_summary_command_runs_and_prints_json():
    result = subprocess.run(
        [sys.executable, "-m", "ingestion.cli", "ingestion-summary", "--limit", "1"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"recent_runs"' in result.stdout


def test_cli_validate_sources_command_runs_and_prints_json():
    if not _sources_present():
        pytest.skip("Download the reviewed DE-SynPUF and Synthea sources to run this test")
    result = subprocess.run(
        [sys.executable, "-m", "ingestion.cli", "validate-sources"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert '"cms_synpuf"' in result.stdout and '"synthea_fhir"' in result.stdout
