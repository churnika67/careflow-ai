"""Phase 13 Slice 6: a small, bounded, thread-safe in-process metrics
foundation -- not a monitoring platform.

`prometheus_client` is not a dependency of this project (confirmed by
inspection before writing this module), and this slice deliberately does
not add it -- see the module's docstring in
docs/phase13_reliability_observability_design.md's "Slice 6" section for
why. This is a fixed, small registry of counters and latency aggregates,
not a generic metrics library: the set of metric NAMES is bounded and
declared once, at the bottom of this module, exactly like this codebase's
existing FORBIDDEN_FIELD_NAMES/CacheReadStatus-style bounded-vocabulary
conventions elsewhere in Phase 13.

Cardinality discipline (critical -- see docs/phase13_reliability_
observability_design.md's "Metric cardinality policy"): every label used
here is drawn from a small, fixed vocabulary known at call time -- an HTTP
method, a route TEMPLATE (never a raw dynamic path), an HTTP status class,
or one of Slice 2's own CacheReadStatus/CacheWriteStatus enum values.
Nothing here ever accepts a request_id, a raw path, a query, a patient/
beneficiary/claim/review ID, a cache key, or an exception message as a
label -- there is no code path in this module through which one could
become a label, by construction.

Storage is bounded: a counter is a dict keyed by a fixed label tuple, and a
latency aggregate stores only count/sum/min/max plus a small fixed set of
bucket counts (_LATENCY_BUCKETS_MS) -- never a growing list of raw
observations. The number of distinct label combinations is bounded by the
number of fixed labels' own bounded vocabularies (HTTP methods x
registered route templates x status classes, etc.), not by request volume
or by anything request-supplied.

Latency aggregates are intentionally NOT a Prometheus-style cumulative
histogram and do NOT expose or compute any percentile (p50/p95/p99) --
count/sum/min/max plus per-bucket (exclusive, not cumulative) counts are
exposed as-is. Computing a percentile from this coarse a bucket layout
would misrepresent precision this module does not have; a real percentile
would need either raw samples (which this module deliberately never
retains) or a proper streaming quantile structure, neither of which is
in scope for this slice."""

import threading

# A small, fixed bucket boundary set (upper-bound-inclusive, milliseconds).
# An observation strictly greater than the largest boundary falls into the
# final "+Inf" bucket. Deliberately coarse -- this is for a rough shape at
# a glance on an internal JSON endpoint, not precise percentile estimation.
_LATENCY_BUCKETS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)


class _Counter:
    """A thread-safe counter keyed by a fixed-arity label tuple. Never
    stores anything but an integer per distinct label combination -- no
    per-observation history."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, ...], int] = {}

    def inc(self, labels: tuple[str, ...], amount: int = 1) -> None:
        with self._lock:
            self._values[labels] = self._values.get(labels, 0) + amount

    def snapshot(self) -> dict[tuple[str, ...], int]:
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


class _LatencyAggregate:
    """A thread-safe, bounded latency aggregate keyed by a fixed-arity
    label tuple: count, sum, min, max, plus exclusive counts across
    _LATENCY_BUCKETS_MS. Never retains an individual observation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[tuple[str, ...], dict[str, object]] = {}

    def observe(self, labels: tuple[str, ...], duration_ms: float) -> None:
        with self._lock:
            entry = self._data.get(labels)
            if entry is None:
                entry = {
                    "count": 0,
                    "sum_ms": 0.0,
                    "min_ms": None,
                    "max_ms": None,
                    "bucket_counts": [0] * (len(_LATENCY_BUCKETS_MS) + 1),
                }
                self._data[labels] = entry
            entry["count"] += 1
            entry["sum_ms"] += duration_ms
            entry["min_ms"] = (
                duration_ms if entry["min_ms"] is None else min(entry["min_ms"], duration_ms)
            )
            entry["max_ms"] = (
                duration_ms if entry["max_ms"] is None else max(entry["max_ms"], duration_ms)
            )
            for index, boundary in enumerate(_LATENCY_BUCKETS_MS):
                if duration_ms <= boundary:
                    entry["bucket_counts"][index] += 1
                    break
            else:
                entry["bucket_counts"][-1] += 1

    def snapshot(self) -> dict[tuple[str, ...], dict[str, object]]:
        with self._lock:
            return {
                labels: {**entry, "bucket_counts": list(entry["bucket_counts"])}
                for labels, entry in self._data.items()
            }

    def reset(self) -> None:
        with self._lock:
            self._data.clear()


