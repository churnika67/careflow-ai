from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.multi_agent import router as multi_agent_router
from app.api.orchestrate import router as orchestrate_router
from app.api.query import router as query_router
from app.api.reviews import router as reviews_router
from app.observability.config import configure_logging
from app.observability.middleware import RequestContextMiddleware

# Configured once, at this deterministic module-import boundary -- not
# per-request, not inside middleware. Idempotent if this module is ever
# imported more than once in the same process (e.g. some test setups).
configure_logging()

app = FastAPI(
    title="CareFlow AI",
    version="0.1.0",
    description="Healthcare operations intelligence using public policies and synthetic data.",
)
app.add_middleware(RequestContextMiddleware)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(query_router)
app.include_router(orchestrate_router)
app.include_router(multi_agent_router)
app.include_router(reviews_router)
