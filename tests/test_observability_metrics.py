import glob
import threading

import pytest
from app.observability import metrics as metrics_module
from app.observability.metrics import (
    _LATENCY_BUCKETS_MS,
    _Counter,
    _LatencyAggregate,
    http_errors_total,
    http_request_duration_ms,
    http_requests_total,
    query_embedding_cache_duration_ms,
    query_embedding_cache_reads_total,
    query_embedding_cache_writes_total,
    record_http_request,
    record_query_embedding_cache_read,
    record_query_embedding_cache_write,
    reset_metrics_for_tests,
    snapshot_metrics,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_metrics_for_tests()
    yield
    reset_metrics_for_tests()


# --- _Counter primitive ---------------------------------------------------------


def test_counter_increments_per_label_combination():
    counter = _Counter()
    counter.inc(("GET", "/health"))
    counter.inc(("GET", "/health"))
    counter.inc(("POST", "/orchestrate"))
    snap = counter.snapshot()
    assert snap[("GET", "/health")] == 2
    assert snap[("POST", "/orchestrate")] == 1


def test_counter_amount_parameter():
    counter = _Counter()
    counter.inc(("x",), amount=5)
    assert counter.snapshot()[("x",)] == 5


def test_counter_reset_clears_all_labels():
    counter = _Counter()
    counter.inc(("x",))
    counter.reset()
    assert counter.snapshot() == {}


def test_counter_concurrent_increments_lose_no_updates():
    counter = _Counter()
    threads_n, increments_per_thread = 20, 200

    def worker():
        for _ in range(increments_per_thread):
            counter.inc(("shared",))

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter.snapshot()[("shared",)] == threads_n * increments_per_thread


# --- _LatencyAggregate primitive -------------------------------------------------


def test_latency_aggregate_count_sum_min_max():
    agg = _LatencyAggregate()
    for value in (10.0, 20.0, 5.0):
        agg.observe(("GET", "/x"), value)
    entry = agg.snapshot()[("GET", "/x")]
    assert entry["count"] == 3
    assert entry["sum_ms"] == 35.0
    assert entry["min_ms"] == 5.0
    assert entry["max_ms"] == 20.0


def test_latency_aggregate_never_stores_raw_observations():
    # Only the bounded aggregate fields exist -- no list of individual
    # observations is retained anywhere in the entry.
    agg = _LatencyAggregate()
    agg.observe((), 1.0)
    entry = agg.snapshot()[()]
    assert set(entry) == {"count", "sum_ms", "min_ms", "max_ms", "bucket_counts"}


def test_latency_bucket_boundary_is_inclusive():
    agg = _LatencyAggregate()
    boundary = _LATENCY_BUCKETS_MS[0]
    agg.observe((), boundary)
    entry = agg.snapshot()[()]
    assert entry["bucket_counts"][0] == 1
    assert sum(entry["bucket_counts"]) == 1


def test_latency_value_above_largest_boundary_falls_into_overflow_bucket():
    agg = _LatencyAggregate()
    agg.observe((), _LATENCY_BUCKETS_MS[-1] + 1)
    entry = agg.snapshot()[()]
    assert entry["bucket_counts"][-1] == 1
    assert sum(entry["bucket_counts"][:-1]) == 0


def test_latency_bucket_count_is_bounded_regardless_of_observation_count():
    agg = _LatencyAggregate()
    for i in range(500):
        agg.observe((), float(i))
    entry = agg.snapshot()[()]
    assert len(entry["bucket_counts"]) == len(_LATENCY_BUCKETS_MS) + 1
    assert entry["count"] == 500


def test_latency_aggregate_concurrent_observations_lose_no_updates():
    agg = _LatencyAggregate()
    threads_n, observations_per_thread = 20, 200

    def worker():
        for _ in range(observations_per_thread):
            agg.observe(("shared",), 1.0)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entry = agg.snapshot()[("shared",)]
    assert entry["count"] == threads_n * observations_per_thread
    assert entry["sum_ms"] == float(threads_n * observations_per_thread)


# --- record_* / snapshot_metrics() -----------------------------------------------


def test_record_http_request_updates_count_duration_and_not_error_by_default():
    record_http_request(
        method="GET", route="/health", status_class="2xx", duration_ms=1.0, error=False
    )
    assert http_requests_total.snapshot()[("GET", "/health", "2xx")] == 1
    assert http_request_duration_ms.snapshot()[("GET", "/health")]["count"] == 1
    assert http_errors_total.snapshot() == {}


def test_record_http_request_error_true_increments_error_counter():
    record_http_request(
        method="GET", route="/reviews", status_class="5xx", duration_ms=1.0, error=True
    )
    assert http_errors_total.snapshot()[("GET", "/reviews")] == 1


def test_record_query_embedding_cache_read_and_write():
    record_query_embedding_cache_read(cache_status="hit", duration_ms=2.0)
    record_query_embedding_cache_write(write_status="written")
    assert query_embedding_cache_reads_total.snapshot()[("hit",)] == 1
    assert query_embedding_cache_writes_total.snapshot()[("written",)] == 1
    assert query_embedding_cache_duration_ms.snapshot()[()]["count"] == 1


def test_snapshot_metrics_is_bounded_and_well_formed():
    record_http_request(
        method="GET", route="/health", status_class="2xx", duration_ms=1.0, error=False
    )
    record_query_embedding_cache_read(cache_status="miss", duration_ms=3.0)
    snap = snapshot_metrics()
    assert set(snap) == {
        "http_requests_total",
        "http_errors_total",
        "http_request_duration_ms",
        "query_embedding_cache_reads_total",
        "query_embedding_cache_writes_total",
        "query_embedding_cache_duration_ms",
    }
    for series in snap.values():
        assert isinstance(series, list)


def test_reset_metrics_for_tests_clears_every_series():
    record_http_request(
        method="GET", route="/health", status_class="2xx", duration_ms=1.0, error=True
    )
    record_query_embedding_cache_read(cache_status="hit", duration_ms=1.0)
    record_query_embedding_cache_write(write_status="written")
    reset_metrics_for_tests()
    snap = snapshot_metrics()
    assert all(series == [] for series in snap.values())


# --- resettability is test-only, never an HTTP endpoint (section 28) ------------


def test_reset_metrics_for_tests_is_never_called_from_any_api_route():
    for path in glob.glob("backend/app/api/*.py"):
        with open(path) as f:
            source = f.read()
        assert "reset_metrics_for_tests" not in source, path


# --- cardinality / privacy structural checks -------------------------------------


def test_recording_functions_never_accept_a_request_id_or_credential_parameter():
    import inspect

    forbidden = {"request_id", "redis_url", "database_url", "api_key", "password", "query", "value"}
    for func in (
        metrics_module.record_http_request,
        metrics_module.record_query_embedding_cache_read,
        metrics_module.record_query_embedding_cache_write,
    ):
        params = set(inspect.signature(func).parameters)
        assert not (params & forbidden), (func.__name__, params)
