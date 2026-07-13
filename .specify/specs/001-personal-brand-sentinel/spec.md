# Feature Specification: Personal Brand Sentinel

**Feature Branch**: `001-personal-brand-sentinel`
**Created**: 2026-07-13
**Status**: Draft
**Input**: User description: "Build a Personal Brand Sentinel on n8n that manages social media posting via Postiz, following the Panaversity Agent Architecture pattern. Supports AI drafts, human drafts, Telegram approval, and multi-platform posting."

## User Scenarios & Testing

### User Story 1 — Submit Draft via Webhook and Post After Approval (Priority: P1)

A user (or upstream Odysseus agent) sends a draft post to the Sentinel webhook endpoint. The Sentinel validates the draft, checks deadlines, adapts content per platform, sends a Telegram approval request with inline Approve/Reject buttons. On approval, the Sentinel dispatches the post to Postiz for immediate or scheduled publishing. On rejection, it logs the feedback and optionally notifies the upstream agent.

**Why this priority**: This is the core loop — without draft submission and approval-to-posting flow, nothing works. Everything else builds on top of this.

**Independent Test**: Can be fully tested by: (1) Send a POST request to the Sentinel webhook with valid draft JSON, (2) Receive Telegram notification with Approve/Reject buttons, (3) Tap Approve, (4) Verify post appears on target social platform within acceptable latency.

**Acceptance Scenarios**:

1. **Given** the Sentinel webhook is running, **When** a valid POST request is sent with `{ content, platforms: ["x", "linkedin"], type: "now" }`, **Then** the Sentinel returns `202 Accepted`, a Telegram notification appears with Approve/Reject buttons containing the draft text and AI review summary.
2. **Given** the Telegram notification is visible, **When** the user taps "Approve", **Then** the Sentinel calls Postiz `POST /public/v1/posts` with `type: "now"`, and the post appears on X and LinkedIn within 60 seconds.
3. **Given** the Telegram notification is visible, **When** the user taps "Reject", **Then** the Sentinel logs the rejection with reason (if provided) and returns a callback to `reply_to` with `status: "rejected"`.
4. **Given** a draft is submitted with a `deadline` in the past, **When** the Sentinel processes the request, **Then** it returns `{ status: "expired" }` immediately without sending a Telegram notification or calling Postiz.

---

### User Story 2 — Daily Cron Generates and Schedules Content (Priority: P1)

The Sentinel wakes up daily on a configurable cron schedule, triggers the upstream Odysseus agent (or an LLM) to generate a fresh post draft about the user's niche/topics, validates the generated draft, sends it for Telegram approval, and on approval schedules it at the optimal posting time. If no upstream agent is configured, it uses a pre-defined content template.

**Why this priority**: Proactive content generation ensures consistent posting even when the user doesn't manually submit drafts. Combined with Story 1, it gives full coverage: reactive + proactive.

**Independent Test**: Can be tested by: (1) Set cron to fire in 2 minutes, (2) Configure a test upstream agent that returns known draft content, (3) Verify Telegram approval fires, (4) Approve and verify scheduled post in Postiz.

**Acceptance Scenarios**:

1. **Given** the Sentinel has a cron trigger configured at 09:00 UTC daily, **When** the cron fires, **Then** the Sentinel calls the upstream agent (`POST /generate-content`), receives a draft, and sends a Telegram approval notification.
2. **Given** the generated draft passes AI validation (confidence > threshold), **When** it's approved, **Then** the Sentinel schedules it at the next optimal posting time via Postiz with `type: "schedule"`.
3. **Given** the upstream agent fails to respond (timeout > 15s), **When** the cron fires, **Then** the Sentinel logs the failure and sends an alert to Telegram that content generation failed.

---

### User Story 3 — Multi-Platform Content Adaptation (Priority: P1)

When a draft is approved for posting across multiple platforms, the Sentinel adapts the content per platform before dispatching to Postiz. X posts enforce character limits and thread splitting. LinkedIn preserves full text. Threads uses a condensed version. Each platform receives its appropriate settings schema (`__type`, required fields).

**Why this priority**: Posting raw identical content across platforms creates a poor experience. Platform-specific adaptation is the core value differentiator.

**Independent Test**: Submit a 500-character draft targeting X, LinkedIn, and Threads. Verify the X version is split into threads (< 280 chars each), LinkedIn preserves the full text, Threads gets an adapted version.

**Acceptance Scenarios**:

1. **Given** a 500-character draft is approved for X, **When** the Sentinel prepares the Postiz payload, **Then** the text is split into N threads (each < 280 chars) with `who_can_reply_post: "everyone"` in X settings.
2. **Given** a draft with markdown formatting is approved for LinkedIn, **When** the Sentinel prepares the payload, **Then** markdown is preserved and `value[0].content` contains the full HTML-converted text.
3. **Given** a draft is approved for X + LinkedIn + Threads, **When** the Sentinel dispatches, **Then** three separate Postiz requests are made (one per platform), each with correct `settings.__type` and platform-specific content.

