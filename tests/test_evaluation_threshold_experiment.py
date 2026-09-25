import os

import pytest

from evaluation.threshold_experiment import (
    THRESHOLD_GRID,
    CaseTransition,
    citation_expected_evidence,
    detect_case_transitions,
    explicit_abstention_labels,
    gate_score_distribution,
)

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_INGESTION_INTEGRATION") != "1",
    reason="Set CAREFLOW_INGESTION_INTEGRATION=1 with Compose running and the frozen CMS "
    "source snapshot present to exercise the real production-index threshold sweep",
)


# --- threshold grid is frozen ----------------------------------------------


def test_threshold_grid_is_exactly_the_five_frozen_points():
    assert THRESHOLD_GRID == [0.40, 0.45, 0.50, 0.55, 0.60]


def test_production_threshold_is_the_top_of_the_grid():
    from evaluation.run_experiment import PRODUCTION_SETTINGS

    assert THRESHOLD_GRID[-1] == PRODUCTION_SETTINGS.rag_min_score


# --- explicit abstention labels (pure) -------------------------------------


def test_explicit_abstention_labels_matches_existing_confusion_counts():
    entry = {
        "positive_cases": 10,
        "negative_cases": 4,
        "correct_abstentions": 3,  # TP -> unsupported_abstained
        "incorrect_answer_attempts": 1,  # FN -> unsupported_answered
        "positive_abstentions": 2,  # FP -> supported_abstained
    }
    labels = explicit_abstention_labels(entry)
    assert labels["unsupported_abstained"] == 3
    assert labels["unsupported_answered"] == 1
    assert labels["supported_abstained"] == 2
    assert labels["supported_answered"] == 8  # 10 - 2
    assert labels["supported_answer_rate"] == 0.8
    assert labels["false_abstention_rate"] == 0.2
    assert labels["correct_abstention_rate"] == 0.75
    assert labels["false_answer_rate"] == 0.25


def test_explicit_abstention_labels_uses_non_tp_fp_terminology():
    entry = {
        "positive_cases": 1,
        "negative_cases": 1,
        "correct_abstentions": 0,
        "incorrect_answer_attempts": 0,
        "positive_abstentions": 0,
    }
    labels = explicit_abstention_labels(entry)
    for forbidden in ("tp", "fp", "fn", "tn", "true_positive", "false_positive"):
        assert forbidden not in labels


def test_explicit_abstention_labels_null_on_zero_denominator():
    entry = {
        "positive_cases": 0,
        "negative_cases": 0,
        "correct_abstentions": 0,
        "incorrect_answer_attempts": 0,
        "positive_abstentions": 0,
    }
    labels = explicit_abstention_labels(entry)
    assert labels["supported_answer_rate"] is None
    assert labels["false_abstention_rate"] is None
    assert labels["correct_abstention_rate"] is None
    assert labels["false_answer_rate"] is None


# --- citation_expected_evidence (pure) --------------------------------------


def _case(case_id, answerable, abstained, cites_expected, mode="hybrid_reranked"):
    return {
        "case_id": case_id,
        "answerable": answerable,
        "modes": {mode: {"abstained": abstained, "cites_expected": cites_expected}},
    }


def test_citation_expected_evidence_only_counts_answered_positive_cases():
    cases = [
        _case("c1", True, False, True),  # answered, supported, cites expected -> counted, hit
        _case("c2", True, False, False),  # answered, supported, does not cite -> counted, miss
        _case("c3", True, True, False),  # abstained -> excluded from denominator
        _case("c4", False, False, False),  # negative case -> excluded from denominator
    ]
    result = citation_expected_evidence(cases, "hybrid_reranked")
    assert result["answered_supported_cases"] == 2
    assert result["citation_expected_hits"] == 1
    assert result["citation_expected_evidence_rate"] == 0.5


def test_citation_expected_evidence_null_when_no_answered_supported_cases():
    cases = [_case("c1", True, True, False), _case("c2", False, False, False)]
    result = citation_expected_evidence(cases, "hybrid_reranked")
    assert result["answered_supported_cases"] == 0
    assert result["citation_expected_evidence_rate"] is None


# --- gate_score_distribution (pure) -----------------------------------------


def _case_with_gate(case_id, answerable, cosine, mode="hybrid_reranked"):
    hits = [{"cosine": cosine}] if cosine is not None else []
    return {
        "case_id": case_id,
        "answerable": answerable,
        "modes": {mode: {"eligibility": {"hits": hits}}},
    }


def test_gate_score_distribution_splits_supported_and_unsupported():
    cases = [
        _case_with_gate("c1", True, 0.70),
        _case_with_gate("c2", True, 0.50),
        _case_with_gate("c3", False, 0.30),
    ]
    dist = gate_score_distribution(cases, "hybrid_reranked")
    assert dist["supported"] == {"n": 2, "min": 0.50, "median": 0.60, "max": 0.70}
    assert dist["unsupported"] == {"n": 1, "min": 0.30, "median": 0.30, "max": 0.30}


def test_gate_score_distribution_skips_cases_with_no_hits():
    cases = [_case_with_gate("c1", True, None)]
    dist = gate_score_distribution(cases, "hybrid_reranked")
    assert dist["supported"] is None
    assert dist["unsupported"] is None


def test_gate_score_distribution_output_keys_never_say_confidence():
    # The output schema itself -- not the explanatory docstring -- must
    # never use "confidence"/"calibrated" framing for a raw cosine score.
    cases = [_case_with_gate("c1", True, 0.70)]
    dist = gate_score_distribution(cases, "hybrid_reranked")
    keys = set(dist) | set(dist["supported"])
    for key in keys:
        assert "confidence" not in key.lower()
        assert "calibrat" not in key.lower()


