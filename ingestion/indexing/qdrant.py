import re
from uuid import uuid4

import numpy as np
from qdrant_client import QdrantClient, models

from ingestion.embeddings.providers import EmbeddingProvider
from ingestion.models import Chunk, digest

ALIAS = "careflow_cms_ncd"


class NCDIndex:
    def __init__(self, client: QdrantClient, alias: str = ALIAS):
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,60}", alias):
            raise ValueError("Invalid collection alias")
        self.client, self.alias = client, alias

    def resolve(self) -> str | None:
        return next(
            (
                a.collection_name
                for a in self.client.get_aliases().aliases
                if a.alias_name == self.alias
            ),
            None,
        )

    def publish(
        self, chunks: list[Chunk], vectors: np.ndarray, embedding: dict, reindex: bool = False
    ) -> dict:
        if vectors.shape != (len(chunks), embedding["dimension"]) or not np.isfinite(vectors).all():
            raise ValueError("Invalid vector dimensions or non-finite values")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
            raise ValueError("Expected unit-normalized embeddings")
        if not chunks or len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("Empty or duplicate chunks")
        fingerprint = digest({"chunks": [c.payload() for c in chunks], "embedding": embedding})
        previous = self.resolve()
        base = f"{self.alias}__{fingerprint[:20]}"
        collection = f"{base}__{uuid4().hex[:8]}" if reindex else base
        # A repeat uses the current generation, including one created by --reindex.
        if previous and previous.startswith(base) and not reindex:
            collection = previous
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection,
                vectors_config=models.VectorParams(
                    size=embedding["dimension"], distance=models.Distance.COSINE
                ),
            )
            for field in (
                "NCD_id",
                "NCD_vrsn_num",
                "source_field",
                "coverage_code",
                "document_version_id",
            ):
                self.client.create_payload_index(
                    collection, field, models.PayloadSchemaType.KEYWORD, wait=True
                )
        info = self.client.get_collection(collection)
        if (
            info.config.params.vectors.size != embedding["dimension"]
            or info.config.params.vectors.distance != models.Distance.COSINE
        ):
            raise ValueError("Existing collection configuration does not match")
        points = [
            models.PointStruct(
                id=c.chunk_id,
                vector=v.tolist(),
                payload=c.payload() | {"embedding": embedding, "index_fingerprint": fingerprint},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        # Finish all writes and verify exact contents before making this generation searchable.
        for start in range(0, len(points), 64):
            self.client.upsert(collection, points[start : start + 64], wait=True)
        if self.client.count(collection, exact=True).count != len(points):
            raise ValueError("Unexpected point count; alias was not changed")
        actual = self.client.retrieve(
            collection, ids=[p.id for p in points], with_payload=True, with_vectors=True
        )
        by_id = {str(p.id): p for p in actual}
        for expected in points:
            point = by_id.get(str(expected.id))
            if (
                point is None
                or point.payload != expected.payload
                or not np.allclose(point.vector, expected.vector, atol=1e-5)
            ):
                raise ValueError("Read-back verification failed; alias was not changed")
        actions = []
        if previous:
            actions.append(
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=self.alias))
            )
        actions.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(collection_name=collection, alias_name=self.alias)
            )
        )
        self.client.update_collection_aliases(actions)
        return {
            "alias": self.alias,
            "collection": collection,
            "previous_collection": previous,
            "index_fingerprint": fingerprint,
            "points": len(points),
            "dimension": embedding["dimension"],
            "distance": "Cosine",
            "read_back_verified": True,
        }

    def search(
        self,
        query: str,
        provider: EmbeddingProvider,
        limit: int = 5,
        filters: dict | None = None,
        *,
        collection: str | None = None,
    ) -> list[dict]:
        if not query.strip() or len(query) > 4000 or not 1 <= limit <= 20:
            raise ValueError("Query must be nonempty, at most 4000 characters; limit must be 1–20")
        allowed = {"NCD_id", "NCD_vrsn_num", "source_field", "coverage_code", "document_version_id"}
        filters = filters or {}
        if set(filters) - allowed or any(not isinstance(v, str) or not v for v in filters.values()):
            raise ValueError("Unsupported metadata filter")
        collection = collection or self.resolve()
        if collection is None:
            raise ValueError("No published index; run ingestion first")
        sample, _ = self.client.scroll(collection, limit=1, with_payload=True)
        if not sample or sample[0].payload["embedding"] != provider.describe():
            raise ValueError("Embedding configuration differs from indexed model")
        vector = provider.embed([query])[0]
        conditions = [
            models.FieldCondition(key=k, match=models.MatchValue(value=v))
            for k, v in filters.items()
        ]
        hits = self.client.query_points(
            collection,
            query=vector.tolist(),
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=limit,
            with_payload=True,
        ).points
        return [{"score": hit.score, "collection": collection, **hit.payload} for hit in hits]