---

### User Story 4 — Health and Capabilities Discovery (Priority: P2)

The Sentinel exposes `/health` (deep check — pings n8n webhook, Postiz API, Telegram-Drive) and `/capabilities` (lists managed platforms, supported task types, worker URLs). Other agents in the Odysseus ecosystem discover the Sentinel and understand its capabilities without external documentation.

**Why this priority**: Deep health checks and discovery are required by the Panaversity standard (Golden Rule #6). Without these, the Sentinel can't integrate into the broader agent ecosystem.

**Independent Test**: Call `GET /health` and verify it returns `"status": "ok"` with per-worker status. Call `GET /capabilities` and verify it returns supported platforms and task types.

**Acceptance Scenarios**:

1. **Given** all dependencies (Postiz API, n8n, Telegram-Drive) are running, **When** `GET /health` is called, **Then** it returns `{ "status": "ok", "workers": { "postiz": "ok", "n8n": "ok", "telegram-drive": "ok" } }`.
2. **Given** Postiz API is unreachable, **When** `GET /health` is called, **Then** it returns `{ "status": "degraded", "workers": { "postiz": "unreachable: ..." } }`.
3. **Given** the Sentinel is running, **When** `GET /capabilities` is called, **Then** it returns `{ "sentinel_type": "personal-brand-sentinel", "capabilities": ["post-draft", "schedule-post", "generate-content"], "workers": { "postiz": "...", "n8n": "...", "telegram-drive": "..." } }`.

---

### User Story 5 — Video Post via Telegram-Drive (Priority: P3)

An AI-edited video is uploaded to Telegram-Drive. A draft is submitted referencing the video (by Telegram-Drive file ID or URL). The Sentinel downloads the video from Telegram-Drive (`GET /files/{id}/download`), uploads it to Postiz (`POST /public/v1/upload-from-url`), creates a scheduled post with the video attached, and sends a Telegram approval request before posting.

**Why this priority**: Video is the most engaging content format but requires complex file handling. This is a future enhancement once the text pipeline is stable.

**Independent Test**: Upload a test video to Telegram-Drive, submit a draft referencing it, approve via Telegram, verify the video post is scheduled in Postiz.

**Acceptance Scenarios**:

1. **Given** a video file exists in Telegram-Drive with ID `123`, **When** the Sentinel processes a draft referencing `{ "video_id": "123" }`, **Then** it downloads the file via `GET /api/v1/files/123/download`.
2. **Given** the video is successfully downloaded from Telegram-Drive, **When** the Sentinel uploads it to Postiz, **Then** it calls `POST /public/v1/upload-from-url` and receives a media ID.
3. **Given** the video is uploaded and approved, **When** the Sentinel creates the post, **Then** Postiz receives `POST /public/v1/posts` with the video attached and `type: "schedule"`.

---

### User Story 6 — Custom Approval Dashboard (Priority: P3)

A lightweight web UI (built into the Sentinel FastAPI server or as a standalone page) lists all pending drafts with AI review notes, confidence scores, side-by-side diffs between original and adapted content, and Approve/Reject/Edit buttons. This replaces Telegram as the primary approval interface.

**Why this priority**: Telegram approval is fast but limited. A dashboard gives richer context (before/after adaptation, confidence breakdown, draft history). This is a v2 enhancement.

**Independent Test**: Deploy the dashboard, navigate to it in a browser, verify pending drafts are listed, test Approve and Reject actions, verify post is created/skipped.

**Acceptance Scenarios**:

1. **Given** there are 3 pending drafts, **When** the user navigates to `/dashboard`, **Then** all 3 are displayed with content preview, AI confidence scores, and target platforms.
2. **Given** a draft has AI review notes, **When** viewed in the dashboard, **Then** the notes are displayed alongside the original draft for comparison.
3. **Given** the user clicks "Approve" on a draft, **When** the dashboard processes the action, **Then** the Sentinel dispatches the draft to Postiz and removes it from the pending queue.
4. **Given** the user clicks "Edit" on a draft, **When** the dashboard shows an edit form, **Then** the user can modify content before approving.

---

### Edge Cases

- **Deadline in the past**: Both Sentinel and Worker check `is_expired(deadline)` before any processing. Returns `status: "expired"` immediately.
- **Unknown platform requested**: Sentinel returns `status: "rejected"` with error `"No worker for platform '{name}'"`. Never throws KeyError.
- **Postiz returns HTML error page**: Sentinel validates `content-type` header before `resp.json()`. Returns structured error response.
- **Telegram bot unreachable**: Sentinel logs the failure and retries up to 3 times. After max retries, falls back to email notification.
- **Postiz rate limited (30 req/hour)**: Sentinel reads `Retry-After` header from Postiz 429 response and returns `status: "rate_limited"` with retry-after duration. Upstream agent retries. No Job Queue for MVP.
- **Upstream agent timeout during cron generation**: Sentinel catches timeout, logs, sends Telegram alert. Does not crash.
- **Video file too large for Postiz**: Sentinel checks size before upload. Returns `status: "rejected"` with size error.
- **Concurrent approval race**: Only the first Approve/Reject action is processed. Subsequent actions return `status: "already_processed"`.

## Requirements

### Functional Requirements

- **FR-001**: System MUST expose a POST `/dispatch` endpoint that accepts draft content, target platforms, optional deadline, and optional reply_to callback URL.
- **FR-002**: System MUST send a Telegram notification with inline Approve/Reject buttons for every draft that passes AI validation.
- **FR-003**: System MUST call Postiz `POST /public/v1/posts` when a draft is approved, with correct platform-specific settings.
- **FR-004**: System MUST support immediate (`type: "now"`) and scheduled (`type: "schedule"`) posting modes.
- **FR-005**: System MUST check `is_expired(deadline)` before processing any draft.
- **FR-006**: System MUST return `202 Accepted` immediately for drafts with `reply_to`, process asynchronously, and POST result to `{reply_to}/callback`.
- **FR-007**: System MUST expose `GET /health` as a deep check pinging Postiz, n8n, and Telegram-Drive.
- **FR-008**: System MUST expose `GET /capabilities` listing supported platforms and task types.
- **FR-009**: System MUST run a daily cron that triggers content generation from an upstream agent.
- **FR-010**: System MUST adapt content per platform (character limits, thread splitting, markdown preservation) before dispatching to Postiz.
- **FR-011**: System MUST log all approvals, rejections, errors, and timeouts with timestamps.
- **FR-012**: System MUST handle Postiz API errors (non-JSON responses, 4xx, 5xx) without crashing — return structured error response.
- **FR-013**: System MUST use `.get(key, default)` for all dictionary lookups — never `dict[key]`.
- **FR-014**: System MUST enforce layered timeouts: Worker API calls (15s), Sentinel processing (20s).
- **FR-015**: System MUST report split confidence scores (`confidence_retrieval`, `confidence_generation`, `confidence_combined`) in dispatch responses.
- **FR-016**: System MUST support video drafts with Telegram-Drive integration for file storage and retrieval (future).
- **FR-017**: System MUST lock processed drafts against duplicate approval.
- **FR-018**: System MUST handle Postiz 429 rate-limit errors by reading the `Retry-After` header and returning `status: "rate_limited"` with retry-after duration to the caller.
- **FR-019**: System MUST auto-expire pending approval requests whose `deadline` has passed. A `/cleanup` endpoint sweeps expired approvals and marks them `status: "expired"`.

### Key Entities

- **Draft**: Content item submitted for posting. Attributes: content (string), platforms (array of Platform), deadline (ISO 8601 or null), reply_to (URL or null), type ("now" | "schedule" | "draft"), scheduled_at (ISO 8601 or null), media (array of File or null), source ("human" | "ai" | "cron").
- **Platform**: Target social media channel registered in Postiz. Attributes: name (string), integration_id (string, Postiz ID), settings_schema (object with __type and platform-specific fields), character_limit (number), supports_media (boolean).
- **Approval Request**: A pending approval sent to Telegram. Attributes: draft_id (string), chat_id (string), message_id (string), status ("pending" | "approved" | "rejected"), created_at (ISO 8601), responded_at (ISO 8601 or null).
- **Post Record**: Record of a successfully posted/scheduled item. Attributes: postiz_post_id (string), platforms (array of {platform, postiz_id, status}), created_at (ISO 8601), confidence (object with retrieval/generation/combined).
- **Video File**: Reference to a video stored in Telegram-Drive. Attributes: telegram_drive_id (number), filename (string), size_bytes (number), mime_type (string), status ("stored" | "downloading" | "uploading" | "posted" | "failed").

## Success Criteria

### Measurable Outcomes

- **SC-001**: A draft submitted via webhook reaches the target social platform in under 60 seconds (text-only, "now" type, approval time excluded).
- **SC-002**: Sentinel handles 50 concurrent draft submissions without degradation (12GB RAM VM, Docker Compose stack).
- **SC-003**: 100% of expired deadlines are caught and return `"expired"` status before any external API calls.
- **SC-004**: Zero crashes from Worker errors — all Postiz/n8n/Telegram-Drive failures return structured error responses.
- **SC-005**: Daily cron generates and dispatches at least one post per configured schedule without manual intervention.
- **SC-006**: Content adapted per platform (X threads, LinkedIn full text, Threads condensed) matches platform-native formatting expectations.
- **SC-007**: Approval via Telegram completes in under 5 seconds from button tap to Postiz API call.
