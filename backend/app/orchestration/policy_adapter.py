"""Thin adapter onto the existing, verified Phase 1-7 RAG pipeline. Does not
reimplement retrieval, RRF, reranking, evidence eligibility, or citation
validation — reuses get_rag_service() exactly as POST /query does, so every
Phase 1-7 safety behavior applies unchanged to the orchestrated policy route.
"""

from app.generation.models import RAGAnswer
from app.generation.runtime import get_rag_service


def call_policy(question: str) -> RAGAnswer:
    return get_rag_service().answer(question)
