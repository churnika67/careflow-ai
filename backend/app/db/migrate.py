import hashlib
import json
from pathlib import Path

from app.core.config import Settings, get_settings
from app.db.connection import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[str, str]]:
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise ValueError(f"No migration files found in {directory}")
    return [(f.name, f.read_text()) for f in files]


async def migrate(settings: Settings, directory: Path = MIGRATIONS_DIR) -> dict:
    """Apply not-yet-applied migrations in filename order. Idempotent: a second
    run applies nothing. Refuses to proceed if an already-applied migration's
    file content has changed, since editing history would silently desync
    databases that already ran the original version."""
    migrations = discover_migrations(directory)
    connection = await connect(settings)
    applied, skipped = [], []
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(BOOTSTRAP_SQL)
            await cursor.execute("SELECT filename, checksum FROM schema_migrations")
            recorded = dict(await cursor.fetchall())
            for filename, text in migrations:
                checksum = _digest(text)
                if filename in recorded:
                    if recorded[filename] != checksum:
                        raise ValueError(
                            f"{filename}: checksum differs from the applied migration; "
                            "do not edit a migration once it has been applied"
                        )
                    skipped.append(filename)
                    continue
                await cursor.execute(text)
                await cursor.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                    (filename, checksum),
                )
                applied.append(filename)
    return {"applied": applied, "skipped": skipped}


async def _main() -> None:
    result = await migrate(get_settings())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
