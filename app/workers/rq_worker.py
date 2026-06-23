"""
RQ Worker entrypoint.
Run via: python -m app.workers.rq_worker

Starts an RQ worker that:
- Listens on the configured queue.
- Supports multiple parallel workers (run multiple containers).
- Never exits on individual job failures.
- Logs structured JSON.
"""
from __future__ import annotations

import logging
import os
import signal
import sys

# Fix macOS fork safety issue with objc
os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'

from rq import Worker
from rq.timeouts import JobTimeoutException

from app.config.settings import get_settings
from app.db.session import init_db
from app.queue.connection import get_queue, get_redis_connection
from app.utils.logging import configure_logging, get_logger


def main() -> None:
    configure_logging()
    logger = get_logger(__name__)

    settings = get_settings()
    logger.info(
        "RQ Worker starting",
        extra={"queue": settings.rq_queue_name, "redis_url": settings.redis_url},
    )

    # Ensure schema is ready
    init_db()

    redis_conn = get_redis_connection()
    queue = get_queue()

    worker = Worker(
        queues=[queue],
        connection=redis_conn,
        log_job_description=True,
    )

    logger.info("Worker listening", extra={"queue": settings.rq_queue_name})

    try:
        worker.work(with_scheduler=False)
    except KeyboardInterrupt:
        logger.info("Worker received shutdown signal, stopping gracefully")
        sys.exit(0)


if __name__ == "__main__":
    main()
