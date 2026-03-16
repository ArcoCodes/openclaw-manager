from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class GatewayClient:
    def __init__(self) -> None:
        self._base_url = settings.gateway_base_url.rstrip("/")

    async def activate_token(self, email: str) -> str:
        """Call gateway POST /admin/v2/activate to get a session token."""
        url = f"{self._base_url}/admin/v2/activate"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"email": email},
                headers={"X-Admin-Key": settings.gateway_biz_key},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token") or data.get("data", {}).get("token", "")
            if not token:
                raise ValueError(f"No token in gateway response: {data}")
            logger.info("Activated gateway token for %s", email)
            return token
