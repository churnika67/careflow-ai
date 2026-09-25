import json
import os

import pytest

from evaluation.reranker_comparison import (
    PairedCase,
    _entered_left,
    _failure_categories,
    _summarize_dataset,
    load_retrieval_and_rerank_latency,
)

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_RERANKER_COMPARISON_INTEGRATION") != "1",
    reason="Set CAREFLOW_RERANKER_COMPARISON_INTEGRATION=1 with Compose running and the frozen "
    "CMS source snapshot present to exercise the real paired hybrid/hybrid_reranked comparison",
)


def _case(
    case_id="c1",
    dataset="development",
    category="semantic",
    answerable=True,
    hybrid_rank=None,
    hybrid_abstained=False,
    hybrid_reranked_rank=None,
    hybrid_reranked_abstained=False,
    candidate_set_equal=True,
    hybrid_cites_expected=None,
    hybrid_reranked_cites_expected=None,
):
    from evaluation.metrics import rank_change

    change = rank_change(hybrid_rank, hybrid_reranked_rank) if answerable else None
    e1, l1 = _entered_left(hybrid_rank, hybrid_reranked_rank, 1)
    e3, l3 = _entered_left(hybrid_rank, hybrid_reranked_rank, 3)
    e5, l5 = _entered_left(hybrid_rank, hybrid_reranked_rank, 5)
    return PairedCase(
        case_id=case_id,
        dataset=dataset,
        category=category,
        answerable=answerable,
        hybrid_rank=hybrid_rank,
        hybrid_abstained=hybrid_abstained,
        hybrid_gate_score=0.7,
        hybrid_top_chunk_ids=["a", "b"],
        hybrid_reranked_rank=hybrid_reranked_rank,
        hybrid_reranked_abstained=hybrid_reranked_abstained,
        hybrid_reranked_gate_score=0.7,
        hybrid_reranked_top_chunk_ids=["a", "b"],
        hybrid_reranked_scores=[1.0, 0.5],
        rank_change_class=change["classification"] if change else "not_applicable",
        entered_top1=e1,
        left_top1=l1,
        entered_top3=e3,
        left_top3=l3,
        entered_top5=e5,
        left_top5=l5,
        candidate_set_equal=candidate_set_equal,
        hybrid_cites_expected=hybrid_cites_expected,
        hybrid_reranked_cites_expected=hybrid_reranked_cites_expected,
        failure_categories=[],
    )


# --- top-k entry/exit classification (pure) ---------------------------------


def test_entered_left_top_k_detects_entry():
    entered, left = _entered_left(None, 3, 5)
    assert entered is True
    assert left is False


def test_entered_left_top_k_detects_exit():
    entered, left = _entered_left(2, None, 5)
    assert entered is False
    assert left is True


def test_entered_left_top_k_neither_when_both_outside():
    entered, left = _entered_left(8, 9, 5)
    assert entered is False
    assert left is False


def test_entered_left_top_k_neither_when_both_inside_unchanged_rank():
    entered, left = _entered_left(2, 2, 5)
    assert entered is False
    assert left is False


# --- absent-from-top-k representation (pure) ---------------------------------


def test_absent_from_topk_is_represented_as_none_not_a_fabricated_rank():
    c = _case(hybrid_rank=None, hybrid_reranked_rank=3)
    assert c.hybrid_rank is None  # never coerced to e.g. 6 or 999
    assert c.rank_change_class == "improved"


# --- improved / unchanged / degraded classification (pure, reuses rank_change) --


def test_rank_change_classification_improved():
    c = _case(hybrid_rank=3, hybrid_reranked_rank=1)
    assert c.rank_change_class == "improved"


def test_rank_change_classification_degraded():
    c = _case(hybrid_rank=1, hybrid_reranked_rank=3)
    assert c.rank_change_class == "degraded"


def test_rank_change_classification_unchanged():
    c = _case(hybrid_rank=2, hybrid_reranked_rank=2)
    assert c.rank_change_class == "unchanged"


def test_rank_change_classification_not_applicable_for_negative_cases():
    c = _case(answerable=False, hybrid_rank=None, hybrid_reranked_rank=None)
    assert c.rank_change_class == "not_applicable"


