"""Reviewer-controlled promotion of captured evidence into the retained business kernel.

Reviewers select existing observations and declare source roles. This endpoint
cannot create source text, change a capture URL, or turn internal knowledge into
an official source. A review is a human judgment with immutable inputs, not proof
that a network fetch or authoritative legal validation occurred.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from tradecase.assessment import calculate_assessment
from tradecase.buyer_research import research_from_local
from tradecase.case_store import CaseStore
from tradecase.compliance import evaluate_compliance
from tradecase.models import BuyerProfile, Candidate, Evidence, RuleSet, SellerContext, Signal
from tradecase.platform import db as m
from tradecase.platform.services import ServiceError, fingerprint
from tradecase.providers import validate_public_url
from tradecase.util import json_bytes, utc_now
from tradecase.validation import validate_case

SourceType = Literal[
    "official_site",
    "government",
    "platform_official",
    "registry",
    "news",
    "directory",
    "user_provided",
    "search_snippet",
    "other",
]


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=64)
    entity_candidate_id: str | None = Field(default=None, max_length=100)
    assertion_status: Literal["supported", "contradicted", "unverified"] = "unverified"
    source_type: SourceType = "other"
    source_permission_confirmed: Literal[True]
    source_role_confirmed: Literal[True]
    confidence_label: Literal["high", "medium", "low"] = "medium"


class ReviewInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_version: int = Field(ge=1)
    candidates: list[Candidate] = Field(default_factory=list, max_length=50)
    profile: BuyerProfile
    signals: dict[str, Signal] = Field(default_factory=dict)
    seller_context: SellerContext = Field(default_factory=SellerContext)
    rules: RuleSet = Field(default_factory=RuleSet)
    evidence_bindings: list[EvidenceBinding] = Field(default_factory=list, max_length=100)
    current_rules_confirmed: bool = False
    review_note: str = Field(min_length=1, max_length=4000)


class ReviewInputsService:
    def __init__(self, service):
        self.service, self.db = service, service.db

    def template(self, tenant, case_id):
        case = self.service.get(tenant, case_id)
        prepared = research_from_local(case["inquiry"], [])
        result = {
            "case_version": case["version"],
            "candidates": prepared["candidates"],
            "profile": prepared["profile"],
            "signals": {},
            "seller_context": SellerContext().model_dump(),
            "rules": {"rules": []},
            "evidence_bindings": [],
            "current_rules_confirmed": False,
            "review_note": "",
        }
        prior = None
        with self.db.session() as session:
            if case["data"].get("review_inputs_ref"):
                version = self.service.scoped(session, m.ArtifactVersion, tenant, case["data"]["review_inputs_ref"])
                prior = json.loads(self.service.storage.get(version.storage_ref))
                result = prior["request"]
                result["case_version"] = case["version"]
                result["current_rules_confirmed"] = False
                result["review_note"] = ""
                for binding in result["evidence_bindings"]:
                    binding["source_permission_confirmed"] = False
                    binding["source_role_confirmed"] = False
            else:
                links = session.scalars(
                    select(m.ClaimEvidenceLink).where(
                        m.ClaimEvidenceLink.tenant_id == tenant, m.ClaimEvidenceLink.case_id == case_id
                    )
                )
                for link in links:
                    source = self.service.scoped(session, m.Source, tenant, link.source_id)
                    role = source.source_type if source.source_type in SourceType.__args__ else "other"
                    result["evidence_bindings"].append(
                        {
                            "evidence_id": "ev-" + fingerprint([link.claim_id, link.source_id])[:24],
                            "claim_id": link.claim_id,
                            "source_id": link.source_id,
                            "entity_candidate_id": None,
                            "assertion_status": "unverified",
                            "source_type": role,
                            "confidence_label": "low",
                            "source_permission_confirmed": False,
                            "source_role_confirmed": False,
                        }
                    )
        return {
            "input": result,
            "last_review_artifact_id": case["data"].get("review_inputs_ref"),
            "instructions": [
                "Use evidence_id aliases in candidates, profile.claim_evidence_map, signals and rules.",
                "Source text/URL come only from existing captures; inspect the snapshot and exact quoted claim.",
                "Confirm source permission and source role separately for every binding before submitting.",
                "Confirm current official rule scope/dates explicitly; missing context remains unknown.",
                "This records human judgments, not automatic source truth or legal assurance.",
            ],
        }

    def _assemble(self, session, case, request, actor):
        inquiry = self.service.scoped(session, m.Inquiry, case.tenant_id, case.inquiry_id).data
        if request.profile.case_id != case.id:
            raise ServiceError("Reviewed profile belongs to another Case", 422)
        if len({binding.evidence_id for binding in request.evidence_bindings}) != len(request.evidence_bindings):
            raise ServiceError("Duplicate evidence aliases", 422)
        if any(rule.source_current for rule in request.rules.rules) and not request.current_rules_confirmed:
            raise ServiceError("Current official rules require explicit reviewer confirmation", 422)
        evidence, snapshots, declarations = [], {}, []
        roles = {}
        for binding in request.evidence_bindings:
            source = self.service.scoped(session, m.Source, case.tenant_id, binding.source_id)
            claim = self.service.scoped(session, m.Claim, case.tenant_id, binding.claim_id)
            if source.case_id != case.id or claim.case_id != case.id:
                raise ServiceError("Evidence belongs to another Case", 404)
            linked = session.scalar(
                select(m.ClaimEvidenceLink).where(
                    m.ClaimEvidenceLink.tenant_id == case.tenant_id,
                    m.ClaimEvidenceLink.case_id == case.id,
                    m.ClaimEvidenceLink.claim_id == claim.id,
                    m.ClaimEvidenceLink.source_id == source.id,
                )
            )
            if linked is None:
                raise ServiceError("Claim and source are not linked", 422)
            if source.status.upper() != "FETCHED" or not source.snapshot_ref or not source.snapshot_hash:
                raise ServiceError("Source has no available immutable snapshot", 422)
            expiry = source.data.get("expires_at")
            if expiry and binding.assertion_status == "supported":
                try:
                    current = datetime.fromisoformat(expiry) > m.utcnow()
                except (TypeError, ValueError):
                    current = False
                if not current:
                    raise ServiceError("Expired source cannot support a current decision; retain as historical context", 422)
            raw = self.service.storage.get(source.snapshot_ref)
            if hashlib.sha256(raw).hexdigest() != source.snapshot_hash:
                raise ServiceError("Source snapshot hash mismatch", 422)
            if len(raw) > 5 * 1024 * 1024:
                raise ServiceError("Reviewed snapshot exceeds compatibility limit", 422)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ServiceError("Reviewed snapshot must be inert UTF-8 text", 422) from None
            if not linked.excerpt or linked.excerpt not in text:
                raise ServiceError("Claim quote does not match the captured snapshot", 422)
            if roles.get(source.id, binding.source_type) != binding.source_type:
                raise ServiceError("One source cannot receive conflicting source roles in a review", 422)
            roles[source.id] = binding.source_type
            knowledge = (
                source.data.get("authority") == "user_provided_unverified"
                or source.url
                and source.url.startswith("knowledge:")
            )
            if knowledge and binding.source_type != "user_provided":
                raise ServiceError("Internal knowledge cannot be promoted to an official public source", 422)
            synthetic = bool(source.data.get("synthetic") or source.license_status == "SYNTHETIC")
            if synthetic and not case.data.get("synthetic"):
                raise ServiceError("Synthetic evidence cannot determine a real Case", 422)
            url = None if knowledge else source.url
            if url and not synthetic:
                try:
                    validate_public_url(url)
                except ValueError:
                    raise ServiceError("Reviewed source URL is not a permitted public URL", 422) from None
            snapshot_name = "snapshots/review-" + source.snapshot_hash + ".txt"
            snapshots[snapshot_name] = {"storage_ref": source.snapshot_ref, "sha256": source.snapshot_hash}
            item = Evidence(
                evidence_id=binding.evidence_id,
                claim=claim.statement,
                source_url=url,
                source_type=binding.source_type,
                source_title=source.title,
                captured_at=source.captured_at.isoformat(),
                excerpt=linked.excerpt,
                locator=linked.locator,
                retrieved_by="human-reviewed captured observation; reviewer=" + actor["id"],
                entity_candidate_id=binding.entity_candidate_id,
                assertion_status=binding.assertion_status,
                confidence_label=binding.confidence_label,
                is_synthetic=synthetic,
                local_snapshot_ref=snapshot_name,
            )
            evidence.append(item.model_dump(mode="json"))
            declarations.append(
                {
                    **binding.model_dump(),
                    "snapshot_hash": source.snapshot_hash,
                    "capture_url": source.url,
                    "captured_at": source.captured_at.isoformat(),
                    "original_source_type": source.source_type,
                    "retrieval_method": source.data.get("retrieval_method", "adapter_capture"),
                    "tested_live": bool(source.data.get("tested_live", False)),
                }
            )
        candidates = [c.model_dump(mode="json") for c in request.candidates]
        profile = request.profile.model_dump(mode="json")
        signals = {name: signal.model_dump(mode="json") for name, signal in request.signals.items()}
        seller = request.seller_context.model_dump(mode="json")
        rules = request.rules.model_dump(mode="json")
        timestamp = utc_now()
        try:
            assessment = calculate_assessment(inquiry, profile, candidates, evidence, signals)
            compliance = evaluate_compliance(inquiry, seller, evidence, rules, checked_at=timestamp)
            # Reuse all existing cross-artifact reference checks, not only schema parsing.
            with tempfile.TemporaryDirectory(prefix="tradecase-review-") as directory:
                store = CaseStore.create(Path(directory).resolve() / case.id, inquiry, seller)
                store.transition("running", "review_preflight")
                for name, metadata in snapshots.items():
                    store.save_snapshot(name, self.service.storage.get(metadata["storage_ref"]).decode())
                store.write("candidates.jsonl", candidates)
                store.write("evidence.jsonl", evidence)
                store.write("buyer_profile.json", profile)
                store.write("assessment.json", assessment)
                store.write("rules_snapshot.json", rules)
                store.write("compliance.json", compliance)
                errors = validate_case(store.path)
                if errors:
                    raise ValueError("; ".join(errors))
        except ValueError as exc:
            raise ServiceError("Review bundle validation failed: " + str(exc), 422) from None
        return {
            "schema_version": 1,
            "request": request.model_dump(mode="json"),
            "inquiry": inquiry,
            "candidates": candidates,
            "profile": profile,
            "signals": signals,
            "seller_context": seller,
            "rules": rules,
            "evidence": evidence,
            "snapshots": snapshots,
            "assessment": assessment,
            "compliance": compliance,
            "source_declarations": declarations,
            "reviewer_id": actor["id"],
            "reviewed_at": timestamp,
        }

    def submit(self, actor, case_id, request: ReviewInputs, key: str):
        self.service.require(actor, "admin", "reviewer")
        if not key or len(key) > 200:
            raise ServiceError("Bounded Idempotency-Key is required", 422)
        if len(json_bytes(request.model_dump(mode="json"))) > 1024 * 1024:
            raise ServiceError("Review bundle exceeds 1 MiB", 413)
        digest = fingerprint(request.model_dump(mode="json"))
        with self.db.session() as session:
            case = self.service.lock_case(session, actor["tenant_id"], case_id)
            prior = list(
                session.scalars(
                    select(m.ArtifactVersion)
                    .join(
                        m.Artifact,
                        (m.Artifact.id == m.ArtifactVersion.artifact_id)
                        & (m.Artifact.tenant_id == m.ArtifactVersion.tenant_id),
                    )
                    .where(
                        m.ArtifactVersion.tenant_id == case.tenant_id,
                        m.ArtifactVersion.case_id == case.id,
                        m.Artifact.kind == "review_inputs",
                    )
                )
            )
            existing = next((version for version in prior if version.data.get("idempotency_key") == key), None)
            if existing:
                if existing.data.get("request_fingerprint") != digest:
                    raise ServiceError("Review idempotency key reused for different inputs")
                return {
                    "artifact_id": existing.id,
                    "case_version": existing.data["case_version"],
                    "assessment": existing.data["assessment"],
                    "compliance": existing.data["compliance"],
                    "status": "REVIEW_INPUTS_SAVED",
                }
            if request.case_version != case.version:
                raise ServiceError("Case changed; reload review inputs")
            self.service.ensure_no_outbound_inflight(session, case)
            if case.status == "RESEARCHING":
                raise ServiceError("Wait for the running workflow before reviewing evidence")
            bundle = self._assemble(session, case, request, actor)
            case.version += 1
            bundle["case_version"] = case.version
            metadata = {
                "idempotency_key": key,
                "request_fingerprint": digest,
                "reviewer_id": actor["id"],
                "case_version": case.version,
                "assessment": bundle["assessment"],
                "compliance": bundle["compliance"],
            }
            version = self.service.save_artifact(session, case, "review_inputs", bundle, metadata)
            case.data = {
                **case.data,
                "review_inputs_ref": version.id,
                "research_status": "UNKNOWN",
                "quality_passed": False,
                "reviewed_inputs_by": actor["id"],
            }
            session.execute(
                update(m.Approval)
                .where(
                    m.Approval.tenant_id == case.tenant_id,
                    m.Approval.case_id == case.id,
                    m.Approval.status.in_(["PENDING", "APPROVED", "CHANGES_REQUESTED"]),
                )
                .values(status="INVALIDATED")
            )
            if case.workflow_run_id:
                workflow = self.service.scoped(session, m.WorkflowRun, case.tenant_id, case.workflow_run_id)
                workflow.status = "CANCELLED"
                workflow.lease_token = workflow.lease_until = workflow.lease_owner = None
                workflow.finished_at = m.utcnow()
            session.execute(
                update(m.Task)
                .where(
                    m.Task.tenant_id == case.tenant_id,
                    m.Task.case_id == case.id,
                    m.Task.status.in_(["READY", "PENDING", "WAITING_HUMAN", "BLOCKED"]),
                )
                .values(status="CANCELLED")
            )
            case.workflow_run_id = None
            if case.status not in {"NEW", "FAILED", "CLOSED"}:
                self.service.transition(session, case, "NEEDS_REVIEW")
            self.service.event(
                session,
                case.tenant_id,
                case.id,
                "review_inputs.accepted",
                {"artifact_id": version.id, "version": case.version},
                actor=actor["id"],
            )
            return {
                "artifact_id": version.id,
                "case_version": case.version,
                "assessment": bundle["assessment"],
                "compliance": bundle["compliance"],
                "status": "REVIEW_INPUTS_SAVED",
            }

    def bundle(self, tenant, case_id):
        case = self.service.get(tenant, case_id)
        identity = case["data"].get("review_inputs_ref")
        if not identity:
            return None
        with self.db.session() as session:
            version = self.service.scoped(session, m.ArtifactVersion, tenant, identity)
            if version.case_id != case_id:
                raise ServiceError("Review artifact belongs to another Case", 404)
            raw = self.service.storage.get(version.storage_ref)
            if hashlib.sha256(raw).hexdigest() != version.content_hash:
                raise ServiceError("Review artifact integrity failure")
            return json.loads(raw)
