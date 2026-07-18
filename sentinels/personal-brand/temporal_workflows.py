"""Temporal Workflows for durable sentinel dispatch.

Replaces FastAPI BackgroundTasks — survives container crashes and restarts.

NOTE: Activities must use lazy imports because Temporal's sandbox
restricts non-deterministic modules like httpx and asyncpg inside
workflow definitions. All I/O lives in activities.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

logger = logging.getLogger("temporal-workflows")


# ── Activities (import I/O modules lazily) ──────────────────────────────

@activity.defn
async def send_approval_activity(draft_id: str, content: str,
                                  platforms: list[str],
                                  n8n_url: str, chat_id: str,
                                  timeout_sec: int = 15) -> bool:
    import httpx
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


@activity.defn
async def postiz_dispatch_activity(draft_id: str, content: str,
                                    platforms: list[str],
                                    postiz_url: str, postiz_key: str,
                                    timeout_sec: int = 15) -> dict:
    import httpx
    import os

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


@activity.defn
async def send_callback_activity(url: str, payload: dict,
                                   timeout_sec: int = 10) -> bool:
    import httpx
    if not url:
        return True
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(url, json=payload)
            return resp.is_success
    except Exception as e:
        logger.error("callback to %s failed: %s", url, e)
        return False


@activity.defn
async def db_log_activity(draft_id: str, content: str,
                           platforms: list, result: dict) -> None:
    import asyncpg
    import json
    import os
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


# ── Workflow ────────────────────────────────────────────────────────────

@workflow.defn
class ApprovalWorkflow:
    """Handles the approval request and follow-up dispatch.

    This workflow is started from /dispatch and continues running even
    if the sentinel container restarts. It waits for a signal from /callback.
    """

    def __init__(self) -> None:
        self._decision: Optional[dict] = None

    @workflow.signal
    def approval_decision(self, payload: dict) -> None:
        self._decision = payload

    @workflow.run
    async def run(self, draft_id: str, content: str, platforms: list[str],
                  reply_to: Optional[str], n8n_url: str, chat_id: str,
                  postiz_url: str, postiz_key: str,
                  approval_timeout: int = 300) -> dict:

        # Step 1: Send approval request to n8n/Telegram
        sent = await workflow.execute_activity(
            send_approval_activity,
            args=[draft_id, content, platforms, n8n_url, chat_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not sent:
            logger.warning("Approval request failed for %s", draft_id)

        # Step 2: Wait for callback signal from /callback endpoint
        try:
            await asyncio.wait_for(
                workflow.wait_condition(lambda: self._decision is not None),
                timeout=approval_timeout,
            )
            decision = self._decision or {}
        except asyncio.TimeoutError:
            logger.warning("Approval %s timed out", draft_id)
            if reply_to:
                await workflow.execute_activity(
                    send_callback_activity,
                    args=[f"{reply_to}/callback",
                          {"draft_id": draft_id, "status": "expired"}],
                    start_to_close_timeout=timedelta(seconds=10),
                )
            return {"status": "expired", "draft_id": draft_id}

        status = decision.get("status", "rejected")
        reason = decision.get("reason")

        if status != "approved":
            if reply_to:
                await workflow.execute_activity(
                    send_callback_activity,
                    args=[f"{reply_to}/callback",
                          {"draft_id": draft_id, "status": "rejected", "reason": reason}],
                    start_to_close_timeout=timedelta(seconds=10),
                )
            return {"status": "rejected", "draft_id": draft_id, "reason": reason}

        # Step 3: Dispatch to Postiz (with retries)
        result = await workflow.execute_activity(
            postiz_dispatch_activity,
            args=[draft_id, content, platforms, postiz_url, postiz_key],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Step 4: Log to database
        platform_logs = [
            {"platform": p, "status": d.get("status"), "postiz_id": d.get("postiz_id")}
            for p, d in result.get("platforms", {}).items()
        ]
        await workflow.execute_activity(
            db_log_activity,
            args=[draft_id, content, platform_logs, result],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Step 5: Send callback to caller (if reply_to was provided)
        if reply_to:
            await workflow.execute_activity(
                send_callback_activity,
                args=[f"{reply_to}/callback",
                      {"draft_id": draft_id, "status": result["status"], "result": result}],
                start_to_close_timeout=timedelta(seconds=15),
            )

        return {"status": result["status"], "draft_id": draft_id, "result": result}
