"""Phase 12 Slice 5: performance/latency evaluation at meaningful system
boundaries. Measurement only -- no optimization, no production or
architecture change, no new observability infrastructure.

Reuses evaluation.metrics.Latency / latency_summary() for every statistic —
there is no second, incompatible latency-statistics implementation in this
module. Every timing boundary uses time.perf_counter(), matching the
convention already established by evaluation/run_retrieval_eval.py,
evaluation/chunking_experiment.py, evaluation/threshold_experiment.py, and
the structured JSON latency logging already present in
backend/app/agents/graph.py, backend/app/agents/structured_specialist.py,
and backend/app/api/multi_agent.py (duration_ms via perf_counter()).

Retrieval-stage and reranker-only latency are NOT re-measured here — they
are read directly from Slice 2's existing retrieval_baseline artifacts
(artifacts/evaluation/eb59bc90_774ea9a697a1 for development,
eb59bc90_a223469082ce for held_out), which already exercise exactly the
production 700/120 + hybrid_reranked configuration this slice must not
re-run or change.

Audited (not assumed) before this module was written: the live multi-agent
POLICY_ONLY path calls app.orchestration.policy_adapter.call_policy() ->
app.generation.runtime.get_rag_service() -> retrieve(), which resolves
retrieval_mode/rerank_enabled from app.core.config.get_settings() — this
process's actual environment resolves retrieval_mode="dense",
rerank_enabled=False (verified directly, not assumed). This is a genuinely
different, cheaper pipeline than the evaluation package's own
PRODUCTION_SETTINGS object (hybrid + reranking), which Slices 2-4
deliberately freeze independently of the API's mutable runtime defaults —
matching evaluation/run_retrieval_eval.py's own comment: "Freeze the Phase 6
experiment, independently of mutable API defaults." Both are real, both are
reported, and they are never conflated."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from app.agents.graph import build_multi_agent_graph
from app.agents.models import MultiAgentResponse, MultiAgentState, WorkflowDecision
from app.core.config import get_settings
from app.db.connection import connect
from app.orchestration.models import Route, Status
from app.orchestration.tools import execute_tool
from app.review.models import ReviewDecisionType
from app.review.policy import determine_review_requirement
from app.review.repository import apply_decision, create_review

from evaluation.artifacts import write_experiment_artifacts
from evaluation.config import current_git_commit, git_source_state
from evaluation.environment import capture_environment
from evaluation.metrics import latency_summary
from evaluation.run_experiment import ARTIFACT_ROOT
from ingestion.models import digest

# Known synthetic identifiers, reused verbatim from the existing Phase 8/9/10
# test fixtures (tests/test_orchestration_tools.py,
# tests/test_agents_structured_specialist.py) -- not invented here.
KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"

# A real, answerable, in-corpus development question (cms-v1-001, frozen
# dataset) -- not invented -- so POLICY_ONLY exercises genuine retrieval and
# generation, not a trivial/degenerate query.
POLICY_BENCHMARK_QUESTION = (
    "What clinical testing must support an initial claim for oxygen therapy at home?"
)
# A question with no in-corpus policy match and no structured identifier --
# resolves to ABSTAIN via the deterministic classifier/explicit workflow.
ABSTAIN_BENCHMARK_QUESTION = "What is the weather today?"

# Reused Slice 2 retrieval_baseline artifacts -- read, never re-run.
RETRIEVAL_BASELINE_ARTIFACTS = {
    "development": "eb59bc90_774ea9a697a1",
    "held_out": "eb59bc90_a223469082ce",
}


@dataclass
class BoundaryTiming:
    cold_first_ms: float | None
    warmup_count: int
    samples_ms: list[float]
    successful_calls: int
    failed_calls: int
    failures: list[str] = field(default_factory=list)

    def to_summary(self) -> dict:
        if self.samples_ms:
            stats = latency_summary(self.samples_ms)
        else:
            stats = {"calls": 0, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
        return {
            "cold_first_ms": self.cold_first_ms,
            "warmup_count": self.warmup_count,
            "measured_calls": len(self.samples_ms),
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "failures": self.failures[:10],  # bounded -- never an unbounded dump
            **stats,
        }


async def _time_async[U](
    calls: list[Callable[[], Awaitable[U]]], *, cold: bool, warmup: int
) -> BoundaryTiming:
    """calls[0:cold_count] (0 or 1) is the untimed-but-recorded cold call,
    calls[cold_count:cold_count+warmup] are untimed warmup, the remainder are
    measured. A failed call (exception) is counted as failed, its duration
    excluded from samples_ms, and never silently absorbed into a "successful
    subset" average."""
    cold_first_ms = None
    idx = 0
    if cold:
        started = perf_counter()
        try:
            await calls[idx]()
        except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
            cold_first_ms = None
            return BoundaryTiming(cold_first_ms, warmup, [], 0, 1, [repr(exc)])
        cold_first_ms = (perf_counter() - started) * 1000
        idx += 1
    for _ in range(warmup):
        await calls[idx]()
        idx += 1
    samples: list[float] = []
    successful = 0
    failed = 0
    failures: list[str] = []
    for call in calls[idx:]:
        started = perf_counter()
        try:
            await call()
        except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
            failed += 1
            failures.append(repr(exc))
            continue
        samples.append((perf_counter() - started) * 1000)
        successful += 1
    return BoundaryTiming(cold_first_ms, warmup, samples, successful, failed, failures)


