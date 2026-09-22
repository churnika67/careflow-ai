import json
import math
from dataclasses import dataclass

FIELDS = (
    "chunk_id",
    "NCD_id",
    "NCD_vrsn_num",
    "title",
    "manual_section",
    "source_field",
    "section",
    "effective_date",
    "termination_date",
    "snapshot_data_as_of",
    "text",
    "is_continuation",
    "section_char_start",
    "section_char_end",
    "section_token_end",
    "section_token_count",
)


@dataclass(frozen=True)
class EvidenceContext:
    chunks: tuple[dict, ...]
    rendered: str


def substantive_text(chunk: dict) -> str:
    text = chunk["text"].strip()
    heading = chunk.get("section", "")
    if heading and text.startswith(heading):
        text = text[len(heading) :].strip()
    return "" if text.casefold() in {"", "n/a", "na", "not applicable"} else text


def build_context(hits: list[dict], min_score: float, max_chars: int) -> EvidenceContext:
    chunks, blocks, seen = [], [], set()
    used = 0
    for hit in hits:
        score = (
            hit.get("evidence_gate_score")
            if hit.get("retrieval_method") in {"bm25", "hybrid"}
            else hit["score"]
        )
        if score is None or not math.isfinite(score) or score < min_score:
            continue
        if not substantive_text(hit) or hit["chunk_id"] in seen:
            continue
        # JSON escaping keeps evidence text from introducing structural delimiters.
        block = json.dumps(
            {key: hit[key] for key in FIELDS if hit.get(key) is not None},
            ensure_ascii=True,
            sort_keys=True,
        )
        if used + len(block) + 1 > max_chars:
            continue  # Keep entire chunks; never truncate policy conditions.
        used += len(block) + 1
        seen.add(hit["chunk_id"])
        chunks.append(hit)
        blocks.append(block)
    return EvidenceContext(tuple(chunks), "\n".join(blocks))
