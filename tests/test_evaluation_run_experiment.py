import pytest
from pydantic import ValidationError

from evaluation import run_experiment
from evaluation.config import ExperimentType
from evaluation.run_experiment import (
    HeldoutDatasetTamperedError,
    RunRequest,
    UnsupportedExperimentTypeError,
    _resolve_dataset,
    dispatch,
)

# --- dataset selection -------------------------------------------------


def test_development_selection_loads_the_dev_dataset():
    dataset = _resolve_dataset("development")
    assert dataset.dataset_version == "cms-retrieval-v1"
    assert len(dataset.cases) == 32


def test_held_out_selection_loads_the_frozen_heldout_dataset():
    dataset = _resolve_dataset("held_out")
    assert dataset.dataset_version == "cms-retrieval-heldout-v1"
    assert len(dataset.cases) == 12


def test_dataset_selection_is_config_driven_not_filename_sniffing():
    # DATASET_PATHS is the sole source of truth for "development"/"held_out"
    # -> path; there is no filename-substring inference anywhere in
    # _resolve_dataset.
    assert set(run_experiment.DATASET_PATHS) == {"development", "held_out"}
    assert set(run_experiment.EXPECTED_DATASET_VERSION) == {"development", "held_out"}


# --- frozen held-out hash validation -------------------------------------


def test_held_out_hash_matches_the_frozen_constant_right_now():
    # The actual live check Slice 2 must pass before any comparative
    # experiment work begins.
    dataset = _resolve_dataset("held_out")
    from ingestion.models import digest

    assert digest(dataset.model_dump()) == run_experiment.FROZEN_HELDOUT_SHA256


def test_tampered_held_out_hash_is_rejected_without_touching_the_real_file(monkeypatch):
    # Simulates a post-freeze edit by monkeypatching the expected constant
    # to a wrong value -- the real frozen file on disk is never touched.
    monkeypatch.setattr(run_experiment, "FROZEN_HELDOUT_SHA256", "0" * 64)
    with pytest.raises(HeldoutDatasetTamperedError):
        _resolve_dataset("held_out")


def test_development_dataset_has_no_frozen_hash_check():
    # Only the held-out set is frozen; the dev/regression set has no
    # equivalent tamper check (nothing in this codebase claims it's
    # immutable -- quite the opposite, Phase 7 already predates the freeze
    # concept).
    import inspect

    source = inspect.getsource(_resolve_dataset)
    assert 'name == "held_out"' in source


# --- experiment_type dispatch --------------------------------------------


IMPLEMENTED_EXPERIMENT_TYPES = {
    ExperimentType.RETRIEVAL_BASELINE,
    ExperimentType.CHUNKING,
    ExperimentType.THRESHOLD,
    ExperimentType.LATENCY,
    ExperimentType.RERANKER_COMPARISON,
}


def test_dispatch_rejects_every_unimplemented_experiment_type():
    # As of Slice 6, every ExperimentType value is genuinely implemented --
    # this loop is now vacuous by construction, kept as a regression guard:
    # if a 6th ExperimentType is ever added without a dispatch branch, this
    # starts failing (or silently running live work) rather than staying
    # silently green.
    assert set(ExperimentType) == IMPLEMENTED_EXPERIMENT_TYPES
    for experiment_type in ExperimentType:
        if experiment_type in IMPLEMENTED_EXPERIMENT_TYPES:
            continue
        request = RunRequest(experiment_type=experiment_type, dataset="development")
        with pytest.raises(UnsupportedExperimentTypeError):
            dispatch(request)


def test_dispatch_never_silently_falls_back_to_retrieval_baseline(monkeypatch):
    called = []
    monkeypatch.setattr(
        run_experiment, "run_retrieval_baseline", lambda request: called.append(request)
    )
    # latency is a real, genuinely-different implemented ExperimentType --
    # dispatching it must route to its own handler, never silently fall
    # back to retrieval_baseline. Its real handler is stubbed out so this
    # stays a fast, non-live check.
    import evaluation.latency_experiment as latency_experiment

    async def fake_run():
        return {"experiment_id": "fake"}

    monkeypatch.setattr(latency_experiment, "run_latency_evaluation", fake_run)
    request = RunRequest(experiment_type=ExperimentType.LATENCY, dataset="development")
    dispatch(request)
    assert called == []  # run_retrieval_baseline was never invoked


def test_run_request_accepts_plain_string_experiment_type():
    request = RunRequest.model_validate(
        {"experiment_type": "retrieval_baseline", "dataset": "development"}
    )
    assert request.experiment_type == ExperimentType.RETRIEVAL_BASELINE


def test_run_request_rejects_unknown_experiment_type_string():
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"experiment_type": "not_a_real_type", "dataset": "development"})


def test_run_request_rejects_unknown_dataset_value():
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {"experiment_type": "retrieval_baseline", "dataset": "not_a_real_dataset"}
        )


def test_run_request_default_repeats_is_three():
    request = RunRequest(experiment_type=ExperimentType.RETRIEVAL_BASELINE, dataset="development")
    assert request.repeats == 3
