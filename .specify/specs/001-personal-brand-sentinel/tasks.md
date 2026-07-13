# Tasks: Personal Brand Sentinel

**Input**: Design documents from `/specs/001-personal-brand-sentinel/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api-spec.json
**Constitution**: `.specify/memory/constitution.md`
**Clarifications**: `clarify.md` (all 10 resolved)

**Format**: `[ID] [P?] [Story] Description — file path`
- **[P]**: Parallel-safe (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Foundation (Shared Infrastructure)

**Purpose**: Docker Compose stack, env config, shared database schema. Everything runs from here.

- [ ] T001 Create project directory structure — `docker-compose.yml`, `sentinels/personal-brand/`, `janitor/`, `n8n-workflows/`
- [ ] T002 [P] Write Docker Compose stack with all services — `docker-compose.yml`
- [ ] T003 [P] Create `.env.example` with all configurable variables — `.env.example`
- [ ] T004 [P] Create PostgreSQL schema migration script — `data/schema.sql`
- [ ] T005 [P] Create Sentinel Dockerfile — `sentinels/personal-brand/Dockerfile`
- [ ] T006 [P] Create Sentinel Python dependencies — `sentinels/personal-brand/requirements.txt`
- [ ] T007 [P] Create Janitor Dockerfile — `janitor/Dockerfile`
- [ ] T008 [P] Create Janitor Python dependencies — `janitor/requirements.txt`

**Checkpoint**: `docker compose up -d` starts all services. PostgreSQL tables created.

---

## Phase 2: Sentinel Core (Blocks All User Stories)

**Purpose**: FastAPI application with all endpoints. This is the brain — nothing works without it.

**⚠️ CRITICAL**: All user stories depend on this phase.

- [ ] T009 Write FastAPI application entry point and config — `sentinels/personal-brand/main.py`
  - App config from env vars (port, worker URLs, timeouts)
  - Logging setup
  - CORS if needed

- [ ] T010 [P] Define Pydantic models for all request/response schemas — `sentinels/personal-brand/main.py`
  - `DispatchRequest`, `DispatchResponse`, `CallbackRequest`
  - `CapabilitiesResponse`, `HealthResponse`
  - `Confidence` split scoring

- [ ] T011 [P] Implement platform registry and content adaptation — `sentinels/personal-brand/main.py`
  - Platform config dict with X, LinkedIn, Threads, Bluesky
  - Content adaptation per platform (X → thread split, LinkedIn → full text, Threads → condensed)
  - Safe `.get()` lookup — never `dict[key]`

- [ ] T012 [P] Implement `is_expired()` deadline checker — `sentinels/personal-brand/main.py`
  - ISO 8601 parse with timezone normalization
  - Handle `Z` suffix, naive timestamps
  - Fail-safe: unparseable → treat as expired

- [ ] T013 Implement `GET /health` deep check — `sentinels/personal-brand/main.py`
  - Ping n8n webhook health endpoint
  - Ping Postiz `/health` or integration list endpoint
  - Return `"degraded"` status if any worker unreachable

- [ ] T014 Implement `GET /capabilities` — `sentinels/personal-brand/main.py`
  - Return sentinel type, capability list, worker registry URLs

- [ ] T015 Implement `POST /dispatch` (sync mode) — `sentinels/personal-brand/main.py`
  - Check `is_expired(deadline)` → return `"expired"` immediately
  - Validate platforms against registry → return `"rejected"` for unknown
  - Adapt content per platform
  - If no `reply_to`: send Telegram approval via n8n, wait for result, return sync response

- [ ] T016 Implement `POST /dispatch` (async mode with reply_to) — `sentinels/personal-brand/main.py`
  - Same validation as T015
  - If `reply_to` set: return `202 Accepted` immediately
  - BackgroundTasks: send to n8n for approval, receive callback at `/callback`
  - On callback result: dispatch to Postiz or log rejection
  - POST final result to `{reply_to}/callback`

- [ ] T017 Implement `POST /callback` — `sentinels/personal-brand/main.py`
  - Receive approval/rejection from n8n
  - On `"approved"`: call Postiz `POST /public/v1/posts`
  - On `"rejected"`: log reason, notify reply_to
  - On `"expired"`: log, no action
  - Content-type validation before `resp.json()`
  - try/except around all Postiz calls — never crash

- [ ] T018 Implement `GET /cleanup` — `sentinels/personal-brand/main.py`
  - Find all pending approvals past deadline
  - Mark as `"expired"`
  - Return count of purged records

**Checkpoint**: `curl localhost:8103/health` returns `{"status":"ok"}`. `curl localhost:8103/capabilities` returns platform list. All endpoints respond correctly.

---

## Phase 3: User Story 1 — Webhook Draft → Telegram Approval → Post (P1)

**Goal**: Submit a draft via webhook, get Telegram approval notification with inline Approve/Reject buttons, tap Approve → post appears on social platform.

**Independent Test**: POST a draft → receive Telegram notification → tap Approve → verify post on social platform.

### Implementation

- [ ] T019 [US1] Create n8n webhook receiver workflow — `n8n-workflows/telegram-approval.json`
  - Webhook node (receives POST from Sentinel at `/webhook/approval-request`)
  - Telegram node (sends message with inline Approve/Reject buttons)
  - Callback data format: `approve:<draft_id>` / `reject:<draft_id>`
  - Response webhook node (POSTs result to Sentinel `/callback`)

- [ ] T020 [US1] Wire Sentinel `/dispatch` to n8n webhook — `sentinels/personal-brand/main.py`
  - POST to `N8N_WEBHOOK_URL` with draft payload
  - Return Telegram approval status to caller (sync) or via reply_to (async)

- [ ] T021 [US1] Wire n8n callback to Sentinel `/callback` — n8n workflow + `sentinels/personal-brand/main.py`
  - n8n sends `{ draft_id, status, reason }` to Sentinel
  - On approval: Sentinel calls Postiz `POST /public/v1/posts` with `type: "now"`
  - Postiz publishes to connected platform

- [ ] T022 [US1] Handle approval rejection flow — `sentinels/personal-brand/main.py`
  - Log rejection reason
  - POST rejection to `reply_to` if provided
  - No Postiz API call

- [ ] T023 [US1] Handle approval expiry — `sentinels/personal-brand/main.py`
  - `is_expired()` before dispatching to Postiz (double-check)
  - If expired between approval and dispatch: return `"expired"`, no post

**Checkpoint**: POST a draft → Telegram Approve → post on X. Full pipeline works end-to-end.

---

## Phase 4: User Story 2 — Daily Cron Content Generation (P1)

**Goal**: Sentinel wakes up on cron, triggers upstream agent for content, sends for Telegram approval, schedules at optimal time.

**Independent Test**: Set cron to fire in 2 minutes. Verify Telegram notification appears with generated content.

### Implementation

- [ ] T024 [P] [US2] Create n8n cron workflow — `n8n-workflows/telegram-approval.json` (add Schedule trigger)
  - Cron node (configurable, default 09:00 UTC)
  - HTTP Request node (POST to upstream agent `/generate-content`)
  - Same Telegram approval flow as US1

- [ ] T025 [US2] Handle upstream agent timeout/failure — `sentinels/personal-brand/main.py`
  - Catch HTTP timeout (15s worker timeout per Panaversity standard)
  - Log failure
  - Send Telegram alert to user: content generation failed
  - Do not crash — return structured error

- [ ] T026 [US2] Scheduled posting via Postiz — `sentinels/personal-brand/main.py`
  - On approval: call Postiz with `type: "schedule"` + `date: SCHEDULED_POST_TIME`
  - Log scheduled post ID and time

**Checkpoint**: Cron fires → content generated → Telegram approval → post scheduled in Postiz.

---

## Phase 5: User Story 3 — Multi-Platform Content Adaptation (P1)

**Goal**: Same draft adapted per platform before posting — X threads, LinkedIn full text, Threads condensed.

**Independent Test**: Submit 500-char draft targeting X + LinkedIn + Threads. Verify 3 different Postiz payloads.

### Implementation

- [ ] T027 [P] [US3] Implement X content adaptor — `sentinels/personal-brand/main.py`
  - Split text into < 280-char threads
  - Each thread item becomes separate Postiz `value[]` entry
  - Set `settings.__type: "x"` with `who_can_reply_post: "everyone"`

- [ ] T028 [P] [US3] Implement LinkedIn content adaptor — `sentinels/personal-brand/main.py`
  - Full text preserved (markdown → HTML conversion)
  - Set `settings.__type: "linkedin"`
  - Enforce 3000 char max (truncate with "..." if exceeded)

- [ ] T029 [P] [US3] Implement Threads content adaptor — `sentinels/personal-brand/main.py`
  - Condensed version (first 500 chars)
  - Set `settings.__type: "threads"`

- [ ] T030 [P] [US3] Implement Bluesky content adaptor — `sentinels/personal-brand/main.py`
  - Condensed version (first 300 chars)
  - Set `settings.__type: "bluesky"`

- [ ] T031 [US3] Build per-platform Postiz payload builder — `sentinels/personal-brand/main.py`
  - Accept adapted content + platform config
  - Build complete Postiz `POST /posts` payload with integration IDs
  - Platform-specific settings merged

**Checkpoint**: One draft targeting 4 platforms → 4 different Postiz API calls with correct content and settings.

---

## Phase 6: User Story 4 — Health & Capabilities Discovery (P2)

**Goal**: Deep health checks and capability discovery for Odysseus ecosystem integration.

**Independent Test**: Call `/health` and `/capabilities` — verify response structure matches Panaversity spec.

### Implementation

- [ ] T032 [P] [US4] Implement n8n health check in Sentinel — `sentinels/personal-brand/main.py`
  - Ping n8n health endpoint with 5s timeout
  - Return `"ok"` or `"unreachable: <error>"`

- [ ] T033 [P] [US4] Implement Postiz health check in Sentinel — `sentinels/personal-brand/main.py`
  - Ping Postiz API with API key auth
  - Verify API key works (e.g., list integrations)

- [ ] T034 [P] [US4] Implement Telegram-Drive health check (stub for future) — `sentinels/personal-brand/main.py`
  - Ping `http://telegram-drive:8550/api/v1/health`
  - Return `"unreachable"` gracefully if not deployed (don't degrade overall health)

- [ ] T035 [US4] Wire aggregated health into `/health` endpoint — `sentinels/personal-brand/main.py`
  - Aggregate all worker checks
  - Return `"ok"` only if all workers healthy
  - Return `"degraded"` with per-worker detail if any fail

**Checkpoint**: `/health` returns full worker status. `/capabilities` returns complete capability listing.

---

## Phase 7: User Story 5 — Video Post via Telegram-Drive (P3 — Future)

**Goal**: AI-edited video in Telegram-Drive → download → upload to Postiz → schedule.

**Independent Test**: Upload test video to Telegram-Drive, submit draft referencing it, verify Postiz has video scheduled.

### Implementation

- [ ] T036 [P] [US5] Implement Telegram-Drive download in Sentinel — `sentinels/personal-brand/main.py`
  - Fetch video via `GET /api/v1/files/{id}/download` with `X-API-Key`
  - Stream to temp file (or buffer)
  - Delete temp file after upload

- [ ] T037 [P] [US5] Implement Postiz video upload — `sentinels/personal-brand/main.py`
  - Call `POST /public/v1/upload-from-url` or `POST /public/v1/upload`
  - Attach returned media ID to post payload
  - Handle file size limits before upload

- [ ] T038 [US5] Create video-aware draft flow — `sentinels/personal-brand/main.py`
  - Accept `video_id` in DispatchRequest
  - Flow: download → upload → schedule → callback
  - Same Telegram approval pipeline

**Checkpoint**: Video draft → Telegram approval → video scheduled in Postiz.

---

## Phase 8: User Story 6 — Custom Approval Dashboard (P3 — Future)

**Goal**: Web UI listing pending drafts with approval/rejection/edit controls. Replaces Telegram as primary approval surface.

**Independent Test**: Open dashboard URL, see pending drafts, Approve/Reject one, verify action.

### Implementation

- [ ] T039 [P] [US6] Create dashboard HTML/CSS — `sentinels/personal-brand/static/dashboard.html`
  - List pending approvals with content preview
  - Show confidence scores per draft
  - Show target platforms per draft
  - Approve/Reject buttons per draft

- [ ] T040 [P] [US6] Create dashboard API endpoint — `sentinels/personal-brand/main.py`
  - `GET /pending` — list pending approval requests
  - `POST /dashboard/approve/{draft_id}` — approve
  - `POST /dashboard/reject/{draft_id}` — reject with optional reason
  - `POST /dashboard/edit/{draft_id}` — update content before approving

- [ ] T041 [US6] Wire dashboard actions to existing approval pipeline — `sentinels/personal-brand/main.py`
  - Dashboard approve → same path as Telegram approve (Postiz API call)
  - Dashboard reject → same as Telegram reject (log + callback)
  - Edit → update draft content in approval_requests, then approve

**Checkpoint**: Dashboard shows pending drafts. Approve/Reject/Edit actions work and post to Postiz.

---

## Phase 9: Janitor & Production Hardening

**Purpose**: Zombie prevention, heartbeat, stale job cleanup. Panaversity standard compliance.

- [ ] T042 Implement Janitor main loop — `janitor/main.py`
  - Connect to PostgreSQL via `DATABASE_URL`
  - Every 60 seconds:
    - Find `processing` jobs with `heartbeat_at > 5 min ago`
    - If `retry_count < max_retries`: reset to `pending`, increment retry
    - If `retry_count >= max_retries`: move to `failed` (Dead-Letter Queue)
    - Find `pending` jobs past `deadline`: move to `failed`

- [ ] T043 Implement job heartbeat in Sentinel — `sentinels/personal-brand/main.py`
  - For long-running jobs (> 15s expected): update `heartbeat_at` every 30s
  - Use PostgreSQL `UPDATE job_queue SET heartbeat_at = now() WHERE id = :id`

**Checkpoint**: Janitor runs, finds stale jobs, resets them. Logs confirm cleanup cycles.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [ ] T044 [P] Add request logging to all Sentinel endpoints — `sentinels/personal-brand/main.py`
  - Log: method, path, status, duration, draft_id
  - Structured JSON logging for log aggregation

- [ ] T045 [P] Add error taxonomy with consistent status codes — `sentinels/personal-brand/main.py`
  - 400: invalid request (unknown platform, missing fields)
  - 422: validation error (bad content format)
  - 500: internal error (sentinel-side, not worker-side)
  - Worker errors return 200 with `status: "error"` in body

- [ ] T046 [P] Verify Panaversity standard compliance — cross-check all 13 Golden Rules
  - Rule 11 (Heartbeat): covered by Janitor (T042)
  - Rule 13 (Auth): acknowledged as deferred — document in README

- [ ] T047 Run quickstart.md validation — verify full deploy-to-test flow works
  - `cp .env.example .env` → fill secrets
  - `docker compose up -d` → all services healthy
  - Test dispatch → Telegram → approve → posted

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Foundation)**: No dependencies — start immediately
- **Phase 2 (Sentinel Core)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3-6 (US1-US4)**: All depend on Phase 2
- **Phase 7-8 (US5-US6)**: Future enhancements — depend on Phase 2, can start whenever
- **Phase 9 (Janitor)**: Depends on PostgreSQL (Phase 1) — independent of user stories
- **Phase 10 (Polish)**: Depends on Phase 2 completion

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories — standalone
- **US2 (P1)**: No dependencies on US1 — standalone cron trigger
- **US3 (P1)**: Depends on platform registry from Sentinel Core — but uses same dispatch pipeline as US1
- **US4 (P2)**: No dependencies — health/capabilities are standalone endpoints
- **US5 (P3)**: Depends on US1 pipeline + Telegram-Drive
- **US6 (P3)**: Depends on approval_requests table — can be added anytime

### Parallel Opportunities

| Phase | Parallel Tasks |
|---|---|
| Phase 1 | T002, T003, T004, T005, T006, T007, T008 (all [P]) |
| Phase 2 | T010, T011, T012 (all [P] — models + utils) |
| Phase 3 | T024 ([P] — n8n workflow independent of Sentinel) |
| Phase 5 | T027, T028, T029, T030 (all [P] — platform adaptors) |
| Phase 6 | T032, T033, T034 (all [P] — independent health checks) |
| Phase 9 | T042 (Janitor) can run alongside user stories — polls DB independently |

### Recommended Build Order (Single Person)

1. Phase 1 (Foundation) — write all infra files
2. Phase 2 (Sentinel Core) — build the brain
3. Phase 9 (Janitor) — write alongside Sentinel, simple loop
4. Phase 3 (US1 — Webhook → Telegram → Post) — **MVP complete, deployable**
5. Phase 4 (US2 — Cron) — add cron trigger
6. Phase 5 (US3 — Multi-platform) — add adaptors
7. Phase 6 (US4 — Health) — polish the integration layer
8. Phase 10 (Polish) — logging, error taxonomy, compliance check
9. Phase 7 (US5 — Video) — future
10. Phase 8 (US6 — Dashboard) — future
