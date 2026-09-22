import os
from pathlib import Path

import pytest
from app.core.config import get_settings

from ingestion.cms_synpuf.loader import ingest_synpuf
from ingestion.cms_synpuf.normalize import claim_row_id, normalize_beneficiaries, normalize_claims
from ingestion.cms_synpuf.source import load_source_tables

RAW_DIR = Path("data/raw/cms_synpuf")
PROFILE = Path("docs/cms_inspection/desynpuf_profile.json")
SUBSET = Path("docs/cms_inspection/desynpuf_dev_subset.json")

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running to test real Postgres",
)


def _beneficiary_row(**overrides) -> dict:
    row = {
        "DESYNPUF_ID": "TESTBENE0000001",
        "BENE_BIRTH_DT": "19400101",
        "BENE_DEATH_DT": "",
        "BENE_SEX_IDENT_CD": "1",
        "BENE_RACE_CD": "1",
        "BENE_ESRD_IND": "0",
        "SP_STATE_CODE": "26",
        "BENE_COUNTY_CD": "950",
        "BENE_HI_CVRAGE_TOT_MONS": "12",
        "BENE_SMI_CVRAGE_TOT_MONS": "12",
        "BENE_HMO_CVRAGE_TOT_MONS": "0",
        "PLAN_CVRG_MOS_NUM": "12",
        "SP_ALZHDMTA": "2",
        "SP_CHF": "2",
        "SP_CHRNKIDN": "2",
        "SP_CNCR": "2",
        "SP_COPD": "2",
        "SP_DEPRESSN": "2",
        "SP_DIABETES": "1",
        "SP_ISCHMCHT": "2",
        "SP_OSTEOPRS": "2",
        "SP_RA_OA": "2",
        "SP_STRKETIA": "2",
        "MEDREIMB_IP": "0.00",
        "BENRES_IP": "0.00",
        "PPPYMT_IP": "0.00",
        "MEDREIMB_OP": "50.00",
        "BENRES_OP": "10.00",
        "PPPYMT_OP": "0.00",
        "MEDREIMB_CAR": "0.00",
        "BENRES_CAR": "0.00",
        "PPPYMT_CAR": "0.00",
    }
    row.update(overrides)
    return row


def _claim_row(**overrides) -> dict:
    row = {
        "DESYNPUF_ID": "TESTBENE0000001",
        "CLM_ID": "CLAIM0001",
        "SEGMENT": "1",
        "CLM_FROM_DT": "20090101",
        "CLM_THRU_DT": "20090102",
        "CLM_PMT_AMT": "4000.00",
        "NCH_PRMRY_PYR_CLM_PD_AMT": "0.00",
        "CLM_ADMSN_DT": "20090101",
        "NCH_BENE_DSCHRG_DT": "20090102",
        "PRVDR_NUM": "2600GD",
        "AT_PHYSN_NPI": "3139083564",
        "OP_PHYSN_NPI": "",
        "OT_PHYSN_NPI": "",
        "CLM_DRG_CD": "217",
        "ADMTNG_ICD9_DGNS_CD": "4580",
        "ICD9_DGNS_CD_1": "7802",
        "ICD9_DGNS_CD_2": "",
        "ICD9_DGNS_CD_3": "4280",
        "ICD9_PRCDR_CD_1": "0331",
        "HCPCS_CD_1": "99283",
        "HCPCS_CD_2": "",
    }
    row.update(overrides)
    return row


def test_normalize_beneficiaries_accepts_valid_row():
    accepted, rejected = normalize_beneficiaries([_beneficiary_row()], {"TESTBENE0000001"})
    assert rejected == []
    assert len(accepted) == 1
    b = accepted[0]
    assert b.beneficiary_id == "TESTBENE0000001"
    assert b.death_date is None
    assert b.chronic_diabetes == 1
    assert b.reimb_outpatient == 50


def test_normalize_beneficiaries_filters_by_allowed_ids():
    accepted, rejected = normalize_beneficiaries([_beneficiary_row()], {"SOME_OTHER_ID"})
    assert accepted == []
    assert rejected == []


def test_normalize_beneficiaries_rejects_missing_id():
    accepted, rejected = normalize_beneficiaries([_beneficiary_row(DESYNPUF_ID="")], {""})
    assert accepted == []
    assert len(rejected) == 1
    assert "missing DESYNPUF_ID" in rejected[0].reason


def test_normalize_beneficiaries_rejects_death_before_birth():
    accepted, rejected = normalize_beneficiaries(
        [_beneficiary_row(BENE_DEATH_DT="19300101")], {"TESTBENE0000001"}
    )
    assert accepted == []
    assert "death date precedes birth date" in rejected[0].reason


