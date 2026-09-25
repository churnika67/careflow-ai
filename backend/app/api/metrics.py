from fastapi import APIRouter

from app.observability.metrics import snapshot_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> dict[str, list[dict[str, object]]]:
    """Phase 13 Slice 6: a bounded internal JSON snapshot of this
    project's own operational metrics -- NOT Prometheus exposition format,
    and not intended to be scraped by a Prometheus server expecting that
    format. See docs/phase13_reliability_observability_design.md's
    "Slice 6" section for the exact schema, the metric names, and the
    cardinality/privacy guarantees. This project has no production auth
    layer; a real deployment would normally restrict or authenticate this
    endpoint -- that is explicitly out of scope for this slice."""
    return snapshot_metrics()
