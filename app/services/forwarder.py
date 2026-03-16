from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

import httpx

from app.config import settings
from app.models.schemas import SenderInfo
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


# ── Handle normalization ─────────────────────────────────

_PREFIX_RE = re.compile(r"^(imessage|sms|auto):", re.IGNORECASE)


def normalize_handle(raw: str) -> str:
    """Normalize a BlueBubbles handle: strip prefixes, lowercase emails, strip phone whitespace."""
    s = raw.strip()
    # Recursively strip known prefixes
    while _PREFIX_RE.match(s):
        s = _PREFIX_RE.sub("", s, count=1)
    if "@" in s:
        return s.lower()
    return re.sub(r"\s+", "", s)


# ── Sender extraction ────────────────────────────────────


def _read_str(obj: Any, *keys: str) -> str:
    """Safely read a string value from nested dict keys."""
    if not isinstance(obj, dict):
        return ""
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _is_group_chat(chat_guid: str) -> bool:
    return ";+;" in chat_guid


def _extract_handle_from_chat_guid(chat_guid: str) -> str:
    parts = chat_guid.split(";")
    return ";".join(parts[2:]) if len(parts) >= 3 else ""


def extract_sender_info(payload: dict[str, Any]) -> SenderInfo:
    """Extract sender info from a BlueBubbles webhook payload."""
    # Handle nested data.message or flat payload
    data = payload.get("data", payload)
    if isinstance(data, dict) and "message" in data:
        msg = data["message"]
    else:
        msg = data
    if not isinstance(msg, dict):
        msg = {}

    handle = msg.get("handle")
    if isinstance(handle, dict):
        sender_id = _read_str(handle, "address", "handle", "id")
        sender_name = _read_str(handle, "displayName", "name") or None
    else:
        sender_id = ""
        sender_name = None

    if not sender_id:
        sender_id = _read_str(msg, "senderId", "sender", "from")
    if not sender_name:
        sender_name = _read_str(msg, "senderName") or None

    chat_guid = _read_str(msg, "chatGuid", "chat_guid", "chatId") or ""
    is_from_me = bool(msg.get("isFromMe", False))
    is_group = _is_group_chat(chat_guid) if chat_guid else False

    # Compute routing key
    if is_group and chat_guid:
        routing_key = f"chat_guid:{chat_guid}"
    elif is_from_me and chat_guid:
        extracted = _extract_handle_from_chat_guid(chat_guid)
        routing_key = normalize_handle(extracted) if extracted else chat_guid
    elif sender_id:
        routing_key = normalize_handle(sender_id)
    else:
        routing_key = chat_guid or ""

    return SenderInfo(
        sender_id=sender_id,
        sender_name=sender_name,
        chat_guid=chat_guid,
        is_group=is_group,
        is_from_me=is_from_me,
        routing_key=routing_key,
    )


# ── Forward to sandbox ───────────────────────────────────


async def forward_to_sandbox(
    sandbox_url: str,
    body: Any,
    sender_key: str,
    event_type: str | None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Fire-and-forget POST to sandbox URL. Returns result dict."""
    timeout_ms = timeout_ms or settings.forward_timeout_ms
    timeout_s = timeout_ms / 1000.0
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                sandbox_url,
                json=body if isinstance(body, dict) else {"payload": body},
                headers={
                    "X-Sender-Key": sender_key,
                    **({"X-Event-Type": event_type} if event_type else {}),
                },
            )
        latency_ms = round((time.monotonic() - start) * 1000)
        logger.info(
            "Forwarded to %s status=%d latency=%dms sender=%s",
            sandbox_url,
            resp.status_code,
            latency_ms,
            sender_key,
        )
        return {"ok": resp.is_success, "status_code": resp.status_code, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        logger.error("Forward failed to %s: %s (%dms)", sandbox_url, exc, latency_ms)
        return {"ok": False, "error": str(exc), "latency_ms": latency_ms}


# ── Unknown sender callback ──────────────────────────────

_notified_senders: set[str] = set()


async def notify_unknown_sender(
    sender_key: str,
    sender_id: str,
    chat_guid: str | None,
    is_group: bool,
) -> None:
    callback_url = settings.unknown_sender_callback_url
    if not callback_url:
        logger.debug("No unknown sender callback URL configured")
        return

    if sender_key in _notified_senders:
        return

    _notified_senders.add(sender_key)

    payload = {
        "senderKey": sender_key,
        "senderId": sender_id,
        "chatGuid": chat_guid or "",
        "isGroup": is_group,
        "timestamp": int(time.time()),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(callback_url, json=payload)
        if not resp.is_success:
            # Allow retry on next message
            _notified_senders.discard(sender_key)
            logger.warning("Unknown sender callback returned %d", resp.status_code)
        else:
            logger.info("Notified unknown sender: %s", sender_key)
    except Exception as exc:
        _notified_senders.discard(sender_key)
        logger.error("Unknown sender callback failed: %s", exc)
