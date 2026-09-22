from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QueryRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value.strip()


class EvidenceQuote(StrictModel):
    chunk_id: str
    quote: str


class GenerationDraft(StrictModel):
    insufficient_evidence: bool
    quotes: list[EvidenceQuote]


class Citation(StrictModel):
    document_id: str
    document_version: str
    title: str | None
    section: str | None
    chunk_id: str
    source: str | None


class RAGAnswer(StrictModel):
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool
    retrieved_chunk_ids: list[str]
    model_provider: str
    model_name: str
    prompt_version: str
    abstention_reason: str | None = None
