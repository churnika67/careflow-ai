import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
import psycopg
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.config import Settings

logger = logging.getLogger(__name__)


class DependencyHealth(BaseModel):
    status: Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str = "careflow-ai"
    version: str = "0.1.0"
    dependencies: dict[str, DependencyHealth]


class LivenessResponse(BaseModel):
    """Process liveness only -- "is the CareFlow API process itself alive
    and capable of serving HTTP?" Deliberately carries no dependency
    information: a caller who needs to know whether Postgres/Qdrant/Redis
    are reachable wants ReadinessResponse (GET /ready), not this."""

    status: Literal["alive"] = "alive"
    service: str = "careflow-ai"


class ReadinessResponse(BaseModel):
    """Authoritative-dependency readiness -- "are the dependencies required
    for CareFlow's normal application behavior available?" `redis` is
    included in `dependencies` for operational visibility only: per Phase
    13's standing principle (Slice 2 onward), Redis is an OPTIONAL
    PERFORMANCE dependency, never authoritative, so its status never
    affects `status` here -- see check_readiness()."""

    status: Literal["ready", "unready"]
    service: str = "careflow-ai"
    version: str = "0.1.0"
    dependencies: dict[str, DependencyHealth]


async def check_postgres(settings: Settings) -> None:
    connection = await psycopg.AsyncConnection.connect(settings.database_url.get_secret_value())
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            if await cursor.fetchone() != (1,):
                raise RuntimeError("Unexpected database health result")


async def check_qdrant(settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=settings.health_timeout_seconds) as client:
        response = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")
        response.raise_for_status()


async def check_redis(settings: Settings) -> None:
    async with Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=settings.health_timeout_seconds,
        socket_timeout=settings.health_timeout_seconds,
    ) as client:
        if not await client.ping():
            raise RuntimeError("Unexpected Redis health result")


async def _probe(
    name: str, check: Callable[[Settings], Awaitable[None]], settings: Settings
) -> DependencyHealth:
    try:
        async with asyncio.timeout(settings.health_timeout_seconds):
            await check(settings)
        return DependencyHealth(status="ok")
    except Exception as exc:
        # Do not expose connection strings or exception messages containing credentials.
        logger.warning("Dependency %s failed (%s)", name, type(exc).__name__)
        return DependencyHealth(status="unavailable")


async def _probe_all(settings: Settings) -> dict[str, DependencyHealth]:
    checks = {"postgresql": check_postgres, "qdrant": check_qdrant, "redis": check_redis}
    results = await asyncio.gather(
        *(_probe(name, check, settings) for name, check in checks.items())
    )
    return dict(zip(checks, results, strict=True))


async def check_dependencies(settings: Settings) -> HealthResponse:
    """Legacy /health behavior -- unchanged since Phase 8: all three
    dependencies (including Redis) must be "ok" for status="ok". Preserved
    exactly, byte-for-byte in observable behavior, for backward
    compatibility (see Slice 6's design-doc section for why Redis being
    treated as required here is a known, deliberately-preserved legacy
    quirk rather than something this slice silently changes)."""
    dependencies = await _probe_all(settings)
    healthy = all(result.status == "ok" for result in dependencies.values())
    return HealthResponse(status="ok" if healthy else "degraded", dependencies=dependencies)


async def check_readiness(settings: Settings) -> ReadinessResponse:
    """Phase 13 Slice 6: readiness = Postgres AND Qdrant are both
    reachable. Each backs an entire major supported workflow (Postgres:
    structured healthcare tools and review persistence; Qdrant: every
    retrieval mode, including bm25/hybrid, which still load the corpus
    from Qdrant) -- a conservative, deliberately coarse binary rule, not
    per-workflow readiness. Redis is probed and reported for visibility
    but never gates `status`: a Redis outage alone must never make this
    endpoint report unready, per Phase 13's standing "Redis is an OPTIONAL
    PERFORMANCE dependency" principle."""
    dependencies = await _probe_all(settings)
    authoritative_ok = (
        dependencies["postgresql"].status == "ok" and dependencies["qdrant"].status == "ok"
    )
    return ReadinessResponse(
        status="ready" if authoritative_ok else "unready", dependencies=dependencies
    )
