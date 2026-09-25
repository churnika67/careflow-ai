from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    # Bounded to the standard levels only -- Pydantic's Literal rejects any
    # other string outright, never silently falling back to a default.
    # INFO is the production default so the existing structured operational
    # events (Phase 13 Slice 3) are actually visible, per Slice 4.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql://careflow:careflow_local_only@localhost:55432/careflow"
    )
    qdrant_url: str = "http://localhost:6333"
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    health_timeout_seconds: float = Field(default=3, gt=0, le=30)
    # Deliberately short and separate from health_timeout_seconds: a cache
    # operation sits in the hot request path (Redis is an OPTIONAL
    # performance dependency there, per Phase 13 Slice 2), while the health
    # check is a periodic infrastructure probe that can tolerate more
    # latency. Cache failures must not dominate request latency.
    cache_connect_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    cache_socket_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    cache_schema_version: str = Field(default="v1", min_length=1)
    # Off by default (Phase 13 Slice 5): this is the first production cache
    # integration, and existing tests/local development must see exactly
    # pre-Slice-5 behavior unless an operator explicitly opts in.
    query_embedding_cache_enabled: bool = False
    # A day, not indefinite: repeated identical policy questions within the
    # same day get the cache benefit, while long-tail distinct queries
    # naturally roll off instead of growing Redis storage unboundedly. Any
    # change to the embedding model/revision/config already invalidates via
    # the cache key itself (see build_query_embedding_cache_key), so this
    # TTL is about bounding storage/staleness of the query distribution, not
    # correctness. Bounded to at most 7 days, matching this codebase's
    # explicit-bounded-setting convention.
    query_embedding_cache_ttl_seconds: int = Field(default=86400, gt=0, le=604800)
    rag_provider: Literal["deterministic", "openai"] = "deterministic"
    rag_model: str = Field(default="gpt-4.1-mini", min_length=1)
    openai_api_key: SecretStr | None = None
    rag_provider_timeout_seconds: float = Field(default=30, gt=0, le=120)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_min_score: float = Field(default=0.6, ge=-1, le=1)
    rag_context_chars: int = Field(default=24000, ge=1000, le=80000)
    rag_model_cache: str = ".cache/models"
    rag_embedding_offline: bool = True
    rag_qdrant_alias: str = "careflow_cms_ncd"
    retrieval_mode: Literal["dense", "bm25", "hybrid"] = "dense"
    retrieval_candidate_k: int = Field(default=10, ge=1, le=20)
    retrieval_rrf_constant: int = Field(default=60, ge=1, le=1000)
    bm25_k1: float = Field(default=1.2, gt=0, le=10)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    rerank_enabled: bool = False
    rerank_candidate_k: int = Field(default=10, ge=1, le=20)
    rerank_model_cache: str = ".cache/models"
    rerank_offline: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
