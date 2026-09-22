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


async def check_dependencies(settings: Settings) -> HealthResponse:
    async def probe(name: str, check: Callable[[Settings], Awaitable[None]]) -> DependencyHealth:
        try:
            async with asyncio.timeout(settings.health_timeout_seconds):
                await check(settings)
            return DependencyHealth(status="ok")
        except Exception as exc:
            # Do not expose connection strings or exception messages containing credentials.
            logger.warning("Dependency %s failed (%s)", name, type(exc).__name__)
            return DependencyHealth(status="unavailable")

    checks = {"postgresql": check_postgres, "qdrant": check_qdrant, "redis": check_redis}
    results = await asyncio.gather(*(probe(name, check) for name, check in checks.items()))
    dependencies = dict(zip(checks, results, strict=True))
    healthy = all(result.status == "ok" for result in results)
    return HealthResponse(status="ok" if healthy else "degraded", dependencies=dependencies)
