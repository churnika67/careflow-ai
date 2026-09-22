import re
from collections.abc import Callable

from pydantic import ValidationError

from app.core.config import Settings
from app.generation.context import build_context, substantive_text
from app.generation.models import Citation, GenerationDraft, QueryRequest, RAGAnswer
from app.generation.prompts import PROMPT_VERSION
from app.generation.providers import GenerationError, GenerationProvider

GENERIC_WORDS = set(
    "a an the is are it this that what which how can i my me please tell "
    "about of for to in on and or do does must should would be covered coverage "
    "required requirements documentation document justify".split()
)


class RAGService:
    def __init__(
        self,
        retrieve: Callable[[str], list[dict]],
        provider: GenerationProvider,
        settings: Settings,
    ):
        self.retrieve, self.provider, self.settings = retrieve, provider, settings

    def answer(self, question: str) -> RAGAnswer:
        question = QueryRequest(question=question).question
        hits = []

        def abstain(reason: str) -> RAGAnswer:
            return RAGAnswer(
                answer="Insufficient evidence.",
                citations=[],
                insufficient_evidence=True,
                retrieved_chunk_ids=[hit["chunk_id"] for hit in hits],
                model_provider=self.provider.name,
                model_name=self.provider.model,
                prompt_version=PROMPT_VERSION,
                abstention_reason=reason,
            )

        terms = set(re.findall(r"[a-z0-9]+", question.lower())) - GENERIC_WORDS
        if not terms:
            return abstain("ambiguous_question")
        hits = self.retrieve(question)
        if not hits:
            return abstain("no_retrieval_results")
        context = build_context(hits, self.settings.rag_min_score, self.settings.rag_context_chars)
        if not context.chunks:
            return abstain("no_eligible_evidence")
        try:
            draft = GenerationDraft.model_validate_json(self.provider.generate(question, context))
        except ValidationError as exc:
            raise GenerationError("malformed_model_output") from exc
        if draft.insufficient_evidence:
            return abstain("model_abstained")
        if not draft.quotes:
            return abstain("no_citations")
        if len(draft.quotes) > 8:
            raise GenerationError("invalid_evidence_output")
        allowed = {hit["chunk_id"]: hit for hit in context.chunks}
        citations, paragraphs, seen = [], [], set()
        for quote in draft.quotes:
            hit = allowed.get(quote.chunk_id)
            if hit is None:
                return abstain("invalid_citation")
            start = hit["text"].find(quote.quote)
            end = start + len(quote.quote)
            whole_paragraphs = (
                start >= 0
                and (start == 0 or hit["text"][start - 2 : start] == "\n\n")
                and (end == len(hit["text"]) or hit["text"][end : end + 2] == "\n\n")
            )
            if not whole_paragraphs or not substantive_text(hit | {"text": quote.quote}):
                return abstain("unsupported_quote")
            if (quote.chunk_id, quote.quote) in seen:
                continue
            seen.add((quote.chunk_id, quote.quote))
            paragraphs.append(f"CMS evidence [{quote.chunk_id}]:\n{quote.quote}")
            if not any(c.chunk_id == quote.chunk_id for c in citations):
                citations.append(
                    Citation(
                        document_id=hit["NCD_id"],
                        document_version=hit["NCD_vrsn_num"],
                        title=hit.get("title"),
                        section=hit.get("section"),
                        chunk_id=quote.chunk_id,
                        source=hit.get("viewer_url") or hit.get("source_url"),
                    )
                )
        return RAGAnswer(
            answer="\n\n".join(paragraphs),
            citations=citations,
            insufficient_evidence=False,
            retrieved_chunk_ids=[hit["chunk_id"] for hit in hits],
            model_provider=self.provider.name,
            model_name=self.provider.model,
            prompt_version=PROMPT_VERSION,
        )
