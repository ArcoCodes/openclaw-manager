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

    async def _maintenance_check(self) -> None:
        """Single pass: idle-pause then renew for all running sandboxes."""
        logger.info("Running maintenance check")
        try:
            all_sandboxes = await self._sandbox_service.list_all()
        except Exception:
            logger.exception("Failed to list sandboxes for maintenance")
            return

        now = datetime.utcnow()
        idle_threshold = timedelta(minutes=settings.idle_timeout_minutes)
        renewal_threshold = timedelta(hours=settings.renewal_interval_hours)

        for meta in all_sandboxes:
            if meta.state != "running":
                continue

            last_active = self._sandbox_service.get_last_active(meta.sandbox_id)
            idle_duration = (now - last_active) if last_active else None

            # ── Idle check ──────────────────────────────────
            if idle_duration is not None and idle_duration >= idle_threshold:
                try:
                    if meta.apple_id:
                        await self._sandbox_service.backup(meta.sandbox_id)
                    await self._sandbox_service.pause(meta.sandbox_id)
                    self._sandbox_service._activity.pop(meta.sandbox_id, None)
                    logger.info(
                        "Auto-paused idle sandbox %s (idle %s)",
                        meta.sandbox_id, idle_duration,
                    )
                except Exception:
                    logger.exception(
                        "Failed to auto-pause sandbox %s", meta.sandbox_id,
                    )
                continue  # paused → skip renewal

            # ── Renewal check ───────────────────────────────
            if settings.renewal_enabled:
                elapsed = now - meta.last_renewed_at
                if elapsed >= renewal_threshold:
                    try:
                        await self._sandbox_service.renew(meta.sandbox_id)
                        logger.info(
                            "Renewed sandbox %s (elapsed %s)",
                            meta.sandbox_id, elapsed,
                        )
                    except Exception:
                        logger.exception("Failed to renew sandbox %s", meta.sandbox_id)

        # ── Flush activity timestamps to S3 ─────────────────
        try:
            await self._sandbox_service.flush_activity()
        except Exception:
            logger.exception("Failed to flush activity timestamps")

    async def _backup_check(self) -> None:
        """Backup all running sandboxes to S3."""
        logger.info("Running backup check")
        try:
            all_sandboxes = await self._sandbox_service.list_all()
        except Exception:
            logger.exception("Failed to list sandboxes for backup")
            return

        for meta in all_sandboxes:
            if meta.state != "running":
                continue
            if not meta.apple_id:
                continue
            try:
                await self._sandbox_service.backup(meta.sandbox_id)
                logger.info("Backed up sandbox %s", meta.sandbox_id)
            except Exception:
                logger.exception("Failed to backup sandbox %s", meta.sandbox_id)

    def start(self) -> None:
        interval_minutes = settings.renewal_check_minutes
        self._scheduler.add_job(
            self._maintenance_check,
            "interval",
            minutes=interval_minutes,
            id="sandbox_maintenance",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._backup_check,
            "interval",
            hours=settings.backup_interval_hours,
            id="sandbox_backup",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started (maintenance every %d min, backup every %d h)",
            interval_minutes,
            settings.backup_interval_hours,
        )

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
