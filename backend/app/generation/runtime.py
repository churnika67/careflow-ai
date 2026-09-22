from contextlib import closing
from functools import lru_cache
from threading import Lock

from app.core.config import Settings, get_settings
from app.generation.providers import GenerationError, create_provider
from app.generation.service import RAGService

_embedding_lock = Lock()


@lru_cache(maxsize=1)
def load_embedding(cache: str, offline: bool):
    from ingestion.embeddings.providers import SentenceTransformerEmbedding

    return SentenceTransformerEmbedding(cache, offline)


@lru_cache(maxsize=1)
def load_reranker(cache: str, offline: bool):
    from app.reranking.cross_encoder import MiniLMCrossEncoder

    return MiniLMCrossEncoder(cache, offline)


def retrieve(question: str, settings: Settings) -> list[dict]:
    try:
        from qdrant_client import QdrantClient

        from app.retrieval.search import Retriever
        from ingestion.indexing.qdrant import NCDIndex

        # The shared tokenizer changes padding state during inference.
        with _embedding_lock:
            embedding = load_embedding(settings.rag_model_cache, settings.rag_embedding_offline)
            with closing(QdrantClient(url=settings.qdrant_url, timeout=10)) as client:
                depth = (
                    max(settings.rag_top_k, settings.rerank_candidate_k)
                    if settings.rerank_enabled
                    else settings.rag_top_k
                )
                hits = Retriever(
                    NCDIndex(client, settings.rag_qdrant_alias),
                    embedding,
                    settings.retrieval_candidate_k,
                    settings.retrieval_rrf_constant,
                    settings.bm25_k1,
                    settings.bm25_b,
                ).search(question, settings.retrieval_mode, depth, for_rag=True)
                if settings.rerank_enabled and hits:
                    from app.reranking.cross_encoder import RerankQueryError
                    from app.reranking.service import rerank

                    try:
                        hits = rerank(
                            question,
                            hits,
                            load_reranker(settings.rerank_model_cache, settings.rerank_offline),
                            settings.rag_top_k,
                        )
                    except RerankQueryError as exc:
                        raise GenerationError("rerank_query_too_long", 422) from exc
                    except Exception as exc:
                        raise GenerationError("reranking_unavailable", 503) from exc
                return hits
    except GenerationError:
        raise
    except Exception as exc:
        raise GenerationError("retrieval_unavailable", 503) from exc


def get_rag_service() -> RAGService:
    settings = get_settings()
    return RAGService(
        lambda question: retrieve(question, settings), create_provider(settings), settings
    )
