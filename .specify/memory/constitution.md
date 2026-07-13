# Personal Brand Sentinel Constitution

## Core Principles

### I. Panaversity Agent Architecture
The Personal Brand Sentinel follows the Odysseus Orchestration Pattern: Odysseus delegates to Sentinels, Sentinels validate/route/supervise Workers, Workers execute one job and report back. Sentinels never execute work directly. Workers never make decisions.

### II. Layered Timeouts (NON-NEGOTIABLE)
Every agent enforces strict cascading timeouts to prevent orphaned executions: Worker (15s) < Sentinel (20s) < Odysseus (30s). For tasks exceeding these bounds, use the Job Queue (Method B) or Async Callbacks (Method C). The HTTP Trap — where Odysseus drops a connection while downstream agents keep running — must never occur.

### III. Deadline-First Execution
Both Sentinels and Workers check `is_expired(deadline)` before any expensive work. Expired tasks return `status: "expired"` immediately. No LLM tokens, DB queries, or API calls are wasted on tasks whose deadline has passed.

### IV. Production Hardening
All agents implement:
- Content-type validation before `resp.json()` — avoid ContentTypeError on HTML error pages
- Safe dictionary lookups with `.get(key, default)` — never `dict[key]`
- Try/except around all Worker calls — Sentinels never crash on Worker errors
- Deep health checks — `/health` pings every dependency, returns `"degraded"` if any are unreachable
- Split confidence scoring — `confidence_retrieval`, `confidence_generation`, `confidence_combined`

### V. Human-in-the-Loop Approval
Content does not post without human approval. The default pipeline is: AI/Human draft → Sentinel validates → Telegram approval request → User approves/rejects → Postiz posts. A web-based approval dashboard is a future enhancement.

### VI. Async-First Callbacks
`/dispatch` returns `202 Accepted` immediately for any task with a `reply_to` field. Processing happens via background tasks. Results are delivered via `POST {reply_to}/callback`. The dispatch endpoint never blocks waiting for Worker completion.

### VII. Multi-Platform Content Distribution
Content is adapted per platform before posting. Platform-specific settings (character limits, media requirements, thread splitting, visibility) are applied by the Sentinel before dispatch to Postiz. Launch platforms: X, LinkedIn, Threads, Bluesky. Instagram and video platforms (TikTok, YouTube) follow after pipeline stabilization.

### VIII. Infrastructure Constraints
Deployed on Oracle VM (2 OCPU, 12GB RAM). All services run via Docker Compose with `restart: unless-stopped`. Port convention: Odysseus 8000, Sentinels 8100-8199, Workers 8200-8299, n8n 5678, Postiz 5000, PostgreSQL 5432, Telegram-Drive 8550. No service exceeds 4GB RAM allocation.

## Content Pipeline & Quality Gates

### Draft Sources
- **Webhook-triggered**: One-off posts pushed from Odysseus or manually via curl/form
- **Cron-triggered**: Daily batch — Sentinel triggers main agent to generate fresh content
- **Human-written**: Direct drafts submitted for AI review + approval

### Approval Flow
1. Draft enters Sentinel (from any source)
2. Sentinel validates: platform compatibility, brand tone, confidence scoring
3. Sentinel sends Telegram notification with draft + AI review + Approve/Reject buttons
4. User taps Approve → Sentinel calls Postiz API to schedule/publish
5. User taps Reject → Sentinel logs rejection reason, optionally notifies upstream agent
6. Result callback sent to `reply_to` if provided

### Platform Routing
Sentinel maintains a platform registry mapping platform names to Postiz integration IDs. Unknown platforms return `status: "rejected"`. Each platform has an associated settings schema (`__type`, required fields) that the Sentinel enforces before dispatch.

### Video Pipeline (Future)
AI-edited videos stored in Telegram-Drive (`localhost:8550`). Sentinel downloads video, uploads to Postiz via `POST /public/v1/upload`, then creates scheduled post with `scheduledAt`. No large video files stored on VM disk.

## Deployment & Operations

### Service Stack
| Service | Port | Container | Dependencies |
|---|---|---|---|
| n8n | 5678 | n8nio/n8n | PostgreSQL |
| Postiz | 5000 | postiz/postiz | PostgreSQL, Redis |
| PostgreSQL | 5432 | postgres:16-alpine | — |
| Personal Brand Sentinel | 8103 | Custom FastAPI | n8n, Postiz |
| Telegram-Drive | 8550 | Custom Tauri | Telegram API |
| Janitor (Cron) | — | Custom Python | PostgreSQL |

### Health & Monitoring
Every agent exposes `/health` as a deep check. Sentinel's health pings all managed Workers (Postiz API, n8n webhook, Telegram-Drive). Status returns `"ok"` only if all dependencies respond. `"degraded"` otherwise with per-dependency error details.

### Job Queue Production Hardening
- Heartbeat: Workers update `heartbeat_at` every 30s while processing
- Zombie prevention: Janitor CronJob runs every 1min, resets stale `processing` jobs (>5min old) to `pending`
- Dead-Letter: After `max_retries` (default 3), job moves to `failed` status
- Deadline enforcement: Queue janitor also checks pending jobs past deadline

### Inter-Agent Security
All agent-to-agent HTTP calls carry `Authorization: Bearer <token>`. API keys and secrets stored as n8n credentials or environment variables — never in code. Postiz API key, Telegram bot token, and inter-agent tokens are configured at deploy time.

## Development Workflow

### Spec-Driven Development
All features follow spec-kit-plus workflow: `/sp.constitution` → `/sp.specify` → `/sp.clarify` → `/sp.plan` → `/sp.tasks` → `/sp.implement`. Specifications, architecture decisions, and prompt history are first-class artifacts.

### Testing
- Health endpoints tested after every deployment
- Approval flow tested with mock Telegram bot
- Platform routing tested with Postiz sandbox/staging
- Deadline and timeout tests for every new Sentinel/Worker
- Job queue tested with zombie simulation (kill worker mid-job)

### Iteration Order
1. Personal Brand Sentinel FastAPI server (port 8103) — /dispatch, /health, /capabilities
2. n8n workflow — Telegram approval, webhook trigger, cron trigger
3. Postiz integration — platform routing, content adaptation, schedule/create
4. Telegram bot — approve/reject inline buttons, notification formatting
5. Job queue + Janitor — for long-running content batches
6. Telegram-Drive integration — video storage pipeline (future)

## Governance
This constitution supersedes all ad-hoc practices. Amendments require documenting the rationale, updating this file, and adding a corresponding ADR in `.seeds/`. All implementations must be verifiable against these principles. The Panaversity Agent Architecture Standard document governs the Sentinel/Worker contract.

**Version**: 1.0.0 | **Ratified**: 2026-07-13 | **Last Amended**: 2026-07-13
