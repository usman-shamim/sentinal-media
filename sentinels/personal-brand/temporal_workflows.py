"""Temporal Workflows for durable sentinel dispatch.

Replaces FastAPI BackgroundTasks — survives container crashes and restarts.
"""

import asyncio
import json
import logging
import os
from datetime import timedelta
from typing import Optional

import httpx
from temporalio import activity, workflow

logger = logging.getLogger("temporal-workflows")

# ── Activity: Send approval request to n8n/Telegram ─────────────────────

@activity.defn
async def send_approval_activity(draft_id: str, content: str,
                                  platforms: list[str],
                                  n8n_url: str, chat_id: str,
                                  timeout_sec: int = 15) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(
                n8n_url,
                json={
                    "draft_id": draft_id,
                    "content": content[:500],
                    "platforms": platforms,
                    "chat_id": chat_id,
                },
            )
            return resp.is_success
    except Exception as e:
        logger.error("approval activity failed: %s", e)
        return False


# ── Activity: Dispatch content to Postiz ────────────────────────────────

@activity.defn
async def postiz_dispatch_activity(draft_id: str, content: str,
                                    platforms: list[str],
                                    postiz_url: str, postiz_key: str,
                                    timeout_sec: int = 15) -> dict:
    """Dispatch content to Postiz for one or more platforms."""

    PLATFORMS = {
        "x": {"settings": {"__type": "x", "who_can_reply_post": "everyone"}, "limit": 280},
        "linkedin": {"settings": {"__type": "linkedin"}, "limit": 3000},
        "threads": {"settings": {"__type": "threads"}, "limit": 500},
        "bluesky": {"settings": {"__type": "bluesky"}, "limit": 300},
    }

    results = {}
    overall_status = "posted"

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        for platform_key in platforms:
            config = PLATFORMS.get(platform_key)
            if not config:
                results[platform_key] = {"status": "skipped", "error": "unknown platform"}
                overall_status = "partial"
                continue

            integration_id = os.environ.get(f"POSTIZ_INTEGRATION_{platform_key.upper()}")
            if not integration_id:
                results[platform_key] = {"status": "skipped", "error": "no integration id"}
                overall_status = "partial"
                continue

            adapted = _adapt_content(content, platform_key, config["limit"])
            try:
                payload = {
                    "integration_id": integration_id,
                    "value": adapted,
                    "type": "now",
                    "settings": dict(config["settings"]),
                }
                resp = await client.post(
                    f"{postiz_url}/public/v1/posts",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {postiz_key}",
                        "Content-Type": "application/json",
                    },
                )

                if resp.status_code == 429:
                    results[platform_key] = {
                        "status": "rate_limited",
                        "retry_after_seconds": int(resp.headers.get("Retry-After", "60")),
                    }
                    overall_status = "partial"
                elif resp.status_code >= 400:
                    data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                    results[platform_key] = {
                        "status": "error",
                        "error": data.get("error", data.get("message", str(resp.status_code))),
                    }
                    overall_status = "partial"
                else:
                    data = resp.json()
                    results[platform_key] = {
                        "status": "posted",
                        "postiz_id": data.get("id", data.get("data", {}).get("id")),
                    }
            except Exception as e:
                results[platform_key] = {"status": "error", "error": str(e)}
                overall_status = "partial"

    return {"status": overall_status, "platforms": results}


def _adapt_content(content: str, platform: str, limit: int) -> list[dict]:
    if platform == "x":
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
        return threads or [{"content": ""}]

    truncated = content[:limit]
    if len(content) > limit:
        truncated = truncated.rstrip() + "..."
    return [{"content": truncated}]


# ── Activity: Send HTTP callback ────────────────────────────────────────

@activity.defn
async def send_callback_activity(url: str, payload: dict,
                                   timeout_sec: int = 10) -> bool:
    if not url:
        return True
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(url, json=payload)
            return resp.is_success
    except Exception as e:
        logger.error("callback to %s failed: %s", url, e)
        return False


# ── Activity: Log to database ───────────────────────────────────────────

@activity.defn
async def db_log_activity(draft_id: str, content: str,
                           platforms: list, result: dict) -> None:
    import asyncpg
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        logger.warning("DATABASE_URL not set, skipping db log")
        return
    try:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                """INSERT INTO post_records
                   (draft_id, content, platforms, postiz_response, status)
                   VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)""",
                draft_id, content,
                json.dumps(platforms),
                json.dumps(result),
                result.get("status", "error"),
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.error("db log failed: %s", e)


# ── Workflow: Approval + Dispatch (replaces background_tasks) ──────────

@workflow.defn
class ApprovalWorkflow:
    """Handles the approval request and follow-up dispatch.

    This workflow is started from /dispatch and continues running even
    if the sentinel container restarts.
    """

    @workflow.run
    async def run(self, draft_id: str, content: str, platforms: list[str],
                  reply_to: Optional[str], n8n_url: str, chat_id: str,
                  postiz_url: str, postiz_key: str,
                  approval_timeout: int = 300) -> dict:
        # Step 1: Send approval request to n8n/Telegram
        sent = await workflow.execute_activity(
            send_approval_activity,
            draft_id, content, platforms, n8n_url, chat_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy={"maximum_attempts": 3},
        )
        if not sent:
            logger.warning("Approval request failed for %s", draft_id)

        # Step 2: Wait for callback (external signal via /callback -> workflow signal)
        # The /callback endpoint will signal this workflow with approval decision
        try:
            signal = await workflow.wait_for_signal(
                "approval_decision",
                timeout=timedelta(seconds=approval_timeout),
            )
        except asyncio.TimeoutError:
            # If callback never comes, mark as expired
            logger.warning("Approval %s timed out", draft_id)
            if reply_to:
                await workflow.execute_activity(
                    send_callback_activity,
                    f"{reply_to}/callback",
                    {"draft_id": draft_id, "status": "expired"},
                    start_to_close_timeout=timedelta(seconds=10),
                )
            return {"status": "expired", "draft_id": draft_id}

        decision = signal.get("status", "rejected")
        reason = signal.get("reason")

        if decision != "approved":
            if reply_to:
                await workflow.execute_activity(
                    send_callback_activity,
                    f"{reply_to}/callback",
                    {"draft_id": draft_id, "status": "rejected", "reason": reason},
                    start_to_close_timeout=timedelta(seconds=10),
                )
            return {"status": "rejected", "draft_id": draft_id, "reason": reason}

        # Step 3: Dispatch to Postiz (with retries)
        result = await workflow.execute_activity(
            postiz_dispatch_activity,
            draft_id, content, platforms, postiz_url, postiz_key,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy={"maximum_attempts": 2},
        )

        # Step 4: Log to database
        await workflow.execute_activity(
            db_log_activity,
            draft_id, content,
            [{"platform": p, "status": d.get("status"), "postiz_id": d.get("postiz_id")}
             for p, d in result.get("platforms", {}).items()],
            result,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Step 5: Send callback to caller (if reply_to was provided)
        if reply_to:
            await workflow.execute_activity(
                send_callback_activity,
                f"{reply_to}/callback",
                {"draft_id": draft_id, "status": result["status"], "result": result},
                start_to_close_timeout=timedelta(seconds=15),
            )

        return {"status": result["status"], "draft_id": draft_id, "result": result}
