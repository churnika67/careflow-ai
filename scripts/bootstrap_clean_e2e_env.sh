#!/usr/bin/env bash
# Phase 16 Slice 3: proves E2E prerequisites (Postgres, Qdrant, Redis,
# backend, CMS retrieval index, FHIR fixtures, SynPUF fixtures) can be
# established deterministically from a completely fresh environment.
#
# Isolation strategy: a SEPARATE Docker Compose project
# ("careflow-ai-e2e-clean" by default, override with E2E_CLEAN_PROJECT)
# reusing the SAME docker-compose.yml service definitions, on different
# host ports and with its own Postgres database name. Compose namespaces
# named volumes by project name, so this project's postgres_data/
# qdrant_data are entirely separate volumes from the developer stack's --
# nothing here can read, write, or delete the developer stack's data, and
# the developer stack is never stopped.
#
# Schema and data are established using the SAME commands the developer
# stack was built with -- no second ETL implementation:
#   - `python -m app.db.migrate`          (schema, idempotent)
#   - `python -m ingestion.cli ingest`         (CMS policy corpus -> Qdrant)
#   - `python -m ingestion.cli ingest-fhir`    (Synthea dev-subset -> Postgres)
#   - `python -m ingestion.cli ingest-synpuf`  (DE-SynPUF dev-subset -> Postgres)
#
# Usage:
#   scripts/bootstrap_clean_e2e_env.sh up       # create + populate, print .env.e2e-clean
#   scripts/bootstrap_clean_e2e_env.sh down     # tear down (stop + remove volumes)
#
# `up` is idempotent-ish (safe to re-run; migrations/ingestion no-op or
# reindex as their own commands already guarantee) but is intended to run
# against a brand-new project so it always proves a genuinely clean start.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT="${E2E_CLEAN_PROJECT:-careflow-ai-e2e-clean}"
POSTGRES_DB="${E2E_CLEAN_POSTGRES_DB:-careflow_e2e_clean}"
POSTGRES_USER="${E2E_CLEAN_POSTGRES_USER:-careflow}"
POSTGRES_PASSWORD="${E2E_CLEAN_POSTGRES_PASSWORD:-careflow_local_only}"
POSTGRES_PORT="${E2E_CLEAN_POSTGRES_PORT:-25432}"
QDRANT_PORT="${E2E_CLEAN_QDRANT_PORT:-26333}"
REDIS_PORT="${E2E_CLEAN_REDIS_PORT:-26379}"
BACKEND_PORT="${E2E_CLEAN_BACKEND_PORT:-28000}"

COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml)

export POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_PORT QDRANT_PORT REDIS_PORT BACKEND_PORT
# Deterministic provider: no OpenAI key needed to prove any of this.
export RAG_PROVIDER="${RAG_PROVIDER:-deterministic}"
export OPENAI_API_KEY=""

DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}"
QDRANT_URL="http://localhost:${QDRANT_PORT}"
REDIS_URL="redis://localhost:${REDIS_PORT}/0"
BACKEND_URL="http://localhost:${BACKEND_PORT}"

cmd="${1:-up}"

teardown() {
  echo "[bootstrap] tearing down project '$PROJECT' (containers + volumes only for this project)..."
  "${COMPOSE[@]}" down -v --remove-orphans
}

if [[ "$cmd" == "down" ]]; then
  teardown
  exit 0
fi

if [[ "$cmd" != "up" ]]; then
  echo "usage: $0 [up|down]" >&2
  exit 2
fi

START_TS=$(date +%s)

echo "[bootstrap] project=$PROJECT db=$POSTGRES_DB ports pg=$POSTGRES_PORT qdrant=$QDRANT_PORT redis=$REDIS_PORT backend=$BACKEND_PORT"
echo "[bootstrap] starting isolated postgres/qdrant/redis..."
"${COMPOSE[@]}" up -d postgres qdrant redis

echo "[bootstrap] waiting for postgres+redis healthchecks..."
deadline=$((SECONDS + 90))
while true; do
  pg_status=$("${COMPOSE[@]}" ps postgres --format '{{.Health}}' 2>/dev/null || echo "")
  redis_status=$("${COMPOSE[@]}" ps redis --format '{{.Health}}' 2>/dev/null || echo "")
  if [[ "$pg_status" == "healthy" && "$redis_status" == "healthy" ]]; then
    break
  fi
  if (( SECONDS > deadline )); then
    echo "[bootstrap] FAILED: postgres/redis did not become healthy in time (pg=$pg_status redis=$redis_status)" >&2
    exit 1
  fi
  sleep 2
done
echo "[bootstrap] postgres+redis healthy."

echo "[bootstrap] applying schema migrations (python -m app.db.migrate)..."
DATABASE_URL="$DATABASE_URL" QDRANT_URL="$QDRANT_URL" REDIS_URL="$REDIS_URL" \
  python -m app.db.migrate

