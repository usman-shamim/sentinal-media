-- ──────────────────────────────────────────
-- Personal Brand Sentinel — PostgreSQL Schema
-- ──────────────────────────────────────────

-- job_queue — async task queue for long-running operations
CREATE TABLE IF NOT EXISTS job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    input JSONB,
    output JSONB,
    deadline TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    assigned_to TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_queue_pending
    ON job_queue(status, created_at)
    WHERE status = 'pending';

-- approval_requests — Telegram approval state tracking
CREATE TABLE IF NOT EXISTS approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id TEXT NOT NULL,
    content TEXT NOT NULL,
    platforms TEXT[] NOT NULL,
    post_type TEXT NOT NULL DEFAULT 'now'
        CHECK (post_type IN ('now', 'schedule', 'draft')),
    scheduled_at TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    reply_to TEXT,
    source TEXT DEFAULT 'manual'
        CHECK (source IN ('manual', 'ai', 'cron')),
    telegram_chat_id TEXT NOT NULL,
    telegram_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    confidence JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    responded_at TIMESTAMPTZ,
    UNIQUE(draft_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_pending
    ON approval_requests(status, created_at)
    WHERE status = 'pending';

-- post_records — history of posted content
CREATE TABLE IF NOT EXISTS post_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id TEXT NOT NULL,
    content TEXT NOT NULL,
    platforms JSONB NOT NULL,
    postiz_response JSONB,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'posted', 'failed', 'partial')),
    posted_at TIMESTAMPTZ DEFAULT now(),
    FOREIGN KEY (draft_id) REFERENCES approval_requests(draft_id)
);