def _time_sync[U](calls: list[Callable[[], U]], *, cold: bool, warmup: int) -> BoundaryTiming:
    cold_first_ms = None
    idx = 0
    if cold:
        started = perf_counter()
        try:
            calls[idx]()
        except Exception as exc:  # noqa: BLE001
            return BoundaryTiming(None, warmup, [], 0, 1, [repr(exc)])
        cold_first_ms = (perf_counter() - started) * 1000
        idx += 1
    for _ in range(warmup):
        calls[idx]()
        idx += 1
    samples: list[float] = []
    successful = 0
    failed = 0
    failures: list[str] = []
    for call in calls[idx:]:
        started = perf_counter()
        try:
            call()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append(repr(exc))
            continue
        samples.append((perf_counter() - started) * 1000)
        successful += 1
    return BoundaryTiming(cold_first_ms, warmup, samples, successful, failed, failures)


# --- A. retrieval / reranker latency (reused, not re-measured) -------------


def load_retrieval_latency() -> dict:
    result = {}
    for dataset, experiment_id in RETRIEVAL_BASELINE_ARTIFACTS.items():
        path = ARTIFACT_ROOT / experiment_id / "latency.json"
        import json

        result[dataset] = {
            "source_experiment_id": experiment_id,
            "stages": json.loads(path.read_text())["stages"],
        }
    return result


# --- B. structured specialist tool latency ----------------------------------


async def _resolve_claim_row_id(connection) -> str:
    outcome = await execute_tool(
        connection,
        Route.SYNPUF,
        "get_claims_for_beneficiary",
        {"beneficiary_id": KNOWN_BENEFICIARY_ID},
    )
    return outcome.data[0]["claim_row_id"]