# --- candidate-set equality validation (pure) --------------------------------


def test_summary_flags_when_any_case_has_unequal_candidate_sets():
    cases = [
        _case(case_id="c1", candidate_set_equal=True),
        _case(case_id="c2", candidate_set_equal=False),
    ]
    summary = _summarize_dataset("development", cases)
    assert summary["candidate_set_equal_for_all_cases"] is False


def test_summary_true_when_all_cases_have_equal_candidate_sets():
    cases = [_case(case_id="c1"), _case(case_id="c2")]
    summary = _summarize_dataset("development", cases)
    assert summary["candidate_set_equal_for_all_cases"] is True


# --- abstention transition classification (pure) -----------------------------


def test_abstention_transition_creates_false_abstention():
    c = _case(answerable=True, hybrid_abstained=False, hybrid_reranked_abstained=True)
    summary = _summarize_dataset("development", [c])
    assert len(summary["abstention_transitions"]) == 1
    assert summary["abstention_transitions"][0]["effect"] == "creates_false_abstention"


def test_abstention_transition_removes_false_abstention():
    c = _case(answerable=True, hybrid_abstained=True, hybrid_reranked_abstained=False)
    summary = _summarize_dataset("development", [c])
    assert summary["abstention_transitions"][0]["effect"] == "removes_false_abstention"


def test_abstention_transition_creates_unsupported_answer():
    c = _case(answerable=False, hybrid_abstained=True, hybrid_reranked_abstained=False)
    summary = _summarize_dataset("development", [c])
    assert summary["abstention_transitions"][0]["effect"] == "creates_unsupported_answer"


def test_abstention_transition_removes_unsupported_answer():
    c = _case(answerable=False, hybrid_abstained=False, hybrid_reranked_abstained=True)
    summary = _summarize_dataset("development", [c])
    assert summary["abstention_transitions"][0]["effect"] == "removes_unsupported_answer"


def test_no_abstention_transition_when_status_unchanged():
    c = _case(answerable=True, hybrid_abstained=False, hybrid_reranked_abstained=False)
    summary = _summarize_dataset("development", [c])
    assert summary["abstention_transitions"] == []


# --- failure taxonomy reuses only approved categories (pure) ----------------


def test_failure_categories_uses_only_approved_values():
    from evaluation.metrics import FailureCategory

    approved = {c.value for c in FailureCategory}
    categories = _failure_categories(
        answerable=True,
        hybrid_rank=None,
        hybrid_reranked_rank=3,
        hybrid_abstained=False,
        hybrid_reranked_abstained=False,
    )
    assert set(categories) <= approved


# --- aggregate metric deltas (pure) ------------------------------------------


def test_metric_deltas_reflect_rank_improvement():
    cases = [_case(case_id="c1", hybrid_rank=3, hybrid_reranked_rank=1)]
    summary = _summarize_dataset("development", cases)
    assert summary["metric_deltas"]["Hit@1"] == pytest.approx(1.0)  # 0 -> 1 hit at k=1


def test_metric_deltas_zero_when_ranks_unchanged():
    cases = [_case(case_id="c1", hybrid_rank=1, hybrid_reranked_rank=1)]
    summary = _summarize_dataset("development", cases)
    for key in ("Hit@1", "Hit@3", "Hit@5", "MRR@5"):
        assert summary["metric_deltas"][key] == pytest.approx(0.0)


# --- no winner / recommendation field (pure, structural contract) -----------


def test_summary_never_contains_a_winner_or_recommendation_field():
    cases = [_case(case_id="c1", hybrid_rank=2, hybrid_reranked_rank=1)]
    summary = _summarize_dataset("development", cases)

    def _walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                assert "winner" not in key.lower()
                assert "recommend" not in key.lower()
                assert "best_config" not in key.lower()
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(summary)


# --- latency comparison schema (pure, reads real Slice 2 artifacts) ---------


def test_latency_comparison_schema_has_required_fields():
    latency = load_retrieval_and_rerank_latency()
    for dataset in ("development", "held_out"):
        entry = latency[dataset]
        assert "hybrid_candidates_with_gate" in entry
        assert "rerank_only" in entry
        assert entry["descriptive_summed_stage_medians_ms"] == pytest.approx(
            entry["hybrid_candidates_with_gate"]["median_ms"] + entry["rerank_only"]["median_ms"]
        )
        assert entry["rerank_to_hybrid_median_ratio"] > 1  # rerank is the expensive stage


