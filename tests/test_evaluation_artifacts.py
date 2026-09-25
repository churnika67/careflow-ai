import json

import pytest

from evaluation.artifacts import (
    ExperimentAlreadyExistsError,
    experiment_artifacts_complete,
    write_experiment_artifacts,
)


def _files(**overrides):
    defaults = {
        "config.json": {"a": 1},
        "per_query.jsonl": [{"row": 1}, {"row": 2}],
        "summary.json": {"b": 2},
        "latency.json": {"c": 3},
        "environment.json": {"d": 4},
    }
    defaults.update(overrides)
    return defaults


def test_writes_all_five_files(tmp_path):
    result_dir = write_experiment_artifacts(tmp_path, "exp-1", _files())
    assert result_dir == tmp_path / "exp-1"
    names = {p.name for p in result_dir.iterdir()}
    assert names == {
        "config.json",
        "per_query.jsonl",
        "summary.json",
        "latency.json",
        "environment.json",
    }


def test_json_files_round_trip(tmp_path):
    result_dir = write_experiment_artifacts(tmp_path, "exp-1", _files())
    assert json.loads((result_dir / "config.json").read_text()) == {"a": 1}
    assert json.loads((result_dir / "summary.json").read_text()) == {"b": 2}


def test_jsonl_is_one_json_object_per_line(tmp_path):
    result_dir = write_experiment_artifacts(tmp_path, "exp-1", _files())
    lines = (result_dir / "per_query.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert [json.loads(line) for line in lines] == [{"row": 1}, {"row": 2}]


def test_second_write_with_same_experiment_id_refuses_to_overwrite(tmp_path):
    write_experiment_artifacts(tmp_path, "exp-1", _files())
    original = (tmp_path / "exp-1" / "config.json").read_text()
    with pytest.raises(ExperimentAlreadyExistsError):
        write_experiment_artifacts(tmp_path, "exp-1", _files(**{"config.json": {"a": 999}}))
    # untouched -- not overwritten, not appended to
    assert (tmp_path / "exp-1" / "config.json").read_text() == original


def test_no_temp_directory_left_behind_after_a_successful_write(tmp_path):
    write_experiment_artifacts(tmp_path, "exp-1", _files())
    entries = {p.name for p in tmp_path.iterdir()}
    assert entries == {"exp-1"}


def test_failed_write_leaves_no_partial_artifact_directory(tmp_path, monkeypatch):
    # Simulate a mid-write failure (e.g. disk full, serialization error) by
    # making one field unserializable.
    class Unserializable:
        pass

    with pytest.raises(TypeError):
        write_experiment_artifacts(tmp_path, "exp-1", _files(**{"summary.json": Unserializable()}))
    assert not (tmp_path / "exp-1").exists()
    # and no stray hidden temp directory either
    assert list(tmp_path.iterdir()) == []


def test_experiment_artifacts_complete_true_only_when_all_five_present(tmp_path):
    result_dir = write_experiment_artifacts(tmp_path, "exp-1", _files())
    assert experiment_artifacts_complete(result_dir) is True


def test_experiment_artifacts_complete_false_for_missing_directory(tmp_path):
    assert experiment_artifacts_complete(tmp_path / "does-not-exist") is False


def test_experiment_artifacts_complete_false_for_partial_directory(tmp_path):
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "config.json").write_text("{}")
    assert experiment_artifacts_complete(partial) is False
