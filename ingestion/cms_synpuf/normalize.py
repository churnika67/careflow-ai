import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from ingestion.cms_synpuf.source import RejectedRecord
from ingestion.models import digest

CHRONIC_FIELDS = (
    ("chronic_alzheimers", "SP_ALZHDMTA"),
    ("chronic_heart_failure", "SP_CHF"),
    ("chronic_kidney_disease", "SP_CHRNKIDN"),
    ("chronic_cancer", "SP_CNCR"),
    ("chronic_copd", "SP_COPD"),
    ("chronic_depression", "SP_DEPRESSN"),
    ("chronic_diabetes", "SP_DIABETES"),
    ("chronic_ischemic_heart", "SP_ISCHMCHT"),
    ("chronic_osteoporosis", "SP_OSTEOPRS"),
    ("chronic_ra_oa", "SP_RA_OA"),
    ("chronic_stroke_tia", "SP_STRKETIA"),
)
MONEY_FIELDS = (
    ("reimb_inpatient", "MEDREIMB_IP"),
    ("benres_inpatient", "BENRES_IP"),
    ("pppymt_inpatient", "PPPYMT_IP"),
    ("reimb_outpatient", "MEDREIMB_OP"),
    ("benres_outpatient", "BENRES_OP"),
    ("pppymt_outpatient", "PPPYMT_OP"),
    ("reimb_carrier", "MEDREIMB_CAR"),
    ("benres_carrier", "BENRES_CAR"),
    ("pppymt_carrier", "PPPYMT_CAR"),
)
DIAGNOSIS_COLUMN = re.compile(r"^ICD9_DGNS_CD_(\d+)$")
PROCEDURE_COLUMN = re.compile(r"^ICD9_PRCDR_CD_(\d+)$")
HCPCS_COLUMN = re.compile(r"^HCPCS_CD_(\d+)$")


@dataclass(frozen=True)
class Beneficiary:
    beneficiary_id: str
    birth_date: date
    death_date: date | None
    sex_code: str
    race_code: str
    esrd_indicator: str
    state_code: str
    county_code: str
    hi_coverage_months: int
    smi_coverage_months: int
    hmo_coverage_months: int
    plan_coverage_months: int
    chronic_alzheimers: int
    chronic_heart_failure: int
    chronic_kidney_disease: int
    chronic_cancer: int
    chronic_copd: int
    chronic_depression: int
    chronic_diabetes: int
    chronic_ischemic_heart: int
    chronic_osteoporosis: int
    chronic_ra_oa: int
    chronic_stroke_tia: int
    reimb_inpatient: Decimal
    benres_inpatient: Decimal
    pppymt_inpatient: Decimal
    reimb_outpatient: Decimal
    benres_outpatient: Decimal
    pppymt_outpatient: Decimal
    reimb_carrier: Decimal
    benres_carrier: Decimal
    pppymt_carrier: Decimal
    source_row_sha256: str


@dataclass(frozen=True)
class Claim:
    claim_row_id: str
    claim_type: str
    claim_id: str
    segment: int
    beneficiary_id: str
    from_date: date
    thru_date: date
    admission_date: date | None
    discharge_date: date | None
    provider_number: str | None
    claim_payment_amount: Decimal
    primary_payer_paid_amount: Decimal
    attending_physician_npi: str | None
    operating_physician_npi: str | None
    other_physician_npi: str | None
    drg_code: str | None
    admitting_diagnosis_code: str | None
    source_row_sha256: str
    diagnoses: tuple[tuple[int, str], ...]
    procedures: tuple[tuple[int, str], ...]
    lines: tuple[tuple[int, str], ...]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _parse_optional_date(value: str) -> date | None:
    return _parse_date(value) if value.strip() else None


def _parse_money(value: str) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError("negative or non-finite amount")
    return amount


def _numbered_codes(row: dict, pattern: re.Pattern) -> tuple[tuple[int, str], ...]:
    codes = []
    for key, value in row.items():
        match = pattern.match(key)
        if match and value.strip():
            codes.append((int(match.group(1)), value.strip()))
    return tuple(sorted(codes))


def claim_row_id(claim_type: str, claim_id: str, segment: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"careflow:synpuf:{claim_type}:{claim_id}:{segment}"))


