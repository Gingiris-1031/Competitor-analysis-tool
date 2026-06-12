-- Audit Q&A feature: lets users ask follow-up questions about their
-- shared growth-audit report and get DeepSeek-backed answers grounded in
-- the report itself.
--
-- Shape: 1 row per Q&A exchange. We don't aggregate into a "session" yet
-- — every Q is independent enough that paginating by audit_job_id and
-- created_at gives you the conversation.

CREATE TABLE IF NOT EXISTS audit_qa (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_job_id     TEXT NOT NULL,                -- reports.id / jobs_dict key
    user_id          UUID,                          -- profiles.id, NULL for anon share viewers
    visitor_id       TEXT,                          -- anon fingerprint for rate limiting
    question         TEXT NOT NULL,
    answer           TEXT NOT NULL,
    cited_section    TEXT,                          -- exec / diag / plan / mixed
    model            TEXT NOT NULL DEFAULT 'deepseek-chat',
    latency_ms       INTEGER,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    refused          BOOLEAN NOT NULL DEFAULT FALSE,
    refused_reason   TEXT,                          -- 'out_of_scope' / 'rate_limit' / etc
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_qa_job_created
    ON audit_qa (audit_job_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_qa_user_created
    ON audit_qa (user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

-- Hourly rate-limit helper view: count questions per visitor in the last hour
CREATE INDEX IF NOT EXISTS idx_audit_qa_visitor_created
    ON audit_qa (visitor_id, created_at DESC)
    WHERE visitor_id IS NOT NULL;

-- Anonymous reads of the share page should not be able to enumerate Q&A
-- for other audits — we only return the rows the caller's job_id matches
-- via the API, never via PostgREST direct queries.
ALTER TABLE audit_qa DISABLE ROW LEVEL SECURITY;
