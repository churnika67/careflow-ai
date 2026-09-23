-- Phase 11: human-in-the-loop review/audit workflow.
--
-- A separate application/workflow domain, deliberately not touching
-- synpuf_*, fhir_*, ingestion_runs, or source_files (those remain Phase 8's
-- healthcare source-data and provenance tables). review_cases holds current
-- state; review_events is an append-only application-level audit history
-- (the database does not itself forbid a privileged administrator from
-- editing rows — no UPDATE/DELETE repository method is ever implemented for
-- it, and "append-only" here means an application-level guarantee, not a
-- database-enforced or cryptographic one).

CREATE TABLE IF NOT EXISTS review_cases (
    review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id TEXT NOT NULL UNIQUE,          -- correlates to MultiAgentResponse.request_id
    workflow TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'revision_requested')),
    trigger_reason_codes TEXT[] NOT NULL,
    evidence_snapshot JSONB NOT NULL,
    evidence_fingerprint TEXT NOT NULL CHECK (evidence_fingerprint ~ '^[a-f0-9]{64}$'),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    previous_review_id UUID REFERENCES review_cases (review_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (previous_review_id IS NULL OR previous_review_id <> review_id)
);

CREATE INDEX IF NOT EXISTS review_cases_status_created_at_idx
    ON review_cases (status, created_at, review_id);

CREATE TABLE IF NOT EXISTS review_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id UUID NOT NULL REFERENCES review_cases (review_id),
    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'review_created', 'review_approved', 'review_rejected', 'revision_requested'
        )),
    actor_id TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('system', 'reviewer')),
    previous_status TEXT
        CHECK (previous_status IS NULL
            OR previous_status IN ('pending', 'approved', 'rejected', 'revision_requested')),
    new_status TEXT NOT NULL
        CHECK (new_status IN ('pending', 'approved', 'rejected', 'revision_requested')),
    reason TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS review_events_review_id_created_at_idx
    ON review_events (review_id, created_at, event_id);
