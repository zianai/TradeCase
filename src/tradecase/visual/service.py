"""Optional visual business operations, separate from facts and Case scheduling."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import timedelta

from sqlalchemy import select, update

from tradecase.platform import db as m
from tradecase.platform.services import ServiceError, fingerprint

from . import models as v
from .opportunities import detect
from .schemas import ProductInput
from .settings import VisualSettings

DISCLAIMER = "Concept / AI-assisted visualization for discussion only. Not evidence of an existing product, manufacturing capability or certification. Supplier feasibility and final specifications require confirmation."


def image_type(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    raise ServiceError("Only PNG, JPEG or WebP image bytes are allowed", 422)


class VisualService:
    def __init__(self, cases, engine=None, settings=None):
        self.cases = cases
        self.db = cases.db
        self.storage = cases.storage
        self.settings = settings or VisualSettings()
        if engine is None:
            from .engine import engine_from_env

            try:
                engine = engine_from_env()
            except (ValueError, RuntimeError):
                from .engine import DisabledCreativeEngine

                engine = DisabledCreativeEngine()
        self.engine = engine

    def enabled(self):
        if not self.settings.enabled:
            raise ServiceError("Visual Tasks are disabled", 403)

    def event(self, s, task, kind, actor="system", **data):
        s.add(
            v.VisualEvent(
                tenant_id=task.tenant_id,
                case_id=task.case_id,
                task_id=task.id,
                kind=kind,
                data={"actor": actor, **data},
            )
        )
        self.cases.event(
            s,
            task.tenant_id,
            task.case_id,
            "visual." + kind,
            {"status": task.status, "version": task.version},
            actor=actor,
        )

    def locked(self, s, actor, identity, version=None):
        task = s.scalar(
            select(v.VisualTask)
            .where(v.VisualTask.id == identity, v.VisualTask.tenant_id == actor["tenant_id"])
            .with_for_update()
        )
        if task is None:
            raise ServiceError("Visual task not found", 404)
        if version is not None and task.version != version:
            raise ServiceError("Visual task changed; reload")
        return task

    def _product(self, s, tenant, cid, pid):
        product = self.cases.scoped(s, v.Product, tenant, pid)
        if product.case_id != cid:
            raise ServiceError("Product belongs to another Case", 403)
        return product

    def _replay(self, s, tenant, scope, key, payload):
        if not key:
            return None
        row = s.scalar(
            select(v.RequestReceipt).where(
                v.RequestReceipt.tenant_id == tenant, v.RequestReceipt.scope == scope, v.RequestReceipt.key == key
            )
        )
        if row and row.fingerprint != fingerprint(payload):
            raise ServiceError("Idempotency payload mismatch")
        return row.result if row else None

    def _receipt(self, s, tenant, scope, key, payload, result):
        if key:
            from fastapi.encoders import jsonable_encoder

            s.add(
                v.RequestReceipt(
                    tenant_id=tenant,
                    scope=scope,
                    key=key,
                    fingerprint=fingerprint(payload),
                    result=jsonable_encoder(result),
                )
            )
        return result

    def product(self, actor, cid, body: ProductInput, key=None):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            self.cases.lock_case(s, actor["tenant_id"], cid)
            replay = self._replay(s, actor["tenant_id"], "product:" + cid, key, body.model_dump())
            if replay:
                return replay
            product = s.scalar(
                select(v.Product)
                .where(v.Product.tenant_id == actor["tenant_id"], v.Product.case_id == cid, v.Product.sku == body.sku)
                .with_for_update()
            )
            if product:
                if body.expected_version != product.version:
                    raise ServiceError("Product version required or changed")
                product.version += 1
                product.data = body.model_dump(exclude={"expected_version"})
                for task in s.scalars(
                    select(v.VisualTask).where(
                        v.VisualTask.tenant_id == actor["tenant_id"],
                    )
                ):
                    current_plan = self.cases.scoped(s, v.PlanSnapshot, task.tenant_id, task.plan_id)
                    if product.id not in current_plan.data.get("product_versions", {task.product_id: 1}):
                        continue
                    task.data = {**task.data, "truth_stale": True}
                    task.version += 1
                    self.event(s, task, "truth_stale", actor["id"])
            else:
                if body.expected_version is not None:
                    raise ServiceError("Product does not exist", 404)
                product = v.Product(
                    id=m.uid(),
                    tenant_id=actor["tenant_id"],
                    case_id=cid,
                    sku=body.sku,
                    data=body.model_dump(exclude={"expected_version"}),
                )
                s.add(product)
            s.flush()
            return self._receipt(s, actor["tenant_id"], "product:" + cid, key, body.model_dump(), m.row_dict(product))

    def upload(self, actor, cid, pid, raw, source, authorized, external_use, kind, key=None):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        if not raw or len(raw) > self.settings.max_asset_bytes:
            raise ServiceError("Image exceeds limit", 413)
        mime = image_type(raw)
        if kind not in {"product", "logo", "packaging"} or not source or len(source) > 2000:
            raise ServiceError("Invalid asset metadata", 422)
        with self.db.session() as s:
            self.cases.lock_case(s, actor["tenant_id"], cid)
            self._product(s, actor["tenant_id"], cid, pid)
            payload = {
                "product_id": pid,
                "hash": hashlib.sha256(raw).hexdigest(),
                "source": source,
                "authorized": authorized,
                "external_use": external_use,
                "kind": kind,
            }
            replay = self._replay(s, actor["tenant_id"], "upload:" + cid, key, payload)
            if replay:
                return replay
            digest = hashlib.sha256(raw).hexdigest()
            if s.scalar(
                select(v.VisualAsset.id).where(
                    v.VisualAsset.tenant_id == actor["tenant_id"], v.VisualAsset.content_hash == digest
                )
            ):
                raise ServiceError("Generated imagery cannot be imported as factual source material", 403)
            obj = self.storage.put(raw)
            row = v.SourceAsset(
                tenant_id=actor["tenant_id"],
                case_id=cid,
                product_id=pid,
                source=source,
                kind=kind,
                authorized=authorized,
                external_use=external_use,
                mime_type=mime,
                content_hash=obj.sha256,
                storage_ref=obj.key,
            )
            s.add(row)
            s.flush()
            return self._receipt(s, actor["tenant_id"], "upload:" + cid, key, payload, self.asset_dict(row, True))

    def asset_dict(self, a, source=False):
        result = m.row_dict(a)
        result.pop("storage_ref", None)
        if result.get("created_at"):
            result["created_at"] = result["created_at"].isoformat()
        result["content_url"] = f"/api/visual-{'source-' if source else ''}assets/{a.id}/content"
        return result

    def _task_dict(self, s, t):
        result = m.row_dict(t)
        plan = self.cases.scoped(s, v.PlanSnapshot, t.tenant_id, t.plan_id)
        result["plan"] = {**m.row_dict(plan), "hash": plan.content_hash}
        result["assets"] = [
            self.asset_dict(a)
            for a in s.scalars(
                select(v.VisualAsset).where(v.VisualAsset.tenant_id == t.tenant_id, v.VisualAsset.task_id == t.id)
            )
        ]
        result["reviews"] = [
            m.row_dict(a)
            for a in s.scalars(
                select(v.VisualReview).where(v.VisualReview.tenant_id == t.tenant_id, v.VisualReview.task_id == t.id)
            )
        ]
        result["runs"] = [
            m.row_dict(a)
            for a in s.scalars(
                select(v.EngineRun).where(v.EngineRun.tenant_id == t.tenant_id, v.EngineRun.task_id == t.id)
            )
        ]
        return result

    def get(self, actor, identity):
        with self.db.session() as s:
            return self._task_dict(s, self.locked(s, actor, identity))

    def summary_for_case(self, tenant, cid):
        with self.db.session() as s:
            case = self.cases.scoped(s, m.Case, tenant, cid)
            inquiry = self.cases.scoped(s, m.Inquiry, tenant, case.inquiry_id)
            raw = self.storage.get(inquiry.raw_content_ref).decode("utf-8", errors="replace")
            suggestions = detect(raw, case.data.get("visual_semantic_candidates", []))
            products = list(s.scalars(select(v.Product).where(v.Product.tenant_id == tenant, v.Product.case_id == cid)))
            sources = list(
                s.scalars(select(v.SourceAsset).where(v.SourceAsset.tenant_id == tenant, v.SourceAsset.case_id == cid))
            )
            for suggestion in suggestions:
                suggestion["evidence_refs"] = [f"inquiry:{inquiry.id}"]
                if not products or not sources:
                    suggestion["status"] = "needs_input"
            mode = getattr(self.engine, "mode", type(self.engine).__name__)
            return {
                "enabled": self.settings.enabled,
                "engine_mode": mode,
                "engine": {"mode": mode, "available": mode not in {"disabled", "DisabledCreativeEngine"}},
                "suggestions": suggestions,
                "opportunities": suggestions,
                "products": [m.row_dict(p) for p in products],
                "source_assets": [self.asset_dict(a, True) for a in sources],
                "tasks": [
                    self._task_dict(s, t)
                    for t in s.scalars(
                        select(v.VisualTask).where(v.VisualTask.tenant_id == tenant, v.VisualTask.case_id == cid)
                    )
                ],
                "proposals": [
                    m.row_dict(p)
                    for p in s.scalars(
                        select(v.BuyerProposal).where(
                            v.BuyerProposal.tenant_id == tenant, v.BuyerProposal.case_id == cid
                        )
                    )
                ],
                "not_recommended_reason": None
                if suggestions
                else "No visual requirement detected; original inquiry workflow continues.",
            }

    def suggest(self, actor, cid, candidates):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            case = self.cases.lock_case(s, actor["tenant_id"], cid)
            inquiry = self.cases.scoped(s, m.Inquiry, actor["tenant_id"], case.inquiry_id)
            raw = self.storage.get(inquiry.raw_content_ref).decode("utf-8", errors="replace")
            accepted = detect(raw, candidates)
            case.data = {**case.data, "visual_semantic_candidates": accepted}
        return self.summary_for_case(actor["tenant_id"], cid)

    def _plan(self, s, actor, task, body):
        product = self._product(s, actor["tenant_id"], task.case_id, body.product_id)
        concept = body.concept or body.intent == "odm_concept"
        if body.variants > self.settings.max_variants or body.budget_usd > self.settings.max_budget_usd:
            raise ServiceError("Visual budget or variant limit exceeded", 422)
        missing = []
        if not concept:
            for k in ["dimensions", "material", "structure"]:
                if not product.data.get(k):
                    missing.append(k)
            if product.data.get("fact_status") != "verified":
                missing.append("verified product facts")
            if not product.data.get("external_use"):
                missing.append("product external use permission")
        sources = []
        for identity in dict.fromkeys(body.source_asset_ids):
            a = self.cases.scoped(s, v.SourceAsset, actor["tenant_id"], identity)
            if a.case_id != task.case_id:
                raise ServiceError("Asset from another Case", 403)
            if a.product_id != product.id and body.intent != "product_comparison":
                raise ServiceError("Asset product mismatch", 422)
            sources.append(a)
        if not sources and not concept:
            missing.append("real product reference image")
        if not concept:
            for pid in {a.product_id for a in sources}:
                secondary = self._product(s, actor["tenant_id"], task.case_id, pid)
                if secondary.data.get("fact_status") != "verified" or not secondary.data.get("external_use"):
                    missing.append("verified externally permitted facts for every comparison SKU")
            if any(change in {"product_structure", "material", "dimensions"} for change in body.allowed_changes):
                missing.append("structural/material/dimension changes require an explicit concept plan")
        if any(not a.authorized or not a.external_use for a in sources):
            missing.append("reference asset use authorization")
        if "logo" in body.requirement.lower() or "authorized_logo" in body.allowed_changes:
            if not any(a.kind == "logo" and a.authorized and a.external_use for a in sources):
                missing.append("authorized Logo")
        if body.intent == "product_comparison" and len({a.product_id for a in sources if a.kind == "product"}) < 2:
            missing.append("references from at least two SKUs")
        if body.intent == "oem_preview" and not concept and not product.data.get("customization"):
            missing.append("confirmed customization capability")
        for ref in body.evidence_refs:
            if ref.startswith("inquiry:"):
                case = self.cases.scoped(s, m.Case, actor["tenant_id"], task.case_id)
                if ref.split(":", 1)[1] != case.inquiry_id:
                    raise ServiceError("Inquiry reference mismatch", 403)
            else:
                claim = self.cases.scoped(s, m.Claim, actor["tenant_id"], ref)
                if claim.case_id != task.case_id:
                    raise ServiceError("Evidence reference mismatch", 403)
        snap = v.TruthSnapshot(
            id=m.uid(),
            tenant_id=actor["tenant_id"],
            case_id=task.case_id,
            product_id=product.id,
            product_version=product.version,
            data=product.data,
            content_hash=fingerprint(product.data),
        )
        s.add(snap)
        plan_data = {
            **body.model_dump(),
            "concept": concept,
            "output_is_concept": True,
            "missing_inputs": missing,
            "product": product.data,
            "truth_snapshot_id": snap.id,
            "product_version": product.version,
            "product_versions": {
                pid: self._product(s, actor["tenant_id"], task.case_id, pid).version
                for pid in {product.id, *[a.product_id for a in sources]}
            },
            "provider": self.settings.provider,
            "engine_mode": getattr(self.engine, "mode", "disabled"),
            "engine_identity": getattr(
                self.engine, "engine_identity", {"mode": getattr(self.engine, "mode", "disabled")}
            ),
            "source_assets": [self.asset_dict(a, True) for a in sources],
            "estimated_cost_usd": None,
            "budget_is_maximum": True,
            "strategy": "generate"
            if concept
            else "reuse/compose"
            if body.intent in {"product_comparison", "buyer_presentation", "spec_illustration"}
            else "compose/edit",
            "disclaimer": DISCLAIMER,
        }
        prev = (
            s.scalar(
                select(v.PlanSnapshot.version)
                .where(v.PlanSnapshot.task_id == task.id)
                .order_by(v.PlanSnapshot.version.desc())
            )
            or 0
        )
        plan = v.PlanSnapshot(
            id=m.uid(),
            tenant_id=actor["tenant_id"],
            case_id=task.case_id,
            task_id=task.id,
            version=prev + 1,
            truth_snapshot_id=snap.id,
            data=plan_data,
            content_hash=fingerprint(plan_data),
        )
        s.add(plan)
        s.flush()
        task.plan_id = plan.id
        task.product_id = product.id
        task.intent = body.intent
        task.status = "needs_input" if missing else "awaiting_plan_approval"
        task.data = {"truth_stale": False}
        self.event(s, task, "plan.created", actor["id"], plan_hash=plan.content_hash)

    def create(self, actor, cid, body, key):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            self.cases.lock_case(s, actor["tenant_id"], cid)
            old = s.scalar(
                select(v.VisualTask).where(
                    v.VisualTask.tenant_id == actor["tenant_id"],
                    v.VisualTask.case_id == cid,
                    v.VisualTask.idempotency_key == key,
                )
            )
            if old:
                if old.fingerprint != fingerprint(body.model_dump()):
                    raise ServiceError("Idempotency payload mismatch")
                return self._task_dict(s, old)
            t = v.VisualTask(
                id=m.uid(),
                tenant_id=actor["tenant_id"],
                case_id=cid,
                product_id=body.product_id,
                intent=body.intent,
                idempotency_key=key,
                fingerprint=fingerprint(body.model_dump()),
            )
            s.add(t)
            s.flush()
            self._plan(s, actor, t, body)
            return self._task_dict(s, t)

    def revise(self, actor, tid, request, key):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            t = self.locked(s, actor, tid)
            replay = self._replay(s, actor["tenant_id"], "revise:" + tid, key, request.model_dump())
            if replay:
                return replay
            if t.version != request.version:
                raise ServiceError("Visual task changed; reload")
            if t.status in {"queued", "running", "reconciling", "qa_pending"}:
                raise ServiceError("Reconcile or cancel active generation before revision")
            failed = t.data.get("failed_variants", 0)
            if failed and request.plan.variants > failed:
                raise ServiceError(
                    "Partial recovery may request only failed variants; successful assets remain in history"
                )
            self._plan(s, actor, t, request.plan)
            t.version += 1
            return self._receipt(
                s, actor["tenant_id"], "revise:" + tid, key, request.model_dump(), self._task_dict(s, t)
            )

    def _fresh(self, s, t, plan):
        p = self._product(s, t.tenant_id, t.case_id, t.product_id)
        for pid, version in plan.data.get("product_versions", {t.product_id: plan.data["product_version"]}).items():
            if self._product(s, t.tenant_id, t.case_id, pid).version != version:
                raise ServiceError("Product Truth changed; create and approve a new plan")
        if p.version != plan.data["product_version"] or t.data.get("truth_stale"):
            raise ServiceError("Product Truth changed; create and approve a new plan")

    def _review_replay(self, s, actor, tid, key, payload):
        r = s.scalar(
            select(v.VisualReview).where(
                v.VisualReview.tenant_id == actor["tenant_id"],
                v.VisualReview.task_id == tid,
                v.VisualReview.idempotency_key == key,
            )
        )
        if r and r.fingerprint != fingerprint(payload):
            raise ServiceError("Idempotency payload mismatch")
        return r

    def approve(self, actor, tid, body, key):
        self.enabled()
        self.cases.require(actor, "admin", "reviewer")
        with self.db.session() as s:
            t = self.locked(s, actor, tid)
            if self._review_replay(s, actor, tid, key, body.model_dump()):
                return self._task_dict(s, t)
            if t.version != body.version or t.status != "awaiting_plan_approval":
                raise ServiceError("Plan is not awaiting this approval")
            p = self.cases.scoped(s, v.PlanSnapshot, t.tenant_id, t.plan_id)
            self._fresh(s, t, p)
            if body.plan_hash != p.content_hash or not body.data_processing_authorized:
                raise ServiceError("Exact plan and data processing authorization required", 403)
            if p.data["missing_inputs"]:
                raise ServiceError("Required product facts or authorization missing", 403)
            if p.data.get("provider") != "mock" and not self.settings.paid_enabled:
                raise ServiceError("Paid Visual Provider execution disabled", 403)
            s.add(
                v.VisualReview(
                    tenant_id=t.tenant_id,
                    case_id=t.case_id,
                    task_id=t.id,
                    subject_id=p.id,
                    subject_hash=p.content_hash,
                    scope="plan",
                    reviewer_id=actor["id"],
                    decision="approve",
                    idempotency_key=key,
                    fingerprint=fingerprint(body.model_dump()),
                    data={"budget_usd": p.data["budget_usd"], "data_processing_authorized": True},
                )
            )
            s.add(
                v.EngineRun(
                    id=m.uid(),
                    tenant_id=t.tenant_id,
                    case_id=t.case_id,
                    task_id=t.id,
                    plan_id=p.id,
                    idempotency_key=f"visual-{t.id}-{p.content_hash[:32]}",
                )
            )
            t.status = "queued"
            t.version += 1
            self.event(s, t, "plan.approved", actor["id"])
            s.flush()
            return self._task_dict(s, t)

    def _wire(self, s, t, p):
        product = p.data["product"]
        assets = []
        for identity in p.data["source_asset_ids"]:
            a = self.cases.scoped(s, v.SourceAsset, t.tenant_id, identity)
            assets.append(
                {
                    "external_id": a.id,
                    "filename": a.id + {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[a.mime_type],
                    "data_base64": base64.b64encode(self.storage.get(a.storage_ref)).decode(),
                    "kind": {"product": "product_photo", "logo": "logo", "packaging": "reference"}[a.kind],
                    "authorized": a.authorized,
                    "verified": product["fact_status"] == "verified",
                    "sensitive_data_cleared": True,
                    "source_version": a.content_hash,
                }
            )
        # An immutable user-supplied Product Context document is the fact provenance,
        # not a generated asset or an unrelated photograph.
        source_id = p.truth_snapshot_id
        document = json.dumps(
            {"source": product["source"], "status": product["fact_status"], "product": product}, ensure_ascii=False
        ).encode()
        source_version = hashlib.sha256(document).hexdigest()
        assets.append(
            {
                "external_id": source_id,
                "filename": "product-context.txt",
                "data_base64": base64.b64encode(document).decode(),
                "kind": "document",
                "authorized": True,
                "verified": product["fact_status"] == "verified",
                "sensitive_data_cleared": True,
                "source_version": source_version,
            }
        )
        facts = [
            {
                "name": k,
                "value": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                "source_asset_id": source_id,
                "source_version": source_version,
                "evidence_status": product["fact_status"],
                "confirmed_at": p.created_at.isoformat(),
                "external_allowed": product["external_use"] and product["fact_status"] == "verified",
            }
            for k, value in product.items()
            if k in {"name", "dimensions", "material", "colors", "structure", "customization"} and value
        ]
        return {
            "case_id": t.case_id,
            "visual_task_id": t.id,
            "product_id": t.product_id,
            "truth_snapshot": {"version": p.truth_snapshot_id, "facts": facts},
            "source_assets": assets,
            "requirements": p.data["requirement"],
            "intent": t.intent,
            "fidelity": "concept" if p.data["concept"] else "controlled",
            "allowed_changes": p.data["allowed_changes"],
            "forbidden_changes": p.data["preserve"],
            "variants": p.data["variants"],
            "budget_usd": p.data["budget_usd"],
            "concept": p.data["concept"],
            "output_is_concept": p.data.get("output_is_concept", True),
            "provider": self.settings.provider,
        }

    async def sync(self, actor, tid, version=None):
        """One bounded engine interaction; durable run fences prevent duplicate submits."""
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            t = self.locked(s, actor, tid, version)
            if t.status not in {"queued", "running", "qa_pending", "reconciling", "blocked", "cancelling"}:
                return self._task_dict(s, t)
            p = self.cases.scoped(s, v.PlanSnapshot, t.tenant_id, t.plan_id)
            try:
                self._fresh(s, t, p)
            except ServiceError:
                t.status = "blocked"
                t.data = {**t.data, "error": "product_truth_stale"}
                return self._task_dict(s, t)
            run = s.scalar(
                select(v.EngineRun)
                .where(v.EngineRun.tenant_id == t.tenant_id, v.EngineRun.plan_id == p.id)
                .with_for_update()
            )
            if run is None:
                raise ServiceError("No authorized execution", 403)
            now = m.utcnow()
            lease = run.data.get("lease_until", 0)
            if lease > now.timestamp():
                return self._task_dict(s, t)
            token = m.uid()
            stage = run.status
            run.data = {**run.data, "lease_until": (now + timedelta(seconds=90)).timestamp(), "lease": token}
            if stage == "queued":
                run.status = "planning"
            if (
                p.data.get("provider") != self.settings.provider
                or p.data.get("engine_mode") != getattr(self.engine, "mode", "disabled")
                or p.data.get("engine_identity")
                != getattr(self.engine, "engine_identity", {"mode": getattr(self.engine, "mode", "disabled")})
            ):
                raise ServiceError("Execution configuration changed; approve a new plan")
            payload = self._wire(s, t, p)
            run_id = run.id
            key = run.idempotency_key
            remote_plan = run.remote_plan_id
            batch_id = run.batch_id
        try:
            batch = None
            if batch_id:
                batch = await self.engine.get_batch(batch_id)
            elif stage in {"submitting", "reconciling", "planning"}:
                if not remote_plan:
                    raise ServiceError("Unknown plan submission outcome; manual reconciliation required")
                batch = await self.engine.lookup(key, plan_id=remote_plan)
                if batch is None:
                    raise ServiceError("Submission outcome unknown; no automatic paid retry")
            else:
                remote = await self.engine.plan(payload, key + "-plan")
                remote_plan = remote["id"]
                if remote.get("blocked_reasons"):
                    raise ServiceError("Creative Engine plan blocked: " + str(remote["blocked_reasons"])[:400])
                if not set(remote.get("allowed_changes", payload["allowed_changes"])).issubset(
                    set(payload["allowed_changes"])
                ) or not set(payload["forbidden_changes"]).issubset(
                    set(remote.get("forbidden_changes", payload["forbidden_changes"]))
                ):
                    raise ServiceError("Remote plan changed approved constraints")
                if (
                    float(remote.get("budget_usd", payload["budget_usd"])) > payload["budget_usd"]
                    or int(remote.get("variants", payload["variants"])) > payload["variants"]
                ):
                    raise ServiceError("Remote plan exceeds approved constraints")
                if self.settings.provider != "mock" and not self.settings.paid_enabled:
                    raise ServiceError("Paid Visual Provider execution disabled", 403)
                with self.db.session() as s:
                    run = self.cases.scoped(s, v.EngineRun, actor["tenant_id"], run_id)
                    t = self.locked(s, actor, tid)
                    if run.data.get("lease") != token:
                        return self._task_dict(s, t)
                    if t.status == "cancelling":
                        raise ServiceError("Cancelled before paid submission")
                    self._fresh(s, t, self.cases.scoped(s, v.PlanSnapshot, t.tenant_id, t.plan_id))
                    run.remote_plan_id = remote_plan
                    run.status = "submitting"
                batch = await self.engine.submit(
                    {
                        "plan_id": remote_plan,
                        "budget_usd": payload["budget_usd"],
                        "authorize_paid": self.settings.paid_enabled,
                        "provider": self.settings.provider,
                    },
                    key,
                )
            # Persist the remote identity before asset downloads so a transient file
            # failure recovers by GET instead of another batch creation.
            with self.db.session() as s:
                persisted = self.cases.scoped(s, v.EngineRun, actor["tenant_id"], run_id)
                if persisted.data.get("lease") == token:
                    persisted.batch_id = batch["id"]
            fetched = []
            if batch.get("cost_usd") is not None and batch["cost_usd"] > payload["budget_usd"]:
                raise ServiceError("Remote cost exceeds approved budget; reconcile before delivery")
            for item in batch.get("assets", []):
                if item.get("identity") == "mock" and self.settings.provider != "mock":
                    raise ServiceError("Unexpected mock fallback; approve a mock plan explicitly")
                if item.get("identity") == "concept" and not payload.get("output_is_concept", False):
                    raise ServiceError("Unexpected concept asset; approve a concept plan explicitly")
                raw, mime = await self.engine.get_asset(item["id"])
                if len(raw) > self.settings.max_asset_bytes or image_type(raw) != mime:
                    raise ServiceError("Invalid remote image", 422)
                obj = self.storage.put(raw)
                if item.get("sha256") and obj.sha256 != item["sha256"]:
                    raise ServiceError("Remote asset hash mismatch")
                if item.get("plan_id") and item["plan_id"] != remote_plan:
                    raise ServiceError("Remote asset plan mismatch")
                fetched.append((item, obj, mime))
            with self.db.session() as s:
                t = self.locked(s, actor, tid)
                run = self.cases.scoped(s, v.EngineRun, t.tenant_id, run_id)
                if run.data.get("lease") != token:
                    return self._task_dict(s, t)
                run.batch_id = batch["id"]
                run.status = batch["status"]
                run.data = {
                    **run.data,
                    "lease_until": 0,
                    "last_sync": m.utcnow().isoformat(),
                    "cost_usd": batch.get("cost_usd"),
                    "remote_status": batch["status"],
                }
                for item, obj, mime in fetched:
                    old = s.scalar(
                        select(v.VisualAsset).where(
                            v.VisualAsset.tenant_id == t.tenant_id,
                            v.VisualAsset.run_id == run_id,
                            v.VisualAsset.remote_id == item["id"],
                        )
                    )
                    if old:
                        if old.content_hash != obj.sha256:
                            raise ServiceError("Remote immutable asset changed")
                        if old.status in {"qa_pending", "awaiting_review"}:
                            old.qa = item.get("qa", {})
                            old.status = (
                                "awaiting_review"
                                if old.qa.get("status") == "passed"
                                else "qa_failed"
                                if old.qa.get("status") == "failed"
                                else "qa_pending"
                            )
                        continue
                    qa = item.get("qa", {})
                    status = (
                        "awaiting_review"
                        if qa.get("status") == "passed"
                        else "qa_failed"
                        if qa.get("status") == "failed"
                        else "qa_pending"
                    )
                    s.add(
                        v.VisualAsset(
                            tenant_id=t.tenant_id,
                            case_id=t.case_id,
                            task_id=t.id,
                            run_id=run.id,
                            plan_id=run.plan_id,
                            remote_id=item["id"],
                            status=status,
                            content_hash=obj.sha256,
                            storage_ref=obj.key,
                            mime_type=mime,
                            qa=qa,
                            data={
                                "identity": item.get("identity"),
                                "mock": self.settings.provider == "mock" or item.get("identity") == "mock",
                            },
                        )
                    )
                state = batch["status"]
                if t.status == "cancelling":
                    t.status = (
                        "cancelled"
                        if state
                        in {
                            "cancelled",
                            "completed",
                            "review_pending",
                            "approved",
                            "failed",
                            "partial_failed",
                            "awaiting_asset_review",
                        }
                        else "cancelling"
                    )
                elif state in {
                    "completed",
                    "review_pending",
                    "approved",
                    "awaiting_asset_review",
                    "partially_completed",
                    "partial_failed",
                }:
                    t.status = "awaiting_asset_review" if fetched else "failed"
                elif state == "failed" and fetched:
                    t.status = "awaiting_asset_review"
                elif state in {"failed", "cancelled"}:
                    t.status = state
                elif state in {"qa_pending"}:
                    t.status = "qa_pending"
                elif state in {"queued", "running", "pending", "rendering", "planning"}:
                    t.status = "running"
                else:
                    t.status = "reconciling"
                if (
                    t.status == "awaiting_asset_review"
                    and fetched
                    and all(item.get("qa", {}).get("status") == "pending" for item, _, _ in fetched)
                ):
                    t.status = "qa_pending"
                t.version += 1
                t.data = {
                    **t.data,
                    "error": None,
                    "failed_variants": max(0, payload["variants"] - len(fetched))
                    if state in {"failed", "partial_failed", "partially_completed"}
                    else 0,
                }
                self.event(s, t, "synced")
                s.flush()
                return self._task_dict(s, t)
        except Exception as exc:
            with self.db.session() as s:
                t = self.locked(s, actor, tid)
                run = self.cases.scoped(s, v.EngineRun, t.tenant_id, run_id)
                if run.data.get("lease") == token:
                    uncertain = (
                        getattr(exc, "uncertain", False)
                        or stage in {"reconciling", "planning", "submitting"}
                        or run.status in {"submitting", "reconciling"}
                        or (run.status == "planning" and not hasattr(exc, "uncertain"))
                    )
                    t.status = "reconciling" if uncertain else "blocked"
                    t.version += 1
                    run.status = "reconciling" if uncertain else "queued"
                    run.data = {**run.data, "lease_until": 0, "error_class": type(exc).__name__}
                    t.data = {
                        **t.data,
                        "error": getattr(
                            exc, "code", str(exc) if isinstance(exc, ServiceError) else type(exc).__name__
                        ),
                    }
                    self.event(s, t, "sync_failed", error_class=type(exc).__name__)
                return self._task_dict(s, t)

    async def recover_due(self):
        if not self.settings.enabled:
            return
        with self.db.session() as s:
            rows = [
                (t.tenant_id, t.id)
                for t in s.scalars(
                    select(v.VisualTask)
                    .where(v.VisualTask.status.in_(["queued", "running", "qa_pending", "reconciling", "cancelling"]))
                    .limit(50)
                )
            ]
        for tenant, tid in rows:
            try:
                await self.sync({"id": "visual-worker", "tenant_id": tenant, "role": "admin"}, tid)
            except Exception:
                pass

    async def cancel(self, actor, tid, body, key):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            t = self.locked(s, actor, tid)
            replay = self._replay(s, actor["tenant_id"], "cancel:" + tid, key, body.model_dump())
            if replay:
                return replay
            if t.version != body.version:
                raise ServiceError("Visual task changed; reload")
            if t.status in {"approved", "attached_to_proposal"}:
                raise ServiceError("Delivered revisions cannot be cancelled")
            run = s.scalar(
                select(v.EngineRun).where(v.EngineRun.tenant_id == t.tenant_id, v.EngineRun.plan_id == t.plan_id)
            )
            active = run and (run.batch_id or run.status in {"planning", "submitting", "reconciling"})
            t.status = "cancelling" if active else "cancelled"
            t.version += 1
            self.event(s, t, "cancel_requested", actor["id"])
            batch_id = run.batch_id if run else None
            self._receipt(s, actor["tenant_id"], "cancel:" + tid, key, body.model_dump(), self._task_dict(s, t))
        if batch_id:
            try:
                await self.engine.cancel(batch_id)
            except Exception:
                pass
        return self.get(actor, tid)

    def review(self, actor, tid, body, key):
        self.enabled()
        self.cases.require(actor, "admin", "reviewer")
        with self.db.session() as s:
            t = self.locked(s, actor, tid)
            if self._review_replay(s, actor, tid, key, body.model_dump()):
                return self._task_dict(s, t)
            if t.version != body.version or t.status not in {"awaiting_asset_review", "approved", "rejected"}:
                raise ServiceError("Assets not ready for this review")
            p = self.cases.scoped(s, v.PlanSnapshot, t.tenant_id, t.plan_id)
            self._fresh(s, t, p)
            a = self.cases.scoped(s, v.VisualAsset, t.tenant_id, body.asset_id)
            if a.task_id != t.id or a.plan_id != p.id or a.content_hash != body.asset_hash:
                raise ServiceError("Asset review subject mismatch")
            if body.decision == "approve" and (
                a.qa.get("status") != "passed" or a.status not in {"awaiting_review", "rejected"}
            ):
                raise ServiceError("QA must pass before business approval", 403)
            if a.status == "approved":
                raise ServiceError("Approved asset is immutable; revise task")
            a.status = "approved" if body.decision == "approve" else "rejected"
            s.add(
                v.VisualReview(
                    tenant_id=t.tenant_id,
                    case_id=t.case_id,
                    task_id=t.id,
                    subject_id=a.id,
                    subject_hash=a.content_hash,
                    scope="asset",
                    reviewer_id=actor["id"],
                    decision=body.decision,
                    idempotency_key=key,
                    fingerprint=fingerprint(body.model_dump()),
                    data={"comment": body.comment},
                )
            )
            s.flush()
            states = list(
                s.scalars(
                    select(v.VisualAsset.status).where(v.VisualAsset.task_id == t.id, v.VisualAsset.plan_id == p.id)
                )
            )
            t.status = (
                "approved"
                if "approved" in states
                else "awaiting_asset_review"
                if "awaiting_review" in states
                else "rejected"
            )
            t.version += 1
            self.event(s, t, "asset.reviewed", actor["id"], decision=body.decision)
            return self._task_dict(s, t)

    def _deliverable(self, s, tenant, tid, asset_ids):
        t = self.cases.scoped(s, v.VisualTask, tenant, tid)
        p = self.cases.scoped(s, v.PlanSnapshot, tenant, t.plan_id)
        self._fresh(s, t, p)
        assets = []
        for identity in dict.fromkeys(asset_ids):
            a = self.cases.scoped(s, v.VisualAsset, tenant, identity)
            if a.task_id != tid or a.plan_id != p.id or a.status != "approved" or a.qa.get("status") != "passed":
                raise ServiceError("Only current human-approved assets may be delivered", 403)
            if not self.storage.verify(a.storage_ref, a.content_hash):
                raise ServiceError("Asset integrity failure")
            assets.append(a)
        if not assets:
            raise ServiceError("Approved assets required", 422)
        return t, p, assets

    def attach(self, actor, tid, body, key):
        self.enabled()
        self.cases.require(actor, "admin", "operator", "reviewer")
        with self.db.session() as s:
            old = s.scalar(
                select(v.BuyerProposal).where(
                    v.BuyerProposal.tenant_id == actor["tenant_id"],
                    v.BuyerProposal.task_id == tid,
                    v.BuyerProposal.idempotency_key == key,
                )
            )
            if old:
                if old.fingerprint != fingerprint(body.model_dump()):
                    raise ServiceError("Idempotency payload mismatch")
                return m.row_dict(old)
            t = self.locked(s, actor, tid, body.version)
            case = self.cases.lock_case(s, t.tenant_id, t.case_id, body.case_version)
            self.cases.ensure_no_outbound_inflight(s, case)
            _, p, assets = self._deliverable(s, t.tenant_id, tid, body.asset_ids)
            if case.status in {"RESEARCHING", "CLOSED"}:
                raise ServiceError("Case is not available for proposal revision")
            proposal = v.BuyerProposal(
                id=m.uid(),
                tenant_id=t.tenant_id,
                case_id=t.case_id,
                task_id=tid,
                idempotency_key=key,
                fingerprint=fingerprint(body.model_dump()),
                data={
                    "requirement": p.data["requirement"],
                    "product": p.data["product"],
                    "truth_snapshot_id": p.truth_snapshot_id,
                    "plan_id": p.id,
                    "plan_hash": p.content_hash,
                    "asset_ids": [a.id for a in assets],
                    "assets": [
                        {
                            "id": a.id,
                            "sha256": a.content_hash,
                            "mime_type": a.mime_type,
                            "source_asset_ids": p.data["source_asset_ids"],
                            "reviewed": True,
                        }
                        for a in assets
                    ],
                    "concept": p.data.get("output_is_concept", True),
                    "product_concept": p.data["concept"],
                    "disclaimer": DISCLAIMER,
                    "buyer_questions": ["Please confirm the preferred variant, color and Logo placement."],
                    "supplier_questions": ["Please confirm final specifications and manufacturing feasibility."],
                    "mock": any(a.data.get("mock") for a in assets),
                },
            )
            s.add(proposal)
            s.flush()
            self.cases.save_artifact(s, case, "visual_proposal", proposal.data, {"proposal_id": proposal.id})
            # New report artifact revision preserves the original report and its evidence snapshot.
            try:
                oldreport = self.cases.current_artifact(s, case.tenant_id, case.id, "report")
                raw = self.storage.get(oldreport.storage_ref).decode()
                try:
                    report = json.loads(raw)
                    report["visual_proposal"] = proposal.data
                except (json.JSONDecodeError, TypeError):
                    report = raw + "\n\n## Visual Proposal\n" + json.dumps(proposal.data, ensure_ascii=False)
                self.cases.save_artifact(s, case, "report", report, {"proposal_id": proposal.id})
            except ServiceError:
                pass
            if body.update_draft:
                draftversion = self.cases.current_artifact(s, case.tenant_id, case.id, "draft")
                draft = json.loads(self.storage.get(draftversion.storage_ref))
                addition = (
                    "\n\nWe have prepared an internally reviewed visual proposal for your consideration. Please confirm your preferred variant, color and Logo placement. "
                    + DISCLAIMER
                )
                draft["body_text"] = draft.get("body_text", "") + addition
                draft["visual_attachment_ids"] = [a.id for a in assets]
                draft["visual_proposal_id"] = proposal.id
                case.version += 1
                self.cases.save_artifact(
                    s,
                    case,
                    "draft",
                    draft,
                    {"visual_proposal_id": proposal.id, "quality_passed": case.data.get("quality_passed", False)},
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
                s.execute(
                    update(m.Task)
                    .where(
                        m.Task.tenant_id == case.tenant_id,
                        m.Task.case_id == case.id,
                        m.Task.task_type == "prepare_approval",
                        m.Task.status == "WAITING_HUMAN",
                    )
                    .values(status="CANCELLED")
                )
                if case.status != "NEW":
                    self.cases.transition(s, case, "NEEDS_REVIEW")
                self.cases.prepare_approval(s, case)
                if case.workflow_run_id:
                    run = self.cases.scoped(s, m.WorkflowRun, case.tenant_id, case.workflow_run_id)
                    run.data = {**run.data, "refresh_approval": True}
                    run.status = "PENDING"
            t.status = "attached_to_proposal"
            t.version += 1
            self.event(s, t, "proposal.attached", actor["id"])
            return {**m.row_dict(proposal), "proposal_id": proposal.id, "case_version": case.version}

    def validate_delivery(self, s, case, draft):
        ids = draft.get("visual_attachment_ids", [])
        if not ids:
            return
        pid = draft.get("visual_proposal_id")
        p = self.cases.scoped(s, v.BuyerProposal, case.tenant_id, pid)
        if p.case_id != case.id or sorted(ids) != sorted(p.data["asset_ids"]):
            raise ServiceError("Visual proposal mismatch", 403)
        self._deliverable(s, case.tenant_id, p.task_id, ids)
        if p.data.get("mock"):
            raise ServiceError("Mock visual assets cannot be externally delivered", 403)

    def content(self, actor, identity, source=False):
        with self.db.session() as s:
            a = self.cases.scoped(s, v.SourceAsset if source else v.VisualAsset, actor["tenant_id"], identity)
            raw = self.storage.get(a.storage_ref)
            if hashlib.sha256(raw).hexdigest() != a.content_hash:
                raise ServiceError("Asset integrity failure")
            return raw, a.mime_type

    def export(self, actor, pid):
        with self.db.session() as s:
            p = self.cases.scoped(s, v.BuyerProposal, actor["tenant_id"], pid)
            _, _, assets = self._deliverable(s, p.tenant_id, p.task_id, p.data["asset_ids"])
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("proposal.json", json.dumps(p.data, indent=2, ensure_ascii=False))
                z.writestr(
                    "README.txt",
                    DISCLAIMER
                    + "\n"
                    + (
                        "MOCK FIXTURE — NOT FOR EXTERNAL DELIVERY"
                        if p.data.get("mock")
                        else "Prepared materials; no email has been sent."
                    ),
                )
                for a in assets:
                    z.writestr(
                        a.id + {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[a.mime_type],
                        self.storage.get(a.storage_ref),
                    )
            return output.getvalue()
