import os

import pytest

from evaluation.latency_experiment import (
    WORKFLOW_STATE_BUILDERS,
    BoundaryTiming,
    _time_async,
    _time_sync,
    analyze_concurrency,
)

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_LATENCY_INTEGRATION") != "1",
    reason="Set CAREFLOW_LATENCY_INTEGRATION=1 with Compose running (Postgres, Qdrant), the "
    "Phase 8 dev-subset ingestion applied, and models cached to exercise the real Slice 5 "
    "latency benchmarks",
)


# --- BoundaryTiming.to_summary() schema (pure) -------------------------------


def test_boundary_timing_to_summary_reuses_latency_summary_stats():
    timing = BoundaryTiming(
        cold_first_ms=12.5, warmup_count=3, samples_ms=[1, 2, 3], successful_calls=3, failed_calls=0
    )
    summary = timing.to_summary()
    for key in ("median_ms", "p95_ms", "min_ms", "max_ms", "calls"):
        assert key in summary
    assert summary["calls"] == 3
    assert summary["cold_first_ms"] == 12.5
    assert summary["warmup_count"] == 3
    assert summary["successful_calls"] == 3
    assert summary["failed_calls"] == 0


def test_boundary_timing_to_summary_handles_zero_samples():
    timing = BoundaryTiming(
        cold_first_ms=None, warmup_count=0, samples_ms=[], successful_calls=0, failed_calls=1
    )
    summary = timing.to_summary()
    assert summary["measured_calls"] == 0
    assert summary["median_ms"] is None
    assert summary["failed_calls"] == 1


def test_boundary_timing_never_reports_p99():
    timing = BoundaryTiming(
        cold_first_ms=None,
        warmup_count=0,
        samples_ms=[1, 2, 3, 4, 5],
        successful_calls=5,
        failed_calls=0,
    )
    assert "p99_ms" not in timing.to_summary()


def test_boundary_timing_failures_list_is_bounded():
    timing = BoundaryTiming(
        cold_first_ms=None,
        warmup_count=0,
        samples_ms=[],
        successful_calls=0,
        failed_calls=50,
        failures=[f"error-{i}" for i in range(50)],
    )
    assert len(timing.to_summary()["failures"]) <= 10


# --- warmup exclusion / failure tracking (pure, synchronous harness) --------


def test_time_sync_excludes_warmup_from_measured_count():
    calls_made = []

    def make_call(tag):
        def call():
            calls_made.append(tag)

        return call

    calls = [make_call("warmup") for _ in range(3)] + [make_call("measured") for _ in range(5)]
    timing = _time_sync(calls, cold=False, warmup=3)
    assert timing.warmup_count == 3
    assert len(timing.samples_ms) == 5
    assert calls_made.count("warmup") == 3
    assert calls_made.count("measured") == 5


def test_time_sync_cold_first_is_separate_from_warmup_and_measured():
    order = []

    def make_call(tag):
        def call():
            order.append(tag)

        return call

    calls = [make_call("cold")] + [make_call("warmup")] * 2 + [make_call("measured")] * 4
    timing = _time_sync(calls, cold=True, warmup=2)
    assert timing.cold_first_ms is not None
    assert len(timing.samples_ms) == 4
    assert order == ["cold", "warmup", "warmup", "measured", "measured", "measured", "measured"]


def test_time_sync_tracks_failed_calls_separately_not_silently():
    def ok():
        pass

    def fails():
        raise ValueError("boom")

    calls = [ok, fails, ok, fails, ok]
    timing = _time_sync(calls, cold=False, warmup=0)
    assert timing.successful_calls == 3
    assert timing.failed_calls == 2
    assert len(timing.samples_ms) == 3  # failed calls never contribute a sample
    assert len(timing.failures) == 2


async def test_time_async_excludes_warmup_from_measured_count():
    calls_made = []

    def make_call(tag):
        async def call():
            calls_made.append(tag)

        return call

    calls = [make_call("warmup") for _ in range(3)] + [make_call("measured") for _ in range(5)]
    timing = await _time_async(calls, cold=False, warmup=3)
    assert timing.warmup_count == 3
    assert len(timing.samples_ms) == 5


async def test_time_async_tracks_failed_calls_separately_not_silently():
    async def ok():
        pass

    async def fails():
        raise ValueError("boom")

    calls = [ok, fails, ok]
    timing = await _time_async(calls, cold=False, warmup=0)
    assert timing.successful_calls == 2
    assert timing.failed_calls == 1
    assert len(timing.samples_ms) == 2


async def test_time_async_cold_failure_is_reported_not_hidden():
    async def fails():
        raise RuntimeError("cold boom")

    async def ok():
        pass

    calls = [fails, ok, ok]
    timing = await _time_async(calls, cold=True, warmup=0)
    assert timing.cold_first_ms is None
    assert timing.failed_calls == 1


def test_perf_counter_is_the_only_elapsed_time_source():
    import inspect

    import evaluation.latency_experiment as mod

    source = inspect.getsource(mod)
    assert "datetime.now()" not in source
    assert "perf_counter" in source


# --- multi-agent workflow cases map to the four existing workflows ---------


