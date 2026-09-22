"""Run real protocol probes; requires the infrastructure to be running."""

import asyncio
import sys

from app.core.config import get_settings
from app.services.health import check_dependencies


async def main() -> int:
    result = await check_dependencies(get_settings())
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
