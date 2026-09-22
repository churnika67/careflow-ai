from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.query import router as query_router

app = FastAPI(
    title="CareFlow AI",
    version="0.1.0",
    description="Healthcare operations intelligence using public policies and synthetic data.",
)
app.include_router(health_router)
app.include_router(query_router)
