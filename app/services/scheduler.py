from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services.sandbox import SandboxService

logger = logging.getLogger(__name__)


class RenewalScheduler:
    def __init__(self, sandbox_service: SandboxService) -> None:
        self._sandbox_service = sandbox_service
        self._scheduler = AsyncIOScheduler()

    async def _renewal_check(self) -> None:
        """Check all running sandboxes and renew those past the interval."""
        logger.info("Running renewal check")
        try:
            all_sandboxes = await self._sandbox_service.list_all()
        except Exception:
            logger.exception("Failed to list sandboxes for renewal")
            return

        now = datetime.utcnow()
        threshold = timedelta(hours=settings.renewal_interval_hours)

        for meta in all_sandboxes:
            if meta.state != "running":
                continue
            elapsed = now - meta.last_renewed_at
            if elapsed >= threshold:
                try:
                    await self._sandbox_service.renew(meta.sandbox_id)
                    logger.info("Renewed sandbox %s (elapsed %s)", meta.sandbox_id, elapsed)
                except Exception:
                    logger.exception("Failed to renew sandbox %s", meta.sandbox_id)

    def start(self) -> None:
        interval_minutes = settings.renewal_check_minutes
        self._scheduler.add_job(
            self._renewal_check,
            "interval",
            minutes=interval_minutes,
            id="sandbox_renewal",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("Renewal scheduler started (every %d min)", interval_minutes)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Renewal scheduler stopped")
