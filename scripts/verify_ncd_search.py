"""Measured Phase 3 smoke checks, not the Phase 7 retrieval benchmark."""

import argparse
import json
from contextlib import closing
from pathlib import Path

from app.core.config import get_settings
from qdrant_client import QdrantClient

from ingestion.chunking.sections import ChunkingConfig
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import ALIAS, NCDIndex
from ingestion.pipeline import build_corpus
from ingestion.verification import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--alias", default=ALIAS)
    args = parser.parse_args()
    provider = SentenceTransformerEmbedding(local_only=True)
    _, chunks, _ = build_corpus(
        Path("data/raw/cms_coverage/ncd.zip"),
        Path("docs/cms_inspection/dev_subset.json"),
        Path("docs/cms_inspection/ncd_profile.json"),
        provider,
        ChunkingConfig(),
    )
    cases = json.loads(Path("docs/phase3_search_cases.json").read_text())
    with closing(QdrantClient(url=get_settings().qdrant_url, timeout=30)) as client:
        report = verify(provider, NCDIndex(client, args.alias), chunks, cases)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['cases_passed']}/{report['cases_total']} expected documents found in top 5")
    print("Provenance, versions, null page numbers and metadata filters verified")
    if report["cases_passed"] != report["cases_total"]:
        raise SystemExit("Search smoke checks failed; see measured report")


if __name__ == "__main__":
    main()