def _labeled_snapshot(counter: _Counter, label_names: tuple[str, ...]) -> list[dict[str, object]]:
    return [
        {**dict(zip(label_names, labels, strict=True)), "count": count}
        for labels, count in sorted(counter.snapshot().items())
    ]


def _latency_snapshot(
    aggregate: _LatencyAggregate, label_names: tuple[str, ...]
) -> list[dict[str, object]]:
    return [
        {
            **dict(zip(label_names, labels, strict=True)),
            "count": entry["count"],
            "sum_ms": entry["sum_ms"],
            "min_ms": entry["min_ms"],
            "max_ms": entry["max_ms"],
            "bucket_boundaries_ms": list(_LATENCY_BUCKETS_MS),
            "bucket_counts": entry["bucket_counts"],
        }
        for labels, entry in sorted(aggregate.snapshot().items())
    ]


# --- the fixed metric registry (bounded metric names) -------------------------

http_requests_total = _Counter()  # labels: method, route, status_class
http_errors_total = _Counter()  # labels: method, route
http_request_duration_ms = _LatencyAggregate()  # labels: method, route

query_embedding_cache_reads_total = _Counter()  # labels: cache_status
query_embedding_cache_writes_total = _Counter()  # labels: write_status
query_embedding_cache_duration_ms = _LatencyAggregate()  # unlabeled


def record_http_request(
    *, method: str, route: str, status_class: str, duration_ms: float, error: bool
) -> None:
    http_requests_total.inc((method, route, status_class))
    http_request_duration_ms.observe((method, route), duration_ms)
    if error:
        http_errors_total.inc((method, route))


def record_query_embedding_cache_read(*, cache_status: str, duration_ms: float) -> None:
    query_embedding_cache_reads_total.inc((cache_status,))
    query_embedding_cache_duration_ms.observe((), duration_ms)


def record_query_embedding_cache_write(*, write_status: str) -> None:
    query_embedding_cache_writes_total.inc((write_status,))


def snapshot_metrics() -> dict[str, list[dict[str, object]]]:
    """Bounded aggregate metrics only -- never a request ID, a query, a
    patient/beneficiary/claim/review ID, a cache key, or a credential; see
    this module's own docstring for why none of those can appear here by
    construction."""
    return {
        "http_requests_total": _labeled_snapshot(
            http_requests_total, ("method", "route", "status_class")
        ),
        "http_errors_total": _labeled_snapshot(http_errors_total, ("method", "route")),
        "http_request_duration_ms": _latency_snapshot(
            http_request_duration_ms, ("method", "route")
        ),
        "query_embedding_cache_reads_total": _labeled_snapshot(
            query_embedding_cache_reads_total, ("cache_status",)
        ),
        "query_embedding_cache_writes_total": _labeled_snapshot(
            query_embedding_cache_writes_total, ("write_status",)
        ),
        "query_embedding_cache_duration_ms": _latency_snapshot(
            query_embedding_cache_duration_ms, ()
        ),
    }


def reset_metrics_for_tests() -> None:
    """Test-only. Never exposed as an HTTP endpoint -- there is no route
    anywhere in backend/app/api/ that calls this."""
    for counter in (
        http_requests_total,
        http_errors_total,
        query_embedding_cache_reads_total,
        query_embedding_cache_writes_total,
    ):
        counter.reset()
    for aggregate in (http_request_duration_ms, query_embedding_cache_duration_ms):
        aggregate.reset()
