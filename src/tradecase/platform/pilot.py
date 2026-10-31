"""Thin pilot intake and frozen review exports over existing Case/Evidence services.

No new queue, model loop, authorization authority or business acceptance is added.
Real input requires the existing OS-installed P7 grant before any storage write.
"""

from datetime import datetime
from typing import Literal

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from tradecase.p7_policy import PolicyDenied, ValidationRunPolicy, digest
from tradecase.platform import db as m
from tradecase.platform.contracts import CreateCase
from tradecase.platform.services import ServiceError


class PilotIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    raw_content: str = Field(min_length=1, max_length=100000)
    classification: Literal["synthetic", "public_licensed", "private_cleared", "restricted"]
    synthetic: bool
    dataset_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rights_reference: str = Field(min_length=1, max_length=1000)
    source_locator: str = Field(min_length=1, max_length=1000)
    captured_at: datetime
    retention_until: datetime

    @field_validator("captured_at", "retention_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value

    @field_validator("source_locator")
    @classmethod
    def locator_is_not_path(cls, value):
        if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("Locator must be relative metadata, not a filesystem path")
        return value

    @model_validator(mode="after")
    def validate_origin(self):
        if self.synthetic != (self.classification == "synthetic"):
            raise ValueError("Synthetic classification mismatch")
        if digest(self.raw_content.encode()) != self.dataset_sha256:
            raise ValueError("Input hash mismatch")
        if self.captured_at > m.utcnow() or self.retention_until <= m.utcnow():
            raise ValueError("Capture/retention period is not current")
        return self


class PilotService:
    def __init__(self, service):
        self.service = service

    @staticmethod
    def authorize_data(actor, metadata, input_hash):
        """Revalidate operator scope on each private read/write, including exports."""
        try:
            retained = datetime.fromisoformat(metadata["retention_until"])
            if retained.tzinfo is None or retained <= m.utcnow():
                raise PolicyDenied("RETENTION_EXPIRED")
            policy = ValidationRunPolicy.from_env("tradecase")
            context = policy.context()
            if (context.get("tenant_id") != actor["tenant_id"]
                    or context.get("dataset_id") != metadata["dataset_id"]
                    or context.get("input_hash") != input_hash
                    or context.get("rights_hash") != digest(metadata["rights_reference"].encode())):
                raise PolicyDenied("SUBJECT_MISMATCH")
            mapped = {"public_licensed": "public", "private_cleared": "redacted_business"}.get(metadata["classification"])
            if not mapped or context.get("data_classification") != mapped:
                raise PolicyDenied("DATA_SCOPE_DENIED")
            if policy.preflight({**context, "action": "inspect_customer_data"}, 0)["status"] != "allowed":
                raise PolicyDenied("AUTH_REQUIRED")
        except (PolicyDenied, OSError, KeyError, TypeError, ValueError):
            raise ServiceError("BLOCKED_EXTERNAL: current scoped operator data grant and retention required", 403) from None

    def intake(self, actor, request):
        self.service.require(actor, "admin", "reviewer", "operator")
        if request.classification == "restricted":
            raise ServiceError("BLOCKED_EXTERNAL: restricted data is not eligible", 403)
        if not request.synthetic:
            self.authorize_data(actor, request.model_dump(mode="json"), request.dataset_sha256)
        elif not self.service.settings.demo_enabled:
            raise ServiceError("Synthetic pilot intake is disabled", 403)
        metadata = request.model_dump(mode="json", exclude={"raw_content", "title"})
        # Equal input+provenance is the same logical sample even under a new HTTP key.
        key = "pilot:" + digest({"tenant": actor["tenant_id"], "metadata": metadata})
        return self.service.create(
            actor, CreateCase(title=request.title, raw_content=request.raw_content), key,
            pilot_metadata=metadata,
        )

    def export_scope(self, actor, case_id):
        """Only IDs/hashes/version; this is an authorization subject, never a grant."""
        case = self.service.get(actor["tenant_id"], case_id)
        evidence = self.service.evidence(actor["tenant_id"], case_id)
        with self.service.db.session() as session:
            inquiry = self.service.scoped(session, m.Inquiry, actor["tenant_id"], case["inquiry_id"])
            input_hash = inquiry.raw_hash
        sources = sorted(evidence["sources"], key=lambda item: item["id"])
        mixed = any(source["data"].get("synthetic") is not True for source in sources)
        pilot = case["data"].get("pilot", {})
        # Any manual/unknown source is a new data subject; Case.synthetic does not
        # establish the provenance or permission of its added sources.
        classification = ("sensitive_business" if mixed else
                          "synthetic" if case["synthetic"] else
                          "public" if pilot.get("classification") == "public_licensed" else "redacted_business")
        return {"case_id": case_id, "case_version": case["version"], "tenant_id": actor["tenant_id"],
                "dataset_id": pilot.get("dataset_id", case_id), "data_classification": classification,
                "requires_data_grant": not case["synthetic"] or mixed,
                "input_hash": digest(jsonable_encoder({"case_id": case_id, "case_version": case["version"],
                    "inquiry_hash": input_hash, "sources": sources,
                    "claims": sorted(evidence["claims"], key=lambda x: x["id"]),
                    "links": sorted(evidence["links"], key=lambda x: x["id"]), "conflicts": evidence["conflicts"]})),
                "rights_hash": digest({"pilot": pilot, "sources": [{"id": source["id"],
                    "snapshot_hash": source["snapshot_hash"], "license_status": source["license_status"],
                    "authority": source["data"].get("authority"), "synthetic": source["data"].get("synthetic"),
                    "expires_at": source["data"].get("expires_at")} for source in sources]})}

    def authorize_export(self, actor, case, scope):
        if not scope["requires_data_grant"]:
            return
        try:
            pilot = case["data"].get("pilot", {})
            if not case["synthetic"] and not pilot:
                raise PolicyDenied("ORIGIN_UNKNOWN")
            if pilot:
                retained = datetime.fromisoformat(pilot["retention_until"])
                if retained.tzinfo is None or retained <= m.utcnow():
                    raise PolicyDenied("RETENTION_EXPIRED")
            policy = ValidationRunPolicy.from_env("tradecase")
            context = policy.context()
            for key in ("tenant_id", "case_id", "dataset_id", "input_hash", "rights_hash", "data_classification"):
                if context.get(key) != scope[key]:
                    raise PolicyDenied("SUBJECT_MISMATCH")
            if policy.preflight({**context, "action": "inspect_customer_data"}, 0)["status"] != "allowed":
                raise PolicyDenied("AUTH_REQUIRED")
        except (PolicyDenied, OSError, KeyError, TypeError, ValueError):
            raise ServiceError("BLOCKED_EXTERNAL: exact current export subject and data-read grant required", 403) from None

    def export(self, actor, case_id):
        tenant = actor["tenant_id"]
        case = self.service.get(tenant, case_id)
        scope = self.export_scope(actor, case_id)
        self.authorize_export(actor, case, scope)
        with self.service.db.session() as session:
            inquiry = self.service.scoped(session, m.Inquiry, tenant, case["inquiry_id"])
            runs = session.scalars(select(m.AgentRun).where(m.AgentRun.tenant_id == tenant, m.AgentRun.case_id == case_id)).all()
            input_hash = inquiry.raw_hash
            run_versions = [{"id": run.id, "model": run.model, "provider": run.provider,
                             "provenance": run.data.get("provenance", {}), "status": run.status,
                             "result_refs": run.artifact_refs} for run in runs]
        evidence = self.service.evidence(tenant, case_id)
        source_map = {source["id"]: source for source in evidence["sources"]}
        citations = []
        for link in evidence["links"]:
            source = source_map[link["source_id"]]
            raw = self.service.source_body(tenant, case_id, source["id"]) if source["snapshot_ref"] else b""
            excerpt = link["excerpt"] or ""
            locatable = bool(excerpt and excerpt in raw.decode("utf-8", errors="replace"))
            citations.append({
                "claim_id": link["claim_id"], "source_id": source["id"], "relation": link["relation"],
                "excerpt": excerpt, "locator": link["locator"], "snapshot_sha256": source["snapshot_hash"],
                "captured_at": source["captured_at"].isoformat() if source["captured_at"] else None,
                "rights_status": source["license_status"],
                "current_validity": source["current_validity"], "locatable": locatable,
            })
        card = {
            "schema_version": "1.0.0", "project": "tradecase", "case_id": case_id,
            "case_version": case["version"], "input_sha256": input_hash,
            "synthetic": not scope["requires_data_grant"], "classification": scope["data_classification"],
            "authorization_subject": scope,
            "distribution_policy": "private_review_only; never auto-publish",
            "pilot_provenance": case["data"].get("pilot"),
            "claims": [{"id": x["id"], "statement": x["statement"], "classification": x["classification"],
                        "status": x["status"]} for x in evidence["claims"]],
            "citations": sorted(citations, key=lambda x: (x["claim_id"], x["source_id"])),
            "conflicts": evidence["conflicts"], "run_versions": sorted(run_versions, key=lambda x: x["id"]),
            "human_review_status": "pending", "business_evaluation": None,
            "human_baseline_minutes": None, "human_review_minutes": None,
            "critical_errors": None, "external_send_authorized": False,
        }
        card["claims"].sort(key=lambda x: x["id"])
        if self.export_scope(actor, case_id) != scope:
            raise ServiceError("Export subject changed during read; review the new scope", 409)
        self.authorize_export(actor, self.service.get(tenant, case_id), scope)
        return {**card, "subject_sha256": digest(card)}
