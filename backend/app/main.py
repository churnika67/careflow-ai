from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analytics import router as analytics_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.multi_agent import router as multi_agent_router
from app.api.orchestrate import router as orchestrate_router
from app.api.query import router as query_router
from app.api.reviews import router as reviews_router
from app.core.config import get_settings
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

# Phase 14 Slice 1: only added when cors_allowed_origins is non-empty, so
# any deployment that never sets/overrides it (every Phase 1-13 test and
# environment) sees no behavior change at all. Never a wildcard origin,
# never combined with credentials. X-Request-ID is explicitly exposed so
# the frontend can read it cross-origin (browsers hide response headers
# from JS by default unless listed here).
# Phase 14 Slice 2: "POST" added -- Ask CareFlow's POST /query sends a
# JSON body, which triggers a browser CORS preflight regardless of origin;
# GET-only would reject that preflight. Still no other method, no other
# header beyond Content-Type, no credentials.
_cors_origins = [
    origin.strip() for origin in get_settings().cors_allowed_origins.split(",") if origin.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(query_router)
app.include_router(orchestrate_router)
app.include_router(multi_agent_router)
app.include_router(reviews_router)
app.include_router(analytics_router)
