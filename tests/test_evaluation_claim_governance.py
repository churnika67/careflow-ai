import json
from pathlib import Path

import pytest

from evaluation.claim_governance import (
    APPROVED_CLAIM_STATUSES,
    APPROVED_GAP_STATUSES,
    REQUIRED_GAP_FIELDS,
    REQUIRED_GAP_IDS,
    load_gap_registry,
    parse_markdown_table,
    scan_for_prohibited_wording,
    validate_claim_matrix,
    validate_gap_registry,
)

GAP_REGISTRY_PATH = Path("docs/evaluation/phase12_gap_registry.json")
CLAIM_MATRIX_PATH = Path("docs/evaluation/phase12_claim_matrix.md")
FINAL_REPORT_PATH = Path("docs/evaluation/phase12_final_report.md")


# --- gap registry schema (pure) ----------------------------------------------


def test_gap_registry_file_is_valid_json_with_gaps_list():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    assert isinstance(registry.get("gaps"), list)
    assert len(registry["gaps"]) > 0


def test_gap_registry_has_zero_violations():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    assert validate_gap_registry(registry) == []


def test_every_gap_has_all_required_fields():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    for gap in registry["gaps"]:
        assert REQUIRED_GAP_FIELDS <= set(gap), f"{gap.get('gap_id')} missing fields"


def test_gap_ids_are_unique():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    ids = [g["gap_id"] for g in registry["gaps"]]
    assert len(ids) == len(set(ids))


def test_every_gap_status_is_approved():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    for gap in registry["gaps"]:
        assert gap["status"] in APPROVED_GAP_STATUSES


def test_gap_registry_validator_rejects_unapproved_status():
    bad = {
        "gaps": [
            {
                "gap_id": "X",
                "title": "t",
                "category": "c",
                "status": "SEVERITY_HIGH",
                "evidence": "e",
                "impact_on_claims": "i",
                "future_evaluation_needed": "f",
                "production_change_required_now": False,
            }
        ]
    }
    violations = validate_gap_registry(bad)
    assert any("unapproved status" in v for v in violations)


def test_gap_registry_validator_rejects_duplicate_ids():
    entry = {
        "gap_id": "DUP",
        "title": "t",
        "category": "c",
        "status": "OPEN",
        "evidence": "e",
        "impact_on_claims": "i",
        "future_evaluation_needed": "f",
        "production_change_required_now": False,
    }
    bad = {"gaps": [entry, dict(entry)]}
    violations = validate_gap_registry(bad)
    assert any("duplicate" in v for v in violations)


def test_gap_registry_validator_rejects_missing_field():
    bad = {"gaps": [{"gap_id": "X", "title": "t"}]}
    violations = validate_gap_registry(bad)
    assert any("missing required fields" in v for v in violations)


# --- required gap categories present (pure) ----------------------------------


def test_all_minimum_required_gap_ids_are_present():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    ids = {g["gap_id"] for g in registry["gaps"]}
    assert REQUIRED_GAP_IDS <= ids


# --- specific documented gaps (pure, content checks) -------------------------


def test_runtime_eval_config_drift_documented():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    gap = next(g for g in registry["gaps"] if g["gap_id"] == "EVAL-RUNTIME-CONFIG-DRIFT")
    assert "dense" in gap["evidence"].lower()
    assert "rerank" in gap["evidence"].lower()
    assert gap["production_change_required_now"] is False


def test_slice2_candidate_depth_confound_documented():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    gap = next(g for g in registry["gaps"] if g["gap_id"] == "EVAL-SLICE2-CANDIDATE-DEPTH-CONFOUND")
    assert "depth" in gap["evidence"].lower()
    assert "slice 6" in gap["impact_on_claims"].lower()


def test_cms_v1_032_documented():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    gap = next(g for g in registry["gaps"] if g["gap_id"] == "EVAL-UNSUPPORTED-HIGH-SIMILARITY")
    assert "cms-v1-032" in gap["evidence"]
    assert "0.6134" in gap["evidence"] or "0.613495" in gap["evidence"]


def test_cms_v1_h003_documented():
    registry = load_gap_registry(GAP_REGISTRY_PATH)
    gap = next(g for g in registry["gaps"] if g["gap_id"] == "EVAL-RERANKER-FALSE-ABSTENTION")
    assert "cms-v1-h003" in gap["evidence"]
    assert "0.4949534" in gap["evidence"]


def test_held_out_authorship_limitation_documented():
    text = CLAIM_MATRIX_PATH.read_text()
    assert "project-authored" in text.lower()
    assert "not independently annotated" in text.lower() or "not independently" in text.lower()


def test_synthetic_data_limitation_documented():
    text = CLAIM_MATRIX_PATH.read_text()
    lowered = text.lower()
    assert "synthetic" in lowered
    assert "de-synpuf" in lowered or "synpuf" in lowered
    assert "synthea" in lowered


