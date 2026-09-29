import json

import pytest
from app.analytics import snapshot as snapshot_module
from app.analytics.snapshot import (
    EvaluationArtifactMalformedError,
    EvaluationArtifactMissingError,
    load_evaluation_snapshot,
)


def test_canonical_snapshot_loads_against_the_real_repository_artifacts():
    """This is the real, unmocked snapshot -- proves the canonical artifact
    IDs this module hardcodes actually exist and parse, against the
    repository's real artifacts/ and docs/evaluation/ directories."""
    result = load_evaluation_snapshot()

    assert result.datasets["development"].case_count == 32
    assert result.datasets["development"].positive_cases == 25
    assert result.datasets["development"].negative_cases == 7
    assert result.datasets["held_out"].case_count == 12
    assert result.datasets["held_out"].positive_cases == 10

    assert result.retrieval_baseline["development"].experiment_id == "eb59bc90_774ea9a697a1"
    assert result.retrieval_baseline["held_out"].experiment_id == "eb59bc90_a223469082ce"
    assert result.reranker_comparison.experiment_id == "eb59bc90_reranker_comparison"
    assert result.latency.experiment_id == "eb59bc90_latency_1790202561"

    assert result.threshold.grid == [0.40, 0.45, 0.50, 0.55, 0.60]
    assert result.threshold.production_threshold == 0.60
    assert result.threshold.case_transitions_observed == 27
    assert result.threshold.known_issue["case_id"] == "cms-v1-032"
    assert result.threshold.known_issue["gate_score_at_production_threshold"] == pytest.approx(
        0.613495
    )

    assert result.cost_tokens.status == "not_evaluated"

    # Recomputed from the live markdown/JSON docs, not hardcoded -- these
    # must match the Phase 12 final report's corrected summary exactly.
    assert result.claim_matrix.supported == 6
    assert result.claim_matrix.partially_supported == 10
    assert result.claim_matrix.not_evaluated == 11
    assert result.claim_matrix.out_of_scope == 3
    assert result.claim_matrix.total == 30

    assert result.gaps.open == 5
    assert result.gaps.out_of_scope_phase12 == 4
    assert result.gaps.documented_limitation == 4
    assert result.gaps.total == 13

    assert result.provenance.corpus_fingerprint == (
        "1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2"
    )
    assert result.provenance.evaluated_production_config.chunk_size == 700
    assert result.provenance.evaluated_production_config.chunk_overlap == 120
    assert result.provenance.evaluated_production_config.evidence_threshold == 0.6
    assert result.provenance.generation_provider == "deterministic"


def test_gap_entries_are_individually_exposed_for_the_evaluation_gaps_section():
    """Phase 15 Slice 2: GapRegistrySummary.entries was added because the
    Evaluation Gaps section needs to name individual gaps (routing
    accuracy, production-load latency, reranker false-abstention, etc),
    not just per-status counts."""
    result = load_evaluation_snapshot()
    assert len(result.gaps.entries) == 13
    by_id = {entry.gap_id: entry for entry in result.gaps.entries}
    assert by_id["EVAL-RUNTIME-CONFIG-DRIFT"].status == "OPEN"
    assert by_id["EVAL-ROUTING-ACCURACY-NOT-EVALUATED"].status == "OPEN"
    assert by_id["EVAL-PRODUCTION-LOAD-LATENCY-NOT-EVALUATED"].status == "OPEN"
    assert by_id["EVAL-RERANKER-FALSE-ABSTENTION"].status == "OPEN"
    assert by_id["EVAL-UNSUPPORTED-HIGH-SIMILARITY"].status == "OPEN"
    status_counts: dict[str, int] = {}
    for entry in result.gaps.entries:
        status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
    assert status_counts == {
        "OPEN": result.gaps.open,
        "DOCUMENTED_LIMITATION": result.gaps.documented_limitation,
        "OUT_OF_SCOPE_PHASE12": result.gaps.out_of_scope_phase12,
    }


def test_not_evaluated_categories_stay_null_not_zero():
    """A development-set category with zero cases (e.g. 'ambiguous', which
    has no positive cases) must report Hit@1 as null, never as 0 -- a
    reader must be able to tell "not evaluated" apart from "measured and
    scored zero"."""
    result = load_evaluation_snapshot()
    dev_metrics = result.retrieval_baseline["development"].metrics
    ambiguous = dev_metrics["dense"]["categories"]["ambiguous"]
    assert ambiguous["count"] == 0
    assert ambiguous["Hit@1"] is None
    assert ambiguous["MRR@5"] is None


def test_no_experiment_id_parameter_exists_anywhere_in_the_public_api():
    """Security-by-construction check: this module must never grow a
    function that accepts a caller-supplied path or experiment_id --
    the only way it can be made unsafe is by adding one."""
    import inspect

    public_functions = [
        obj
        for name, obj in vars(snapshot_module).items()
        if inspect.isfunction(obj)
        and not name.startswith("_")
        and obj.__module__ == snapshot_module.__name__
    ]
    assert public_functions == [snapshot_module.load_evaluation_snapshot]
    assert inspect.signature(snapshot_module.load_evaluation_snapshot).parameters == {}


def test_missing_canonical_artifact_raises_missing_error(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot_module, "_ARTIFACT_ROOT", tmp_path / "does-not-exist")
    with pytest.raises(EvaluationArtifactMissingError):
        load_evaluation_snapshot()


def test_malformed_json_artifact_raises_malformed_error(monkeypatch, tmp_path):
    baseline_dir = tmp_path / "eb59bc90_774ea9a697a1"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "summary.json").write_text("{not valid json")
    monkeypatch.setattr(snapshot_module, "_ARTIFACT_ROOT", tmp_path)
    with pytest.raises(EvaluationArtifactMalformedError):
        load_evaluation_snapshot()


def test_artifact_missing_a_required_field_raises_malformed_error(monkeypatch, tmp_path):
    baseline_dir = tmp_path / "eb59bc90_774ea9a697a1"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "summary.json").write_text(json.dumps({"dataset_version": "x"}))
    monkeypatch.setattr(snapshot_module, "_ARTIFACT_ROOT", tmp_path)
    with pytest.raises(EvaluationArtifactMalformedError):
        load_evaluation_snapshot()


def test_resolved_artifact_paths_never_escape_the_artifact_root():
    """Even though no client input ever reaches these paths, prove the
    property directly: every path this module reads resolves inside the
    fixed artifact/docs roots, never outside via '..' or an absolute
    override."""
    result = load_evaluation_snapshot()
    for block in (
        result.retrieval_baseline["development"],
        result.retrieval_baseline["held_out"],
        result.reranker_comparison,
        result.latency,
    ):
        resolved = (snapshot_module._REPO_ROOT / block.artifact_path).resolve()
        assert resolved.is_relative_to(snapshot_module._ARTIFACT_ROOT.resolve())
    assert (
        (snapshot_module._REPO_ROOT / result.claim_matrix.source)
        .resolve()
        .is_relative_to(snapshot_module._DOCS_ROOT.resolve())
    )
    assert (
        (snapshot_module._REPO_ROOT / result.gaps.source)
        .resolve()
        .is_relative_to(snapshot_module._DOCS_ROOT.resolve())
    )
