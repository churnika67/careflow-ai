import json
from dataclasses import asdict, dataclass
from uuid import NAMESPACE_URL, uuid5

from ingestion.cms_coverage.cleaning import CLEANER_VERSION
from ingestion.models import Chunk, Document, digest


@dataclass(frozen=True)
class ChunkingConfig:
    target_tokens: int = 700
    overlap_tokens: int = 120
    version: str = "section-paragraph-v1"

    def __post_init__(self):
        if not 32 <= self.target_tokens <= 4000:
            raise ValueError("Chunk target must be between 32 and 4000 tokens")
        if not 0 <= self.overlap_tokens < self.target_tokens // 2:
            raise ValueError("Overlap must be nonnegative and less than half the target")


def chunk_documents(documents: list[Document], tokenizer, config: ChunkingConfig) -> list[Chunk]:
    tokenizer_state = json.loads(tokenizer.backend_tokenizer.to_str())
    # Per-call padding/truncation state is not part of tokenizer identity.
    tokenizer_state.pop("padding", None)
    tokenizer_state.pop("truncation", None)
    tokenizer_sha = digest(tokenizer_state)
    chunks = []
    for document in documents:
        for section in document.sections:
            offsets = tokenizer(
                section.text,
                add_special_tokens=False,
                truncation=False,
                return_offsets_mapping=True,
                verbose=False,
            )["offset_mapping"]
            start = 0
            while start < len(offsets):
                stop = min(start + config.target_tokens, len(offsets))
                if stop < len(offsets):
                    # Prefer a paragraph boundary in the latter half of the token window.
                    lower = offsets[start + config.target_tokens // 2][0]
                    boundary = section.text.rfind("\n\n", lower, offsets[stop - 1][1])
                    if boundary >= 0:
                        while offsets[stop - 1][1] > boundary:
                            stop -= 1
                    else:
                        while stop > start + 1 and offsets[stop - 1][1] == offsets[stop][0]:
                            stop -= 1
                char_start, char_end = offsets[start][0], offsets[stop - 1][1]
                text = section.text[char_start:char_end]
                token_count = len(tokenizer.encode(text, add_special_tokens=False, verbose=False))
                if not text.strip() or token_count > config.target_tokens:
                    raise ValueError("Invalid chunk boundary or token budget")
                section_id = digest(
                    {
                        "document": document.metadata["document_version_id"],
                        "field": section.field,
                        "ordinal": section.ordinal,
                        "text": section.text,
                    }
                )
                trace = {
                    "source_field": section.field,
                    "section_ordinal": section.ordinal,
                    "section": section.heading or section.field,
                    "section_id": section_id,
                    "section_text_sha256": digest(section.text),
                    "raw_field_sha256": section.raw_field_sha256,
                    "section_char_start": char_start,
                    "section_char_end": char_end,
                    "section_token_start": start,
                    "section_token_end": stop,
                    "section_token_count": len(offsets),
                    "token_count": token_count,
                    "is_continuation": start > 0,
                    "section_links": list(section.links),
                    "chunking": asdict(config),
                    "cleaner_version": CLEANER_VERSION,
                    "tokenizer": tokenizer.name_or_path,
                    "tokenizer_sha256": tokenizer_sha,
                }
                identity = digest({"metadata": document.metadata, "trace": trace, "text": text})
                chunk_id = str(uuid5(NAMESPACE_URL, f"careflow:{identity}"))
                chunks.append(Chunk(chunk_id, text, document.metadata | trace))
                if stop == len(offsets):
                    break
                previous_start = start
                start = max(start + 1, stop - config.overlap_tokens)
                # Move to a whole-word boundary, keeping a little extra overlap if necessary.
                while start > 0 and offsets[start - 1][1] == offsets[start][0]:
                    start -= 1
                if start <= previous_start:
                    raise ValueError("A word exceeds the chunk budget; increase the target")
    if not chunks or len({c.chunk_id for c in chunks}) != len(chunks):
        raise ValueError("Empty corpus or duplicate chunk identities")
    return chunks
