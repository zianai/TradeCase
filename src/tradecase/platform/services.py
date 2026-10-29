"""Tenant-scoped business authority, immutable artifacts and versioned decisions."""

from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from tradecase.ingestion import parse_inquiry
from tradecase.platform import db as m
from tradecase.platform.contracts import CreateCase, Decision, EditDraft, FollowUpInput
from tradecase.platform.inquiry_facts import inquiry_facts
from tradecase.platform.storage import configured_storage
from tradecase.upstream import claim_risk
from tradecase.util import json_bytes


class ServiceError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def fingerprint(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def redacted(data):
    # Event payloads intentionally carry IDs/counts/status only, never source prose.
    allowed = {
        "status",
        "version",
        "count",
        "task_type",
        "decision",
        "approval_id",
        "artifact_id",
        "error_class",
        "attempt",
        "scope",
        "synthetic",
        "workflow_run_id",
        "reason",
        "action_id",
    }
    return {k: v for k, v in data.items() if k in allowed and isinstance(v, (str, bool, int, float, type(None)))}


TRANSITIONS = {
    "NEW": {"RESEARCHING", "CLOSED"},
    "RESEARCHING": {"NEEDS_INPUT", "NEEDS_REVIEW", "FAILED", "CLOSED"},
    "NEEDS_INPUT": {"RESEARCHING", "NEEDS_REVIEW", "CLOSED"},
    "NEEDS_REVIEW": {"RESEARCHING", "NEEDS_INPUT", "READY_TO_FOLLOW_UP", "CLOSED", "FAILED"},
    "READY_TO_FOLLOW_UP": {"RESEARCHING", "NEEDS_REVIEW", "FOLLOW_UP_IN_PROGRESS", "CLOSED"},
    "FOLLOW_UP_IN_PROGRESS": {"RESEARCHING", "NEEDS_REVIEW", "READY_TO_FOLLOW_UP", "CLOSED"},
    "FAILED": {"RESEARCHING", "CLOSED"},
    "CLOSED": {"RESEARCHING"},
}


class CaseService:
    def __init__(self, db, settings, storage=None):
        self.db, self.settings = db, settings
        self.storage = storage or configured_storage(settings)

    def provision(self, tenant_id, name, role="admin", token=None):
        if role not in {"admin", "reviewer", "operator", "viewer"}:
            raise ServiceError("Invalid role", 422)
        token = token or secrets.token_urlsafe(40)
        if len(token) < 24:
            raise ServiceError("Credential must contain at least 24 characters", 422)
        with self.db.session() as s:
            if not s.get(m.Organization, tenant_id):
                s.add(m.Organization(id=tenant_id, name=tenant_id))
                s.flush()
            user = m.User(
                id=m.uid(),
                tenant_id=tenant_id,
                name=name,
                role=role,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
            s.add(user)
            s.flush()
            return m.row_dict(user), token

    def authenticate(self, token):
        if not token or len(token) > 512:
            raise ServiceError("Authentication required", 401)
        with self.db.session() as s:
            user = s.scalar(
                select(m.User).where(
                    m.User.token_hash == hashlib.sha256(token.encode()).hexdigest(), m.User.active.is_(True)
                )
            )
            if not user:
                raise ServiceError("Invalid credentials", 401)
            return {"id": user.id, "tenant_id": user.tenant_id, "role": user.role, "name": user.name}

    @staticmethod
    def require(actor, *roles):
        if actor["role"] not in roles:
            raise ServiceError("Role does not permit this action", 403)

    @staticmethod
    def scoped(s, cls, tenant, identity):
        row = s.scalar(select(cls).where(cls.tenant_id == tenant, cls.id == identity))
        if row is None:
            raise ServiceError("Resource not found", 404)
        return row

    def lock_case(self, s, tenant, case_id, version=None):
        conditions = [m.Case.tenant_id == tenant, m.Case.id == case_id]
        if version is not None:
            conditions.append(m.Case.version == version)
        # A write lock works for both SQLite and PostgreSQL, unlike SELECT FOR UPDATE on SQLite.
        result = s.execute(update(m.Case).where(*conditions).values(updated_at=m.utcnow()))
        if result.rowcount != 1:
            if s.scalar(select(m.Case.id).where(m.Case.tenant_id == tenant, m.Case.id == case_id)) is None:
                raise ServiceError("Resource not found", 404)
            raise ServiceError("Case changed; reload before applying this action")
        return self.scoped(s, m.Case, tenant, case_id)

    def event(self, s, tenant, case_id, kind, data=None, actor="system", **refs):
        s.add(
            m.EventLog(tenant_id=tenant, case_id=case_id, event_type=kind, data_redacted=redacted(data or {}), **refs)
        )
        s.add(
            m.AuditLog(
                tenant_id=tenant, case_id=case_id, actor_id=actor, action=kind, data_redacted=redacted(data or {})
            )
        )

    def transition(self, s, case, status):
        if case.status != status and status not in TRANSITIONS.get(case.status, set()):
            raise ServiceError(f"Illegal Case transition: {case.status} -> {status}")
        if case.status != status:
            case.status = status
            self.event(s, case.tenant_id, case.id, "case.status", {"status": status, "version": case.version})

    def create(self, actor, request: CreateCase, key: str, raw_bytes: bytes | None = None):
        self.require(actor, "admin", "operator", "reviewer")
        tenant = actor["tenant_id"]
        digest = fingerprint(
            {
                "request": request.model_dump(mode="json"),
                "raw_bytes_hash": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None,
            }
        )
        if request.fixture and not self.settings.demo_enabled:
            raise ServiceError("Synthetic fixtures are disabled in this deployment", 403)
        with self.db.session() as s:
            existing = s.scalar(select(m.Case).where(m.Case.tenant_id == tenant, m.Case.idempotency_key == key))
            if existing:
                if existing.input_fingerprint != digest:
                    raise ServiceError("Idempotency-Key was already used for different content")
                return self._case_dict(s, existing)
        case_id = m.uid()
        raw = raw_bytes if raw_bytes is not None else request.raw_content.encode()
        if not raw and not request.fixture:
            raise ServiceError("Inquiry content is required", 422)
        if len(raw) > self.settings.max_upload_bytes:
            raise ServiceError("Upload exceeds limit", 413)
        if request.fixture:
            fixture = self.fixture_path(request.fixture)
            data = json.loads((fixture / "fixture.json").read_text())
            raw = json_bytes(data["inquiry"])
            suffix = ".json"
        else:
            suffix = ".eml" if request.source_type == "eml" else ".txt"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / ("inquiry" + suffix)
            path.write_bytes(raw)
            inquiry = parse_inquiry(
                path,
                case_id,
                buyer_email=request.buyer_email,
                buyer_company_hint=request.buyer_company,
                target_country=request.buyer_country,
                product_summary=request.product,
                buyer_website_hint=request.website,
                platform=request.platform,
            )
        obj = self.storage.put(raw)
        domain = (inquiry.buyer_email or "").rpartition("@")[2].lower() or None
        try:
            with self.db.session() as s:
                row = m.Inquiry(
                    id=m.uid(),
                    tenant_id=tenant,
                    source_type=request.source_type,
                    raw_content_ref=obj.key,
                    raw_hash=obj.sha256,
                    data=inquiry.model_dump(mode="json"),
                )
                s.add(row)
                s.flush()
                case = m.Case(
                    id=case_id,
                    tenant_id=tenant,
                    inquiry_id=row.id,
                    title=request.title,
                    idempotency_key=key,
                    input_fingerprint=digest,
                    data={
                        "fixture": request.fixture,
                        "synthetic": bool(request.fixture),
                        "domain": domain,
                        "research_status": "UNKNOWN",
                    },
                )
                s.add(case)
                s.flush()
                self.event(s, tenant, case.id, "case.created", {"synthetic": bool(request.fixture)}, actor=actor["id"])
                return self._case_dict(s, case)
        except IntegrityError:
            with self.db.session() as s:
                row = s.scalar(select(m.Case).where(m.Case.tenant_id == tenant, m.Case.idempotency_key == key))
                if row and row.input_fingerprint == digest:
                    return self._case_dict(s, row)
            raise ServiceError("Conflicting Case creation") from None

    @staticmethod
    def fixture_path(name):
        # Fixture name has an enum allowlist at the request boundary. Never accept paths.
        return Path(__file__).resolve().parents[3] / "fixtures" / name

    def _case_dict(self, s, row):
        result = m.row_dict(row)
        inquiry = self.scoped(s, m.Inquiry, row.tenant_id, row.inquiry_id)
        result["inquiry"] = inquiry.data
        result["inquiry_facts"] = inquiry_facts(inquiry.data)
        result["synthetic"] = row.data.get("synthetic", False)
        result["research_status"] = row.data.get("research_status", "UNKNOWN")
        result["outbound_enabled"] = self.settings.outbound_enabled
        result["assessment"] = row.data.get("assessment")
        result["conflicts"] = row.data.get("conflicts", [])
        return result

    def get(self, tenant, case_id):
        with self.db.session() as s:
            return self._case_dict(s, self.scoped(s, m.Case, tenant, case_id))

    def list(self, tenant, query="", status=None, tag=None, limit=100, offset=0):
        with self.db.session() as s:
            stmt = select(m.Case).where(m.Case.tenant_id == tenant)
            if query:
                pattern = "%" + query.replace("%", "").replace("_", "") + "%"
                stmt = stmt.join(
                    m.Inquiry, (m.Inquiry.id == m.Case.inquiry_id) & (m.Inquiry.tenant_id == m.Case.tenant_id)
                ).where(
                    or_(
                        m.Case.title.ilike(pattern),
                        m.Inquiry.data["buyer_company_hint"].as_string().ilike(pattern),
                        m.Inquiry.data["buyer_email"].as_string().ilike(pattern),
                        m.Inquiry.data["product_summary"].as_string().ilike(pattern),
                    )
                )
            if status:
                stmt = stmt.where(m.Case.status == status)
            rows = s.scalars(
                stmt.order_by(m.Case.priority.desc(), m.Case.created_at.desc()).limit(limit).offset(offset)
            )
            return [self._case_dict(s, r) for r in rows if not tag or tag in r.tags]

    def rows(self, tenant, case_id, cls):
        with self.db.session() as s:
            self.scoped(s, m.Case, tenant, case_id)
            return [
                m.row_dict(r) for r in s.scalars(select(cls).where(cls.tenant_id == tenant, cls.case_id == case_id))
            ]

    def evidence(self, tenant, case_id):
        claims = self.rows(tenant, case_id, m.Claim)
        sources = self.rows(tenant, case_id, m.Source)
        links = self.rows(tenant, case_id, m.ClaimEvidenceLink)
        for c in claims:
            c["text"] = c["statement"]
            c["kind"] = c["classification"]
            c["source_ids"] = [x["source_id"] for x in links if x["claim_id"] == c["id"]]
        for x in sources:
            x["excerpt"] = x["data"].get("excerpt", "")
            x["snapshot_url"] = f"/api/cases/{case_id}/sources/{x['id']}/snapshot"
        return {"claims": claims, "sources": sources, "links": links}

    def source_body(self, tenant, case_id, source_id):
        with self.db.session() as s:
            src = self.scoped(s, m.Source, tenant, source_id)
            if src.case_id != case_id:
                raise ServiceError("Resource not found", 404)
            if not src.snapshot_ref:
                raise ServiceError("Source snapshot unavailable", 404)
            raw = self.storage.get(src.snapshot_ref)
            if hashlib.sha256(raw).hexdigest() != src.snapshot_hash:
                raise ServiceError("Snapshot integrity failure", 409)
            return raw

    def save_artifact(self, s, case, kind, content, data=None):
        raw = content.encode() if isinstance(content, str) else json_bytes(content)
        obj = self.storage.put(raw)
        artifact = s.scalar(
            select(m.Artifact).where(
                m.Artifact.tenant_id == case.tenant_id, m.Artifact.case_id == case.id, m.Artifact.kind == kind
            )
        )
        if artifact is None:
            artifact = m.Artifact(id=m.uid(), tenant_id=case.tenant_id, case_id=case.id, kind=kind, current_version=0)
            s.add(artifact)
            s.flush()
        latest = s.scalar(
            select(m.ArtifactVersion).where(
                m.ArtifactVersion.artifact_id == artifact.id,
                m.ArtifactVersion.tenant_id == case.tenant_id,
                m.ArtifactVersion.version == artifact.current_version,
            )
        )
        if latest and latest.content_hash == obj.sha256:
            return latest
        artifact.current_version += 1
        version = m.ArtifactVersion(
            id=m.uid(),
            tenant_id=case.tenant_id,
            case_id=case.id,
            artifact_id=artifact.id,
            version=artifact.current_version,
            content_hash=obj.sha256,
            storage_ref=obj.key,
            input_fingerprint=str(case.version),
            data=data or {},
        )
        s.add(version)
        s.flush()
        self.event(
            s, case.tenant_id, case.id, "artifact.version", {"artifact_id": artifact.id, "version": version.version}
        )
        return version

    def current_artifact(self, s, tenant, case_id, kind):
        artifact = s.scalar(
            select(m.Artifact).where(
                m.Artifact.tenant_id == tenant, m.Artifact.case_id == case_id, m.Artifact.kind == kind
            )
        )
        if artifact is None:
            raise ServiceError("Artifact not ready", 409)
        return s.scalar(
            select(m.ArtifactVersion).where(
                m.ArtifactVersion.tenant_id == tenant,
                m.ArtifactVersion.artifact_id == artifact.id,
                m.ArtifactVersion.version == artifact.current_version,
            )
        )

    def artifacts(self, tenant, case_id):
        with self.db.session() as s:
            self.scoped(s, m.Case, tenant, case_id)
            kinds = {
                a.id: a.kind
                for a in s.scalars(
                    select(m.Artifact).where(m.Artifact.tenant_id == tenant, m.Artifact.case_id == case_id)
                )
            }
            rows = s.scalars(
                select(m.ArtifactVersion)
                .where(m.ArtifactVersion.tenant_id == tenant, m.ArtifactVersion.case_id == case_id)
                .order_by(m.ArtifactVersion.created_at)
            )
            return [
                {
                    **m.row_dict(v),
                    "kind": kinds[v.artifact_id],
                    "hash": v.content_hash,
                    "content": self.storage.get(v.storage_ref).decode("utf-8"),
                }
                for v in rows
            ]

    def prepare_approval(self, s, case, scope="draft_review", data=None):
        version = self.current_artifact(s, case.tenant_id, case.id, "draft")
        existing = s.scalar(
            select(m.Approval).where(
                m.Approval.tenant_id == case.tenant_id,
                m.Approval.artifact_version_id == version.id,
                m.Approval.action_scope == scope,
                m.Approval.case_version == case.version,
            )
        )
        if existing:
            return existing
        row = m.Approval(
            id=m.uid(),
            tenant_id=case.tenant_id,
            case_id=case.id,
            artifact_version_id=version.id,
            artifact_hash=version.content_hash,
            case_version=case.version,
            action_scope=scope,
            expires_at=m.utcnow() + timedelta(days=7),
            data=data or {},
        )
        s.add(row)
        s.flush()
        self.event(s, case.tenant_id, case.id, "approval.requested", {"approval_id": row.id, "scope": scope})
        return row

    def approvals(self, tenant):
        with self.db.session() as s:
            return [
                {**m.row_dict(a), "scope": a.action_scope}
                for a in s.scalars(
                    select(m.Approval)
                    .where(m.Approval.tenant_id == tenant)
                    .order_by(m.Approval.created_at.desc())
                    .limit(300)
                )
            ]

    def validate_approval(self, s, case, approval, scope=None):
        version = self.current_artifact(s, case.tenant_id, case.id, "draft")
        if (
            approval.case_id != case.id
            or approval.tenant_id != case.tenant_id
            or approval.case_version != case.version
            or approval.artifact_hash != version.content_hash
            or approval.artifact_version_id != version.id
            or (approval.expires_at and approval.expires_at <= m.utcnow())
            or (scope and approval.action_scope != scope)
        ):
            raise ServiceError("Approval is stale, expired or outside this action scope")
        # Verify actual immutable object bytes, not just persisted hash metadata.
        if hashlib.sha256(self.storage.get(version.storage_ref)).hexdigest() != version.content_hash:
            raise ServiceError("Artifact integrity failure")
        return version

    def decide(self, actor, approval_id, request: Decision, key):
        self.require(actor, "admin", "reviewer")
        tenant = actor["tenant_id"]
        decision = {"approve": "approved", "reject": "rejected"}.get(request.decision, request.decision)
        digest = fingerprint(request.model_dump(mode="json"))
        with self.db.session() as s:
            approval = self.scoped(s, m.Approval, tenant, approval_id)
            case = self.lock_case(s, tenant, approval.case_id)
            s.refresh(approval)
            if approval.idempotency_key == key:
                if approval.data.get("decision_fingerprint") != digest:
                    raise ServiceError("Idempotency payload mismatch")
                return m.row_dict(approval)
            if approval.status != "PENDING":
                raise ServiceError("Approval already decided or invalidated")
            self.validate_approval(s, case, approval)
            if request.case_version != case.version or request.artifact_hash != approval.artifact_hash:
                raise ServiceError("Approval version mismatch")
            if approval.action_scope == "draft_review":
                self.ensure_no_outbound_inflight(s, case)
            if decision == "approved" and not case.data.get("quality_passed", False):
                raise ServiceError("Draft failed deterministic quality checks; revise first")
            if decision == "approved" and approval.action_scope in {"mail_send", "crm_sync"}:
                self.require_reviewed_draft(s, case)
                if case.data.get("research_status") != "COMPLETE" or case.data.get("unresolved_risks", True):
                    raise ServiceError("Unresolved evidence or compliance blocks external writes")
            if approval.action_scope == "draft_review" and decision != "approved":
                # Close authorization before releasing the Case lock or waking the
                # revision worker. Its later artifact update is a separate transaction.
                s.execute(
                    update(m.Approval)
                    .where(
                        m.Approval.tenant_id == tenant,
                        m.Approval.case_id == case.id,
                        m.Approval.action_scope.in_(["mail_send", "crm_sync"]),
                        m.Approval.status.in_(["PENDING", "APPROVED"]),
                    )
                    .values(status="INVALIDATED")
                )
            approval.status = (
                "APPROVED" if decision == "approved" else "REJECTED" if decision == "rejected" else "CHANGES_REQUESTED"
            )
            approval.decision = decision
            approval.reviewer_id = actor["id"]
            approval.decided_at = m.utcnow()
            approval.idempotency_key = key
            approval.revision += 1
            approval.data = {**approval.data, "comment": request.comment, "decision_fingerprint": digest}
            self.event(
                s,
                tenant,
                case.id,
                "approval.decided",
                {"decision": decision, "approval_id": approval.id},
                actor=actor["id"],
            )
            return m.row_dict(approval)

    def require_reviewed_draft(self, s, case):
        version = self.current_artifact(s, case.tenant_id, case.id, "draft")
        review = s.scalar(
            select(m.Approval).where(
                m.Approval.tenant_id == case.tenant_id,
                m.Approval.case_id == case.id,
                m.Approval.action_scope == "draft_review",
                m.Approval.case_version == case.version,
                m.Approval.artifact_version_id == version.id,
                m.Approval.status == "APPROVED",
                m.Approval.decision == "approved",
            )
        )
        if review is None:
            raise ServiceError("Current draft review must be approved before external authorization", 403)
        self.validate_approval(s, case, review, "draft_review")

    def ensure_no_outbound_inflight(self, s, case):
        active = s.scalar(
            select(m.OutboundAction.id).where(
                m.OutboundAction.tenant_id == case.tenant_id,
                m.OutboundAction.case_id == case.id,
                m.OutboundAction.status.in_(["DISPATCHING", "DELIVERY_UNCERTAIN"]),
            )
        )
        if active:
            raise ServiceError("Outbound delivery must finish or be reconciled before changing this Case")

    def edit_draft(self, actor, case_id, request: EditDraft):
        self.require(actor, "admin", "reviewer", "operator")
        with self.db.session() as s:
            case = self.lock_case(s, actor["tenant_id"], case_id, request.case_version)
            self.ensure_no_outbound_inflight(s, case)
            if case.status == "RESEARCHING":
                raise ServiceError("Wait for running workflow before editing")
            old = self.current_artifact(s, case.tenant_id, case.id, "draft")
            draft = json.loads(self.storage.get(old.storage_ref))
            draft.update(subject=request.subject, body_text=request.body)
            review_reasons, blocks, actions = [], [], []
            claim_risk(draft, review_reasons, blocks, actions)
            quality = not blocks and not review_reasons
            case.version += 1
            case.data = {**case.data, "quality_passed": quality}
            version = self.save_artifact(s, case, "draft", draft, {"edited_by": actor["id"], "quality_passed": quality})
            s.execute(
                update(m.Approval)
                .where(
                    m.Approval.tenant_id == case.tenant_id,
                    m.Approval.case_id == case.id,
                    m.Approval.status.in_(["PENDING", "APPROVED"]),
                )
                .values(status="INVALIDATED")
            )
            # Invalidated reviews must not remain actionable waiting tasks.
            obsolete = list(s.scalars(select(m.Task).where(
                m.Task.tenant_id == case.tenant_id,
                m.Task.case_id == case.id,
                m.Task.task_type == "prepare_approval",
                m.Task.status == "WAITING_HUMAN",
            )))
            for task in obsolete:
                approval_id = (task.result or {}).get("approval_id")
                if approval_id:
                    approval = self.scoped(s, m.Approval, case.tenant_id, approval_id)
                    if approval.status == "INVALIDATED":
                        task.status = "CANCELLED"
                        self.event(s, case.tenant_id, case.id, "task.cancelled",
                                   {"reason": "approval_invalidated"}, actor=actor["id"], task_id=task.id)
            self.transition(s, case, "NEEDS_REVIEW")
            self.prepare_approval(s, case)
            # Re-enter same workflow from a new approval preparation checkpoint via coordinator.
            if case.workflow_run_id:
                run = self.scoped(s, m.WorkflowRun, case.tenant_id, case.workflow_run_id)
                run.data = {**run.data, "refresh_approval": True}
                run.status = "PENDING"
            self.event(s, case.tenant_id, case.id, "draft.edited", {"version": case.version}, actor=actor["id"])
            return {
                "id": version.id,
                "hash": version.content_hash,
                "version": version.version,
                "case_version": case.version,
            }

    def followups(self, tenant):
        with self.db.session() as s:
            return [
                m.row_dict(r)
                for r in s.scalars(
                    select(m.FollowUp).where(m.FollowUp.tenant_id == tenant).order_by(m.FollowUp.due_at).limit(500)
                )
            ]

    def add_followup(self, actor, case_id, request: FollowUpInput, key):
        self.require(actor, "admin", "reviewer", "operator")
        with self.db.session() as s:
            case = self.lock_case(s, actor["tenant_id"], case_id)
            return m.row_dict(
                self.ensure_followup(s, case, request.next_action, key, request.assignee or actor["id"], request.due_at)
            )

    def ensure_followup(self, s, case, action, key, assignee=None, due_at=None):
        fp = fingerprint(key)
        row = s.scalar(
            select(m.FollowUp).where(
                m.FollowUp.tenant_id == case.tenant_id, m.FollowUp.case_id == case.id, m.FollowUp.fingerprint == fp
            )
        )
        requested = fingerprint([action, assignee, due_at.isoformat() if due_at else None])
        if row:
            if row.data.get("request_fingerprint") != requested:
                raise ServiceError("Follow-up idempotency key reused with different content")
            return row
        if assignee:
            self.scoped(s, m.User, case.tenant_id, assignee)
        row = m.FollowUp(
            id=m.uid(),
            tenant_id=case.tenant_id,
            case_id=case.id,
            fingerprint=fp,
            assignee=assignee,
            next_action=action,
            due_at=due_at or m.utcnow() + timedelta(days=2),
            reason="Human follow-up; no automated external send",
            data={"request_fingerprint": requested},
        )
        s.add(row)
        s.flush()
        self.event(s, case.tenant_id, case.id, "followup.created", {"count": 1})
        return row

    def update_followup(self, actor, identity, due_at=None, complete=False, version=None):
        self.require(actor, "admin", "reviewer", "operator")
        with self.db.session() as s:
            row = self.scoped(s, m.FollowUp, actor["tenant_id"], identity)
            self.lock_case(s, row.tenant_id, row.case_id)
            s.refresh(row)
            if version is not None and version != row.version:
                raise ServiceError("Follow-up changed")
            if complete and row.status == "COMPLETED":
                return m.row_dict(row)
            if complete:
                row.status = "COMPLETED"
                row.completed_at = m.utcnow()
            else:
                row.due_at = due_at
                row.status = "PENDING"
            row.version += 1
            self.event(
                s,
                row.tenant_id,
                row.case_id,
                "followup.completed" if complete else "followup.postponed",
                {"version": row.version},
                actor=actor["id"],
            )
            return m.row_dict(row)

    def events(self, tenant, case_id, after=0, limit=500):
        with self.db.session() as s:
            self.scoped(s, m.Case, tenant, case_id)
            return [
                {**m.row_dict(r), "event_id": r.id}
                for r in s.scalars(
                    select(m.EventLog)
                    .where(m.EventLog.tenant_id == tenant, m.EventLog.case_id == case_id, m.EventLog.sequence > after)
                    .order_by(m.EventLog.sequence)
                    .limit(limit)
                )
            ]

    def close(self, actor, case_id, version):
        self.require(actor, "admin", "reviewer", "operator")
        with self.db.session() as s:
            case = self.lock_case(s, actor["tenant_id"], case_id, version)
            self.ensure_no_outbound_inflight(s, case)
            self.transition(s, case, "CLOSED")
            # A queued action has not reached the connector. Closing a Case
            # cancels it under the same lock used by dispatch admission.
            s.execute(
                update(m.OutboundAction)
                .where(
                    m.OutboundAction.tenant_id == case.tenant_id,
                    m.OutboundAction.case_id == case.id,
                    m.OutboundAction.status == "PENDING",
                )
                .values(status="CANCELLED", finished_at=m.utcnow())
            )
            case.version += 1
            s.execute(
                update(m.WorkflowRun)
                .where(
                    m.WorkflowRun.tenant_id == case.tenant_id,
                    m.WorkflowRun.case_id == case.id,
                    m.WorkflowRun.status != "COMPLETED",
                )
                .values(status="CANCELLED", lease_token=None, lease_until=None, finished_at=m.utcnow())
            )
            s.execute(
                update(m.Task)
                .where(
                    m.Task.tenant_id == case.tenant_id,
                    m.Task.case_id == case.id,
                    m.Task.status.in_(["PENDING", "READY", "RUNNING", "WAITING_HUMAN", "BLOCKED"]),
                )
                .values(status="CANCELLED", lease_token=None, lease_until=None)
            )
            s.execute(
                update(m.TaskAttempt)
                .where(
                    m.TaskAttempt.tenant_id == case.tenant_id,
                    m.TaskAttempt.case_id == case.id,
                    m.TaskAttempt.status == "RUNNING",
                )
                .values(status="CANCELLED", finished_at=m.utcnow())
            )
            s.execute(
                update(m.AgentRun)
                .where(
                    m.AgentRun.tenant_id == case.tenant_id,
                    m.AgentRun.case_id == case.id,
                    m.AgentRun.status == "RUNNING",
                )
                .values(status="CANCELLED", finished_at=m.utcnow())
            )
            s.execute(
                update(m.FollowUp)
                .where(
                    m.FollowUp.tenant_id == case.tenant_id,
                    m.FollowUp.case_id == case.id,
                    m.FollowUp.status == "PENDING",
                )
                .values(status="CANCELLED")
            )
            s.execute(
                update(m.Approval)
                .where(
                    m.Approval.tenant_id == case.tenant_id,
                    m.Approval.case_id == case.id,
                    m.Approval.status.in_(["PENDING", "APPROVED"]),
                )
                .values(status="INVALIDATED")
            )
            self.event(s, case.tenant_id, case.id, "case.closed", {"version": case.version}, actor=actor["id"])
            return self._case_dict(s, case)

    def update_metadata(self, actor, case_id, request):
        self.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            case = self.lock_case(s, actor["tenant_id"], case_id, request.case_version)
            self.ensure_no_outbound_inflight(s, case)
            if case.status == "CLOSED":
                raise ServiceError("Reopen the Case before editing metadata")
            if case.status == "RESEARCHING":
                raise ServiceError("Wait for running workflow before editing")
            for key in ("title", "priority", "tags"):
                value = getattr(request, key)
                if value is not None:
                    setattr(case, key, value)
            case.version += 1
            s.execute(
                update(m.Approval)
                .where(
                    m.Approval.tenant_id == case.tenant_id,
                    m.Approval.case_id == case.id,
                    m.Approval.status.in_(["PENDING", "APPROVED"]),
                )
                .values(status="INVALIDATED")
            )
            artifact = s.scalar(
                select(m.Artifact).where(
                    m.Artifact.tenant_id == case.tenant_id, m.Artifact.case_id == case.id, m.Artifact.kind == "draft"
                )
            )
            if artifact:
                self.transition(s, case, "NEEDS_REVIEW")
                self.prepare_approval(s, case)
                if case.workflow_run_id:
                    run = self.scoped(s, m.WorkflowRun, case.tenant_id, case.workflow_run_id)
                    run.data = {**run.data, "refresh_approval": True}
                    run.status = "PENDING"
            self.event(s, case.tenant_id, case.id, "case.metadata", {"version": case.version}, actor=actor["id"])
            return self._case_dict(s, case)

    def related(self, tenant, case_id):
        with self.db.session() as s:
            case = self.scoped(s, m.Case, tenant, case_id)
            domain = case.data.get("domain")
            if not domain:
                return []
            rows = s.scalars(
                select(m.Case)
                .where(m.Case.tenant_id == tenant, m.Case.id != case_id, m.Case.data["domain"].as_string() == domain)
                .limit(100)
            )
            return [
                {"id": r.id, "title": r.title, "status": r.status, "relation": "shared_email_domain_unverified"}
                for r in rows
            ]

    def metrics(self, tenant):
        with self.db.session() as s:
            counts = dict(
                s.execute(
                    select(m.Case.status, func.count()).where(m.Case.tenant_id == tenant).group_by(m.Case.status)
                ).all()
            )
            return {
                "case_counts": counts,
                "total_cases": sum(counts.values()),
                "pending_approvals": s.scalar(
                    select(func.count())
                    .select_from(m.Approval)
                    .where(m.Approval.tenant_id == tenant, m.Approval.status == "PENDING")
                ),
                "external_sends": s.scalar(
                    select(func.count())
                    .select_from(m.OutboundAction)
                    .where(m.OutboundAction.tenant_id == tenant, m.OutboundAction.status == "SENT")
                ),
            }