async def benchmark_structured_tools(connection, *, warmup: int = 3, repeats: int = 30) -> dict:
    """Five representative bounded tools, chosen to cover the shapes the
    registry actually offers -- not an arbitrary subset and not all 18:
    a simple single-record lookup and a list query in each domain, plus one
    bounded aggregate/frequency query. No new SQL, no new tools; every call
    goes through the existing execute_tool() dispatcher unchanged."""
    claim_row_id = await _resolve_claim_row_id(connection)
    cases = [
        (
            "get_beneficiary_summary",
            Route.SYNPUF,
            {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            "cms_desynpuf",
            "simple_id_lookup",
        ),
        (
            "get_claims_for_beneficiary",
            Route.SYNPUF,
            {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            "cms_desynpuf",
            "list_by_id",
        ),
        (
            "get_claim_details",
            Route.SYNPUF,
            {"claim_row_id": claim_row_id},
            "cms_desynpuf",
            "single_record_by_uuid",
        ),
        (
            "get_patient_summary",
            Route.FHIR,
            {"patient_id": KNOWN_PATIENT_ID},
            "synthea_fhir",
            "simple_id_lookup",
        ),
        (
            "fhir_condition_frequency",
            Route.FHIR,
            {"top_n": 10},
            "synthea_fhir",
            "bounded_aggregate",
        ),
    ]
    results = {}
    case_records = []
    for tool_name, route, arguments, source_dataset, shape in cases:

        def make_call(t=tool_name, r=route, a=arguments):
            async def call():
                outcome = await execute_tool(connection, r, t, a)
                if not outcome.success:
                    raise RuntimeError(f"{t} failed: {outcome.error}")

            return call

        calls = [make_call() for _ in range(1 + warmup + repeats)]
        timing = await _time_async(calls, cold=True, warmup=warmup)
        results[tool_name] = timing.to_summary()
        case_records.append(
            {
                "case_id": f"structured_{tool_name}",
                "tool": tool_name,
                "source_dataset": source_dataset,
                "request_shape_category": shape,
                "read_only": True,
                "repetitions": repeats,
            }
        )
    return {"results": results, "cases": case_records}


# --- C. multi-agent end-to-end workflow latency ------------------------------


def _policy_only_state() -> MultiAgentState:
    return {
        "request_id": str(uuid4()),
        "question": POLICY_BENCHMARK_QUESTION,
        "requested_workflow": WorkflowDecision.POLICY_ONLY,
        "requested_policy_question": POLICY_BENCHMARK_QUESTION,
    }


def _structured_only_state() -> MultiAgentState:
    return {
        "request_id": str(uuid4()),
        "question": f"summarize beneficiary {KNOWN_BENEFICIARY_ID}",
        "requested_workflow": WorkflowDecision.STRUCTURED_ONLY,
        "requested_structured_route": Route.SYNPUF,
        "requested_tools": [
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            }
        ],
    }


def _policy_and_structured_state() -> MultiAgentState:
    return {
        "request_id": str(uuid4()),
        "question": (
            f"{POLICY_BENCHMARK_QUESTION} Also summarize beneficiary {KNOWN_BENEFICIARY_ID}."
        ),
        "requested_workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
        "requested_policy_question": POLICY_BENCHMARK_QUESTION,
        "requested_structured_route": Route.SYNPUF,
        "requested_tools": [
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            }
        ],
    }


def _abstain_state() -> MultiAgentState:
    return {
        "request_id": str(uuid4()),
        "question": ABSTAIN_BENCHMARK_QUESTION,
        "requested_workflow": WorkflowDecision.ABSTAIN,
    }


WORKFLOW_STATE_BUILDERS = {
    "policy_only": _policy_only_state,
    "structured_only": _structured_only_state,
    "policy_and_structured": _policy_and_structured_state,
    "abstain": _abstain_state,
}