@pytest.mark.parametrize("field", ["BENE_HI_CVRAGE_TOT_MONS", "PLAN_CVRG_MOS_NUM"])
def test_normalize_beneficiaries_rejects_out_of_range_coverage_months(field):
    accepted, rejected = normalize_beneficiaries(
        [_beneficiary_row(**{field: "13"})], {"TESTBENE0000001"}
    )
    assert accepted == []
    assert "out of range" in rejected[0].reason


def test_normalize_beneficiaries_rejects_malformed_date():
    accepted, rejected = normalize_beneficiaries(
        [_beneficiary_row(BENE_BIRTH_DT="not-a-date")], {"TESTBENE0000001"}
    )
    assert accepted == []
    assert rejected[0].reason


def test_normalize_claims_accepts_valid_inpatient_row_with_lines():
    accepted, rejected = normalize_claims(
        [_claim_row()], "inpatient", {"TESTBENE0000001"}, {"TESTBENE0000001"}
    )
    assert rejected == []
    assert len(accepted) == 1
    claim = accepted[0]
    assert claim.claim_type == "inpatient"
    assert claim.drg_code == "217"
    assert claim.admission_date is not None and claim.discharge_date is not None
    # Blank ICD9_DGNS_CD_2 is skipped; source column position (1, 3) is preserved, not compacted.
    assert claim.diagnoses == ((1, "7802"), (3, "4280"))
    assert claim.procedures == ((1, "0331"),)
    assert claim.lines == ((1, "99283"),)


def test_normalize_claims_outpatient_never_sets_drg_or_admission_fields():
    accepted, _ = normalize_claims(
        [_claim_row()], "outpatient", {"TESTBENE0000001"}, {"TESTBENE0000001"}
    )
    claim = accepted[0]
    assert claim.drg_code is None


def test_normalize_claims_rejects_blank_required_date():
    accepted, rejected = normalize_claims(
        [_claim_row(CLM_FROM_DT="", CLM_THRU_DT="")],
        "outpatient",
        {"TESTBENE0000001"},
        {"TESTBENE0000001"},
    )
    assert accepted == []
    assert rejected[0].reason


def test_normalize_claims_rejects_negative_payment():
    accepted, rejected = normalize_claims(
        [_claim_row(CLM_PMT_AMT="-10.00")],
        "outpatient",
        {"TESTBENE0000001"},
        {"TESTBENE0000001"},
    )
    assert accepted == []
    assert "negative" in rejected[0].reason


def test_normalize_claims_rejects_orphan_beneficiary():
    accepted, rejected = normalize_claims(
        [_claim_row()], "inpatient", {"TESTBENE0000001"}, known_beneficiaries=set()
    )
    assert accepted == []
    assert "orphan claim" in rejected[0].reason


def test_normalize_claims_rejects_thru_before_from():
    accepted, rejected = normalize_claims(
        [_claim_row(CLM_FROM_DT="20090105", CLM_THRU_DT="20090101")],
        "outpatient",
        {"TESTBENE0000001"},
        {"TESTBENE0000001"},
    )
    assert accepted == []
    assert "precedes" in rejected[0].reason


def test_claim_row_id_is_deterministic_and_scoped_by_type_and_segment():
    a = claim_row_id("inpatient", "CLAIM0001", 1)
    b = claim_row_id("inpatient", "CLAIM0001", 1)
    assert a == b
    assert a != claim_row_id("outpatient", "CLAIM0001", 1)
    assert a != claim_row_id("inpatient", "CLAIM0001", 2)


@pytestmark_live
def test_load_source_tables_against_real_files():
    if not RAW_DIR.exists() or not any(RAW_DIR.glob("*.zip")):
        pytest.skip("Download the reviewed DE-SynPUF Sample 1 files to run this test")
    tables = load_source_tables(RAW_DIR, PROFILE, SUBSET)
    assert set(tables) == {"beneficiary_2008", "inpatient_sample1", "outpatient_sample1"}
    assert len(tables["beneficiary_2008"]) > 100_000


@pytestmark_live
async def test_ingest_synpuf_idempotent_against_live_postgres():
    if not RAW_DIR.exists() or not any(RAW_DIR.glob("*.zip")):
        pytest.skip("Download the reviewed DE-SynPUF Sample 1 files to run this test")
    settings = get_settings()
    first = await ingest_synpuf(settings)
    assert first["beneficiaries"]["selected"] == 15
    second = await ingest_synpuf(settings)
    assert second["beneficiaries"]["inserted"] == 0
    assert second["claims"]["inserted"] == 0
    assert second["beneficiaries"]["selected"] == first["beneficiaries"]["selected"]
    assert second["claims"]["selected"] == first["claims"]["selected"]
    assert second["rejected_records"] == first["rejected_records"]
