# Research: Personal Brand Sentinel

## Panaversity Agent Architecture Standard (v2.1)

The authoritative reference for the Sentinel/Worker pattern is the Panaversity Agent Architecture Standard document. Key confirmed compatibilities:

### Sentinel Template (FastAPI)
The standard provides a production-hardened FastAPI template tested against 6 known edge cases:
- **The HTTP Trap**: Layered timeouts prevent orphaned executions
- **Happy Path Bias**: Content-type validation + safe `.get()` lookups
- **Ghost Deadline**: `is_expired()` before any expensive work
- **Zombie Tasks**: heartbeat_at + Janitor CronJob for stuck processing jobs
- **Ignored Callback**: reply_to + BackgroundTasks + 202 Accepted immediately
- **Confidence Hallucination**: Split confidence (retrieval, generation, combined)

All 6 fixes are incorporated into the Sentinel design.

### Communication Methods
- **Method A (HTTP/REST)**: Primary for MVP — sync dispatch for simple cases, async via reply_to for normal flow
- **Method B (Job Queue)**: Deferred to v1.1
- **Method C (Async Callbacks)**: Used for Telegram approval flow — n8n sends result to `/callback`
- **Method D (Shared DB)**: Not used — coupling without benefit for this scale

### Port Convention
| Service | Port | Standard |
|---|---|---|
| Personal Brand Sentinel | 8103 | Sentinel range: 8100-8199 |
| n8n | 5678 | n8n default |
| Postiz | 5000 | Postiz default |
| PostgreSQL | 5432 | PostgreSQL default |

## Postiz Public API (v1.0)

### Authentication
Bearer token via `Authorization: your-api-key` header.
Rate limit: 30 requests per hour.

### Key Endpoints
- `GET /public/v1/integrations` — list connected social channels
- `POST /public/v1/posts` — create/schedule/immediate post
- `GET /public/v1/posts` — list posts
- `DELETE /public/v1/posts/:id` — cancel scheduled post
- `POST /public/v1/upload` — upload media
- `POST /public/v1/upload-from-url` — upload media from URL
- `GET /public/v1/analytics/:integration` — per-channel analytics

### Post Types
- `"now"` — publish immediately
- `"schedule"` — publish at ISO 8601 `date`
- `"draft"` — save as draft in Postiz UI

### Platform Settings Schemas
Each platform requires a `settings` object with `__type` field:

| Platform | `__type` | Required |
|---|---|---|
| X (Twitter) | `x` | `who_can_reply_post` |
| LinkedIn | `linkedin` | — |
| LinkedIn Page | `linkedin-page` | — |
| Threads | `threads` | — |
| Bluesky | `bluesky` | — |

All four launch platforms are simple text + optional media. No special settings required beyond `__type` for Threads and Bluesky. X requires `who_can_reply_post: "everyone"`.

### n8n Community Node
Postiz has an official n8n community node (`n8n-nodes-postiz`). However, for MVP we use direct HTTP requests to Postiz API from both Sentinel and n8n — simpler than installing community nodes.

## Telegram Bot API

### Inline Keyboards
Telegram inline keyboards support callback buttons. Sent as JSON in `reply_markup`:
```json
{
  "inline_keyboard": [[
    { "text": "✅ Approve", "callback_data": "approve:draft_abc123" },
    { "text": "❌ Reject", "callback_data": "reject:draft_abc123" }
  ]]
}
```

### n8n Telegram Node
n8n has native Telegram trigger node that receives `callback_query` updates. The workflow pattern:
1. Sentinel POSTs approval request to n8n webhook
2. n8n Telegram node sends message with inline keyboard
3. n8n Telegram trigger receives button callback
4. n8n POSTs result to Sentinel `/callback`

## Docker Compose on Oracle VM

### Resource Budget (12GB total)
| Service | Estimated RAM | Notes |
|---|---|---|
| PostgreSQL | 512MB | < 100MB idle, spikes on write |
| n8n | 1GB | Node.js process |
| Postiz | 2GB | Next.js + Node |
| Sentinel | 256MB | FastAPI, Python |
| Janitor | 64MB | Python, sleeps most of the time |
| OS + overhead | 2GB | Ubuntu Server |
| **Total** | **~6GB** | 6GB headroom for growth |

### Oracle VM Firewall
Required open ports: 22 (SSH), 5678 (n8n UI), 5000 (Postiz UI), 8103 (Sentinel health), 5432 (PostgreSQL — restrict to internal Docker network).

## Telegram-Drive (Future v1.1)
Local REST API at `http://localhost:8550/api/v1`. Auth via `X-API-Key` header. Endpoints:
- `POST /files` — upload file
- `GET /files/{id}/download` — download file
- `GET /files/{id}/media-info` — video duration, resolution
