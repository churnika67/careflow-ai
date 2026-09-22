"""Small live smoke run, not a generation-quality benchmark."""

import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.generation.context import build_context
from app.generation.providers import create_provider
from app.generation.runtime import retrieve
from app.generation.service import RAGService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    provider = create_provider(settings)
    cases = json.loads(Path("docs/phase3_search_cases.json").read_text())
    if isinstance(cases, dict):
        cases = cases["cases"]
    questions = [case["query"] for case in cases]
    questions += [
        "What dental implant documentation is required?",
        "What chemotherapy regimen treats pancreatic cancer?",
        "Is it covered?",
        "How do I configure a Kubernetes ingress controller?",
    ]
    results = []
    for question in questions:
        hits = retrieve(question, settings)
        answer = RAGService(lambda _, rows=hits: rows, provider, settings).answer(question)
        context = build_context(hits, settings.rag_min_score, settings.rag_context_chars)
        results.append(
            {
                "question": question,
                "response": answer.model_dump(),
                "retrieval": [
                    {k: hit[k] for k in ("chunk_id", "score", "NCD_id", "NCD_vrsn_num", "section")}
                    for hit in hits
                ],
                "context_chunk_ids": [hit["chunk_id"] for hit in context.chunks],
                "cited_evidence": [
                    hit["text"]
                    for hit in hits
                    if hit["chunk_id"] in {c.chunk_id for c in answer.citations}
                ],
            }
        )
    output = {
        "purpose": "Phase 4 smoke observations; not full RAG evaluation",
        "settings": {
            "provider": provider.name,
            "model": provider.model,
            "top_k": settings.rag_top_k,
            "min_score": settings.rag_min_score,
        },
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            [
                {
                    "question": r["question"],
                    "insufficient": r["response"]["insufficient_evidence"],
                    "top_score": r["retrieval"][0]["score"] if r["retrieval"] else None,
                }
                for r in results
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