# --- case transition detection (pure) ---------------------------------------


def test_detect_case_transitions_finds_answer_to_abstain_flip():
    status = {
        "hybrid_reranked": {
            "c1": {0.40: False, 0.45: False, 0.50: True, 0.55: True, 0.60: True},
        }
    }
    transitions = detect_case_transitions(status)
    assert transitions == [
        CaseTransition("c1", "hybrid_reranked", 0.45, 0.50, "answered", "abstained")
    ]


def test_detect_case_transitions_records_non_monotonic_flip_without_filtering_it():
    # Threshold rises but the case flips abstain->answer -- must still be
    # recorded exactly as observed, not assumed away as impossible.
    status = {"hybrid_reranked": {"c1": {0.40: True, 0.45: False}}}
    transitions = detect_case_transitions(status)
    assert transitions == [
        CaseTransition("c1", "hybrid_reranked", 0.40, 0.45, "abstained", "answered")
    ]


def test_detect_case_transitions_empty_when_status_never_changes():
    status = {"hybrid_reranked": {"c1": dict.fromkeys(THRESHOLD_GRID, False)}}
    assert detect_case_transitions(status) == []


def test_detect_case_transitions_only_checks_adjacent_pairs():
    # A case present only at the endpoints (missing middle thresholds)
    # contributes no transition -- adjacency requires both sides present.
    status = {"hybrid_reranked": {"c1": {0.40: False, 0.60: True}}}
    assert detect_case_transitions(status) == []


# --- dispatch wiring (pure) --------------------------------------------------


def test_run_experiment_dispatches_threshold_to_threshold_sweep(monkeypatch):
    import evaluation.threshold_experiment as threshold_experiment
    from evaluation.config import ExperimentType
    from evaluation.run_experiment import RunRequest, dispatch

    called = []
    monkeypatch.setattr(
        threshold_experiment,
        "run_threshold_sweep",
        lambda repeats: called.append(repeats) or {"datasets": {}},
    )
    request = RunRequest(experiment_type=ExperimentType.THRESHOLD, repeats=2)
    result = dispatch(request)
    assert called == [2]
    assert result == {"datasets": {}}


# --- live: full sweep against the real production index --------------------


@pytestmark_live
def test_local_700_120_rebuild_matches_production_before_sweep():
    # The same baseline-equivalence property Slice 3 proved, re-verified
    # here since Slice 4 depends on it directly for evidence remapping.
    from app.core.config import get_settings
    from app.retrieval.search import load_corpus
    from qdrant_client import QdrantClient

    from evaluation.chunking_experiment import build_experiment_chunks, load_frozen_source
    from ingestion.embeddings.providers import SentenceTransformerEmbedding
    from ingestion.indexing.qdrant import NCDIndex

    settings = get_settings()
    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    documents, _ = load_frozen_source()
    chunks = build_experiment_chunks(documents, embedding, 700, 120)

    client = QdrantClient(settings.qdrant_url, timeout=10)
    index = NCDIndex(client, settings.rag_qdrant_alias)
    production_corpus = load_corpus(index, index.resolve())

    assert {c.chunk_id for c in chunks} == {c["chunk_id"] for c in production_corpus}


@pytestmark_live
def test_run_threshold_sweep_isolated_artifact_root(tmp_path):
    """One live sweep proves all of: (1) artifacts are produced correctly
    under an isolated tmp_path even though the real repository already
    holds legitimate historical artifacts for this exact deterministic
    experiment_id (from an earlier slice's manual run) -- the real
    production Qdrant/corpus is still exercised for retrieval, only WHERE
    artifacts land is redirected; (2) the no-overwrite guarantee still
    holds inside that isolated root (proven cheaply via a second direct
    write_experiment_artifacts() call, not a second full sweep);
    (3) production Qdrant is unaffected; (4) the real repository artifact
    tree is completely untouched by this run."""
    from pathlib import Path

    from app.core.config import get_settings
    from qdrant_client import QdrantClient

    from evaluation.artifacts import ExperimentAlreadyExistsError, write_experiment_artifacts
    from evaluation.run_experiment import ARTIFACT_ROOT
    from evaluation.threshold_experiment import run_threshold_sweep

    settings = get_settings()
    client = QdrantClient(settings.qdrant_url, timeout=10)
    qdrant_before = client.get_collection(settings.rag_qdrant_alias).points_count
    repo_dirs_before = {p.name for p in Path(ARTIFACT_ROOT).iterdir() if p.is_dir()}

    result = run_threshold_sweep(repeats=2, artifact_root=tmp_path)

    # (1) produced correctly, under tmp_path -- not the repo root.
    assert set(result["datasets"]) == {"development", "held_out"}
    for entry in result["datasets"].values():
        assert len(entry["per_threshold_experiment_ids"]) == 5
        assert len(set(entry["per_threshold_experiment_ids"])) == 5  # 5 distinct ids
        assert (tmp_path / entry["per_threshold_experiment_ids"][0]).is_dir()

    # (2) no-overwrite guarantee still holds inside the isolated root.
    exp_id = result["datasets"]["development"]["per_threshold_experiment_ids"][0]
    with pytest.raises(ExperimentAlreadyExistsError):
        write_experiment_artifacts(tmp_path, exp_id, {"config.json": {}})

    # (3) + (4) production and the real repository artifact tree are untouched.
    qdrant_after = client.get_collection(settings.rag_qdrant_alias).points_count
    repo_dirs_after = {p.name for p in Path(ARTIFACT_ROOT).iterdir() if p.is_dir()}
    assert qdrant_before == qdrant_after == 39
    assert repo_dirs_before == repo_dirs_after