async def benchmark_multi_agent_workflows(*, warmup: int = 1, repeats: int = 10) -> dict:
    """One compiled graph is reused across all calls of a given workflow —
    a deliberate service-level isolation of graph EXECUTION cost from graph
    COMPILE cost (the real API compiles a fresh graph per request; that
    per-request compile overhead is not measured here, and is disclosed as
    such). Fixed, documented requests only -- no fifth workflow invented, no
    supervisor/specialist/validator behavior modified. POLICY_ONLY is
    benchmarked FIRST, before any other boundary in this module touches the
    embedding/reranker model cache, so its cold_first_ms genuinely reflects
    first model load -- not a load already warmed by an earlier boundary."""
    settings = get_settings()
    graph = build_multi_agent_graph(settings)
    results = {}
    case_records = []
    for workflow, builder in WORKFLOW_STATE_BUILDERS.items():

        def make_call(b=builder):
            async def call():
                result = await graph.ainvoke(b())
                if result.get("status") == Status.ERROR:
                    raise RuntimeError(f"workflow returned status=error: {result.get('error')}")

            return call

        calls = [make_call() for _ in range(1 + warmup + repeats)]
        timing = await _time_async(calls, cold=True, warmup=warmup)
        results[workflow] = timing.to_summary()
        case_records.append(
            {
                "case_id": f"multi_agent_{workflow}",
                "workflow": workflow,
                "source_dataset": (
                    "cms_ncd_policy"
                    if workflow in ("policy_only", "policy_and_structured")
                    else "cms_desynpuf"
                    if workflow == "structured_only"
                    else "none"
                ),
                "request_shape_category": "fixed_documented_request",
                "read_only": True,
                "repetitions": repeats,
            }
        )
    return {"results": results, "cases": case_records}


def analyze_concurrency(multi_agent_results: dict) -> dict:
    """Compares the measured POLICY_AND_STRUCTURED median against
    max(policy_only, structured_only) (the concurrent-execution prediction)
    and policy_only + structured_only (the sequential-execution prediction).
    Does not assert either outcome without this comparison."""
    policy_median = multi_agent_results["policy_only"]["median_ms"]
    structured_median = multi_agent_results["structured_only"]["median_ms"]
    combined_median = multi_agent_results["policy_and_structured"]["median_ms"]
    if policy_median is None or structured_median is None or combined_median is None:
        return {"determination": "INCONCLUSIVE", "reason": "missing median (zero successful calls)"}
    predicted_sequential = policy_median + structured_median
    predicted_concurrent = max(policy_median, structured_median)
    # Closer (in absolute ms) to one prediction than the other.
    dist_to_sequential = abs(combined_median - predicted_sequential)
    dist_to_concurrent = abs(combined_median - predicted_concurrent)
    determination = "CONCURRENT" if dist_to_concurrent < dist_to_sequential else "SEQUENTIAL"
    return {
        "determination": determination,
        "policy_only_median_ms": policy_median,
        "structured_only_median_ms": structured_median,
        "policy_and_structured_median_ms": combined_median,
        "predicted_if_sequential_ms": predicted_sequential,
        "predicted_if_concurrent_ms": predicted_concurrent,
        "distance_to_sequential_prediction_ms": dist_to_sequential,
        "distance_to_concurrent_prediction_ms": dist_to_concurrent,
    }


# --- D. review-policy decision latency (pure function) -----------------------

_NOT_REQUIRED_RESPONSE = MultiAgentResponse(
    request_id="slice5-benchmark-not-required",
    workflow=WorkflowDecision.POLICY_ONLY,
    status=Status.OK,
    validation={"passed": True, "issues": []},
)
_REQUIRED_RESPONSE = MultiAgentResponse(
    request_id="slice5-benchmark-required",
    workflow=WorkflowDecision.POLICY_AND_STRUCTURED,
    status=Status.OK,
    validation={
        "passed": False,
        "issues": [{"code": "source_mismatch", "detail": "benchmark synthetic issue"}],
    },
)


def benchmark_review_policy(*, warmup: int = 3, repeats: int = 30) -> dict:
    scenarios = {
        "review_not_required": _NOT_REQUIRED_RESPONSE,
        "review_required": _REQUIRED_RESPONSE,
    }
    results = {}
    case_records = []
    for name, response in scenarios.items():
        calls = [
            (lambda r=response: determine_review_requirement(r)) for _ in range(warmup + repeats)
        ]
        timing = _time_sync(calls, cold=False, warmup=warmup)
        results[name] = timing.to_summary()
        case_records.append(
            {
                "case_id": f"review_policy_{name}",
                "workflow": "determine_review_requirement",
                "source_dataset": "synthetic_in_memory_response",
                "request_shape_category": "pure_function",
                "read_only": True,
                "repetitions": repeats,
            }
        )
    return {"results": results, "cases": case_records}


