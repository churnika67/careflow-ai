from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    database_url: SecretStr = SecretStr(
        "postgresql://careflow:careflow_local_only@localhost:55432/careflow"
    )
    qdrant_url: str = "http://localhost:6333"
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    health_timeout_seconds: float = Field(default=3, gt=0, le=30)
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