def test_workflow_state_builders_cover_exactly_the_four_existing_workflows():
    from app.agents.models import WorkflowDecision

    built = {name: builder() for name, builder in WORKFLOW_STATE_BUILDERS.items()}
    workflows = {state["requested_workflow"] for state in built.values()}
    assert workflows == {
        WorkflowDecision.POLICY_ONLY,
        WorkflowDecision.STRUCTURED_ONLY,
        WorkflowDecision.POLICY_AND_STRUCTURED,
        WorkflowDecision.ABSTAIN,
    }
    assert len(WORKFLOW_STATE_BUILDERS) == 4  # no fifth workflow invented


def test_workflow_states_never_contain_full_healthcare_records():
    # Fixed, documented requests only reference bounded identifiers/questions
    # -- never an embedded record payload.
    for builder in WORKFLOW_STATE_BUILDERS.values():
        state = builder()
        for value in state.values():
            assert not isinstance(value, list | dict) or len(str(value)) < 2000


# --- concurrency analysis (pure) ---------------------------------------------


def test_analyze_concurrency_detects_concurrent_when_combined_near_max():
    results = {
        "policy_only": {"median_ms": 400.0},
        "structured_only": {"median_ms": 50.0},
        "policy_and_structured": {"median_ms": 410.0},  # close to max(400,50)
    }
    analysis = analyze_concurrency(results)
    assert analysis["determination"] == "CONCURRENT"


def test_analyze_concurrency_detects_sequential_when_combined_near_sum():
    results = {
        "policy_only": {"median_ms": 400.0},
        "structured_only": {"median_ms": 50.0},
        "policy_and_structured": {"median_ms": 445.0},  # close to sum(400+50)
    }
    analysis = analyze_concurrency(results)
    assert analysis["determination"] == "SEQUENTIAL"


def test_analyze_concurrency_inconclusive_on_missing_median():
    results = {
        "policy_only": {"median_ms": None},
        "structured_only": {"median_ms": 50.0},
        "policy_and_structured": {"median_ms": 60.0},
    }
    analysis = analyze_concurrency(results)
    assert analysis["determination"] == "INCONCLUSIVE"


# --- dispatch wiring (pure) --------------------------------------------------


def test_run_experiment_dispatches_latency_to_run_latency_evaluation(monkeypatch):
    import evaluation.latency_experiment as latency_experiment
    from evaluation.config import ExperimentType
    from evaluation.run_experiment import RunRequest, dispatch

    called = []

    async def fake_run():
        called.append(True)
        return {"experiment_id": "fake"}

    monkeypatch.setattr(latency_experiment, "run_latency_evaluation", fake_run)
    request = RunRequest(experiment_type=ExperimentType.LATENCY)
    result = dispatch(request)
    assert called == [True]
    assert result == {"experiment_id": "fake"}


# --- live: structured tool workload is bounded/read-only, real benchmarks --


@pytestmark_live
async def test_structured_tool_benchmark_uses_exactly_five_representative_tools():
    from app.core.config import get_settings
    from app.db.connection import connect

    from evaluation.latency_experiment import benchmark_structured_tools

    settings = get_settings()
    connection = await connect(settings)
    try:
        result = await benchmark_structured_tools(connection, warmup=1, repeats=2)
    finally:
        await connection.close()
    assert len(result["results"]) == 5
    assert len(result["cases"]) == 5
    for case in result["cases"]:
        assert case["read_only"] is True


@pytestmark_live
async def test_multi_agent_benchmark_produces_zero_failures_for_fixed_requests():
    from evaluation.latency_experiment import benchmark_multi_agent_workflows

    result = await benchmark_multi_agent_workflows(warmup=1, repeats=2)
    for workflow, summary in result["results"].items():
        assert summary["failed_calls"] == 0, f"{workflow} had unexpected failures: {summary}"


@pytestmark_live
async def test_review_persistence_benchmark_restores_counts_on_success():
    from app.core.config import get_settings
    from app.db.connection import connect

    from evaluation.latency_experiment import benchmark_review_persistence

    settings = get_settings()
    connection = await connect(settings)
    try:
        result = await benchmark_review_persistence(connection, repeats=2)
    finally:
        await connection.close()
    assert result["counts_before"] == result["counts_after_cleanup"]


@pytestmark_live
async def test_review_persistence_benchmark_restores_counts_after_injected_failure(monkeypatch):
    from app.core.config import get_settings
    from app.db.connection import connect

    import evaluation.latency_experiment as mod

    settings = get_settings()
    connection = await connect(settings)
    try:
        before = await mod._review_counts(connection)

        async def failing_apply_decision(*args, **kwargs):
            raise RuntimeError("injected benchmark failure")

        monkeypatch.setattr(mod, "apply_decision", failing_apply_decision)
        with pytest.raises(mod.ReviewBenchmarkCleanupError):
            await mod.benchmark_review_persistence(connection, repeats=2)
        monkeypatch.undo()

        after = await mod._review_counts(connection)
        assert after == before
    finally:
        await connection.close()


@pytestmark_live
def test_run_latency_evaluation_produces_artifact_with_no_full_records():
    import asyncio
    import json

    from evaluation.latency_experiment import run_latency_evaluation

    result = asyncio.run(run_latency_evaluation())
    artifact_dir = result["artifact_dir"]
    cases = json.loads((__import__("pathlib").Path(artifact_dir) / "cases.json").read_text())
    for case in cases:
        for value in case.values():
            assert len(str(value)) < 500  # bounded identity metadata only

    environment = json.loads(
        (__import__("pathlib").Path(artifact_dir) / "environment.json").read_text()
    )
    for forbidden in ("username", "hostname", "home", "USER", "HOME"):
        assert forbidden not in environment
