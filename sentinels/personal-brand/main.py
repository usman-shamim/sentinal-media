import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
from dateutil import parser as dateparser
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker as TemporalWorker

from temporal_workflows import ApprovalWorkflow

# ─── Config ─────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    database_url: str = "postgresql://sentinel:password@localhost:5432/sentinel"
    n8n_webhook_url: str = "http://n8n:5678/webhook/approval-request"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    postiz_api_url: str = "http://postiz:5000"
    postiz_api_key: str = ""
    postiz_integration_x: str = ""
    postiz_integration_linkedin: str = ""
    postiz_integration_threads: str = ""
    postiz_integration_bluesky: str = ""
    scheduled_post_time: str = "10:00"
    worker_timeout_seconds: int = 15
    sentinel_timeout_seconds: int = 20
    log_level: str = "INFO"
    sentinel_port: int = 8103
    temporal_url: str = "temporal:7233"
    temporal_task_queue: str = "sentinel-tasks"

    model_config = {"env_prefix": "", "case_sensitive": False}

settings = Settings()

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("sentinel")

# ─── Platform Registry ───────────────────────────────────────────────────────

PLATFORMS = {
    "x": {
        "name": "X",
        "integration_id_env": "POSTIZ_INTEGRATION_X",
        "settings": {"__type": "x", "who_can_reply_post": "everyone"},
        "character_limit": 280,
        "supports_media": True,
    },
    "linkedin": {
        "name": "LinkedIn",
        "integration_id_env": "POSTIZ_INTEGRATION_LINKEDIN",
        "settings": {"__type": "linkedin"},
        "character_limit": 3000,
        "supports_media": True,
    },
    "threads": {
        "name": "Threads",
        "integration_id_env": "POSTIZ_INTEGRATION_THREADS",
        "settings": {"__type": "threads"},
        "character_limit": 500,
        "supports_media": False,
    },
    "bluesky": {
        "name": "Bluesky",
        "integration_id_env": "POSTIZ_INTEGRATION_BLUESKY",
        "settings": {"__type": "bluesky"},
        "character_limit": 300,
        "supports_media": True,
    },
}

def resolve_integration_id(platform_key: str) -> str | None:
    config = PLATFORMS.get(platform_key)
    if not config:
        return None
    env_var = config.get("integration_id_env", "")
    return os.environ.get(env_var) or None

# ─── Content Adaptation ──────────────────────────────────────────────────────

def adapt_content(content: str, platform_key: str) -> list[dict]:
    config = PLATFORMS.get(platform_key, {})
    limit = config.get("character_limit", 99999)

    if platform_key == "x":
        return _adapt_x(content, limit)
    elif platform_key == "linkedin":
        return _adapt_linkedin(content, limit)
    elif platform_key == "threads":
        return _adapt_threads(content, limit)
    elif platform_key == "bluesky":
        return _adapt_bluesky(content, limit)
    return [{"content": content[:limit]}]

def _adapt_x(content: str, limit: int) -> list[dict]:
    words = content.split()
    threads = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > limit:
            if current:
                threads.append({"content": current.strip()})
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        threads.append({"content": current.strip()})
    if not threads:
        threads = [{"content": ""}]
    return threads

def _adapt_linkedin(content: str, limit: int) -> list[dict]:
    truncated = content[:limit]
    if len(content) > limit:
        truncated = truncated.rstrip() + "..."
    return [{"content": truncated}]

def _adapt_threads(content: str, limit: int) -> list[dict]:
    return [{"content": content[:limit].rstrip()}]

def _adapt_bluesky(content: str, limit: int) -> list[dict]:
    return [{"content": content[:limit].rstrip()}]

# ─── Deadline Checker ────────────────────────────────────────────────────────

def is_expired(deadline_str: str | None) -> bool:
    if not deadline_str:
        return False
    try:
        deadline = dateparser.isoparse(deadline_str)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return deadline < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True

# ─── Pydantic Models ─────────────────────────────────────────────────────────

class Confidence(BaseModel):
    retrieval: float = Field(default=0.0, ge=0.0, le=1.0)
    generation: float = Field(default=0.0, ge=0.0, le=1.0)
    combined: float = Field(default=0.0, ge=0.0, le=1.0)

class DispatchRequest(BaseModel):
    content: str
    platforms: list[str]
    type: str = "now"
    scheduled_at: str | None = None
    deadline: str | None = None
    reply_to: str | None = None
    source: str = "manual"

class DispatchResponse(BaseModel):
    status: str
    draft_id: str | None = None
    error: str | None = None
    confidence: Confidence | None = None

class CallbackRequest(BaseModel):
    draft_id: str
    status: str
    reason: str | None = None