# --- model identity recorded (pure) ------------------------------------------


def test_reranker_model_identity_matches_actual_code():
    from app.reranking.cross_encoder import MODEL_NAME, MODEL_REVISION

    from evaluation.reranker_comparison import MODEL_NAME as recorded_name
    from evaluation.reranker_comparison import MODEL_REVISION as recorded_revision

    assert recorded_name == MODEL_NAME == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert recorded_revision == MODEL_REVISION


# --- runtime-vs-evaluation config distinction documented (pure) -------------


def test_module_docstring_documents_runtime_vs_evaluation_config_distinction():
    import evaluation.reranker_comparison as mod

    assert mod.__doc__ is not None
    # This module evaluates the frozen hybrid+rerank pipeline, not the live
    # multi-agent API's resolved runtime settings (dense/no-rerank, per
    # Slice 5) -- documented in run_reranker_comparison's own docstring/config.
    assert "PRODUCTION_SETTINGS" in __import__("inspect").getsource(mod)


# --- dispatch wiring (pure) --------------------------------------------------


def test_run_experiment_dispatches_reranker_comparison(monkeypatch):
    import evaluation.reranker_comparison as reranker_comparison
    from evaluation.config import ExperimentType
    from evaluation.run_experiment import RunRequest, dispatch

    called = []
    monkeypatch.setattr(
        reranker_comparison,
        "run_reranker_comparison",
        lambda: called.append(True) or {"experiment_id": "fake"},
    )
    request = RunRequest(experiment_type=ExperimentType.RERANKER_COMPARISON)
    result = dispatch(request)
    assert called == [True]
    assert result == {"experiment_id": "fake"}


# --- live: full paired comparison, artifact safety --------------------------


@pytestmark_live
def test_run_reranker_comparison_isolated_artifact_root(tmp_path):
    """One live comparison proves all of: (1) it evaluates the real
    production retrieval/rerank path and produces a safe, complete artifact
    under an isolated tmp_path even though the real repository already
    holds a legitimate historical artifact for this exact deterministic
    experiment_id (from an earlier slice's manual run); (2) the
    no-overwrite guarantee still holds inside that isolated root (proven
    cheaply via a second direct write_experiment_artifacts() call, not a
    second full comparison); (3) the real repository artifact tree is
    completely untouched by this run."""
    from pathlib import Path

    from evaluation.artifacts import ExperimentAlreadyExistsError, write_experiment_artifacts
    from evaluation.reranker_comparison import run_reranker_comparison
    from evaluation.run_experiment import ARTIFACT_ROOT

    repo_dirs_before = {p.name for p in Path(ARTIFACT_ROOT).iterdir() if p.is_dir()}

    result = run_reranker_comparison(artifact_root=tmp_path)
    artifact_dir = Path(result["artifact_dir"])
    assert artifact_dir.is_relative_to(tmp_path)  # written under tmp_path, not the repo root

    paired = [
        json.loads(line) for line in (artifact_dir / "paired_cases.jsonl").read_text().splitlines()
    ]
    assert len(paired) == 32 + 12  # every dev + held-out case is paired
    for row in paired:
        assert "text" not in row["hybrid"]
        assert "text" not in row["hybrid_reranked"]
        for value in row["hybrid"]["top_chunk_ids"] + row["hybrid_reranked"]["top_chunk_ids"]:
            assert len(value) < 100  # chunk_id, never full text

    summary = json.loads((artifact_dir / "summary.json").read_text())
    assert set(summary) == {"development", "held_out"}
    assert result["corpus_fingerprint_unchanged"] is True

    # No-overwrite guarantee still holds inside the isolated root.
    with pytest.raises(ExperimentAlreadyExistsError):
        write_experiment_artifacts(tmp_path, artifact_dir.name, {"config.json": {}})

    # The real repository artifact tree is untouched by this run.
    repo_dirs_after = {p.name for p in Path(ARTIFACT_ROOT).iterdir() if p.is_dir()}
    assert repo_dirs_before == repo_dirs_after
