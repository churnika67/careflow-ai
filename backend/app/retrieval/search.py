from app.retrieval.fusion import dense_results, reciprocal_rank_fusion
from app.retrieval.lexical import BM25Index, validate_search
from ingestion.indexing.qdrant import NCDIndex

MODES = ("dense", "bm25", "hybrid")


def load_corpus(index: NCDIndex, collection: str) -> list[dict]:
    rows, offset = [], None
    expected = index.client.count(collection, exact=True).count
    while True:
        points, offset = index.client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        for point in points:
            if not point.payload or str(point.id) != point.payload.get("chunk_id"):
                raise ValueError("Qdrant point and chunk ID differ")
            rows.append(point.payload | {"collection": collection})
        if offset is None:
            break
    if len(rows) != expected or len({row["chunk_id"] for row in rows}) != expected or not rows:
        raise ValueError("Empty, duplicate or changing corpus")
    if len({row["index_fingerprint"] for row in rows}) != 1:
        raise ValueError("Mixed index generations")
    return sorted(rows, key=lambda row: row["chunk_id"])


class Retriever:
    def __init__(
        self,
        index: NCDIndex,
        embedding=None,
        candidate_k: int = 10,
        rrf_constant: int = 60,
        bm25_k1: float = 1.2,
        bm25_b: float = 0.75,
    ):
        if not 1 <= candidate_k <= 20 or rrf_constant <= 0:
            raise ValueError("Invalid candidate depth or RRF constant")
        self.index, self.embedding = index, embedding
        self.candidate_k, self.rrf_constant = candidate_k, rrf_constant
        self.bm25_k1, self.bm25_b = bm25_k1, bm25_b

    def search(
        self,
        query: str,
        mode: str = "dense",
        top_k: int = 5,
        filters: dict | None = None,
        for_rag: bool = False,
    ) -> list[dict]:
        if mode not in MODES:
            raise ValueError("Invalid retrieval mode")
        filters = validate_search(query, top_k, filters)
        if not query.strip():
            return []
        collection = self.index.resolve()
        if collection is None:
            raise ValueError("No published index; run ingestion first")
        dense = []
        if mode != "bm25" or for_rag:
            if self.embedding is None:
                raise ValueError("Dense retrieval or RAG evidence checking requires embeddings")
            depth = top_k if mode == "dense" else max(top_k, self.candidate_k)
            if for_rag and mode != "dense":
                depth = 20
            dense = dense_results(
                self.index.search(query, self.embedding, depth, filters, collection=collection)
            )
        if mode == "dense":
            return dense
        lexical = BM25Index(load_corpus(self.index, collection), self.bm25_k1, self.bm25_b).search(
            query, max(top_k, self.candidate_k) if mode == "hybrid" else top_k, filters
        )
        hits = (
            lexical
            if mode == "bm25"
            else reciprocal_rank_fusion(
                dense[: max(top_k, self.candidate_k)], lexical, top_k, self.rrf_constant
            )
        )
        if for_rag:
            # Preserve Phase 4's cosine gate without interpreting lexical/fusion scores as cosine.
            cosine = {hit["chunk_id"]: hit["dense_score"] for hit in dense}
            hits = [hit | {"evidence_gate_score": cosine.get(hit["chunk_id"])} for hit in hits]
        return hits
