import os
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db import migrate as migrate_module
from app.db.migrate import discover_migrations, migrate

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running to test real Postgres",
)


def test_discover_migrations_orders_by_filename(tmp_path):
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE second (id INT);")
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE first (id INT);")
    migrations = discover_migrations(tmp_path)
    assert [name for name, _ in migrations] == ["0001_first.sql", "0002_second.sql"]


def test_discover_migrations_rejects_empty_directory(tmp_path):
    with pytest.raises(ValueError, match="No migration files"):
        discover_migrations(tmp_path)


def test_real_migrations_directory_is_discoverable():
    migrations = discover_migrations()
    names = [name for name, _ in migrations]
    assert names == sorted(names)
    assert "0001_provenance.sql" in names
    for _, text in migrations:
        assert text.strip()


@pytestmark_live
async def test_migrate_is_idempotent_against_live_postgres():
    settings = get_settings()
    first = await migrate(settings)
    assert "0001_provenance.sql" in first["applied"] + first["skipped"]

    second = await migrate(settings)
    assert second["applied"] == []
    assert "0001_provenance.sql" in second["skipped"]


@pytestmark_live
async def test_migrate_creates_expected_tables():
    settings = get_settings()
    await migrate(settings)
    connection = await migrate_module.connect(settings)
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN "
                "('schema_migrations', 'ingestion_runs', 'source_files')"
            )
            found = {row[0] for row in await cursor.fetchall()}
    assert found == {"schema_migrations", "ingestion_runs", "source_files"}


@pytestmark_live
async def test_migrate_rejects_changed_applied_migration(tmp_path):
    settings = get_settings()
    (tmp_path / "0001_provenance.sql").write_text(
        (Path(migrate_module.MIGRATIONS_DIR) / "0001_provenance.sql").read_text()
    )
    await migrate(settings, tmp_path)
    (tmp_path / "0001_provenance.sql").write_text("-- tampered\nCREATE TABLE tampered (id INT);")
    with pytest.raises(ValueError, match="checksum differs"):
        await migrate(settings, tmp_path)