# Raw source archives are large and deliberately gitignored (see
# docs/cms_ingestion.md, docs/phase8_structured_health_data.md's
# "Reproduction" section) -- a genuinely fresh checkout has none of them.
# Downloaded here with the exact same commands those docs already give,
# skipped when already present (this script also runs against a developer
# machine that likely already has them, where re-downloading ~130MB on
# every invocation would be pure waste). Each file's own checksum is
# verified by the ingestion pipeline itself against the committed
# docs/cms_inspection/*_profile.json, not by this script.
echo "[bootstrap] fetching raw source archives (skipped if already present)..."
mkdir -p data/raw/cms_coverage data/raw/cms_synpuf data/raw/synthea
# The CMS NCD archive is the one exception to "download the live source":
# https://downloads.cms.gov/.../exports/ncd.zip is CMS's *current* export,
# not a pinned historical release like the FHIR/SynPUF URLs below -- CMS
# updates it over time, so a fresh download today legitimately no longer
# matches the archive_sha256 in the already-committed, already-reviewed
# docs/cms_inspection/ncd_profile.json (confirmed empirically: this is
# exactly the checksum-gate failure a genuinely fresh CI runner hit).
# docs/cms_ingestion.md already documented this as a known upstream
# limitation ("preserve your original download") before this was found.
# The exact byte-identical archive that profile was built from is
# committed at docs/cms_inspection/ncd.zip (1.3MB, public CMS policy
# data, not fetched from the live/drifting URL) -- copied from there
# instead of re-downloaded.
[[ -f data/raw/cms_coverage/ncd.zip ]] || cp docs/cms_inspection/ncd.zip data/raw/cms_coverage/ncd.zip
[[ -f data/raw/cms_synpuf/beneficiary_2008_sample1.zip ]] || curl -sL -o data/raw/cms_synpuf/beneficiary_2008_sample1.zip \
  "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_beneficiary_summary_file_sample_1.zip"
[[ -f data/raw/cms_synpuf/inpatient_sample1.zip ]] || curl -sL -o data/raw/cms_synpuf/inpatient_sample1.zip \
  "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_1.zip"
[[ -f data/raw/cms_synpuf/outpatient_sample1.zip ]] || curl -sL -o data/raw/cms_synpuf/outpatient_sample1.zip \
  "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_outpatient_claims_sample_1.zip"
[[ -f data/raw/synthea/fhir_r4_nov2021.zip ]] || curl -sSfL -o data/raw/synthea/fhir_r4_nov2021.zip \
  "https://github.com/synthetichealth/synthea-sample-data/raw/main/downloads/synthea_sample_data_fhir_r4_nov2021.zip"

echo "[bootstrap] ingesting CMS policy corpus (python -m ingestion.cli ingest)..."
DATABASE_URL="$DATABASE_URL" QDRANT_URL="$QDRANT_URL" REDIS_URL="$REDIS_URL" \
  python -m ingestion.cli ingest --qdrant-url "$QDRANT_URL" --reindex

echo "[bootstrap] ingesting FHIR dev subset (python -m ingestion.cli ingest-fhir)..."
DATABASE_URL="$DATABASE_URL" QDRANT_URL="$QDRANT_URL" REDIS_URL="$REDIS_URL" \
  python -m ingestion.cli ingest-fhir

echo "[bootstrap] ingesting SynPUF dev subset (python -m ingestion.cli ingest-synpuf)..."
DATABASE_URL="$DATABASE_URL" QDRANT_URL="$QDRANT_URL" REDIS_URL="$REDIS_URL" \
  python -m ingestion.cli ingest-synpuf

echo "[bootstrap] starting isolated backend container..."
"${COMPOSE[@]}" up -d backend

echo "[bootstrap] waiting for backend /ready over HTTP ($BACKEND_URL/ready)..."
deadline=$((SECONDS + 90))
while true; do
  if curl -sf "$BACKEND_URL/ready" >/tmp/e2e_clean_ready.json 2>/dev/null; then
    if grep -q '"status":"ready"' /tmp/e2e_clean_ready.json || grep -q '"status": "ready"' /tmp/e2e_clean_ready.json; then
      break
    fi
  fi
  if (( SECONDS > deadline )); then
    echo "[bootstrap] FAILED: backend did not report ready in time" >&2
    "${COMPOSE[@]}" logs backend --tail 100 >&2
    exit 1
  fi
  sleep 2
done
echo "[bootstrap] backend ready: $(cat /tmp/e2e_clean_ready.json)"

# One throwaway policy query to pre-warm the embedding model inside the
# backend process itself. Without this, the FIRST real /query call against
# a freshly started backend can lazily load the sentence-transformer model
# and exceed a normal E2E assertion timeout (observed directly: E2E-2
# timed out at 15s against a just-started isolated backend, then passed
# in under 1s once warm). Ingestion's own model load (python -m
# ingestion.cli ingest, above) happens in a separate short-lived process
# and does not warm this long-running one.
echo "[bootstrap] pre-warming the embedding model with one throwaway policy query..."
curl -sf -X POST "$BACKEND_URL/query" \
  -H 'Content-Type: application/json' \
  -d '{"question":"warm-up query, response is discarded"}' >/dev/null || true

ELAPSED=$(( $(date +%s) - START_TS ))
echo "[bootstrap] DONE in ${ELAPSED}s. Isolated stack is up:"
echo "  DATABASE_URL=$DATABASE_URL"
echo "  QDRANT_URL=$QDRANT_URL"
echo "  REDIS_URL=$REDIS_URL"
echo "  BACKEND_URL=$BACKEND_URL"
echo "  E2E_BASE_URL should point the frontend/backend the E2E suite talks to at $BACKEND_URL"
echo "[bootstrap] developer stack (project 'careflow-ai') was never touched."
echo "[bootstrap] tear down with: scripts/bootstrap_clean_e2e_env.sh down"
