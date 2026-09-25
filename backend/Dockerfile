FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml requirements.lock requirements-ingestion.lock ./
RUN pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements-ingestion.lock \
    && useradd --create-home --uid 10001 careflow
COPY backend ./backend
COPY ingestion ./ingestion
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
