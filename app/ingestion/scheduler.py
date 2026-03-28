"""Scheduler for ingestion tasks."""

from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logger import logger


class IngestionScheduler:
    """Manages scheduled ingestion tasks using APScheduler."""

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler()
        self._is_running = False

    def add_job(
        self,
        func,
        interval_minutes: int = 5,
        job_id: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        """Add a periodic job to the scheduler.

        Args:
            func: Callable to execute on schedule
            interval_minutes: Interval in minutes between executions (default: 5)
            job_id: Optional job identifier
            *args: Positional arguments to pass to func
            **kwargs: Keyword arguments to pass to func
        """
        if not job_id:
            job_id = f"{func.__name__}_{datetime.now().timestamp()}"

        self.scheduler.add_job(
            func,
            IntervalTrigger(minutes=interval_minutes),
            args=args,
            kwargs=kwargs,
            id=job_id,
            name=f"Ingestion Job: {func.__name__}",
            replace_existing=False,
            coalesce=True,
            max_instances=1,
        )
        logger.info(
            f"Added scheduled job '{job_id}' for {func.__name__} "
            f"with interval {interval_minutes} minutes"
        )

    def start(self) -> None:
        """Start the scheduler."""
        if not self._is_running:
            self.scheduler.start()
            self._is_running = True
            logger.info("Ingestion scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown()
            self._is_running = False
            logger.info("Ingestion scheduler stopped")

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running

    def get_jobs(self) -> list[dict]:
        """Get list of scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time,
                }
            )
        return jobs
