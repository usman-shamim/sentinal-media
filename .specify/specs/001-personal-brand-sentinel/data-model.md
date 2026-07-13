# Data Model: Personal Brand Sentinel

## PostgreSQL Tables

### job_queue — Task queue for long-running operations

```sql
CREATE TABLE job_queue (
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

CREATE INDEX idx_job_queue_pending
    ON job_queue(status, created_at)
    WHERE status = 'pending';
```

### approval_requests — Telegram approval state tracking

```sql
CREATE TABLE approval_requests (
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

CREATE INDEX idx_approval_pending
    ON approval_requests(status, created_at)
    WHERE status = 'pending';
```

### post_records — History of posted content

```sql
CREATE TABLE post_records (
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
```

## JSON Structures

### DispatchRequest (inbound from Odysseus)
```json
{
  "content": "string",
  "platforms": ["x", "linkedin"],
  "type": "now | schedule | draft",
  "scheduled_at": "ISO 8601 | null",
  "deadline": "ISO 8601 | null",
  "reply_to": "URL | null",
  "source": "manual | ai | cron"
}
```

### PlatformConfig (internal registry)
```json
{
  "x": {
    "integration_id": "postiz_integration_id",
    "settings": { "__type": "x", "who_can_reply_post": "everyone" },
    "character_limit": 280
  },
  "linkedin": {
    "integration_id": "postiz_integration_id",
    "settings": { "__type": "linkedin" },
    "character_limit": 3000
  },
  "threads": {
    "integration_id": "postiz_integration_id",
    "settings": { "__type": "threads" },
    "character_limit": 500
  },
  "bluesky": {
    "integration_id": "postiz_integration_id",
    "settings": { "__type": "bluesky" },
    "character_limit": 300
  }
}
```

### ApprovalResult (from n8n callback)
```json
{
  "draft_id": "string",
  "status": "approved | rejected",
  "reason": "string | null"
}
```

### Design Decision: Platform Config Storage

Platform config (integration IDs, character limits, settings schemas) is stored **in-memory** as a Python dict in `Sentinel.PLATFORMS`, not in a database table. Rationale:

- Integration IDs are static per deployment — configured once, changed rarely
- Postiz already persists platform integrations — duplicating in PostgreSQL adds sync complexity
- MVP has 4 platforms; an in-memory dict is simpler and faster than a DB query per dispatch
- Future: migrate to a `platforms` DB table if dynamic platform registration is needed

### Entity Relationships

```
DispatchRequest ──→ approval_requests (1:1)
                       │
                       ├── approved ──→ post_records (1:1)
                       │                  └── POST /public/v1/posts
                       │
                       ├── rejected ──→ log + callback reply_to
                       │
                       └── expired ──→ log, no action

job_queue ──→ dispatched to Janitor for processing
                │
                ├── completed ──→ post_records
                ├── failed ──→ dead letter (retry_count >= max_retries)
                └── stale ──→ Janitor resets to pending
```
