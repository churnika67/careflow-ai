import argparse
import json
import os
import sys
from contextlib import closing
from pathlib import Path

from app.core.config import get_settings
from filelock import FileLock
from qdrant_client import QdrantClient

from ingestion.chunking.sections import ChunkingConfig, chunk_documents
from ingestion.cms_coverage.source import load_documents
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import ALIAS, NCDIndex
from ingestion.pipeline import ingest


def main():
    defaults = get_settings()
    parser = argparse.ArgumentParser(description="Ingest and search the reviewed CMS NCD subset")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "search", "rag"):
        command = commands.add_parser(name)
        command.add_argument("--qdrant-url", default=get_settings().qdrant_url)
        command.add_argument(
            "--alias", default=defaults.rag_qdrant_alias if name == "rag" else ALIAS
        )
        command.add_argument(
            "--model-cache", default=defaults.rag_model_cache if name == "rag" else ".cache/models"
        )
        command.add_argument(
            "--offline",
            action="store_true",
            default=defaults.rag_embedding_offline if name == "rag" else False,
        )
        if name == "ingest":
            command.add_argument(
                "--archive", type=Path, default=Path("data/raw/cms_coverage/ncd.zip")
            )
            command.add_argument(
                "--subset", type=Path, default=Path("docs/cms_inspection/dev_subset.json")
            )
            command.add_argument(
                "--profile", type=Path, default=Path("docs/cms_inspection/ncd_profile.json")
            )
            command.add_argument("--chunk-tokens", type=int, default=700)
            command.add_argument("--overlap-tokens", type=int, default=120)
            command.add_argument("--output", type=Path, default=Path("data/processed/cms_ncd"))
            command.add_argument("--reindex", action="store_true")
        else:
            command.add_argument("query")
            command.add_argument(
                "--rerank", action=argparse.BooleanOptionalAction, default=defaults.rerank_enabled
            )
            command.add_argument(
                "--rerank-candidates",
                type=int,
                choices=range(1, 21),
                default=defaults.rerank_candidate_k,
            )
            command.add_argument(
                "--mode", choices=("dense", "bm25", "hybrid"), default=defaults.retrieval_mode
            )
            command.add_argument(
                "--top-k",
                type=int,
                choices=range(1, 21),
                default=defaults.rag_top_k if name == "rag" else 5,
            )
            if name == "search":
                command.add_argument("--document-id")
                command.add_argument("--version")
                command.add_argument("--source-field")
                command.add_argument("--coverage-code")
    args = parser.parse_args()
    if args.command == "rag":
        from app.generation.providers import GenerationError, create_provider
        from app.generation.runtime import retrieve
        from app.generation.service import RAGService
        from pydantic import ValidationError

        settings = get_settings().model_copy(
            update={
                "qdrant_url": args.qdrant_url,
                "rag_qdrant_alias": args.alias,
                "rag_model_cache": args.model_cache,
                "rag_embedding_offline": args.offline,
                "rag_top_k": args.top_k,
                "retrieval_mode": args.mode,
                "rerank_enabled": args.rerank,
                "rerank_candidate_k": args.rerank_candidates,
            }
        )
        try:
            result = RAGService(
                lambda question: retrieve(question, settings), create_provider(settings), settings
            ).answer(args.query)
            print(result.model_dump_json(indent=2))
        except GenerationError as exc:
            print(json.dumps({"error": {"code": exc.code}}), file=sys.stderr)
            raise SystemExit(1) from exc
        except ValidationError as exc:
            print(json.dumps({"error": {"code": "invalid_question"}}), file=sys.stderr)
            raise SystemExit(2) from exc
        return
    os.environ.setdefault("HF_HOME", ".cache/huggingface")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    if args.command == "ingest":
        config = ChunkingConfig(args.chunk_tokens, args.overlap_tokens)
        # Validate the entire source before loading a model or writing to Qdrant.
        documents, report = load_documents(args.archive, args.subset, args.profile)
        Path(".cache").mkdir(exist_ok=True)
        with FileLock(".cache/cms-ingestion.lock", timeout=0):
            provider = SentenceTransformerEmbedding(args.model_cache, args.offline)
            chunks = chunk_documents(documents, provider.tokenizer, config)
            with closing(QdrantClient(url=args.qdrant_url, timeout=30)) as client:
                result = ingest(
                    documents,
                    chunks,
                    report,
                    provider,
                    NCDIndex(client, args.alias),
                    args.output,
                    args.reindex,
                )
    else:
        from app.retrieval.search import Retriever

        provider = (
            SentenceTransformerEmbedding(args.model_cache, args.offline)
            if args.mode != "bm25"
            else None
        )
        filters = {
            key: value
            for key, value in {
                "NCD_id": args.document_id,
                "NCD_vrsn_num": args.version,
                "source_field": args.source_field,
                "coverage_code": args.coverage_code,
            }.items()
            if value is not None
        }
        with closing(QdrantClient(url=args.qdrant_url, timeout=30)) as client:
            depth = max(args.top_k, args.rerank_candidates) if args.rerank else args.top_k
            result = Retriever(
                NCDIndex(client, args.alias),
                provider,
                defaults.retrieval_candidate_k,
                defaults.retrieval_rrf_constant,
                defaults.bm25_k1,
                defaults.bm25_b,
            ).search(args.query, args.mode, depth, filters)
            if args.rerank and result:
                from app.reranking.cross_encoder import MiniLMCrossEncoder, RerankQueryError
                from app.reranking.service import rerank

                try:
                    result = rerank(
                        args.query,
                        result,
                        MiniLMCrossEncoder(defaults.rerank_model_cache, defaults.rerank_offline),
                        args.top_k,
                    )
                except RerankQueryError as exc:
                    print(json.dumps({"error": {"code": "rerank_query_too_long"}}), file=sys.stderr)
                    raise SystemExit(2) from exc
                except Exception as exc:
                    print(json.dumps({"error": {"code": "reranking_unavailable"}}), file=sys.stderr)
                    raise SystemExit(1) from exc
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
