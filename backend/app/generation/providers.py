from typing import Protocol

import httpx

from app.core.config import Settings
from app.generation.context import EvidenceContext
from app.generation.models import EvidenceQuote, GenerationDraft
from app.generation.prompts import SYSTEM_PROMPT, render_input


class GenerationError(Exception):
    def __init__(self, code: str, status_code: int = 502):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class GenerationProvider(Protocol):
    name: str
    model: str

    def generate(self, question: str, context: EvidenceContext) -> str: ...


class DeterministicProvider:
    """Offline test double: quote the first eligible chunk, without language reasoning."""

    name = "deterministic"
    model = "first-evidence-v1"

    def generate(self, question: str, context: EvidenceContext) -> str:
        quotes = []
        if context.chunks:
            hit = context.chunks[0]
            quotes = [EvidenceQuote(chunk_id=hit["chunk_id"], quote=hit["text"])]
        return GenerationDraft(insufficient_evidence=not quotes, quotes=quotes).model_dump_json()


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
            raise GenerationError("provider_not_configured", 503)
        self.model = settings.rag_model
        self.key = settings.openai_api_key.get_secret_value()
        self.timeout = settings.rag_provider_timeout_seconds
        self.transport = transport

    def generate(self, question: str, context: EvidenceContext) -> str:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={
                        "model": self.model,
                        "store": False,
                        "instructions": SYSTEM_PROMPT,
                        "input": render_input(question, context),
                        "max_output_tokens": 4000,
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "cms_evidence_answer",
                                "strict": True,
                                "schema": GenerationDraft.model_json_schema(),
                            }
                        },
                    },
                )
                response.raise_for_status()
                body = response.json()
                if body.get("status") != "completed":
                    raise GenerationError("provider_incomplete")
                parts = [
                    part
                    for item in body["output"]
                    if item.get("type") == "message"
                    for part in item.get("content", [])
                ]
                if any(part.get("type") == "refusal" for part in parts):
                    return GenerationDraft(insufficient_evidence=True, quotes=[]).model_dump_json()
                texts = [part["text"] for part in parts if part.get("type") == "output_text"]
                if len(texts) != 1 or not isinstance(texts[0], str):
                    raise GenerationError("malformed_provider_response")
                return texts[0]
        except httpx.TimeoutException as exc:
            raise GenerationError("provider_timeout", 504) from exc
        except httpx.HTTPError as exc:
            raise GenerationError("provider_unavailable") from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise GenerationError("malformed_provider_response") from exc


def create_provider(settings: Settings) -> GenerationProvider:
    if settings.rag_provider == "deterministic":
        return DeterministicProvider()
    return OpenAIProvider(settings)
