# Clarification Record: Personal Brand Sentinel

> Cross-Reference Against Panaversity Agent Architecture Standard.
> All clarifications resolved 2026-07-13.

## Golden Rules Audit

| # | Rule | Spec Coverage | Status |
|---|---|---|---|
| 1 | Sentinels coordinate, Workers execute | US-1, US-3 | ✅ |
| 2 | One worker, one job | Postiz = single worker | ✅ |
| 3 | Stateless workers | Postiz handles state | ✅ |
| 4 | Workers have no decision authority | Postiz receives commands | ✅ |
| 5 | Split confidence | FR-015 | ✅ |
| 6 | Deep health checks | US-4 | ✅ |
| 7 | Layered timeouts | FR-014 | ✅ |
| 8 | Check deadlines | FR-005 | ✅ |
| 9 | Handle Worker failures gracefully | FR-012 | ✅ |
| 10 | Safe worker lookup | FR-013 | ✅ |
| 11 | Heartbeat on long jobs | Job Queue deferred to v1.1 | ⏳ Deferred |
| 12 | reply_to callbacks | FR-006 | ✅ |
| 13 | Authenticate inter-agent calls | Skipped for MVP (single VM, Docker network) | ⏳ Deferred |

## Production Hardening Fixes Audit

| Fix | Spec Coverage | Status |
|---|---|---|
| 1. Cascading Timeout | FR-014 | ✅ |
| 2. Content-type validation | FR-012 | ✅ |
| 3. Ghost Deadline | FR-005 | ✅ |
| 4. Zombie tasks | Job Queue deferred | ⏳ Deferred |
| 5. Ignored Callback | FR-006 | ✅ |
| 6. Confidence Score | FR-015 | ✅ |
| 7. Deep Health | US-4 | ✅ |

---

## Resolved Clarifications

### 1. Inter-Agent Authentication (Golden Rule #13)
**Decision:** Skip for MVP. All services run on the same VM inside a Docker Compose network. No external exposure. Inter-agent auth (Bearer tokens) added in v1.1 when/if services are exposed beyond localhost.

**Rationale:** Single-tenant setup on private VM. Adding auth now adds complexity with zero threat model benefit at this scale.

---

### 2. Job Queue — Method B?
**Decision:** Skip for MVP. Postiz rate limit is 30 req/hour — manual personal use won't hit it. If rate-limited, return error and let the upstream agent retry. Job Queue + heartbeat + zombie prevention added in v1.1 if needed.

**Spec impact:** Remove Job Queue from edge cases. Add FR to handle Postiz 429 rate-limit errors with retry-after.

---

### 3. Telegram Approval Timeout
**Decision:** Auto-expire after deadline passes. If no `deadline` set, keep pending indefinitely. A `/cleanup` endpoint (or manual command) lets the user purge stale approvals.

**Rationale:** Personal brand — the user owns the queue. No need to force-expire their pending posts. Deadline-based expiry covers the case where a post is time-sensitive.

---

### 4. Confidence Threshold for Auto-Approval
**Decision:** All drafts go to Telegram for approval regardless of confidence score. No auto-reject. The confidence score is displayed in the Telegram notification for the user's reference.

**Rationale:** The user wants full control over their brand voice. Confidence scoring informs, it doesn't decide.

---

### 5. Postiz: Self-Hosted or Cloud?
**Decision:** Self-hosted Postiz on the VM (Docker Compose, port 5000). Same stack as everything else.

**Rationale:** Already have Docker running on the VM. Self-hosting gives full control, zero vendor lock-in, no external API dependency, and Postiz is open-source (26k+ GitHub stars). The `POSTIZ_HOST` env var can be swapped to cloud later if desired.

---

### 6. n8n's Exact Role
**Decision:** **Option C** — FastAPI Sentinel is the primary brain (port 8103). n8n handles:
- Cron trigger (daily content generation)
- Telegram bot I/O (sending notifications, receiving button callbacks)
- Bridging Telegram callbacks back to Sentinel via webhook

**Rationale:** Keeps core business logic (platform routing, content adaptation, dispatch, health) in the FastAPI Sentinel following the Panaversity template pattern. n8n excels at scheduling, webhooks, and chat integrations — use it for what it's good at, not as the main orchestrator.

---

### 7. Content Generation — LLM / Agent
**Decision:** The upstream Odysseus agent (main agent on the VM) handles content generation. The Sentinel accepts whatever draft comes in via webhook. The Sentinel does not call any LLM directly.

**Rationale:** Clean separation of concerns. The Sentinel routes and validates. Content generation belongs to Odysseus. The Sentinel contracts with Odysseus via `POST /dispatch` — whatever agent sits behind Odysseus is its own concern.

---

### 8. Post Schedule Optimal Time
**Decision:** Fixed configurable time set via env var (`SCHEDULED_POST_TIME=10:00`). Postiz doesn't need to suggest times for MVP.

**Rationale:** Simplest possible. The user knows their audience. Postiz analytics integration for optimal timing is a v2 enhancement.

---

### 9. Single-User or Multi-User?
**Decision:** **Single-user** (one Telegram chat, one set of Postiz integrations, one brand voice).

**Rationale:** This is a personal brand tool. Multi-tenant design would double complexity for zero current value. Architecture should avoid multi-user abstractions (no user table, no auth system, no org scoping).

---

### 10. Draft Editing During Approval
**Decision:** **Approve/Reject only.** Edit capability deferred to the custom dashboard (Story 6, P3).

**Rationale:** Telegram inline edits require complex session management. The user edits the draft upstream and resubmits if changes are needed. The dashboard will provide the proper editing experience later.

---

## Summary of Spec Updates Required

| Change | Type |
|---|---|
| Add FR: Handle Postiz 429 rate-limit with retry-after | New requirement |
| Add FR: Auto-expire approvals when deadline passes | New requirement |
| Remove Job Queue references from edge cases | Spec cleanup |
| Clarify n8n scope: cron + Telegram bridge only | Constraint |
| Add env vars: `SCHEDULED_POST_TIME`, `POSTIZ_HOST`, `TELEGRAM_BOT_TOKEN`, `N8N_WEBHOOK_URL` | Config |
