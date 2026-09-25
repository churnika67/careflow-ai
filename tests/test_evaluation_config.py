import pytest
from pydantic import ValidationError

from evaluation.config import (
    ExperimentConfig,
    ExperimentType,
    config_hash,
    experiment_id,
    git_source_state,
)


def _config(**overrides):
    defaults = dict(
        experiment_type=ExperimentType.RETRIEVAL_BASELINE,
        dataset_version="cms-retrieval-v1",
        dataset_sha256="a" * 64,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        chunk_size=700,
        chunk_overlap=120,
        candidate_k=10,
        rrf_k=60,
        rerank_enabled=False,
        reranker_model=None,
        reranker_revision=None,
        rerank_candidates=None,
        final_top_k=5,
        evidence_threshold=0.6,
        generation_provider="deterministic",
        generation_model="first-evidence-v1",
        git_commit="abc123def456",
        timestamp="2026-01-01T00:00:00Z",
        working_tree_clean=True,
        modified_files=[],
        untracked_files=[],
    )
    defaults.update(overrides)
    return ExperimentConfig(**defaults)


def test_valid_config_constructs():
    config = _config()
    assert config.chunk_size == 700


def test_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        _config(not_a_real_field=1)


def test_rejects_chunk_size_out_of_bounds():
    with pytest.raises(ValidationError):
        _config(chunk_size=10)
    with pytest.raises(ValidationError):
        _config(chunk_size=5000)


def test_rejects_negative_chunk_overlap():
    with pytest.raises(ValidationError):
        _config(chunk_overlap=-1)


def test_rejects_candidate_k_out_of_bounds():
    with pytest.raises(ValidationError):
        _config(candidate_k=0)
    with pytest.raises(ValidationError):
        _config(candidate_k=21)


def test_rejects_non_positive_rrf_k():
    with pytest.raises(ValidationError):
        _config(rrf_k=0)


def test_rejects_evidence_threshold_out_of_range():
    with pytest.raises(ValidationError):
        _config(evidence_threshold=1.5)
    with pytest.raises(ValidationError):
        _config(evidence_threshold=-1.5)


def test_rejects_invalid_dataset_version():
    with pytest.raises(ValidationError):
        _config(dataset_version="not_a_real_dataset")


def test_rejects_invalid_generation_provider():
    with pytest.raises(ValidationError):
        _config(generation_provider="not_a_real_provider")


# --- config_hash / experiment_id ---------------------------------------


def test_config_hash_is_deterministic():
    config = _config()
    assert config_hash(config) == config_hash(config)


def test_config_hash_ignores_git_commit_and_timestamp():
    a = _config(git_commit="aaaaaaaaaaaa", timestamp="2026-01-01T00:00:00Z")
    b = _config(git_commit="bbbbbbbbbbbb", timestamp="2027-06-15T12:30:00Z")
    assert config_hash(a) == config_hash(b)


def test_config_hash_ignores_working_tree_state():
    a = _config(working_tree_clean=True, modified_files=[], untracked_files=[])
    b = _config(
        working_tree_clean=False,
        modified_files=["evaluation/config.py"],
        untracked_files=["docs/evaluation/golden_retrieval_heldout_v1.json"],
    )
    assert config_hash(a) == config_hash(b)


def test_dirty_tree_requires_modified_or_untracked_disclosure_is_representable():
    config = _config(
        working_tree_clean=False,
        modified_files=["evaluation/analysis.py", "evaluation/dataset.py"],
        untracked_files=["evaluation/config.py"],
    )
    assert config.working_tree_clean is False
    assert config.modified_files == ["evaluation/analysis.py", "evaluation/dataset.py"]


# --- git_source_state ----------------------------------------------------


def test_git_source_state_returns_the_expected_shape():
    # Deliberately not asserting *which* files are dirty -- this repo's
    # working tree state is a moving target across the life of this test
    # suite (e.g. once Phase 12 is eventually committed, nothing will be
    # dirty at all) -- only that the function's contract holds against
    # real git, not a fixture.
    state = git_source_state()
    assert isinstance(state["working_tree_clean"], bool)
    assert isinstance(state["modified_files"], list)
    assert isinstance(state["untracked_files"], list)
    assert all(isinstance(p, str) for p in state["modified_files"] + state["untracked_files"])
    assert all("/Users/" not in p for p in state["modified_files"] + state["untracked_files"])
    # consistency: clean iff both lists are empty
    is_empty = not state["modified_files"] and not state["untracked_files"]
    assert state["working_tree_clean"] == is_empty


def test_git_source_state_paths_are_repo_relative_not_absolute():
    state = git_source_state()
    for path in state["modified_files"] + state["untracked_files"]:
        assert not path.startswith("/")


def test_config_hash_changes_with_a_real_parameter():
    a = _config(chunk_size=700)
    b = _config(chunk_size=400)
    assert config_hash(a) != config_hash(b)


def test_experiment_id_uses_short_commit_and_config_hash():
    config = _config(git_commit="0123456789abcdef")
    result = experiment_id(config)
    assert result.startswith("01234567_")
    assert result == f"01234567_{config_hash(config)}"


def test_experiment_id_is_identical_for_same_commit_and_params_different_timestamp():
    a = _config(git_commit="aaaaaaaaaaaa", timestamp="2026-01-01T00:00:00Z")
    b = _config(git_commit="aaaaaaaaaaaa", timestamp="2030-01-01T00:00:00Z")
    assert experiment_id(a) == experiment_id(b)


def test_experiment_id_differs_across_commits_for_identical_params():
    a = _config(git_commit="aaaaaaaaaaaa")
    b = _config(git_commit="bbbbbbbbbbbb")
    assert experiment_id(a) != experiment_id(b)
    # but the underlying parameter identity is still recognizably the same
    assert config_hash(a) == config_hash(b)