# --- claim matrix status vocabulary (pure) -----------------------------------


def test_claim_matrix_table_parses_and_has_zero_violations():
    text = CLAIM_MATRIX_PATH.read_text()
    rows = parse_markdown_table(text)
    assert len(rows) > 20  # section 4's required areas are numerous
    assert validate_claim_matrix(rows) == []


def test_claim_matrix_validator_rejects_unapproved_status():
    violations = validate_claim_matrix([{"Claim": "x", "Status": "SUPPORTED (narrow)"}])
    assert violations != []


def test_parse_markdown_table_extracts_expected_columns():
    text = CLAIM_MATRIX_PATH.read_text()
    rows = parse_markdown_table(text)
    assert "Status" in rows[0]
    assert "Allowed wording" in rows[0]
    assert "Disallowed wording" in rows[0]


# --- artifact provenance mapping (pure) --------------------------------------


def test_artifact_provenance_section_names_authoritative_artifacts():
    text = CLAIM_MATRIX_PATH.read_text()
    assert "Artifact provenance" in text
    for artifact_id in (
        "eb59bc90_774ea9a697a1",
        "eb59bc90_a223469082ce",
        "eb59bc90_chunking_grid",
        "eb59bc90_reranker_comparison",
    ):
        assert artifact_id in text


def test_slice6_explicitly_stated_as_superseding_slice2_for_reranker_causal_comparison():
    text = CLAIM_MATRIX_PATH.read_text()
    assert "supersedes Slice 2" in text


# --- no recommendation/winner fields (pure, structural scan) ----------------


def test_claim_matrix_never_contains_a_winner_or_recommendation_field():
    text = CLAIM_MATRIX_PATH.read_text().lower()
    assert "winner" not in text
    assert "recommended configuration" not in text


def test_gap_registry_never_contains_a_winner_or_severity_score():
    text = GAP_REGISTRY_PATH.read_text().lower()
    assert "winner" not in text
    assert '"severity"' not in text
    assert '"priority"' not in text


# --- approved/disallowed wording structure (pure + live-independent) --------


def test_claim_matrix_scan_has_zero_prohibited_wording_findings():
    text = CLAIM_MATRIX_PATH.read_text()
    assert scan_for_prohibited_wording(text) == []


def test_scanner_still_flags_a_genuinely_unguarded_prohibited_phrase():
    bad_doc = "## Results\n\nOur retrieval is clinically validated and HIPAA compliant.\n"
    findings = scan_for_prohibited_wording(bad_doc)
    phrases = {f["phrase"] for f in findings}
    assert "clinically validated" in phrases
    assert "hipaa compliant" in phrases


def test_scanner_exempts_disallowed_wording_table_column():
    doc = "| Claim | Disallowed wording |\n|---|---|\n| X | HIPAA compliant |\n"
    assert scan_for_prohibited_wording(doc) == []


def test_scanner_exempts_avoid_section():
    doc = "## Avoid\n\nHIPAA compliant, production ready.\n"
    assert scan_for_prohibited_wording(doc) == []


def test_scanner_does_not_exempt_prohibited_wording_column_content_other_than_disallowed():
    # A phrase in the "Allowed wording" column of the same table row must
    # still be flagged -- only the Disallowed wording column is exempt.
    doc = (
        "| Claim | Allowed wording | Disallowed wording |\n"
        "|---|---|---|\n"
        "| X | HIPAA compliant | fine here |\n"
    )
    findings = scan_for_prohibited_wording(doc)
    assert any(f["phrase"] == "hipaa compliant" for f in findings)


# --- structural check: gap registry / claim matrix files exist --------------


def test_gap_registry_and_claim_matrix_files_exist():
    assert GAP_REGISTRY_PATH.exists()
    assert CLAIM_MATRIX_PATH.exists()


def test_gap_registry_json_matches_python_json_loads(tmp_path):
    # Round-trips cleanly -- not hand-edited into invalid JSON.
    raw = GAP_REGISTRY_PATH.read_text()
    reparsed = json.loads(raw)
    assert reparsed == load_gap_registry(GAP_REGISTRY_PATH)


# --- no expensive live work required for this slice --------------------------


def test_claim_governance_module_requires_no_live_services():
    # Sanity: importing/using this module never touches Qdrant/Postgres.
    import inspect

    import evaluation.claim_governance as mod

    source = inspect.getsource(mod)
    for forbidden in ("QdrantClient", "psycopg", "connect(", "search.search"):
        assert forbidden not in source


@pytest.mark.parametrize("status", sorted(APPROVED_CLAIM_STATUSES))
def test_each_approved_claim_status_is_a_plain_enum_value_no_numeric_score(status):
    assert status.isupper()
    assert not any(ch.isdigit() for ch in status)


