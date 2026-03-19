from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from aiobotocore.session import get_session

from app.config import settings
from app.models.schemas import RouteMappings, SandboxIndex, SandboxMetadata

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._session = get_session()

    def _ctx(self):
        return self._session.create_client(
            "s3",
            region_name=settings.aws_region,
        )

    def _key(self, *parts: str) -> str:
        prefix = settings.s3_prefix.rstrip("/")
        return f"{prefix}/{'/'.join(parts)}"

    # ── helpers ──

    async def _get_json(self, key: str) -> Optional[dict[str, Any]]:
        async with self._ctx() as client:
            try:
                resp = await client.get_object(Bucket=settings.s3_bucket, Key=key)
                body = await resp["Body"].read()
                return json.loads(body)
            except client.exceptions.NoSuchKey:
                return None
            except Exception:
                logger.exception("S3 get failed: %s", key)
                return None

    async def _put_json(self, key: str, data: dict[str, Any]) -> None:
        async with self._ctx() as client:
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=json.dumps(data, default=str).encode(),
                ContentType="application/json",
            )

    # ── sandbox metadata ──

    async def get_sandbox(self, sandbox_id: str) -> Optional[SandboxMetadata]:
        key = self._key("sandboxes", f"{sandbox_id}.json")
        data = await self._get_json(key)
        if data is None:
            return None
        return SandboxMetadata(**data)

    async def put_sandbox(self, meta: SandboxMetadata) -> None:
        key = self._key("sandboxes", f"{meta.sandbox_id}.json")
        await self._put_json(key, meta.model_dump())

    async def delete_sandbox(self, sandbox_id: str) -> None:
        key = self._key("sandboxes", f"{sandbox_id}.json")
        async with self._ctx() as client:
            await client.delete_object(Bucket=settings.s3_bucket, Key=key)

    # ── sandbox index ──

    async def get_sandbox_index(self) -> SandboxIndex:
        key = self._key("sandboxes", "_index.json")
        data = await self._get_json(key)
        if data is None:
            return SandboxIndex()
        return SandboxIndex(**data)

    async def put_sandbox_index(self, index: SandboxIndex) -> None:
        index.updated_at = datetime.utcnow()
        key = self._key("sandboxes", "_index.json")
        await self._put_json(key, index.model_dump())

    async def add_to_index(self, sandbox_id: str) -> None:
        index = await self.get_sandbox_index()
        if sandbox_id not in index.sandbox_ids:
            index.sandbox_ids.append(sandbox_id)
            await self.put_sandbox_index(index)

    async def remove_from_index(self, sandbox_id: str) -> None:
        index = await self.get_sandbox_index()
        if sandbox_id in index.sandbox_ids:
            index.sandbox_ids.remove(sandbox_id)
            await self.put_sandbox_index(index)

    # ── route mappings ──

    async def get_route_mappings(self) -> RouteMappings:
        key = self._key("routes", "mappings.json")
        data = await self._get_json(key)
        if data is None:
            return RouteMappings()
        return RouteMappings(**data)

    async def put_route_mappings(self, mappings: RouteMappings) -> None:
        mappings.updated_at = datetime.utcnow()
        key = self._key("routes", "mappings.json")
        await self._put_json(key, mappings.model_dump())

    async def list_all_sandboxes(self) -> list[SandboxMetadata]:
        index = await self.get_sandbox_index()
        results: list[SandboxMetadata] = []
        for sid in index.sandbox_ids:
            meta = await self.get_sandbox(sid)
            if meta is not None:
                results.append(meta)
        return results

    # ── userdata backup ──

    async def upload_userdata(self, apple_id: str, data: bytes) -> None:
        key = self._key("userdata", f"{apple_id}.tar.gz")
        async with self._ctx() as client:
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType="application/gzip",
            )

    async def download_userdata(self, apple_id: str) -> Optional[bytes]:
        key = self._key("userdata", f"{apple_id}.tar.gz")
        async with self._ctx() as client:
            try:
                resp = await client.get_object(Bucket=settings.s3_bucket, Key=key)
                return await resp["Body"].read()
            except client.exceptions.NoSuchKey:
                return None
            except Exception:
                logger.exception("S3 get userdata failed: %s", key)
                return None

    async def has_userdata(self, apple_id: str) -> bool:
        key = self._key("userdata", f"{apple_id}.tar.gz")
        async with self._ctx() as client:
            try:
                await client.head_object(Bucket=settings.s3_bucket, Key=key)
                return True
            except Exception:
                return False
