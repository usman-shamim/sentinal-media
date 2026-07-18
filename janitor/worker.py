"""Temporal worker for the janitor workflow.

Connects to the shared Temporal server (temporal:7233) and registers
the JanitorWorkflow so it can be scheduled via Temporal Cron.
"""

import asyncio
import logging
import os

from temporalio.client import Client, Schedule, ScheduleAction, ScheduleSpec
from temporalio.worker import Worker

from workflow import JanitorWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("janitor-worker")

TEMPORAL_URL = os.getenv("TEMPORAL_URL", "temporal:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "janitor-tasks")
CRON_SCHEDULE = os.getenv("JANITOR_CRON", "*/1 * * * *")  # every minute


async def ensure_schedule(client: Client):
    """Register the janitor Cron Schedule if it doesn't exist."""
    try:
        await client.create_schedule(
            "janitor-cron",
            Schedule(
                action=ScheduleAction.start_workflow(
                    JanitorWorkflow,
                    id="janitor-workflow-id",
                    task_queue=TASK_QUEUE,
                ),
                spec=ScheduleSpec(
                    cron_expressions=[CRON_SCHEDULE],
                ),
            ),
        )
        logger.info("Janitor cron schedule created: %s", CRON_SCHEDULE)
    except Exception as e:
        if "already exists" in str(e):
            logger.info("Janitor cron schedule already exists")
        else:
            logger.warning("Could not create schedule: %s", e)


async def main():
    logger.info("Connecting to Temporal at %s", TEMPORAL_URL)
    client = await Client.connect(TEMPORAL_URL)

    await ensure_schedule(client)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[JanitorWorkflow],
        activities=[],
    )
    logger.info("Janitor worker started on queue %s", TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