# --- E. review persistence latency (isolated, cleaned up) -------------------


class ReviewBenchmarkCleanupError(Exception):
    """Raised when benchmark-created review rows could not be fully cleaned
    up, or when review_cases/review_events counts do not exactly match their
    pre-benchmark values afterward. Never silently left in place."""


async def _review_counts(connection) -> tuple[int, int]:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM review_cases")
        cases = (await cursor.fetchone())[0]
        await cursor.execute("SELECT count(*) FROM review_events")
        events = (await cursor.fetchone())[0]
    return cases, events


async def benchmark_review_persistence(connection, *, repeats: int = 10) -> dict:
    """Every row this function creates (1 cold + `repeats` measured, each a
    distinct request_id) is deleted again before returning. Counts are
    checked before and after cleanup; any mismatch raises
    ReviewBenchmarkCleanupError rather than leaving benchmark rows behind.
    Reuses create_review()/apply_decision() exactly as Phase 11 does --
    same connection.transaction() + explicit connection.commit() pattern,
    not reimplemented, so this cannot reintroduce the prior ambient-
    transaction bug."""
    before_cases, before_events = await _review_counts(connection)

    created_ids: list[str] = []
    create_samples: list[float] = []
    decide_samples: list[float] = []
    create_cold_ms = None
    create_failed = 0
    decide_failed = 0

    async def _one_cycle() -> tuple[float, float]:
        request_id = f"slice5-bench-{uuid4()}"
        started = perf_counter()
        case, _created = await create_review(
            connection,
            request_id=request_id,
            workflow="policy_only",
            trigger_reason_codes=["slice5_benchmark"],
            evidence_snapshot={"benchmark": True, "request_id": request_id},
            evidence_fingerprint=digest({"benchmark_request_id": request_id}),
            previous_review_id=None,
        )
        create_ms = (perf_counter() - started) * 1000
        created_ids.append(case.review_id)
        started = perf_counter()
        await apply_decision(
            connection,
            review_id=case.review_id,
            expected_version=case.version,
            decision=ReviewDecisionType.APPROVE,
            reviewer_id="slice5-benchmark",
            reason="benchmark cleanup",
        )
        decide_ms = (perf_counter() - started) * 1000
        return create_ms, decide_ms

    try:
        try:
            create_cold_ms, decide_cold_ms = await _one_cycle()
        except Exception as exc:  # noqa: BLE001
            raise ReviewBenchmarkCleanupError(f"cold benchmark cycle failed: {exc!r}") from exc
        for _ in range(repeats):
            try:
                c_ms, d_ms = await _one_cycle()
            except Exception:  # noqa: BLE001
                create_failed += 1
                decide_failed += 1
                continue
            create_samples.append(c_ms)
            decide_samples.append(d_ms)
    finally:
        if created_ids:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM review_events WHERE review_id = ANY(%s)", (created_ids,)
                    )
                    await cursor.execute(
                        "DELETE FROM review_cases WHERE review_id = ANY(%s)", (created_ids,)
                    )
            await connection.commit()

    after_cases, after_events = await _review_counts(connection)
    if (after_cases, after_events) != (before_cases, before_events):
        raise ReviewBenchmarkCleanupError(
            f"review counts before={before_cases}/{before_events} "
            f"after={after_cases}/{after_events} -- benchmark rows were not fully removed"
        )

    create_summary = (
        latency_summary(create_samples)
        if create_samples
        else {"calls": 0, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    )
    decide_summary = (
        latency_summary(decide_samples)
        if decide_samples
        else {"calls": 0, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    )
    return {
        "results": {
            "review_case_creation": {
                "cold_first_ms": create_cold_ms,
                "warmup_count": 0,
                "measured_calls": len(create_samples),
                "successful_calls": len(create_samples),
                "failed_calls": create_failed,
                **create_summary,
            },
            "review_decision_and_event": {
                "cold_first_ms": decide_cold_ms,
                "warmup_count": 0,
                "measured_calls": len(decide_samples),
                "successful_calls": len(decide_samples),
                "failed_calls": decide_failed,
                **decide_summary,
            },
        },
        "cases": [
            {
                "case_id": "review_persistence_create",
                "workflow": "create_review",
                "source_dataset": "postgres_review",
                "request_shape_category": "db_write_isolated_benchmark_rows",
                "read_only": False,
                "repetitions": repeats,
            },
            {
                "case_id": "review_persistence_decide",
                "workflow": "apply_decision",
                "source_dataset": "postgres_review",
                "request_shape_category": "db_write_isolated_benchmark_rows",
                "read_only": False,
                "repetitions": repeats,
            },
        ],
        "counts_before": {"review_cases": before_cases, "review_events": before_events},
        "counts_after_cleanup": {"review_cases": after_cases, "review_events": after_events},
    }


# --- orchestration -----------------------------------------------------------


async def run_latency_evaluation() -> dict:
    """Runs every Slice 5 boundary once, in a fixed, documented order:
    multi-agent workflows FIRST (so POLICY_ONLY's cold_first_ms reflects a
    genuinely cold embedding/reranker model cache), then structured tools,
    then review policy/persistence. Retrieval/reranker latency is read from
    existing Slice 2 artifacts, not re-run."""
    settings = get_settings()
    git_commit = current_git_commit()
    source_state = git_source_state()

    retrieval = load_retrieval_latency()
    multi_agent = await benchmark_multi_agent_workflows()
    concurrency = analyze_concurrency(multi_agent["results"])

    connection = await connect(settings)
    try:
        structured = await benchmark_structured_tools(connection)
        review_persistence = await benchmark_review_persistence(connection)
    finally:
        await connection.close()
    review_policy = benchmark_review_policy()

    boundaries = {
        "multi_agent": multi_agent["results"],
        "structured_tools": structured["results"],
        "review_policy": review_policy["results"],
        "review_persistence": review_persistence["results"],
    }
    cases = (
        multi_agent["cases"]
        + structured["cases"]
        + review_policy["cases"]
        + review_persistence["cases"]
    )

    config = {
        "experiment_type": "latency",
        "description": (
            "Phase 12 Slice 5: service-level latency at retrieval, reranker, "
            "structured-tool, multi-agent workflow, and review-policy/"
            "persistence boundaries. Measurement only."
        ),
        "runtime_settings_audited": {
            "retrieval_mode": settings.retrieval_mode,
            "rerank_enabled": settings.rerank_enabled,
            "rag_provider": settings.rag_provider,
            "rag_min_score": settings.rag_min_score,
        },
        "git_commit": git_commit,
        "timestamp": datetime.now(UTC).isoformat(),
        **source_state,
    }
    latency = {
        "retrieval_and_reranker": retrieval,
        "boundaries": boundaries,
        "concurrency_analysis": concurrency,
        "review_persistence_counts": {
            "before": review_persistence["counts_before"],
            "after_cleanup": review_persistence["counts_after_cleanup"],
        },
    }

    experiment_id = f"{git_commit[:8]}_latency_{int(time.time())}"
    artifact_dir = write_experiment_artifacts(
        ARTIFACT_ROOT,
        experiment_id,
        {
            "config.json": config,
            "latency.json": latency,
            "environment.json": capture_environment(git_commit),
            "cases.json": cases,
        },
    )
    result = {"experiment_id": experiment_id, "artifact_dir": str(artifact_dir)}
    import json

    print(json.dumps(result, indent=2))
    return {**result, "latency": latency}
