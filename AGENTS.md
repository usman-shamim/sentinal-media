# Personal Brand Sentinel — Agent Context

## Quick Start for a Fresh Agent

```powershell
# 1. Navigate to project
cd C:\Users\usman\Desktop\n8n-social-brand

# 2. Initialize os-eco tools
ml init
sd init
cn init

# 3. Verify specifyplus is available
specifyplus check
```

## Project Overview

A **Personal Brand Sentinel** following the Panaversity Agent Architecture Standard (Odysseus Orchestration Pattern). It manages social media posting via self-hosted Postiz (27+ platforms), with Telegram approval and multi-platform content adaptation.

**Live on**: Oracle VM (2 OCPU, 12GB RAM). Docker Compose fleet deployed via Portainer.

## Architecture

```
Odysseus (upstream agent)
  │ POST /dispatch
  ▼
Personal Brand Sentinel (FastAPI :8103)
  │ POST to n8n webhook → Telegram inline buttons
  │ ← callback from n8n → POST /callback
  │ → Postiz API :5000 → social platforms
  │ GET /health, GET /capabilities, GET /cleanup
  ▼
PostgreSQL 16 (shared: sentinel, n8n, postiz databases)
Janitor (1min loop — resets stale jobs)
```

## Stack

| Service | Port | Image |
|---|---|---|
| PostgreSQL | 5432 | postgres:16-alpine |
| Sentinel | 8103 | Custom (FastAPI) |
| n8n | 5678 | n8nio/n8n:latest |
| Postiz | 5000 | ghcr.io/gofireflyio/postiz:latest |
| Janitor | — | Custom (Python loop) |

## Key Spec Artifacts (all in `.specify/specs/001-personal-brand-sentinel/`)

| File | Content |
|---|---|
| `spec.md` | 6 user stories, 19 FRs, 7 success criteria, edge cases |
| `plan.md` | Architecture, API contracts, implementation phases |
| `tasks.md` | 47 tasks across 10 phases with build order |
| `data-model.md` | 3 PostgreSQL tables, JSON structures |
| `clarify.md` | 10 architectural clarifications resolved |
| `research.md` | Postiz API, Telegram Bot API, Docker resource budget |
| `quickstart.md` | 5-step deploy via Portainer or CLI |
| `contracts/api-spec.json` | OpenAPI 3.1 spec for 5 endpoints |
| `analysis.md` | Cross-artifact gap analysis (all gaps closed) |

## Constitution (`.specify/memory/constitution.md`)

8 principles governing all decisions:
1. Panaversity Architecture — Sentinel/Worker separation
2. Layered Timeouts — Worker 15s, Sentinel 20s
3. Deadline-First — all endpoints check expiry before work
4. Production Hardening — content-type validation, safe `.get()`, deep health
5. Human-in-the-Loop — every draft requires Telegram approval
6. Async-First Callbacks — `reply_to` triggers BackgroundTasks
7. Multi-Platform — X, LinkedIn, Threads, Bluesky at launch
8. Infrastructure Constraints — fits in 12GB, single VM

## Current Implementation Status

### Built (Phase 0 + Phase 1 in progress)
- `docker-compose.yml` — all 5 services
- `.env.example` — all configurable env vars
- `data/init-databases.sh` — creates n8n + postiz DBs
- `data/schema.sql` — job_queue, approval_requests, post_records
- `sentinels/personal-brand/Dockerfile` + `requirements.txt`
- `janitor/Dockerfile` + `requirements.txt`
- `sentinels/personal-brand/main.py` — FastAPI app (being written)

### Remaining
- Complete Phase 1: Sentinel Core (all 5 endpoints + platform adaptors)
- Phase 2: n8n Telegram approval workflow JSON
- Phase 3-6: US1-US4 wiring
- Phase 9: Janitor main loop
- Phase 10: Polish

## Critical Decisions (don't re-debate)

- **No Job Queue for MVP** — Postiz 429 errors return `rate_limited`, upstream retries
- **Platform config in-memory** — Python dict, not DB table (static per deploy)
- **No inter-agent auth for MVP** — single VM, Docker network trust
- **Telegram approval (Option 1)** — custom dashboard is P3
- **No auto-reject** — approvals never auto-reject, only auto-expire on deadline
- **n8n is Telegram bridge + cron only** — NOT the main orchestrator
- **Single user** — no multi-tenant abstractions
- **Fixed schedule time** — `SCHEDULED_POST_TIME` env var

## Port Conventions

- 8100-8199: Sentinels (8103 = Personal Brand)
- 8200-8299: Workers
- 8000: Odysseus

## Useful Commands

```powershell
# Build and run
docker compose up -d --build

# Check sentinel health
curl http://localhost:8103/health

# View logs
docker compose logs -f sentinel

# Submit test draft
curl -X POST http://localhost:8103/dispatch `
  -H "Content-Type: application/json" `
  -d '{"content":"Test post","platforms":["x"],"type":"now","source":"manual"}'

# Run analysis
specifyplus check
```

## Suggested Skills for Next Agent

- `panaversity-agent-architecture` — understand Odysseus/Sentinel/Worker pattern
- `handoff` — read this document
- `customize-opencode` — configure opencode for this project
- `improve-codebase-architecture` — refactor completed code
