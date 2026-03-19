from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.dependencies import sandbox_service, storage
from app.services.forwarder import (
    extract_sender_info,
    forward_to_sandbox,
    notify_unknown_sender,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _authenticate_bb(request: Request, body: dict[str, Any]) -> bool:
    """Validate BlueBubbles password from query params, headers, or body."""
    expected = settings.bluebubbles_password
    if not expected:
        return True  # No password configured → accept all

    # Check query params
    candidate = (
        request.query_params.get("password")
        or request.query_params.get("guid")
        or ""
    )
    if candidate and hmac.compare_digest(candidate, expected):
        return True

    # Check headers
    for header in ("x-password", "x-guid", "x-bluebubbles-guid", "authorization"):
        val = request.headers.get(header, "")
        if val and hmac.compare_digest(val, expected):
            return True

    return False


async def _resume_and_forward(
    sandbox_id: str,
    body: dict[str, Any],
    sender_key: str,
    event_type: str | None,
) -> None:
    """Resume a paused sandbox then forward the webhook payload."""
    try:
        meta = await sandbox_service.ensure_running(sandbox_id)
        await forward_to_sandbox(
            sandbox_url=meta.public_url,
            body=body,
            sender_key=sender_key,
            event_type=event_type,
        )
    except Exception:
        logger.exception("Resume-and-forward failed for sandbox %s", sandbox_id)


@router.post("/bluebubbles-webhook")
async def bluebubbles_webhook(request: Request):
    body = await request.json()

    if not _authenticate_bb(request, body):
        raise HTTPException(status_code=401, detail="Invalid BlueBubbles password")

    sender = extract_sender_info(body)
    event_type = body.get("type")

    if not sender.routing_key:
        return {"status": "ignored", "reason": "no routing key"}

    # Look up route
    mappings = await storage.get_route_mappings()
    route = mappings.mappings.get(sender.routing_key)

    if route:
        if route.sandbox_state == "paused":
            # Sandbox is paused — resume then forward
            asyncio.create_task(
                _resume_and_forward(
                    route.sandbox_id, body, sender.routing_key, event_type,
                )
            )
            return {"status": "resuming", "routingKey": sender.routing_key}
        else:
            # Running — record activity and forward
            sandbox_service.record_activity(route.sandbox_id)
            asyncio.create_task(
                forward_to_sandbox(
                    sandbox_url=route.sandbox_url,
                    body=body,
                    sender_key=sender.routing_key,
                    event_type=event_type,
                )
            )
            return {"status": "forwarded", "routingKey": sender.routing_key}

    # Unknown sender
    asyncio.create_task(
        notify_unknown_sender(
            sender_key=sender.routing_key,
            sender_id=sender.sender_id,
            chat_guid=sender.chat_guid,
            is_group=sender.is_group,
        )
    )
    return {"status": "unknown_sender", "routingKey": sender.routing_key}
