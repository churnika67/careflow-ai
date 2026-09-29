"""Phase 16 Slice 2: E2E/integration startup gate.

Polls the SAME readiness rule GET /ready itself uses (check_readiness --
Postgres and Qdrant authoritative, Redis reported but never gating), not
check_dependencies() (the stricter rule scripts/verify_services.py and
GET /health use, which incorrectly requires Redis too). Reusing
verify_services.py as-is here would risk blocking a genuinely ready E2E
environment on an optional dependency -- see
docs/phase16_testing_ci_design.md's "Readiness strategy" section for the
exact reasoning this script follows.

Deliberately a small, bounded poll loop, not a general-purpose retry
framework: exits 0 the moment Postgres+Qdrant are both healthy, exits 1
if the timeout elapses first."""

import asyncio
import sys
import time

from app.core.config import get_settings
from app.services.health import check_readiness

DEFAULT_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 1


async def main() -> int:
    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
    settings = get_settings()
    last_result = None
    while time.monotonic() < deadline:
        last_result = await check_readiness(settings)
        if last_result.status == "ready":
            print(last_result.model_dump_json(indent=2))
            return 0
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    if last_result is not None:
        print(last_result.model_dump_json(indent=2))
    print(f"Timed out after {DEFAULT_TIMEOUT_SECONDS}s waiting for /ready", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
