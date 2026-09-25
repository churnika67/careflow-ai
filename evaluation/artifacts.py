"""Deterministic, atomic experiment artifact writing.

An experiment's artifact directory (artifacts/evaluation/<experiment_id>/)
either does not exist, or exists complete — there is no state where a
consumer can observe a partially-written experiment. Content is built
entirely in memory by the caller, written into a hidden temporary directory
next to the target (same filesystem, so the final step is a single atomic
rename), and only then moved into place. If anything raises before that
final step, the temporary directory is removed and nothing appears under
the experiment_id at all — a failed run leaves no artifact, not a partial
one."""

import json
import os
import shutil
import tempfile
from pathlib import Path


class ExperimentAlreadyExistsError(Exception):
    """Raised when an experiment_id's artifact directory already exists.

    Because experiment_id intentionally excludes timestamp (see
    evaluation.config.config_hash), the same behavioral configuration run
    twice produces the same experiment_id. Historical artifacts are never
    silently overwritten, appended to, or deleted — the caller must choose
    a different configuration, or manually remove the prior directory
    first."""

    def __init__(self, experiment_id: str, path: Path) -> None:
        self.experiment_id = experiment_id
        self.path = path
        super().__init__(
            f"Experiment {experiment_id!r} already has artifacts at {path} — "
            "refusing to overwrite, append, or delete them."
        )


def write_experiment_artifacts(
    base_dir: Path, experiment_id: str, files: dict[str, object]
) -> Path:
    """files maps a filename (e.g. "config.json", "per_query.jsonl") to its
    content: a JSON-serializable object for ".json" files, or a list of
    JSON-serializable rows for ".jsonl" files (one per line)."""
    base_dir.mkdir(parents=True, exist_ok=True)
    final_dir = base_dir / experiment_id
    if final_dir.exists():
        raise ExperimentAlreadyExistsError(experiment_id, final_dir)

    tmp_dir = Path(tempfile.mkdtemp(dir=base_dir, prefix=f".{experiment_id}."))
    try:
        for filename, content in files.items():
            target = tmp_dir / filename
            if filename.endswith(".jsonl"):
                text = "\n".join(json.dumps(row, ensure_ascii=False) for row in content) + "\n"
            else:
                text = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
            target.write_text(text)
        os.replace(tmp_dir, final_dir)
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return final_dir


def experiment_artifacts_complete(experiment_dir: Path) -> bool:
    expected = {
        "config.json",
        "per_query.jsonl",
        "summary.json",
        "latency.json",
        "environment.json",
    }
    if not experiment_dir.is_dir():
        return False
    return expected.issubset({p.name for p in experiment_dir.iterdir()})
