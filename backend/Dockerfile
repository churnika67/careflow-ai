FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml requirements.lock requirements-ingestion.lock ./
RUN pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements-ingestion.lock \
    && useradd --create-home --uid 10001 careflow
COPY backend ./backend
COPY ingestion ./ingestion
# Phase 17 Slice 2: docker-compose.yml's local dev topology bind-mounts
# .cache/models from the host, so this image has never needed the
# embedding model baked in before -- a real deployment target has no such
# host mount. Bakes it in at build time instead, reusing the exact
# MODEL_NAME/MODEL_REVISION this image's own runtime code already pins
# (ingestion/embeddings/providers.py), so the pinned revision is never
# duplicated or silently changed here. RAG_EMBEDDING_OFFLINE=true (set
# below) then means the running container never attempts a network model
# fetch at request time, matching Phase 1's original offline-serving
# design intent -- just applied consistently, since this image was never
# actually runnable standalone (without the compose host mount) before.
RUN python -c "\
from ingestion.embeddings.providers import MODEL_NAME, MODEL_REVISION; \
from sentence_transformers import SentenceTransformer; \
SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, cache_folder='.cache/models')"
# Phase 15 Slice 1: the read-only analytics API surfaces existing Phase 12
# evaluation evidence by reading these directories directly (fixed
# canonical paths, never a client-supplied path) -- without them the
# container has no evaluation artifacts to serve at all. Small (~3.9MB
# combined); no dataset/model weights live here. `evaluation/` is imported
# only for its lightweight, dependency-free claim_governance module (json
# claim-matrix/gap-registry parsing and validation only) -- importing it
# does not pull in sentence-transformers/torch/qdrant-client, which
# `evaluation`'s other submodules use but its own __init__.py does not.
COPY artifacts/evaluation ./artifacts/evaluation
COPY docs/evaluation ./docs/evaluation
COPY evaluation ./evaluation
# evaluation/artifacts.py writes each experiment directory via
# tempfile.mkdtemp(), which is mode 0700 -- correct on the host (only the
# developer who ran the experiment needs access), but COPY preserves that
# mode verbatim, and the container runs as the unprivileged `careflow`
# user (added below), not root. Relax read/traverse permissions on this
# container's own copy only; the host repository's file modes are
# untouched.
RUN chmod -R a+rX ./artifacts/evaluation ./docs/evaluation .cache
RUN pip install --no-deps .
USER careflow
EXPOSE 8000
# Phase 13 Slice 6: targets /ready, not /health -- /health still treats
# Redis (an OPTIONAL performance dependency, per Phase 13) as required,
# so a Redis-only outage would flip this container to "unhealthy" even
# though the API remains fully able to serve authoritative requests.
# /ready gates only on Postgres and Qdrant. See
# docs/phase13_reliability_observability_design.md's "Slice 6" section.
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
