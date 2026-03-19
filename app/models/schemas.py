from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Sandbox ──────────────────────────────────────────────


class SandboxCreateRequest(BaseModel):
    email: str
    apple_id: Optional[str] = None
    template_id: Optional[str] = None


class SandboxMetadata(BaseModel):
    sandbox_id: str
    owner_email: str
    apple_id: Optional[str] = None
    gateway_token: str
    public_url: str
    state: str = "running"
    template_id: str = "base"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_renewed_at: datetime = Field(default_factory=datetime.utcnow)
    last_backed_up_at: Optional[datetime] = None


class SandboxIndex(BaseModel):
    sandbox_ids: list[str] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SandboxResponse(BaseModel):
    sandbox_id: str
    owner_email: str
    apple_id: Optional[str] = None
    public_url: str
    state: str
    template_id: str
    created_at: datetime
    last_renewed_at: datetime
    last_backed_up_at: Optional[datetime] = None


# ── Routes ───────────────────────────────────────────────


class RouteEntry(BaseModel):
    apple_id: str
    sandbox_id: str
    sandbox_url: str
    owner_email: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RouteMappings(BaseModel):
    version: int = 1
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    mappings: dict[str, RouteEntry] = {}


class RouteUpdateRequest(BaseModel):
    apple_id: str
    sandbox_id: str
    sandbox_url: str
    owner_email: str


# ── Webhook ──────────────────────────────────────────────


class SenderInfo(BaseModel):
    sender_id: str
    sender_name: Optional[str] = None
    chat_guid: Optional[str] = None
    is_group: bool = False
    is_from_me: bool = False
    routing_key: str


# ── Cron Stub ────────────────────────────────────────────


class CronJobCreateRequest(BaseModel):
    name: str
    schedule: Optional[str] = None
    payload: Optional[dict] = None


class CronJobStubResponse(BaseModel):
    status: str = "stub"
    message: str = "Not yet implemented"