# --- Slice 8: final report and claim-matrix count reconciliation ------------


def test_final_report_exists_and_has_zero_prohibited_wording_findings():
    assert FINAL_REPORT_PATH.exists()
    text = FINAL_REPORT_PATH.read_text()
    assert scan_for_prohibited_wording(text) == []


def test_final_report_uses_slice6_not_slice2_for_reranker_causal_comparison():
    text = FINAL_REPORT_PATH.read_text()
    assert "Slice 6" in text
    assert "eb59bc90_reranker_comparison" in text
    assert "not a clean reranker" in text.lower() or "not a clean causal" in text.lower()


def test_final_report_documents_dirty_working_tree_source_state():
    text = FINAL_REPORT_PATH.read_text()
    assert "working_tree_clean" in text
    assert "dirty working tree" in text.lower()


def test_final_report_preserves_slice3_conclusion_wording_verbatim():
    # Normalize markdown line-wrapping whitespace before matching -- the
    # sentence is hard-wrapped across lines in the source file.
    normalized = " ".join(FINAL_REPORT_PATH.read_text().split())
    assert (
        "did not provide sufficient evidence to justify changing the existing 700/120" in normalized
    )


def test_final_report_preserves_threshold_transition_counts():
    text = FINAL_REPORT_PATH.read_text()
    assert "27 case-level transitions" in text
    assert "zero" in text.lower() and "non-monotonic" in text.lower()


def test_final_report_preserves_reranker_same_pool_counts():
    text = FINAL_REPORT_PATH.read_text()
    assert "improved 1, unchanged 23, degraded 1" in text
    assert "improved 2, unchanged 8, degraded 0" in text


def test_claim_matrix_recomputed_counts_match_final_report_table():
    """Section 8's core requirement: the counts in the final report must be
    the PROGRAMMATICALLY RECOMPUTED counts, not a copied prose summary."""
    from collections import Counter

    rows = parse_markdown_table(CLAIM_MATRIX_PATH.read_text())
    counts = Counter(r["Status"] for r in rows)
    assert counts["SUPPORTED"] == 6
    assert counts["PARTIALLY_SUPPORTED"] == 10
    assert counts["NOT_EVALUATED"] == 11
    assert counts["OUT_OF_SCOPE"] == 3
    assert sum(counts.values()) == len(rows) == 30

    report_text = FINAL_REPORT_PATH.read_text()
    assert "| SUPPORTED | 6 |" in report_text
    assert "| PARTIALLY_SUPPORTED | 10 |" in report_text
    assert "| NOT_EVALUATED | 11 |" in report_text
    assert "| OUT_OF_SCOPE | 3 |" in report_text


# --- Slice 8: artifact inventory / schema safety -----------------------------


ARTIFACT_ROOT = Path("artifacts/evaluation")


def _all_experiment_dirs():
    if not ARTIFACT_ROOT.exists():
        return []
    return sorted(d for d in ARTIFACT_ROOT.iterdir() if d.is_dir())


def test_every_artifact_directory_is_non_empty():
    dirs = _all_experiment_dirs()
    assert len(dirs) > 0
    for d in dirs:
        assert any(d.iterdir()), f"{d} is empty"


def test_every_json_artifact_is_valid_json_with_no_nan_or_infinity():
    import math

    def _check(obj):
        if isinstance(obj, float):
            assert not (math.isnan(obj) or math.isinf(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                _check(v)
        elif isinstance(obj, list):
            for v in obj:
                _check(v)

    for d in _all_experiment_dirs():
        for f in d.glob("*.json"):
            _check(json.loads(f.read_text()))


def test_every_jsonl_artifact_parses_row_by_row():
    for d in _all_experiment_dirs():
        for f in d.glob("*.jsonl"):
            lines = f.read_text().splitlines()
            assert lines, f"{f} has no rows"
            for line in lines:
                json.loads(line)  # raises on malformed row


def test_experiment_directory_names_are_unique():
    dirs = _all_experiment_dirs()
    names = [d.name for d in dirs]
    assert len(names) == len(set(names))


def test_no_machine_specific_paths_in_any_artifact():
    forbidden_markers = ("/Users/", "C:\\Users\\", "churnika")
    for d in _all_experiment_dirs():
        for f in list(d.glob("*.json")) + list(d.glob("*.jsonl")):
            text = f.read_text()
            for marker in forbidden_markers:
                assert marker not in text, f"{f} contains {marker!r}"


def test_no_secret_like_patterns_in_any_artifact():
    import re

    secret_pattern = re.compile(r"sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY")
    for d in _all_experiment_dirs():
        for f in list(d.glob("*.json")) + list(d.glob("*.jsonl")):
            assert not secret_pattern.search(f.read_text()), f"possible secret in {f}"