class HealthResponse(BaseModel):
    status: str
    workers: dict
    version: str = "0.1.0"

class CapabilitiesResponse(BaseModel):
    sentinel_type: str = "personal-brand-sentinel"
    capabilities: list[str]
    workers: dict

# ─── Database ────────────────────────────────────────────────────────────────

class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            settings.database_url, min_size=2, max_size=10
        )
        log.info("connected to postgresql")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()
            log.info("disconnected from postgresql")

    async def create_approval(self, draft_id: str, content: str,
                               platforms: list[str], post_type: str,
                               scheduled_at: str | None, deadline: str | None,
                               reply_to: str | None, source: str,
                               telegram_chat_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO approval_requests
                   (draft_id, content, platforms, post_type, scheduled_at,
                    deadline, reply_to, source, telegram_chat_id)
                   VALUES ($1, $2, $3, $4, $5::timestamptz, $6::timestamptz,
                           $7, $8, $9)
                   ON CONFLICT (draft_id) DO NOTHING
                   RETURNING id""",
                draft_id, content, platforms, post_type,
                scheduled_at, deadline, reply_to, source, telegram_chat_id,
            )
            if row:
                return {"id": str(row["id"])}
            return None

    async def get_approval(self, draft_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM approval_requests WHERE draft_id = $1", draft_id
            )
            if not row:
                return None
            return dict(row)

    async def update_approval_status(self, draft_id: str, status: str,
                                     message_id: str | None = None):
        async with self.pool.acquire() as conn:
            if message_id:
                await conn.execute(
                    """UPDATE approval_requests
                       SET status = $2, telegram_message_id = $3,
                           responded_at = now()
                       WHERE draft_id = $1""",
                    draft_id, status, message_id,
                )
            else:
                await conn.execute(
                    """UPDATE approval_requests
                       SET status = $2, responded_at = now()
                       WHERE draft_id = $1""",
                    draft_id, status,
                )

    async def create_post_record(self, draft_id: str, content: str,
                                  platforms: list, postiz_response: dict | None,
                                  status: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO post_records
                   (draft_id, content, platforms, postiz_response, status)
                   VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)""",
                draft_id, content,
                json.dumps(platforms),
                json.dumps(postiz_response) if postiz_response else None,
                status,
            )

    async def cleanup_expired(self) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE approval_requests
                   SET status = 'expired', responded_at = now()
                   WHERE status = 'pending'
                     AND deadline IS NOT NULL
                     AND deadline < now()"""
            )
            parts = result.split()
            return int(parts[-1]) if parts else 0

db = Database()

# ─── HTTP Client ─────────────────────────────────────────────────────────────

http_client: httpx.AsyncClient | None = None

async def get_http() -> httpx.AsyncClient:
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=settings.worker_timeout_seconds)
    return http_client

# ─── Postiz Dispatcher ───────────────────────────────────────────────────────

async def dispatch_to_postiz(draft_id: str, content: str,
                              platforms: list[str]) -> dict:
    client = await get_http()
    results = {}
    overall_status = "posted"

    for platform_key in platforms:
        platform_config = PLATFORMS.get(platform_key)
        if not platform_config:
            results[platform_key] = {"status": "skipped", "error": "unknown platform"}
            continue

        integration_id = resolve_integration_id(platform_key)
        if not integration_id:
            results[platform_key] = {"status": "skipped", "error": "no integration id configured"}
            overall_status = "partial"
            continue

        adapted = adapt_content(content, platform_key)
        try:
            settings_dict = dict(platform_config.get("settings", {}))
            payload = {
                "integration_id": integration_id,
                "value": adapted,
                "type": "now",
                "settings": settings_dict,
            }

            resp = await client.post(
                f"{settings.postiz_api_url}/public/v1/posts",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.postiz_api_key}",
                    "Content-Type": "application/json",
                },
            )

            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                results[platform_key] = {
                    "status": "error",
                    "error": f"non-json response (HTTP {resp.status_code})",
                }
                overall_status = "partial"
                continue

            data = resp.json()
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "60")
                results[platform_key] = {
                    "status": "rate_limited",
                    "retry_after_seconds": int(retry_after),
                }
                overall_status = "partial"
                continue

            if resp.status_code >= 400:
                error_msg = data.get("error", data.get("message", str(resp.status_code)))
                results[platform_key] = {
                    "status": "error",
                    "error": error_msg,
                }
                overall_status = "partial"
                continue

            results[platform_key] = {
                "status": "posted",
                "postiz_id": data.get("id", data.get("data", {}).get("id")),
            }

        except httpx.TimeoutException:
            results[platform_key] = {"status": "error", "error": "timeout"}
            overall_status = "partial"
        except Exception as e:
            results[platform_key] = {"status": "error", "error": str(e)}
            overall_status = "partial"

    return {"status": overall_status, "platforms": results}

# ─── n8n / Telegram Bridge ──────────────────────────────────────────────────

async def send_approval_request(draft_id: str, content: str,
                                 platforms: list[str]) -> bool:
    client = await get_http()
    try:
        resp = await client.post(
            settings.n8n_webhook_url,
            json={
                "draft_id": draft_id,
                "content": content[:500],
                "platforms": platforms,
                "chat_id": settings.telegram_chat_id,
            },
            timeout=settings.worker_timeout_seconds,
        )
        return resp.is_success
    except Exception as e:
        log.error("failed to send approval request to n8n: %s", e)
        return False

async def send_telegram_alert(message: str):
    client = await get_http()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        log.warning("telegram not configured, skipping alert: %s", message)
        return
    try:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )
    except Exception as e:
        log.error("failed to send telegram alert: %s", e)

# ─── Background Task for Async Dispatch ──────────────────────────────────────

async def process_async_dispatch(draft_id: str, content: str,
                                  platforms: list[str], reply_to: str,
                                  post_type: str, scheduled_at: str | None,
                                  source: str):
    sent = await send_approval_request(draft_id, content, platforms)
    if not sent:
        log.error("async dispatch %s: failed to send approval request", draft_id)

# ─── Background Task for Post-Approval Dispatch ──────────────────────────────

async def process_approved_dispatch(draft_id: str, content: str,
                                     platforms: list[str], reply_to: str | None):
    result = await dispatch_to_postiz(draft_id, content, platforms)

    approval = await db.get_approval(draft_id)
    postiz_data = result.get("platforms", {})
    await db.create_post_record(
        draft_id, content,
        [{"platform": p, "status": d.get("status"), "postiz_id": d.get("postiz_id")}
         for p, d in postiz_data.items()],
        result, result.get("status", "error"),
    )

    if reply_to:
        client = await get_http()
        try:
            await client.post(
                f"{reply_to}/callback",
                json={"draft_id": draft_id, "status": result["status"], "result": result},
                timeout=settings.worker_timeout_seconds,
            )
        except Exception as e:
            log.error("failed to callback to %s: %s", reply_to, e)

# ─── FastAPI App ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()

    # Connect to Temporal and start a worker for ApprovalWorkflow
    temporal_client = None
    temporal_worker = None
    try:
        temporal_client = await TemporalClient.connect(settings.temporal_url)
        temporal_worker = TemporalWorker(
            temporal_client,
            task_queue=settings.temporal_task_queue,
            workflows=[ApprovalWorkflow],
            activities=[],
        )
        # Run worker in background task
        asyncio.create_task(temporal_worker.run())
        log.info("Temporal worker started on queue %s", settings.temporal_task_queue)
        app.state.temporal_client = temporal_client
        app.state.temporal_worker = temporal_worker
    except Exception as e:
        log.warning("Temporal not available, falling back to BackgroundTasks: %s", e)
        app.state.temporal_client = None
        app.state.temporal_worker = None

    yield

    if temporal_worker:
        temporal_worker.cancel()
    if temporal_client:
        temporal_client.close()
    await db.disconnect()

app = FastAPI(
    title="Personal Brand Sentinel",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    workers = {}

    n8n_ok = "unreachable"
    try:
        client = await get_http()
        resp = await client.get(
            settings.n8n_webhook_url.replace("/webhook/approval-request", "/health"),
            timeout=5,
        )
        n8n_ok = "ok" if resp.is_success else f"error: HTTP {resp.status_code}"
    except Exception as e:
        n8n_ok = f"unreachable: {e}"
    workers["n8n"] = n8n_ok

    postiz_ok = "unreachable"
    try:
        client = await get_http()
        resp = await client.get(
            f"{settings.postiz_api_url}/public/v1/integrations",
            headers={"Authorization": f"Bearer {settings.postiz_api_key}"},
            timeout=5,
        )
        postiz_ok = "ok" if resp.is_success else f"error: HTTP {resp.status_code}"
    except Exception as e:
        postiz_ok = f"unreachable: {e}"
    workers["postiz"] = postiz_ok

    workers["telegram-drive"] = "unreachable: not deployed"

    overall = "ok" if all(v == "ok" for v in workers.values()) else "degraded"
    return HealthResponse(status=overall, workers=workers)

@app.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities():
    return CapabilitiesResponse(
        capabilities=["post-draft", "schedule-post", "generate-content"],
        workers={
            "n8n": settings.n8n_webhook_url,
            "postiz": settings.postiz_api_url,
        },
    )

@app.post("/dispatch")
async def dispatch(req: DispatchRequest, background_tasks: BackgroundTasks):
    draft_id = f"draft_{uuid.uuid4().hex[:12]}"

    if is_expired(req.deadline):
        return DispatchResponse(status="expired", draft_id=draft_id)

    invalid = [p for p in req.platforms if p not in PLATFORMS]
    if invalid:
        return DispatchResponse(
            status="rejected",
            draft_id=draft_id,
            error=f"unknown platform(s): {', '.join(invalid)}",
        )

    record = await db.create_approval(
        draft_id=draft_id,
        content=req.content,
        platforms=req.platforms,
        post_type=req.type,
        scheduled_at=req.scheduled_at,
        deadline=req.deadline,
        reply_to=req.reply_to,
        source=req.source,
        telegram_chat_id=settings.telegram_chat_id,
    )

    if record is None:
        return DispatchResponse(
            status="error",
            draft_id=draft_id,
            error="duplicate draft_id or database error",
        )

    sent = await send_approval_request(draft_id, req.content, req.platforms)
    if not sent:
        log.warning("approval request failed for %s, queued for retry", draft_id)

    # Try Temporal workflow for durable execution
    temporal_client: TemporalClient | None = getattr(request.app.state, "temporal_client", None)
    if temporal_client:
        try:
            await temporal_client.execute_workflow(
                ApprovalWorkflow.run,
                draft_id,
                req.content,
                req.platforms,
                req.reply_to,
                settings.n8n_webhook_url,
                settings.telegram_chat_id,
                settings.postiz_api_url,
                settings.postiz_api_key,
                id=draft_id,
                task_queue=settings.temporal_task_queue,
                execution_timeout=timedelta(minutes=10),
            )
            log.info("Started Temporal workflow %s for dispatch", draft_id)
        except Exception as e:
            log.error("Temporal workflow failed for %s, falling back: %s", draft_id, e)
            if req.reply_to:
                background_tasks.add_task(
                    process_async_dispatch,
                    draft_id, req.content, req.platforms,
                    req.reply_to, req.type, req.scheduled_at, req.source,
                )
    elif req.reply_to:
        background_tasks.add_task(
            process_async_dispatch,
            draft_id, req.content, req.platforms,
            req.reply_to, req.type, req.scheduled_at, req.source,
        )

    return JSONResponse(
        status_code=202,
        content=DispatchResponse(
            status="accepted", draft_id=draft_id
        ).model_dump(),
    )

@app.post("/callback")
async def callback(req: CallbackRequest, background_tasks: BackgroundTasks):
    approval = await db.get_approval(req.draft_id)
    if not approval:
        return {"status": "error", "error": "draft_id not found"}

    if approval["status"] != "pending":
        return {"status": "already_processed", "current_status": approval["status"]}

    if is_expired(approval.get("deadline")):
        await db.update_approval_status(req.draft_id, "expired")
        return {"status": "expired"}

    # Try to signal the Temporal workflow
    temporal_client: TemporalClient | None = getattr(request.app.state, "temporal_client", None)
    if temporal_client:
        try:
            handle = temporal_client.get_workflow_handle(req.draft_id)
            await handle.signal("approval_decision", {"status": req.status, "reason": req.reason})
            log.info("Signaled workflow %s with %s", req.draft_id, req.status)
        except Exception as e:
            log.warning("Failed to signal workflow %s, using fallback: %s", req.draft_id, e)
            # Fall through to legacy path
            temporal_client = None

    if req.status == "approved":
        await db.update_approval_status(req.draft_id, "approved")
        reply_to = approval.get("reply_to")
        if not temporal_client:
            # Fallback: use BackgroundTasks
            background_tasks.add_task(
                process_approved_dispatch,
                req.draft_id,
                approval["content"],
                approval["platforms"],
                reply_to,
            )
        return {"status": "approved", "dispatched": True}

    await db.update_approval_status(req.draft_id, "rejected")
    log.info("draft %s rejected: %s", req.draft_id, req.reason or "no reason")

    if not temporal_client:
        reply_to = approval.get("reply_to")
        if reply_to:
            client = await get_http()
            try:
                await client.post(
                    f"{reply_to}/callback",
                    json={"draft_id": req.draft_id, "status": "rejected", "reason": req.reason},
                    timeout=settings.worker_timeout_seconds,
                )
            except Exception as e:
                log.error("failed to send rejection callback to %s: %s", reply_to, e)

    return {"status": "rejected"}

@app.get("/cleanup")
async def cleanup():
    purged = await db.cleanup_expired()
    return {"purged": purged}

# ─── Error Handler ───────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "error": "internal server error"},
    )

# ─── Entry ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.sentinel_port)
