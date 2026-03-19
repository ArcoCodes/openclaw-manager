from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx
from e2b_code_interpreter import Sandbox

from app.config import settings
from app.models.schemas import RouteEntry, SandboxMetadata
from app.services.gateway import GatewayClient
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


class SandboxService:
    def __init__(self, storage: StorageService, gateway: GatewayClient) -> None:
        self.storage = storage
        self.gateway = gateway
        self._activity: dict[str, datetime] = {}
        self._resume_locks: dict[str, asyncio.Lock] = {}

    # ── Activity tracking ────────────────────────────────────

    def record_activity(self, sandbox_id: str) -> None:
        """Update in-memory last-active timestamp."""
        self._activity[sandbox_id] = datetime.utcnow()

    def get_last_active(self, sandbox_id: str) -> datetime | None:
        return self._activity.get(sandbox_id)

    async def ensure_running(self, sandbox_id: str) -> SandboxMetadata:
        """If the sandbox is paused, resume it; otherwise return metadata."""
        lock = self._resume_locks.setdefault(sandbox_id, asyncio.Lock())
        async with lock:
            meta = await self.storage.get_sandbox(sandbox_id)
            if meta is None:
                raise ValueError(f"Sandbox {sandbox_id} not found")
            if meta.state == "paused":
                meta = await self.resume(sandbox_id)
            self.record_activity(sandbox_id)
            return meta

    async def flush_activity(self) -> None:
        """Batch-persist in-memory activity timestamps to S3 metadata."""
        for sandbox_id, last_active in list(self._activity.items()):
            try:
                meta = await self.storage.get_sandbox(sandbox_id)
                if meta is None:
                    continue
                meta.last_active_at = last_active
                await self.storage.put_sandbox(meta)
            except Exception:
                logger.exception("Failed to flush activity for %s", sandbox_id)

    async def init_activity_tracker(self) -> None:
        """Load last_active_at from S3 into memory on startup."""
        try:
            all_sandboxes = await self.list_all()
        except Exception:
            logger.exception("Failed to load sandboxes for activity tracker")
            return
        now = datetime.utcnow()
        for meta in all_sandboxes:
            if meta.state == "running":
                self._activity[meta.sandbox_id] = meta.last_active_at or now

    # ── CRUD ────────────────────────────────────────────────

    async def create(
        self,
        email: str,
        apple_id: str | None = None,
        template_id: str | None = None,
    ) -> SandboxMetadata:
        template = template_id or settings.e2b_template_id
        timeout = settings.e2b_sandbox_timeout
        port = settings.e2b_sandbox_port

        # 1. Get gateway token
        token = await self.gateway.activate_token(email)

        # 2. Create E2B sandbox (sync SDK → thread)
        sandbox = await asyncio.to_thread(
            Sandbox.create,
            template,
            timeout=timeout,
            envs={
                "AI_API_KEY": token,
                "AI_BASE_URL": settings.gateway_base_url,
                "BLUEBUBBLES_SERVER_URL": settings.bluebubbles_server_url,
                "BLUEBUBBLES_WEBHOOK_PATH": settings.bluebubbles_webhook_path,
                "BLUEBUBBLES_PASSWORD": settings.bluebubbles_password,
                "BLUEBUBBLES_ALLOW_FROM": apple_id or "",
            },
            api_key=settings.e2b_api_key,
        )

        sandbox_id = sandbox.sandbox_id

        # 3. Restore userdata backup if one exists
        if apple_id:
            backup_data = await self.storage.download_userdata(apple_id)
        else:
            backup_data = None
        if backup_data is not None:
            logger.info(
                "Restoring userdata backup for %s into sandbox %s (%d bytes)",
                apple_id, sandbox_id, len(backup_data),
            )
            upload_url = await asyncio.to_thread(
                sandbox.upload_url, "/tmp/userdata.tar.gz"
            )
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.put(upload_url, content=backup_data)
                resp.raise_for_status()
            await asyncio.to_thread(
                sandbox.commands.run,
                "tar xzf /tmp/userdata.tar.gz -C /home/user",
                timeout=120,
            )
            logger.info("Userdata restored for %s", apple_id)

        # 4. Run setup.sh (baked into template) in background
        #    This overwrites config and plugins, which is expected.
        logger.info("Running setup.sh in sandbox %s", sandbox_id)
        await asyncio.to_thread(
            sandbox.commands.run,
            "bash /opt/setup.sh",
            background=True,
            timeout=300,
        )

        # 5. Get public URL
        public_url = f"https://{sandbox.get_host(port)}"

        now = datetime.utcnow()
        meta = SandboxMetadata(
            sandbox_id=sandbox_id,
            owner_email=email,
            apple_id=apple_id,
            gateway_token=token,
            public_url=public_url,
            state="running",
            template_id=template,
            created_at=now,
            last_renewed_at=now,
        )

        # 6. Persist to S3
        await self.storage.put_sandbox(meta)
        await self.storage.add_to_index(sandbox_id)

        # 7. Update route mapping if apple_id provided
        if apple_id:
            await self._set_route(meta)

        self.record_activity(sandbox_id)
        logger.info("Created sandbox %s for %s", sandbox_id, email)
        return meta

    async def get(self, sandbox_id: str) -> SandboxMetadata | None:
        return await self.storage.get_sandbox(sandbox_id)

    async def list_all(self) -> list[SandboxMetadata]:
        return await self.storage.list_all_sandboxes()

    async def pause(self, sandbox_id: str) -> SandboxMetadata:
        meta = await self.storage.get_sandbox(sandbox_id)
        if meta is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox = await asyncio.to_thread(
            Sandbox.connect, sandbox_id, api_key=settings.e2b_api_key
        )
        await asyncio.to_thread(sandbox.pause)

        meta.state = "paused"
        await self.storage.put_sandbox(meta)

        # Update route mapping state
        if meta.apple_id:
            await self._set_route(meta, state="paused")

        logger.info("Paused sandbox %s", sandbox_id)
        return meta

    async def resume(self, sandbox_id: str) -> SandboxMetadata:
        meta = await self.storage.get_sandbox(sandbox_id)
        if meta is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox = await asyncio.to_thread(
            Sandbox.connect, sandbox_id, api_key=settings.e2b_api_key
        )
        await asyncio.to_thread(sandbox.set_timeout, settings.e2b_sandbox_timeout)

        # Refresh public URL
        port = settings.e2b_sandbox_port
        public_url = f"https://{sandbox.get_host(port)}"

        meta.state = "running"
        meta.public_url = public_url
        meta.last_renewed_at = datetime.utcnow()
        await self.storage.put_sandbox(meta)

        # Update route mapping
        if meta.apple_id:
            await self._set_route(meta)

        logger.info("Resumed sandbox %s", sandbox_id)
        return meta

    async def kill(self, sandbox_id: str) -> SandboxMetadata:
        meta = await self.storage.get_sandbox(sandbox_id)
        if meta is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        try:
            sandbox = await asyncio.to_thread(
                Sandbox.connect, sandbox_id, api_key=settings.e2b_api_key
            )
            await asyncio.to_thread(sandbox.kill)
        except Exception:
            logger.warning("Failed to kill sandbox %s (may already be dead)", sandbox_id)

        meta.state = "killed"
        await self.storage.put_sandbox(meta)
        await self.storage.remove_from_index(sandbox_id)

        # Remove route mapping
        if meta.apple_id:
            await self._remove_route(meta.apple_id)

        # Clean up in-memory tracking
        self._activity.pop(sandbox_id, None)
        self._resume_locks.pop(sandbox_id, None)

        logger.info("Killed sandbox %s", sandbox_id)
        return meta

    async def renew(self, sandbox_id: str) -> SandboxMetadata:
        """Pause then resume to reset E2B 24h timeout."""
        logger.info("Renewing sandbox %s", sandbox_id)
        await self.pause(sandbox_id)
        return await self.resume(sandbox_id)

    async def backup(self, sandbox_id: str) -> SandboxMetadata:
        """Tar the sandbox user-data dir and upload to S3."""
        meta = await self.storage.get_sandbox(sandbox_id)
        if meta is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        if not meta.apple_id:
            raise ValueError(f"Sandbox {sandbox_id} has no apple_id, cannot backup")

        logger.info("Backing up sandbox %s (apple_id=%s)", sandbox_id, meta.apple_id)

        # 1. Connect to the running sandbox
        sandbox = await asyncio.to_thread(
            Sandbox.connect, sandbox_id, api_key=settings.e2b_api_key
        )

        # 2. Tar the user-data directory
        sandbox_dir = settings.backup_sandbox_dir
        parent = sandbox_dir.rsplit("/", 1)[0] if "/" in sandbox_dir else "/"
        dirname = sandbox_dir.rsplit("/", 1)[-1]
        result = await asyncio.to_thread(
            sandbox.commands.run,
            f"tar czf /tmp/userdata.tar.gz -C {parent} {dirname}",
            timeout=120,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"tar failed (exit {result.exit_code}): {result.stderr}"
            )

        # 3. Download the tarball from the sandbox
        download_url = await asyncio.to_thread(
            sandbox.download_url, "/tmp/userdata.tar.gz"
        )
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            data = resp.content

        # 4. Upload to S3 keyed by apple_id
        await self.storage.upload_userdata(meta.apple_id, data)

        # 5. Update metadata
        meta.last_backed_up_at = datetime.utcnow()
        await self.storage.put_sandbox(meta)

        logger.info(
            "Backup complete for sandbox %s (%d bytes)", sandbox_id, len(data)
        )
        return meta

    async def _set_route(
        self, meta: SandboxMetadata, *, state: str = "running",
    ) -> None:
        if not meta.apple_id:
            return
        mappings = await self.storage.get_route_mappings()
        mappings.mappings[meta.apple_id] = RouteEntry(
            apple_id=meta.apple_id,
            sandbox_id=meta.sandbox_id,
            sandbox_url=meta.public_url,
            owner_email=meta.owner_email,
            sandbox_state=state,
        )
        await self.storage.put_route_mappings(mappings)

    async def _remove_route(self, apple_id: str) -> None:
        mappings = await self.storage.get_route_mappings()
        mappings.mappings.pop(apple_id, None)
        await self.storage.put_route_mappings(mappings)
