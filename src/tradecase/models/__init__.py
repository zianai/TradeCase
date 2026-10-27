"""Version 1 business contracts, independent of an Agent session or model provider.

Unknown information remains null. The contracts validate provenance structure;
they do not establish the truth of arbitrary natural-language claims.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("must be a UTC ISO 8601 timestamp") from exc
    if not (value.endswith("Z") or value.endswith("+00:00")) or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must explicitly use UTC (Z or +00:00)")
    return value


def source_url(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("URL cannot contain whitespace or control characters")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use http or https and include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL cannot contain credentials")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc
    return value


def relative_reference(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise ValueError("reference must be a relative path inside the Case")
    if any(ord(character) < 32 for character in value):
        raise ValueError("reference cannot contain control characters")
    return value


def identifier(value: str) -> str:
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError("identifier must contain only letters, digits, dot, underscore or hyphen")
    return value


def email_address(value: str) -> str:
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
        raise ValueError("invalid email address syntax")
    return value


def iso_date(value: str) -> str:
    date.fromisoformat(value)
    return value


UTC = Annotated[str, AfterValidator(utc_timestamp)]
URL = Annotated[str, AfterValidator(source_url)]
Reference = Annotated[str, AfterValidator(relative_reference)]
Identifier = Annotated[str, AfterValidator(identifier)]
Email = Annotated[str, AfterValidator(email_address)]
Nonempty = Annotated[str, Field(min_length=1)]
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Date = Annotated[str, AfterValidator(iso_date)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0"] = "1.0"


class FileRecord(Contract):
    filename: Nonempty
    content_type: Nonempty
    size_bytes: int = Field(ge=0)
    sha256: SHA256 | None = None
    disposition: str | None = None
    source_ref: Reference | None = None


class CaseInput(Contract):
    case_id: Identifier
    received_at: UTC
    buyer_message: Nonempty
    buyer_email: Email | None = None
    buyer_company_hint: str | None = None
    buyer_website_hint: URL | None = None
    seller_profile_ref: Reference | None = None
    product_summary: str | None = None
    origin_country: str | None = None
    target_country: str | None = None
    sales_channel: str | None = None
    platform: str | None = None
    files: list[FileRecord] = Field(default_factory=list)
    user_constraints: list[str] = Field(default_factory=list)
    is_synthetic: bool = False
    parsing_warnings: list[str] = Field(default_factory=list)
    raw_content: str | None = None
    raw_sha256: SHA256 | None = None
    raw_source_ref: Reference | None = None
    raw_bytes_base64: str | None = None

    @model_validator(mode="after")
    def original_bytes_integrity(self):
        if self.raw_bytes_base64 is not None:
            try:
                original = base64.b64decode(self.raw_bytes_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("raw_bytes_base64 must contain valid base64") from exc
            if not self.raw_sha256 or hashlib.sha256(original).hexdigest() != self.raw_sha256:
                raise ValueError("raw_sha256 must match the original bytes in raw_bytes_base64")
        return self


class SellerContext(Contract):
    company_name: str | None = None
    website: URL | None = None
    product_summary: str | None = None
    product_attributes: dict[str, str | bool | None] = Field(default_factory=dict)
    allowed_claims: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    is_synthetic: bool = False


class Candidate(Contract):
    candidate_id: Identifier
    name: Nonempty
    website: URL | None = None
    domain: str | None = None
    country: str | None = None
    registry_id: str | None = None
    identity_status: Literal["unverified", "supported", "ambiguous"] = "unverified"
    evidence_ids: list[Identifier] = Field(default_factory=list)
    is_synthetic: bool = False


class Evidence(Contract):
    evidence_id: Identifier
    claim: Nonempty
    source_url: URL | None = None
    source_type: Literal[
        "official_site", "government", "platform_official", "registry", "news", "directory",
        "user_provided", "search_snippet", "other",
    ]
    source_title: str | None = None
    captured_at: UTC
    excerpt: str | None = None
    locator: str | None = None
    retrieved_by: Nonempty
    entity_candidate_id: Identifier | None = None
    assertion_status: Literal["supported", "contradicted", "unverified"] = "unverified"
    confidence_label: Literal["high", "medium", "low"] = "low"
    is_synthetic: bool
    local_snapshot_ref: Reference | None = None

    @model_validator(mode="after")
    def require_support_location(self):
        if self.assertion_status != "unverified":
            if not (self.excerpt and self.excerpt.strip()) and not (self.locator and self.locator.strip()):
                raise ValueError("supported or contradicted evidence requires excerpt or locator")
            if not self.source_url and not self.local_snapshot_ref:
                raise ValueError("supported or contradicted evidence requires URL or local snapshot")
        return self


class Contact(Contract):
    email: Email
    source_class: Literal["public", "inferred", "user_provided", "unknown"] = "unknown"
    source_url: URL | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)
    verified: bool = False
    send_allowed: Literal[False] = False
    domain_relation: Literal["same_domain", "parent_domain", "third_party", "free_mail", "unknown"] = "unknown"

    @model_validator(mode="after")
    def verified_requires_public_source(self):
        if self.verified and (self.source_class != "public" or not self.source_url or not self.evidence_ids):
            raise ValueError("verified contact requires a public source URL and evidence; inferred is not verified")
        return self


class BuyerProfile(Contract):
    case_id: Identifier
    candidate_ids: list[Identifier] = Field(default_factory=list)
    selected_candidate_id: Identifier | None = None
    company_name: str | None = None
    website: URL | None = None
    domain: str | None = None
    country: str | None = None
    buyer_role: str | None = None
    inquiry_relationship: str | None = None
    contacts: list[Contact] = Field(default_factory=list)
    claim_evidence_map: dict[str, list[Identifier]] = Field(default_factory=dict)
    unresolved_items: list[str] = Field(default_factory=list)
    is_synthetic: bool = False

    @model_validator(mode="after")
    def selected_is_candidate(self):
        if self.selected_candidate_id and self.selected_candidate_id not in self.candidate_ids:
            raise ValueError("selected_candidate_id must be included in candidate_ids")
        return self


class Signal(Contract):
    value: Literal["supported", "contradicted", "unknown"] = "unknown"
    evidence_ids: list[Identifier] = Field(default_factory=list)
    rationale: str = ""

    @model_validator(mode="after")
    def known_requires_evidence(self):
        if self.value != "unknown" and not self.evidence_ids:
            raise ValueError("supported or contradicted signal requires evidence_ids")
        return self


SIGNAL_NAMES = {
    "verified_identity", "buyer_role_evidence", "product_fit_evidence", "inquiry_specificity", "contactability",
}


class Assessment(Contract):
    case_id: Identifier
    rule_version: Nonempty = "priority-v1"
    signals: dict[str, Signal] = Field(default_factory=dict)
    evidence_coverage: float = Field(default=0.0, ge=0, le=1)
    score: int | None = Field(default=None, ge=0, le=100)
    decision: Literal["high_priority", "normal_priority", "low_priority", "needs_review"] = "needs_review"
    reason_codes: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    is_synthetic: bool = False

    @model_validator(mode="after")
    def signal_contract(self):
        if set(self.signals) - SIGNAL_NAMES:
            raise ValueError("unknown assessment signal name")
        if self.decision == "high_priority":
            for key in ("verified_identity", "buyer_role_evidence"):
                if key not in self.signals or self.signals[key].value != "supported":
                    raise ValueError("high_priority requires supported identity and buyer role")
            if self.score is None:
                raise ValueError("high_priority requires a numeric score")
        return self


class ComplianceCheck(Contract):
    check_id: Identifier
    check_type: Literal["country", "platform"]
    jurisdiction: str | None = None
    platform: str | None = None
    product_scope: Nonempty
    rule_id: Identifier
    rule_version: str | None = None
    effective_date: Date | None = None
    checked_at: UTC
    source_url: URL | None = None
    required_attributes: list[str] = Field(default_factory=list)
    observed_attributes: list[str] = Field(default_factory=list)
    status: Literal["pass", "fail", "warning", "needs_verification", "needs_context", "not_applicable"]
    severity: Literal["critical", "high", "medium", "low", "info"]
    rationale: Nonempty
    affected_content: str | None = None
    suggested_action: Nonempty
    evidence_ids: list[Identifier] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    is_synthetic: bool = False

    @model_validator(mode="after")
    def pass_requires_research_context(self):
        if self.status == "pass":
            if not self.source_url or not self.rule_version or not self.evidence_ids:
                raise ValueError("pass requires source_url, rule_version and evidence_ids")
            if self.missing_items or not set(self.required_attributes).issubset(self.observed_attributes):
                raise ValueError("pass cannot have missing required attributes")
            if self.check_type == "country" and not self.jurisdiction:
                raise ValueError("country pass requires jurisdiction")
            if self.check_type == "platform" and not self.platform:
                raise ValueError("platform pass requires platform")
        return self


class ComplianceResult(Contract):
    case_id: Identifier
    checks: list[ComplianceCheck] = Field(default_factory=list)
    is_synthetic: bool = False


class NextAction(Contract):
    action_id: Identifier
    priority: Literal["high", "normal", "low"]
    description: Nonempty
    owner_type: Literal["human", "agent"]
    deadline_suggestion: str | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)


class NextActions(Contract):
    case_id: Identifier
    actions: list[NextAction] = Field(default_factory=list)
    is_synthetic: bool = False


class Manifest(Contract):
    case_id: Identifier
    state: Literal["created", "running", "needs_input", "needs_review", "completed", "failed", "cancelled"] = "created"
    current_stage: Nonempty = "init"
    created_at: UTC
    updated_at: UTC
    input_hash: SHA256
    artifact_index: dict[Reference, SHA256] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def chronological(self):
        if datetime.fromisoformat(self.updated_at) < datetime.fromisoformat(self.created_at):
            raise ValueError("updated_at cannot precede created_at")
        return self


class TaskEvent(Contract):
    case_id: Identifier
    event_id: Identifier
    timestamp: UTC
    event_type: Nonempty
    stage: Nonempty
    revision: int = Field(ge=0)
    detail: dict[str, Any] = Field(default_factory=dict)
