"""Versioned tenant knowledge is background material, separate from Case evidence."""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import update

from tradecase.platform import db as m
from tradecase.platform.services import ServiceError


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=100000)
    scope: str = Field(default="product", pattern=r"^(product|rules|business|email)$")
    valid_until: datetime
    expected_version: int = Field(default=0, ge=0)

    @field_validator("valid_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Validity requires timezone")
        return value


class KnowledgeService:
    def __init__(self, service):
        self.service = service
        self.db = service.db

    def put(self, actor, request: KnowledgeInput):
        self.service.require(actor, "admin", "reviewer")
        if request.valid_until <= m.utcnow():
            raise ServiceError("Knowledge validity must be in the future", 422)
        obj = self.service.storage.put(request.content.encode())
        with self.db.session() as s:
            tenant = actor["tenant_id"]
            # A bounded index in organization settings; object contents are immutable.
            s.execute(update(m.Organization).where(m.Organization.id == tenant).values(name=m.Organization.name))
            org = s.get(m.Organization, tenant)
            entries = list(org.data.get("knowledge", []))
            identity = request.document_id or m.uid()
            previous = [e for e in entries if e["id"] == identity]
            version = max((e["version"] for e in previous), default=0)
            if version != request.expected_version:
                raise ServiceError("Knowledge changed; reload its latest version")
            if len(entries) >= 1000:
                raise ServiceError("Knowledge index limit reached; archive unused versions first")
            entry = {
                "id": identity,
                "title": request.title,
                "scope": request.scope,
                "version": version + 1,
                "content_hash": obj.sha256,
                "storage_ref": obj.key,
                "valid_until": request.valid_until.isoformat(),
                "created_at": m.utcnow().isoformat(),
                "created_by": actor["id"],
                "authority": "user_provided_unverified",
            }
            entries.append(entry)
            org.data = {**org.data, "knowledge": entries}
            self.service.event(s, tenant, None, "knowledge.version", {"version": version + 1}, actor=actor["id"])
            return entry

    def list(self, tenant):
        with self.db.session() as s:
            org = s.get(m.Organization, tenant)
            if org is None:
                raise ServiceError("Resource not found", 404)
            return [
                {**e, "expired": datetime.fromisoformat(e["valid_until"]) <= m.utcnow()}
                for e in org.data.get("knowledge", [])
            ]

    def get(self, tenant, identity, version):
        row = next((e for e in self.list(tenant) if e["id"] == identity and e["version"] == version), None)
        if row is None:
            raise ServiceError("Resource not found", 404)
        raw = self.service.storage.get(row["storage_ref"])
        if hashlib.sha256(raw).hexdigest() != row["content_hash"]:
            raise ServiceError("Knowledge integrity check failed")
        return {**row, "content": raw.decode()}

    def search(self, tenant, query, limit=5):
        rows = self.list(tenant)
        latest = {}
        for row in rows:
            if row["id"] not in latest or row["version"] > latest[row["id"]]["version"]:
                latest[row["id"]] = row
        terms = set(query.casefold().split())
        matches = []
        for row in latest.values():
            if row["expired"]:
                continue
            item = self.get(tenant, row["id"], row["version"])
            haystack = (item["title"] + " " + item["content"]).casefold()
            score = sum(word in haystack for word in terms)
            if score:
                matches.append((score, item))
        return [item for _, item in sorted(matches, key=lambda x: x[0], reverse=True)[:limit]]
