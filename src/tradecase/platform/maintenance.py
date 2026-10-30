"""Explicit retention and integrity operations; every destructive mode is opt-in.

Business purge is tenant-scoped. Object GC is a separate, quiesced operator action
because an online DB scan cannot protect an object between put() and DB commit.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, String, Text, delete, func, or_, select

from tradecase.platform import db as m
from tradecase.platform import source_cache
from tradecase.platform.services import ServiceError
from tradecase.platform.storage import LocalStorage
from tradecase.platform.workflow import checkpoint_saver
from tradecase.util import no_symlinks
from tradecase.visual import models as visual

_KEY = re.compile(r"sha256/[a-f0-9]{2}/[a-f0-9]{64}$")
_DELETE_ORDER = (
    visual.BuyerProposal, visual.VisualReview, visual.VisualEvent, visual.VisualAsset,
    visual.EngineRun, visual.PlanSnapshot, visual.VisualTask, visual.TruthSnapshot,
    visual.SourceAsset, visual.Product,
    m.AgentRun, m.TaskAttempt, m.ClaimEvidenceLink, m.OutboundAction, m.Approval,
    m.ArtifactVersion, m.Artifact, m.RiskFinding, m.LeadAssessment, m.Source,
    m.Claim, m.FollowUp, m.EventLog, m.AuditLog, m.Task, m.WorkflowRun,
)


def _before(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ServiceError("Retention cutoff requires an aware timestamp", 422)
    if value > m.utcnow():
        raise ServiceError("Retention cutoff cannot be in the future", 422)
    return value.astimezone(timezone.utc)


def _object_keys(value):
    if isinstance(value, str):
        if _KEY.fullmatch(value) and value.split("/")[1] == value.rsplit("/", 1)[1][:2]:
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _object_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _object_keys(item)


def referenced_objects(session):
    """Exact content keys in all business columns, across every tenant.

    Scan JSON recursively as task/Agent outputs can also hold object references.
    Workflow checkpoint state is restricted to IDs; purge deletes its thread first.
    """
    refs = set()
    for table in m.Base.metadata.sorted_tables:
        columns = [c for c in table.columns if isinstance(c.type, (JSON, String, Text))]
        if columns:
            for values in session.execute(select(*columns)).yield_per(200):
                for value in values:
                    refs.update(_object_keys(value))
    return refs


def verify_object_references(db, storage, tenant=None):
    """Validate recorded hashes plus every content key in JSON/cache/knowledge refs."""
    checked, errors, seen = 0, [], set()
    with db.session() as session:
        for model, ref_field, hash_field in ((m.Inquiry, "raw_content_ref", "raw_hash"),
                                           (m.Source, "snapshot_ref", "snapshot_hash"),
                                           (m.ArtifactVersion, "storage_ref", "content_hash"),
                                           (visual.SourceAsset, "storage_ref", "content_hash"),
                                           (visual.VisualAsset, "storage_ref", "content_hash")):
            statement = select(model)
            if tenant is not None:
                statement = statement.where(model.tenant_id == tenant)
            for record in session.scalars(statement):
                ref = getattr(record, ref_field)
                if not ref:
                    continue
                checked += 1
                seen.add(ref)
                if not storage.verify(ref, getattr(record, hash_field)):
                    errors.append({"table": model.__tablename__, "id": record.id, "error": "OBJECT_INTEGRITY"})
        for table in m.Base.metadata.sorted_tables:
            columns = [c for c in table.columns if isinstance(c.type, (JSON, String, Text))]
            if not columns:
                continue
            statement = select(*columns)
            if tenant is not None:
                scope = table.c.id if table.name == "organizations" else table.c.tenant_id
                statement = statement.where(scope == tenant)
            for values in session.execute(statement).mappings().yield_per(200):
                refs = set()
                for value in values.values():
                    refs.update(_object_keys(value))
                for key in refs - seen:
                    seen.add(key)
                    checked += 1
                    if not storage.verify(key):
                        errors.append({"table": table.name, "id": values.get("id"), "error": "OBJECT_INTEGRITY"})
    return {"checked": checked, "errors": errors}


class MaintenanceService:
    def __init__(self, service, *, checkpoint_factory=checkpoint_saver):
        self.service = service
        self.db = service.db
        self.storage = service.storage
        self.checkpoint_factory = checkpoint_factory

    def _admin(self, actor):
        self.service.require(actor, "admin")
        # Retention is also available from CLI; recheck a persisted active account.
        with self.db.session() as session:
            user = self.service.scoped(session, m.User, actor["tenant_id"], actor["id"])
            if not user.active or user.role != "admin":
                raise ServiceError("Current tenant administrator required", 403)

    def candidates(self, actor, before, *, limit=100):
        self._admin(actor)
        before = _before(before)
        with self.db.session() as session:
            rows = session.scalars(select(m.Case).where(
                m.Case.tenant_id == actor["tenant_id"], m.Case.status == "CLOSED", m.Case.updated_at < before,
            ).order_by(m.Case.updated_at).limit(min(max(limit, 1), 1000)))
            return [{"case_id": row.id, "version": row.version, "updated_at": row.updated_at,
                     "dry_run": True} for row in rows]

    def _validate(self, session, case, before, expected_version):
        if case.status != "CLOSED" or case.updated_at >= before:
            raise ServiceError("Only closed Cases older than the retention cutoff may be purged")
        if case.version != expected_version:
            raise ServiceError("Case changed; review retention plan again")
        active_visual = session.scalar(select(visual.VisualTask.id).where(
            visual.VisualTask.tenant_id == case.tenant_id, visual.VisualTask.case_id == case.id,
            visual.VisualTask.status.in_(["queued", "running", "qa_pending", "reconciling", "cancelling"]),
        ))
        if active_visual:
            raise ServiceError("Visual execution must be reconciled before retention")
        unresolved_visual_run = session.scalar(select(visual.EngineRun.id).where(
            visual.EngineRun.tenant_id == case.tenant_id, visual.EngineRun.case_id == case.id,
            or_(visual.EngineRun.status.in_(["queued", "planning", "submitting", "running", "qa_pending", "reconciling"]),
                visual.EngineRun.data["lease_until"].as_float() > m.utcnow().timestamp()),
        ))
        if unresolved_visual_run:
            raise ServiceError("Remote Visual run must be reconciled before retention")
        active = session.scalar(select(m.WorkflowRun.id).where(
            m.WorkflowRun.tenant_id == case.tenant_id, m.WorkflowRun.case_id == case.id,
            or_(m.WorkflowRun.status.in_(["PENDING", "RUNNING", "WAITING_HUMAN"]),
                m.WorkflowRun.lease_until > m.utcnow()),
        ))
        if active:
            raise ServiceError("Active workflow must finish or be cancelled before retention")
        active_task = session.scalar(select(m.Task.id).where(
            m.Task.tenant_id == case.tenant_id, m.Task.case_id == case.id,
            m.Task.status.in_(["PENDING", "READY", "RUNNING", "WAITING_HUMAN"]),
        ))
        if active_task:
            raise ServiceError("Active task must finish or be cancelled before retention")
        pending = session.scalar(select(m.OutboundAction.id).where(
            m.OutboundAction.tenant_id == case.tenant_id, m.OutboundAction.case_id == case.id,
            m.OutboundAction.status.in_(["PENDING", "DISPATCHING", "DELIVERY_UNCERTAIN"]),
        ))
        if pending:
            raise ServiceError("Pending or uncertain outbound delivery must be reconciled before retention")

    def _existing(self, session, tenant, key, subject):
        row = session.scalar(select(m.AuditLog).where(
            m.AuditLog.tenant_id == tenant, m.AuditLog.action == "retention.purged", m.AuditLog.correlation_id == key,
        ))
        if row is not None and row.data_redacted.get("case_fingerprint") != subject:
            raise ServiceError("Retention idempotency key was used for a different Case")
        return {"status": "PURGED", "replayed": True, **row.data_redacted} if row else None

    def _work_caches(self, tenant, case_id):
        # These are DB-resolved IDs, but tenant identifiers can originate in an
        # operator command. Never turn an arbitrary identity into a delete path.
        for value in (tenant, case_id):
            if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                raise ServiceError("Unsafe retention materialization identity")
        tenant_root = self.service.settings.work_root / tenant
        no_symlinks(tenant_root)
        paths = [tenant_root / case_id]
        # Kernel review materializations are versioned independently of the
        # current Case pointer. Include every historical review directory, even
        # one whose version was superseded or whose DB transaction rolled back.
        if tenant_root.exists():
            for parent in sorted(tenant_root.glob("review-*")):
                no_symlinks(parent)
                paths.append(parent / case_id)
                # A process killed before atomic publication can leave the
                # temporary CaseStore behind. Inspect only the kernel's bounded
                # staging layout, never recursively traverse arbitrary folders.
                paths.extend(staging / case_id for staging in sorted(parent.glob(".review-build-*")))
        for path in paths:
            no_symlinks(path)
            if path.exists() and not path.is_dir():
                raise ServiceError("Derived Case materialization must be a directory")
        return paths

    async def purge(self, actor, case_id, *, before, expected_version, idempotency_key, dry_run=True):
        self._admin(actor)
        before = _before(before)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 100:
            raise ServiceError("Retention idempotency key requires 1–100 characters", 422)
        tenant = actor["tenant_id"]
        subject = hashlib.sha256((tenant + ":" + case_id).encode()).hexdigest()
        with self.db.session() as session:
            existing = self._existing(session, tenant, idempotency_key, subject)
            if existing:
                return existing
            case = session.scalar(select(m.Case).where(m.Case.tenant_id == tenant, m.Case.id == case_id))
            if case is None:
                existing = self._existing(session, tenant, idempotency_key, subject)
                if existing:
                    return existing
                raise ServiceError("Resource not found", 404)
            # Lock without changing updated_at, otherwise an old Case would become
            # ineligible merely because the maintenance tool inspected it.
            if not dry_run:
                from sqlalchemy import update
                changed = session.execute(update(m.Case).where(
                    m.Case.tenant_id == tenant, m.Case.id == case_id, m.Case.version == expected_version,
                ).values(version=m.Case.version, updated_at=m.Case.updated_at)).rowcount
                if changed != 1:
                    existing = self._existing(session, tenant, idempotency_key, subject)
                    if existing:
                        return existing
                    raise ServiceError("Case changed during retention")
                session.refresh(case)
            self._validate(session, case, before, expected_version)
            workflows = list(session.scalars(select(m.WorkflowRun.thread_id).where(
                m.WorkflowRun.tenant_id == tenant, m.WorkflowRun.case_id == case_id,
            )))
            counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model).where(
                model.tenant_id == tenant, model.case_id == case_id,
            )) for model in _DELETE_ORDER}
            receipts = (visual.RequestReceipt.tenant_id == tenant,
                        visual.RequestReceipt.result["case_id"].as_string() == case_id)
            counts[visual.RequestReceipt.__tablename__] = session.scalar(
                select(func.count()).select_from(visual.RequestReceipt).where(*receipts))
            work_caches = self._work_caches(tenant, case_id)
            if dry_run:
                return {"status": "PLANNED", "dry_run": True, "case_id": case_id, "version": case.version,
                        "row_counts": counts, "checkpoint_threads": len(workflows),
                        "derived_work_cache_exists": any(path.exists() for path in work_caches),
                        "derived_work_cache_count": sum(path.exists() for path in work_caches),
                        "objects": "retained until separate quiesced garbage collection"}
            # Keep the Case write lock through checkpoint deletion. Re-execution
            # of adelete_thread is safe after any crash. If it fails, no business
            # records commit as deleted. If DB commit fails later, retry deletes
            # the already absent closed-workflow threads again.
            if workflows:
                async with self.checkpoint_factory(self.service.settings.checkpoint_url) as saver:
                    for thread_id in workflows:
                        await saver.adelete_thread(thread_id)
            # Materializations are disposable copies of DB/object-backed data.
            # Remove them while the Case lock prevents fresh service work. If
            # this or the later DB commit fails, retry can remove any remainder;
            # original object-backed business records are still recoverable.
            for work_cache in work_caches:
                no_symlinks(work_cache)
                if work_cache.exists():
                    shutil.rmtree(work_cache)
            session.execute(delete(visual.RequestReceipt).where(*receipts))
            inquiry_id, entity_id = case.inquiry_id, case.buyer_entity_id
            for model in _DELETE_ORDER:
                session.execute(delete(model).where(model.tenant_id == tenant, model.case_id == case_id))
            session.execute(delete(m.Case).where(m.Case.tenant_id == tenant, m.Case.id == case_id))
            for model, identity, reference in ((m.Inquiry, inquiry_id, m.Case.inquiry_id),
                                                (m.BuyerEntity, entity_id, m.Case.buyer_entity_id)):
                if identity and session.scalar(select(m.Case.id).where(
                    m.Case.tenant_id == tenant, reference == identity,
                )) is None:
                    session.execute(delete(model).where(model.tenant_id == tenant, model.id == identity))
            summary = {"case_fingerprint": subject, "deleted_rows": sum(counts.values()) + 1,
                       "checkpoint_threads": len(workflows), "objects_deleted": 0,
                       "object_gc_required": True, "derived_work_cache_removed": True}
            session.add(m.AuditLog(
                tenant_id=tenant, case_id=None, actor_id=actor["id"], action="retention.purged",
                correlation_id=idempotency_key, data_redacted=summary,
            ))
            return {"status": "PURGED", "replayed": False, **summary}

    def verify_objects(self, actor):
        self._admin(actor)
        return verify_object_references(self.db, self.storage, actor["tenant_id"])

    def prune_expired_cache(self, actor, *, before=None, dry_run=True):
        """Remove expired tenant cache references, never a live fetch lease or blob."""
        self._admin(actor)
        cutoff = _before(before) if before is not None else m.utcnow()
        cache = source_cache.SourceCache
        conditions = (cache.tenant_id == actor["tenant_id"], cache.expires_at <= cutoff,
                      or_(cache.lease_until.is_(None), cache.lease_until <= m.utcnow()))
        with self.db.session() as session:
            candidates = list(session.scalars(select(cache.id).where(*conditions)))
            deleted = 0
            if not dry_run:
                deleted = session.execute(delete(cache).where(*conditions)).rowcount
            return {"dry_run": dry_run, "candidates": candidates, "deleted_rows": deleted, "objects_deleted": 0}

    def gc_orphans(self, *, dry_run=True, quiesced=False, minimum_age=timedelta(days=7)):
        """Local operator command only, never a tenant HTTP endpoint.

        quiesced=True is an explicit operator assertion that all API, workers and
        import processes are stopped. Without it physical deletion is forbidden.
        """
        if not isinstance(self.storage, LocalStorage):
            raise ServiceError("S3 orphan GC requires separately reviewed bucket inventory/lifecycle policy")
        if minimum_age < timedelta(0):
            raise ServiceError("Object grace period cannot be negative", 422)
        if not dry_run and not quiesced:
            raise ServiceError("Stop every writer and explicitly assert quiesced mode before object GC")
        cutoff = m.utcnow() - minimum_age
        with self.db.session() as session:
            refs = referenced_objects(session)
        candidates = []
        no_symlinks(self.storage.root)
        for path in sorted(self.storage.root.glob("sha256/*/*")):
            no_symlinks(path)
            key = path.relative_to(self.storage.root).as_posix()
            if not path.is_file() or not _KEY.fullmatch(key) or key in refs:
                continue
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= cutoff:
                continue
            candidates.append(key)
        deleted = []
        if not dry_run:
            # Second cross-tenant reference scan closes the normal review/execute
            # gap; quiescence is still required to exclude later writers.
            with self.db.session() as session:
                current_refs = referenced_objects(session)
                for key in candidates:
                    if key not in current_refs:
                        self.storage.delete(key)
                        deleted.append(key)
        return {"dry_run": dry_run, "candidates": candidates, "deleted": deleted,
                "reference_scope": "all tenants", "minimum_age_seconds": minimum_age.total_seconds()}
