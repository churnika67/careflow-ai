-- Shared provenance tables for structured-data ingestion (Phase 8).
-- Every domain table added by later migrations references ingestion_runs
-- so every row remains traceable to the run and source file that produced it.

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    records_read INTEGER CHECK (records_read >= 0),
    records_accepted INTEGER CHECK (records_accepted >= 0),
    records_rejected INTEGER CHECK (records_rejected >= 0),
    source_fingerprint TEXT,
    notes TEXT,
    CHECK (
        status <> 'completed'
        OR (records_read IS NOT NULL AND records_accepted IS NOT NULL AND records_rejected IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS source_files (
    source_file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id),
    source TEXT NOT NULL,
    origin_url TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    downloaded_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS source_files_run_id_idx ON source_files (run_id);
