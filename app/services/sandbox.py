from __future__ import annotations

import asyncio
import logging
from datetime import datetime

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

        # 3. Get public URL
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

        # 4. Persist to S3
        await self.storage.put_sandbox(meta)
        await self.storage.add_to_index(sandbox_id)

        # 5. Update route mapping if apple_id provided
        if apple_id:
            await self._set_route(meta)

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

        logger.info("Killed sandbox %s", sandbox_id)
        return meta

    async def renew(self, sandbox_id: str) -> SandboxMetadata:
        """Pause then resume to reset E2B 24h timeout."""
        logger.info("Renewing sandbox %s", sandbox_id)
        await self.pause(sandbox_id)
        return await self.resume(sandbox_id)

    async def _set_route(self, meta: SandboxMetadata) -> None:
        if not meta.apple_id:
            return
        mappings = await self.storage.get_route_mappings()
        mappings.mappings[meta.apple_id] = RouteEntry(
            apple_id=meta.apple_id,
            sandbox_id=meta.sandbox_id,
            sandbox_url=meta.public_url,
            owner_email=meta.owner_email,
        )
        await self.storage.put_route_mappings(mappings)

    async def _remove_route(self, apple_id: str) -> None:
        mappings = await self.storage.get_route_mappings()
        mappings.mappings.pop(apple_id, None)
        await self.storage.put_route_mappings(mappings)