def normalize_beneficiaries(
    rows: list[dict], allowed_ids: set[str]
) -> tuple[list[Beneficiary], list[RejectedRecord]]:
    accepted, rejected = [], []
    for row in rows:
        bene_id = row.get("DESYNPUF_ID", "").strip()
        if bene_id not in allowed_ids:
            continue
        try:
            if not bene_id:
                raise ValueError("missing DESYNPUF_ID")
            birth_date = _parse_date(row["BENE_BIRTH_DT"])
            death_date = _parse_optional_date(row["BENE_DEATH_DT"])
            if death_date is not None and death_date < birth_date:
                raise ValueError("death date precedes birth date")
            for field in (
                "BENE_SEX_IDENT_CD",
                "BENE_RACE_CD",
                "BENE_ESRD_IND",
                "SP_STATE_CODE",
                "BENE_COUNTY_CD",
            ):
                if not row[field].strip():
                    raise ValueError(f"missing {field}")
            coverage = {}
            for out_key, src_key in (
                ("hi_coverage_months", "BENE_HI_CVRAGE_TOT_MONS"),
                ("smi_coverage_months", "BENE_SMI_CVRAGE_TOT_MONS"),
                ("hmo_coverage_months", "BENE_HMO_CVRAGE_TOT_MONS"),
                ("plan_coverage_months", "PLAN_CVRG_MOS_NUM"),
            ):
                value = int(row[src_key])
                if not 0 <= value <= 12:
                    raise ValueError(f"{src_key} out of range")
                coverage[out_key] = value
            chronic = {out_key: int(row[src_key]) for out_key, src_key in CHRONIC_FIELDS}
            money = {out_key: _parse_money(row[src_key]) for out_key, src_key in MONEY_FIELDS}
        except (ValueError, InvalidOperation, KeyError) as exc:
            rejected.append(RejectedRecord("beneficiary_2008", bene_id or "<blank>", str(exc)))
            continue
        accepted.append(
            Beneficiary(
                beneficiary_id=bene_id,
                birth_date=birth_date,
                death_date=death_date,
                sex_code=row["BENE_SEX_IDENT_CD"],
                race_code=row["BENE_RACE_CD"],
                esrd_indicator=row["BENE_ESRD_IND"],
                state_code=row["SP_STATE_CODE"],
                county_code=row["BENE_COUNTY_CD"],
                source_row_sha256=digest(row),
                **coverage,
                **chronic,
                **money,
            )
        )
    return accepted, rejected


def normalize_claims(
    rows: list[dict], claim_type: str, allowed_ids: set[str], known_beneficiaries: set[str]
) -> tuple[list[Claim], list[RejectedRecord]]:
    if claim_type not in ("inpatient", "outpatient"):
        raise ValueError("claim_type must be 'inpatient' or 'outpatient'")
    accepted, rejected = [], []
    for row in rows:
        bene_id = row.get("DESYNPUF_ID", "").strip()
        clm_id = row.get("CLM_ID", "").strip()
        if bene_id not in allowed_ids:
            continue
        key = f"{clm_id}:{row.get('SEGMENT', '')}"
        try:
            if not clm_id:
                raise ValueError("missing CLM_ID")
            if bene_id not in known_beneficiaries:
                raise ValueError(f"orphan claim: beneficiary {bene_id} not accepted")
            segment = int(row["SEGMENT"])
            from_date = _parse_date(row["CLM_FROM_DT"])
            thru_date = _parse_date(row["CLM_THRU_DT"])
            if thru_date < from_date:
                raise ValueError("CLM_THRU_DT precedes CLM_FROM_DT")
            payment = _parse_money(row["CLM_PMT_AMT"])
            primary_payer = _parse_money(row["NCH_PRMRY_PYR_CLM_PD_AMT"])
            admission_date = _parse_optional_date(row.get("CLM_ADMSN_DT", "") or "")
            discharge_date = _parse_optional_date(row.get("NCH_BENE_DSCHRG_DT", "") or "")
            raw_drg = row.get("CLM_DRG_CD", "").strip()
            drg_code = raw_drg or None if claim_type == "inpatient" else None
            diagnoses = _numbered_codes(row, DIAGNOSIS_COLUMN)
            procedures = _numbered_codes(row, PROCEDURE_COLUMN)
            lines = _numbered_codes(row, HCPCS_COLUMN)
        except (ValueError, InvalidOperation, KeyError) as exc:
            rejected.append(RejectedRecord(f"{claim_type}_sample1", key, str(exc)))
            continue
        accepted.append(
            Claim(
                claim_row_id=claim_row_id(claim_type, clm_id, segment),
                claim_type=claim_type,
                claim_id=clm_id,
                segment=segment,
                beneficiary_id=bene_id,
                from_date=from_date,
                thru_date=thru_date,
                admission_date=admission_date,
                discharge_date=discharge_date,
                provider_number=row.get("PRVDR_NUM", "").strip() or None,
                claim_payment_amount=payment,
                primary_payer_paid_amount=primary_payer,
                attending_physician_npi=row.get("AT_PHYSN_NPI", "").strip() or None,
                operating_physician_npi=row.get("OP_PHYSN_NPI", "").strip() or None,
                other_physician_npi=row.get("OT_PHYSN_NPI", "").strip() or None,
                drg_code=drg_code,
                admitting_diagnosis_code=row.get("ADMTNG_ICD9_DGNS_CD", "").strip() or None,
                source_row_sha256=digest(row),
                diagnoses=diagnoses,
                procedures=procedures,
                lines=lines,
            )
        )
    return accepted, rejected
