import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ingestion.chunking.sections import ChunkingConfig, chunk_documents
from ingestion.cms_coverage.source import load_documents
from ingestion.embeddings.providers import EmbeddingProvider
from ingestion.indexing.qdrant import NCDIndex


def build_corpus(
    archive: Path, subset: Path, profile: Path, provider: EmbeddingProvider, config: ChunkingConfig
):
    documents, source_report = load_documents(archive, subset, profile)
    chunks = chunk_documents(documents, provider.tokenizer, config)
    return documents, chunks, source_report


def ingest(
    documents,
    chunks,
    source_report: dict,
    provider: EmbeddingProvider,
    index: NCDIndex,
    output: Path,
    reindex: bool = False,
) -> dict:
    spec = provider.describe()
    # Titles/headings provide retrieval context. Keywords and revision history are never embedded.
    inputs = [f"{c.metadata['title']}\n{c.metadata['section']}\n{c.text}" for c in chunks]
    vectors = provider.embed(inputs)
    output.mkdir(parents=True, exist_ok=True)
    result = index.publish(chunks, vectors, spec, reindex=reindex)
    report = {
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "source": source_report,
        "documents": len(documents),
        "sections": sum(len(d.sections) for d in documents),
        "chunks": len(chunks),
        "chunking": chunks[0].metadata["chunking"],
        "embedding": spec,
        "index": result,
        "chunk_counts_by_document": {
            d.metadata["document_version_id"]: sum(
                c.metadata["document_version_id"] == d.metadata["document_version_id"]
                for c in chunks
            )
            for d in documents
        },
        "max_chunk_tokens": max(c.metadata["token_count"] for c in chunks),
    }
    generation = output / result["collection"]
    generation.mkdir(exist_ok=True)
    for filename, rows in (
        ("documents.jsonl", [asdict(d) for d in documents]),
        ("chunks.jsonl", [c.payload() for c in chunks]),
    ):
        (generation / filename).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        )
    (generation / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
