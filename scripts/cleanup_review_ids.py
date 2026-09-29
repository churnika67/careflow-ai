"""Phase 16 Slice 3: standalone review-row cleanup for browser-driven E2E
tests (E2E-7).

Mirrors -- does not reimplement -- tests/test_review_api.py's
`created_review_ids` fixture exactly: delete review_events for each given
review_id, then review_cases in reverse creation order, then commit. A
Playwright test cannot import that pytest fixture directly (different
language/runtime), so this script is the same cleanup logic factored out
to run standalone, invoked once per test from Node via a subprocess.

Usage: python scripts/cleanup_review_ids.py <review_id> [<review_id> ...]
Exits 0 always if the deletes succeed (including for zero ids), non-zero
on any database error -- the caller should treat a non-zero exit as a
cleanup failure worth surfacing, not silently swallowing.
"""

import sys

from app.core.config import get_settings
from app.db.connection import connect


async def cleanup_review_ids(review_ids: list[str]) -> None:
    if not review_ids:
        return
    conn = await connect(get_settings())
    try:
        async with conn.cursor() as cursor:
            for review_id in review_ids:
                await cursor.execute("DELETE FROM review_events WHERE review_id = %s", (review_id,))
            for review_id in reversed(review_ids):
                await cursor.execute("DELETE FROM review_cases WHERE review_id = %s", (review_id,))
        await conn.commit()
    finally:
        await conn.close()


def main() -> int:
    import asyncio

    review_ids = sys.argv[1:]
    asyncio.run(cleanup_review_ids(review_ids))
    print(f"Cleaned up {len(review_ids)} review id(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
