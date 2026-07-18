"""Temporal Cron Workflow for janitor — replaces the polling loop."""

from datetime import timedelta
from temporalio import workflow, activity

# ── Activities ──────────────────────────────────────────────────────────

@activity.defn
async def reset_stale_jobs() -> int:
    """Reset jammed processing jobs back to pending.

    Runs inside the Temporal worker container, which has access to the
    shared Postgres on the media_default network.
    """
    import asyncpg
    import os
    from datetime import datetime, timezone

    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://sentinel:${POSTGRES_PASSWORD}@postgres:5432/sentinel",
    )
    threshold_min = int(os.getenv("STALE_THRESHOLD_MINUTES", "5"))
    max_retries = int(os.getenv("MAX_RETRIES", "3"))

    conn = await asyncpg.connect(dsn)
    try:
        # Reset jobs stuck in 'processing' past the heartbeat threshold
        result = await conn.execute(
            """
            UPDATE job_queue
            SET status = 'pending',
                started_at = NULL,
                assigned_to = NULL,
                retry_count = retry_count + 1
            WHERE status = 'processing'
              AND heartbeat_at < NOW() - make_interval(mins => $1)
              AND retry_count < $2
            """,
            threshold_min,
            max_retries,
        )
        # Move exhausted retries to dead-letter
        dead = await conn.execute(
            """
            UPDATE job_queue
            SET status = 'failed',
                finished_at = NOW()
            WHERE status = 'processing'
              AND heartbeat_at < NOW() - make_interval(mins => $1)
              AND retry_count >= $2
            """,
            threshold_min,
            max_retries,
        )
        return int(result.split()[-1]) + int(dead.split()[-1])
    finally:
        await conn.close()


# ── Workflow ────────────────────────────────────────────────────────────

@workflow.defn
class JanitorWorkflow:
    """Runs on a Temporal Cron Schedule — no polling loop needed."""

    @workflow.run
    async def run(self) -> int:
        cleaned = await workflow.execute_activity(
            reset_stale_jobs,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy={"maximum_attempts": 2},
        )
        workflow.logger.info("Janitor cleaned %d stale jobs", cleaned)
        return cleaned
