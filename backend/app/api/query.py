from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.generation.models import QueryRequest, RAGAnswer
from app.generation.providers import GenerationError
from app.generation.runtime import get_rag_service

router = APIRouter()


@router.post(
    "/query",
    response_model=RAGAnswer,
    responses={
        502: {"description": "Generation failed or returned malformed output"},
        503: {"description": "Retrieval or provider configuration unavailable"},
        504: {"description": "Generation provider timed out"},
    },
)
def query(request: QueryRequest):
    try:
        return get_rag_service().answer(request.question)
    except GenerationError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code}})
