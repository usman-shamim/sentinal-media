# Implementation Plan: Personal Brand Sentinel

**Branch**: `001-personal-brand-sentinel` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-personal-brand-sentinel/spec.md`
**Clarifications**: [clarify.md](./clarify.md) — all 10 resolved.

## Summary

Build a Personal Brand Sentinel (Panaversity Sentinel/Worker pattern) that accepts social media drafts via webhook and cron, validates them, sends Telegram inline-button approval requests, and dispatches approved posts to Postiz for multi-platform publishing. The stack runs as a Docker Compose fleet on a single Oracle VM (2 OCPU, 12GB RAM). MVP deploys to X, LinkedIn, Threads, Bluesky. Video pipeline (Telegram-Drive + AI editing) added in v1.1.

## Technical Context

**Language/Version**: Python 3.12+ (FastAPI Sentinel), TypeScript (n8n workflows), Shell/Bun (os-eco tools)
**Primary Dependencies**: FastAPI, httpx, uvicorn, pydantic (Sentinel); n8n (approval workflow); Postiz (social publishing); postgres:16-alpine (data)
**Storage**: PostgreSQL 16 (shared across Sentinel job queue, n8n, Postiz)
**Testing**: pytest (Sentinel unit/integration), manual health-check validation (MVP)
**Target Platform**: Linux amd64 (Oracle VM, Docker Compose)
**Project Type**: Multi-service Docker Compose stack
**Performance Goals**: Draft-to-post under 60s (text, "now" type, excluding human approval time)
**Constraints**: 12GB RAM shared across all services; Postiz 30 req/hour rate limit; VM single-tenant
**Scale/Scope**: Single-user personal brand; 1-5 posts/day; 4 platforms at launch

## Constitution Check

| Gate | Status | Notes |
|---|---|---|
| I. Panaversity Architecture | ✅ Pass | Sentinel/Worker separation enforced |
| II. Layered Timeouts | ✅ Pass | 15s Worker / 20s Sentinel env-configurable |
| III. Deadline-First | ✅ Pass | All endpoints check expiry before work |
| IV. Production Hardening | ✅ Pass | Content-type validation, safe lookups, deep health |
| V. Human-in-the-Loop | ✅ Pass | Every draft requires Telegram approval |
| VI. Async-First Callbacks | ✅ Pass | reply_to triggers BackgroundTasks pattern |
| VII. Multi-Platform | ✅ Pass | Platform adaptation per spec |
| VIII. Infrastructure Constraints | ✅ Pass | All services fit in 12GB with room to spare |

## Project Structure

```text
n8n-social-brand/
├── docker-compose.yml           # Portainer stack — one-command deploy
├── .env.example                 # All configurable env vars
├── sentinels/
│   └── personal-brand/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── main.py              # FastAPI app (port 8103)
├── janitor/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                  # Stale job resetter (1min cron loop)
├── workers/
│   └── postiz/
│       └── README.md            # Postiz config reference
├── n8n-workflows/
│   └── telegram-approval.json   # Importable n8n workflow
├── .specify/
│   ├── memory/constitution.md
│   ├── specs/001-personal-brand-sentinel/
│   │   ├── spec.md
│   │   ├── clarify.md
│   │   ├── plan.md
│   │   ├── research.md
│   │   ├── data-model.md
│   │   ├── quickstart.md
│   │   └── contracts/
│   │       └── api-spec.json
│   └── templates/
├── .mulch/                      # os-eco expertise
├── .seeds/                      # os-eco issues
└── .canopy/                     # os-eco prompts
```

**Structure Decision**: Multi-service Docker Compose stack. Each service has its own directory with Dockerfile. No monolith — microservices by container boundary. Sentinel is the only custom FastAPI service; everything else is off-the-shelf.

## Architecture

```text
                    ┌─────────────────────────────────────┐
                    │       ODYSSEUS (Main Agent)          │
                    │  Generates drafts, sends to Sentinel │
                    └──────────────┬──────────────────────┘
                                   │ POST /dispatch
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│              PERSONAL BRAND SENTINEL (FastAPI :8103)            │
│                                                                  │
│   POST /dispatch   → validate → platform-adapt → POST to n8n    │
│   POST /callback   ← approval result from Telegram              │
│   GET  /health     → deep check (n8n, Postiz, Telegram-Drive)   │
│   GET  /capabilities → list supported platforms + workers       │
│   GET  /cleanup    → purge expired approvals                    │
└────────────────────┬───────────────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
┌──────────────────┐  ┌──────────────────┐
│  n8n (:5678)     │  │  Postiz (:5000)  │
│  Telegram Bot    │  │  POST /posts     │
│  Inline Buttons  │  │  27+ platforms  │
│  Cron Scheduler  │  └──────────────────┘
└──────────────────┘
```

## API Contracts

### POST /dispatch
**From**: Odysseus (main agent) or manual webhook
**To**: Sentinel

```json
{
  "content": "Check out my new blog post about AI agents...",
  "platforms": ["x", "linkedin", "threads"],
  "type": "now",
  "scheduled_at": null,
  "deadline": "2026-07-14T12:00:00Z",
  "reply_to": "http://odysseus:8000/tasks/abc/callback",
  "source": "ai"
}
```

**Response (sync, no reply_to)**: `{ "status": "completed"|"expired"|"rejected"|"error", "post_ids": {...}, "confidence": {...} }`
**Response (async, with reply_to)**: `202 Accepted` → callback later via `POST {reply_to}/callback`

### POST /callback
**From**: n8n (Telegram approval result)
**To**: Sentinel

```json
{
  "draft_id": "draft_abc123",
  "status": "approved" | "rejected",
  "reason": null
}
```

### GET /health
**Response**:
```json
{
  "status": "ok" | "degraded",
  "workers": { "n8n": "ok", "postiz": "ok", "telegram-drive": "unreachable: ..." }
}
```

### GET /capabilities
**Response**:
```json
{
  "sentinel_type": "personal-brand-sentinel",
  "capabilities": ["post-draft", "schedule-post", "generate-content"],
  "workers": { "n8n": "http://n8n:5678", "postiz": "http://postiz:5000" }
}
```

## Implementation Phases

### Phase 0: Foundation
- Docker Compose with all services (PostgreSQL, Sentinel, n8n, Postiz, Janitor)
- `.env.example` with all configurable variables
- `requirements.txt` and `Dockerfile` for custom services

### Phase 1: Sentinel Core
- FastAPI app with `/dispatch`, `/callback`, `/health`, `/capabilities`, `/cleanup`
- `is_expired()` deadline check
- Platform routing + content adaptation (X, LinkedIn, Threads, Bluesky)
- Safe worker lookup with `.get()`, never `dict[key]`
- Content-type validation before `resp.json()`
- BackgroundTasks + `asyncio.run()` bridge for async callbacks

### Phase 2: n8n Approval Bridge
- Webhook trigger (receives approval request from Sentinel)
- Telegram node (sends message with inline Approve/Reject buttons)
- Webhook response (sends result back to Sentinel `/callback`)
- Daily cron workflow (triggers upstream agent for content generation)

### Phase 3: Postiz Integration
- Connect social channels in Postiz UI (X, LinkedIn, Threads, Bluesky)
- Configure Postiz API key
- Platform-specific settings schemas per Postiz docs
- Upload media workflow

### Phase 4: Janitor & Production Hardening
- PostgreSQL job_queue table (pending → processing → completed/failed)
- Janitor cron loop (reset stale processing jobs every 1min)
- Heartbeat updates every 30s for long-running jobs
- Dead-letter after max_retries (default 3)

## Complexity Tracking

N/A — Constitution checks all pass. Single-project structure, no over-engineering.
