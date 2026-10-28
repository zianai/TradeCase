"""Tenant/permission-scoped cache and in-flight deduplication for read-only source fetches."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from tradecase.platform.db import Base, UTCDateTime, uid, utcnow
from tradecase.platform.services import fingerprint


class SourceCache(Base):
    __tablename__ = "source_cache"
    __table_args__ = (UniqueConstraint("tenant_id", "cache_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64))
    object_ref: Mapped[str | None] = mapped_column(String(300))
    expires_at: Mapped[object | None] = mapped_column(UTCDateTime())
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime())
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceCacheService:
    def __init__(self, service, ttl_seconds=3600):
        self.service = service
        self.db = service.db
        self.ttl = ttl_seconds

    def wrap(self, registry):
        original = registry.handlers["fetch_page"]

        async def cached(arguments, request):
            return await self.fetch(arguments, request, original)

        registry.handlers["fetch_page"] = cached

    async def fetch(self, arguments, request, fetcher):
        key = fingerprint(
            {
                "url": arguments.get("url"),
                "domains": sorted(request.allowed_domains),
                "policy_version": "public-read-v1",
            }
        )
        token = uid()
        claimed = False
        # The caller's ToolRegistry timeout bounds waiting for another in-flight fetch.
        while not claimed:
            now = utcnow()
            with self.db.session() as s:
                row = s.scalar(
                    select(SourceCache).where(SourceCache.tenant_id == request.tenant_id, SourceCache.cache_key == key)
                )
                if row is None:
                    try:
                        with s.begin_nested():
                            row = SourceCache(id=uid(), tenant_id=request.tenant_id, cache_key=key)
                            s.add(row)
                            s.flush()
                    except IntegrityError:
                        row = s.scalar(
                            select(SourceCache).where(
                                SourceCache.tenant_id == request.tenant_id, SourceCache.cache_key == key
                            )
                        )
                if row.object_ref and row.expires_at and row.expires_at > now:
                    result = json.loads(self.service.storage.get(row.object_ref))
                    return {**result, "cache_hit": True, "cache_expires_at": row.expires_at.isoformat()}
                changed = s.execute(
                    update(SourceCache)
                    .where(
                        SourceCache.id == row.id,
                        SourceCache.tenant_id == request.tenant_id,
                        or_(SourceCache.lease_until.is_(None), SourceCache.lease_until <= now),
                    )
                    .values(lease_token=token, lease_until=now + timedelta(seconds=request.budget.max_tool_seconds + 5))
                )
                claimed = changed.rowcount == 1
            if not claimed:
                await asyncio.sleep(0.05)
        try:
            result = await fetcher(arguments, request)
            obj = self.service.storage.put(json.dumps(result, sort_keys=True).encode())
            ttl = self.ttl if result.get("status") == "fetched" else 30
            with self.db.session() as s:
                s.execute(
                    update(SourceCache)
                    .where(
                        SourceCache.tenant_id == request.tenant_id,
                        SourceCache.cache_key == key,
                        SourceCache.lease_token == token,
                    )
                    .values(
                        object_ref=obj.key,
                        expires_at=utcnow() + timedelta(seconds=ttl),
                        lease_until=None,
                        lease_token=None,
                    )
                )
            return {**result, "cache_hit": False}
        except BaseException:
            with self.db.session() as s:
                s.execute(
                    update(SourceCache)
                    .where(
                        SourceCache.tenant_id == request.tenant_id,
                        SourceCache.cache_key == key,
                        SourceCache.lease_token == token,
                    )
                    .values(lease_until=None, lease_token=None)
                )
            raise
