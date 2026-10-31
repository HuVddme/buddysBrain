CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id uuid PRIMARY KEY,
    content_hash text NOT NULL UNIQUE,
    resource_id text NOT NULL UNIQUE,
    title text NOT NULL,
    description text NOT NULL,
    course text NOT NULL,
    suffix text NOT NULL CHECK (suffix IN ('.pdf', '.docx', '.txt')),
    source_bytes bytea,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'retrying', 'succeeded', 'failed', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    retryable boolean NOT NULL DEFAULT true,
    error_code text,
    error_message text,
    checkpoint jsonb,
    lease_token uuid,
    lease_until timestamptz,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_bytes IS NULL OR octet_length(source_bytes) <= 10485760)
);
CREATE INDEX IF NOT EXISTS ingestion_pending ON ingestion_jobs (available_at, created_at)
    WHERE status IN ('queued', 'retrying', 'processing');
