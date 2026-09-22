# Phase 1 verification

Verified on 2026-09-08 (America/New_York), macOS arm64, Python 3.12,
using Docker Desktop. This record covers Phase 1 only.

## Completed

- Created the requested directory structure, with `.gitkeep` files for future modules.
- Created a Python virtual environment and installed runtime and development dependencies.
- Added pinned dependency files, a packaged FastAPI backend, validated environment
  configuration, and `.env.example`.
- Added a non-root backend Docker image and a four-service Docker Compose stack.
- Added persistent PostgreSQL, Qdrant, and Redis volumes and loopback-only published ports.
- Implemented `GET /health` with concurrent real PostgreSQL, Qdrant, and Redis probes,
  bounded timeouts, HTTP 503 on dependency failure, and redacted failure responses.
- Added API/configuration tests and opt-in integration tests, a live verification
  script, README, ignore files, and MIT license.

## Commands executed

Environment inspection used `pwd`, `ls`, `rg`, `command -v`, `python3 --version`,
`docker version`, `git status --short`, and `git log -1 --oneline`.
The repository was empty with no commits. Main setup and verification commands:

```bash
python3.12 -m venv .venv
open -a Docker
.venv/bin/python -m pip install -e '.[dev]'
docker compose up -d postgres qdrant redis --wait --wait-timeout 120
.venv/bin/ruff check . --fix
.venv/bin/ruff format .
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pip check
docker compose up --build -d --wait --wait-timeout 180
.venv/bin/python scripts/verify_services.py
CAREFLOW_INTEGRATION=1 .venv/bin/pytest -q
docker compose ps
docker compose exec -T backend python -c "import urllib.request; r=urllib.request.urlopen('http://localhost:8000/health'); print(r.status); print(r.read().decode())"
```

The lock files were generated from the installed environment's package metadata,
excluding the editable project and pip and separating test tools from runtime packages.
The backend image successfully installed the runtime lock on Linux arm64.

## Measured results

| Check | Observed result |
| --- | --- |
| Default pytest run | 11 passed, 2 integration tests skipped, 1 warning |
| Integration-enabled pytest run | 13 passed, 1 warning |
| Ruff lint | All checks passed |
| Ruff formatting | 11 files already formatted |
| `pip check` | No broken requirements found |
| Docker backend build and Compose wait | Exit code 0 |
| Backend | Running, Docker health status healthy |
| PostgreSQL | Running, Docker health status healthy; real SQL probe passed |
| Redis | Running, Docker health status healthy; real PING probe passed |
| Qdrant | Running; real `/readyz` probe passed through backend and host verification |
| Live API | HTTP 200, body below |

Actual response:

```json
{"status":"ok","service":"careflow-ai","version":"0.1.0","dependencies":{"postgresql":{"status":"ok"},"qdrant":{"status":"ok"},"redis":{"status":"ok"}}}
```

Qdrant has no standalone Docker healthcheck; backend health explicitly includes its
readiness endpoint. No RAG quality, latency benchmark, or cost measurements exist yet.

## Issues encountered and resolved

- Docker Desktop was stopped. Launched it with permission.
- Sandboxing prevented PyPI DNS access and local Docker connections. Retried the
  relevant install, Docker, and integration commands with approved elevated access.
- Existing host service occupied port 5432. CareFlow now publishes PostgreSQL on
  **55432** (configurable through `POSTGRES_PORT`) and retains internal port 5432.
  The existing service was left running.
- Ruff fixed two import-order issues; subsequent lint and formatting checks passed.

## Known limitations and blockers

No remaining Phase 1 blocker. Pytest emits a third-party Starlette/AnyIO
`BlockingPortal` deprecation warning; tests pass and runtime readiness works.
Only Python 3.12 and Docker Linux arm64 were exercised. Other platforms are unverified.
The environment uses development credentials and has no authentication yet.
Services remain running for local inspection.

Phase 2 has not started. No CMS datasets were downloaded or parsed. No GitHub remote,
commit, cloud resource, or deployment was created. Await explicit approval:
**“Continue to Phase 2.”**

## Verify locally

From the repository root:

```bash
cp .env.example .env
docker compose up --build -d --wait --wait-timeout 180
curl --fail http://localhost:8000/health
docker compose ps
.venv/bin/python scripts/verify_services.py
CAREFLOW_INTEGRATION=1 .venv/bin/pytest -q
```

For a fresh checkout, first install the Python environment as described in the README.
Do not overwrite an existing customized `.env`; merge changes manually instead.
