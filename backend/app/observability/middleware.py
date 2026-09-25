"""Phase 13 Slice 3: one narrow FastAPI middleware for request-ID
correlation. It does not log request/response bodies, query strings, or
authorization headers, and it does not alter any endpoint's response body
or existing error-response behavior.

Request-ID input policy (deliberately bounded, not open-ended trace-header
support): an inbound `X-Request-ID` header is honored only if it parses as
a UUID; anything else (missing, malformed, arbitrary-length untrusted text)
is replaced with a freshly generated server UUID. No external trace-header
convention (W3C traceparent, X-B3-*, etc.) is introduced -- none existed
before this slice, and none is added now."""

import logging
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.observability.logging import log_event, reset_request_id, set_request_id
from app.observability.metrics import record_http_request

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Phase 13 Slice 6: probe/self-observation endpoints are excluded from
# ordinary HTTP request metrics -- Docker's HEALTHCHECK and any /metrics
# scraper hit these on a fixed short interval, and counting that traffic
# as ordinary application request volume would only add probe noise, not
# signal. A fixed, small, literal set -- never a pattern match against
# arbitrary paths.
_METRICS_EXCLUDED_PATHS = frozenset({"/live", "/ready", "/health", "/metrics"})


def _resolve_inbound_request_id(request: Request) -> str:
    candidate = request.headers.get(REQUEST_ID_HEADER)
    if candidate:
        try:
            UUID(candidate)
        except ValueError:
            pass
        else:
            return candidate
    return str(uuid4())


def _route_template(request: Request) -> str:
    """The matched route's own registered path pattern (e.g.
    "/reviews/{review_id}/decision"), never the raw resolved path -- a
    bounded label, since the set of registered routes is small and fixed
    at startup. Starlette's router sets request.scope["route"] once a
    route has matched, in place on the same scope dict this middleware's
    Request wraps, so it is readable here after call_next() returns. If no
    route matched (e.g. a 404) or a route object cannot supply one, a
    single bounded fallback name is used -- never request.url.path, which
    would be unbounded."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Sets exactly one request_id per HTTP request into the shared
    ContextVar (see app.observability.logging), for the lifetime of that
    request only -- concurrent requests each get their own asyncio Task and
    therefore their own context, so IDs never leak across them (see
    tests/test_observability_middleware.py for a direct concurrency proof).

    Does not generate a second, unrelated ID: endpoints that previously
    called `str(uuid4())` themselves now read this same ID via
    get_request_id() instead (see the migrated api/*.py handlers), so
    exactly one ID exists per request throughout -- in the response body,
    in every downstream structured log line, and in the X-Request-ID
    response header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _resolve_inbound_request_id(request)
        token = set_request_id(request_id)
        started = perf_counter()
        excluded = request.url.path in _METRICS_EXCLUDED_PATHS
        try:
            response = await call_next(request)
        except Exception as exc:
            # A genuine unhandled failure -- today several routes (e.g. the
            # plain GET/list review endpoints) have no per-route error
            # logging at all, so this is a real new safety net, not a
            # duplicate of an endpoint's own logging. Never swallowed:
            # re-raised unchanged so the existing (unhandled-exception ->
            # framework default 500) response behavior is not altered.
            duration_ms = (perf_counter() - started) * 1000
            log_event(
                logger,
                "request_failed",
                level=logging.ERROR,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error_category=type(exc).__name__,
                duration_ms=duration_ms,
            )
            if not excluded:
                # An uncaught exception always counts as an HTTP error
                # (Starlette's own default response for this is a 500) --
                # recorded even though no Response object exists yet here.
                record_http_request(
                    method=request.method,
                    route=_route_template(request),
                    status_class="5xx",
                    duration_ms=duration_ms,
                    error=True,
                )
            raise
        finally:
            reset_request_id(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        if not excluded:
            record_http_request(
                method=request.method,
                route=_route_template(request),
                status_class=_status_class(response.status_code),
                duration_ms=(perf_counter() - started) * 1000,
                error=response.status_code >= 500,
            )
        return response
