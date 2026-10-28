"""Human-supplied public snapshots; never labelled a successful online retrieval."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update

from tradecase.platform import db as m
from tradecase.platform.services import ServiceError, fingerprint
from tradecase.providers import validate_public_url


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_version: int = Field(ge=1)
    url: str = Field(min_length=1, max_length=4096)
    title: str = Field(min_length=1, max_length=500)
    captured_at: datetime
    text: str = Field(min_length=1, max_length=100000)
    excerpt: str = Field(min_length=1, max_length=4000)
    claim: str = Field(min_length=1, max_length=2000)

    @field_validator("captured_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("capture time requires timezone")
        return value


class SourceIntakeService:
    def __init__(self, service):
        self.service = service
        self.db = service.db

    def submit(self, actor, case_id, request: SourceInput, key):
        self.service.require(actor, "admin", "reviewer", "operator")
        validate_public_url(request.url)
        if request.captured_at > m.utcnow():
            raise ServiceError("Capture time cannot be in the future", 422)
        if request.excerpt not in request.text:
            raise ServiceError("Quotation must occur exactly in supplied snapshot", 422)
        obj = self.service.storage.put(request.text.encode())
        digest = fingerprint(request.model_dump(mode="json"))
        with self.db.session() as s:
            case = self.service.lock_case(s, actor["tenant_id"], case_id)
            replay = s.scalar(
                select(m.Source).where(
                    m.Source.tenant_id == case.tenant_id,
                    m.Source.case_id == case.id,
                    m.Source.data["intake_key"].as_string() == key,
                )
            )
            if replay:
                if replay.data.get("request_fingerprint") != digest:
                    raise ServiceError("Source idempotency payload mismatch")
                return {"source_id": replay.id, "case_version": replay.data["result_version"], "tested_live": False}
            if request.case_version != case.version:
                raise ServiceError("Case changed before snapshot import")
            self.service.ensure_no_outbound_inflight(s, case)
            if case.status == "CLOSED":
                raise ServiceError("Reopen the Case before importing additional evidence")
            if case.status == "RESEARCHING":
                raise ServiceError("Wait for running research before importing a snapshot")
            source = m.Source(
                id=m.uid(),
                tenant_id=case.tenant_id,
                case_id=case.id,
                fingerprint=fingerprint([request.url, obj.sha256, key]),
                url=request.url,
                title=request.title,
                source_type="other",
                captured_at=request.captured_at,
                license_status="UNCONFIRMED",
                status="FETCHED",
                snapshot_ref=obj.key,
                snapshot_hash=obj.sha256,
                data={
                    "authority": "manual_public_snapshot",
                    "retrieval_method": "human_uploaded_snapshot",
                    "tested_live": False,
                    "excerpt": request.excerpt,
                    "intake_key": key,
                    "request_fingerprint": digest,
                    "uploaded_by": actor["id"],
                    "result_version": case.version + 1,
                },
            )
            s.add(source)
            s.flush()
            claim = m.Claim(
                id=m.uid(),
                tenant_id=case.tenant_id,
                case_id=case.id,
                fingerprint=fingerprint([source.id, request.claim]),
                statement=request.claim,
                classification="UNKNOWN",
                status="UNVERIFIED",
                data={"authority": "user_supplied_claim"},
            )
            s.add(claim)
            s.flush()
            s.add(
                m.ClaimEvidenceLink(
                    tenant_id=case.tenant_id,
                    case_id=case.id,
                    claim_id=claim.id,
                    source_id=source.id,
                    relation="supports",
                    excerpt=request.excerpt,
                    data={"reviewed": False},
                )
            )
            case.version += 1
            case.data = {
                **case.data,
                "research_status": "PARTIAL",
                "quality_passed": False,
                "previous_review_inputs_ref": case.data.get("review_inputs_ref"),
                "review_inputs_ref": None,
                "assessment": None,
            }
            case.priority = 0
            s.execute(
                update(m.Approval)
                .where(
                    m.Approval.tenant_id == case.tenant_id,
                    m.Approval.case_id == case.id,
                    m.Approval.status.in_(["PENDING", "APPROVED"]),
                )
                .values(status="INVALIDATED")
            )
            if case.workflow_run_id:
                run = self.service.scoped(s, m.WorkflowRun, case.tenant_id, case.workflow_run_id)
                run.status = "CANCELLED"
                run.lease_token = None
                run.lease_until = None
                case.workflow_run_id = None
            s.execute(
                update(m.Task)
                .where(
                    m.Task.tenant_id == case.tenant_id,
                    m.Task.case_id == case.id,
                    m.Task.status.in_(["PENDING", "READY", "WAITING_HUMAN", "BLOCKED"]),
                )
                .values(status="CANCELLED")
            )
            if case.status not in {"NEW", "FAILED"}:
                self.service.transition(s, case, "NEEDS_REVIEW")
            self.service.event(
                s, case.tenant_id, case.id, "source.imported", {"version": case.version}, actor=actor["id"]
            )
            return {"source_id": source.id, "claim_id": claim.id, "case_version": case.version, "tested_live": False}
