"""HTTP inputs are data, never execution authority."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCase(Input):
    title: str = Field(default="New inquiry", min_length=1, max_length=300)
    raw_content: str = Field(default="", max_length=2_000_000)
    source_type: Literal["text", "manual", "eml", "webhook"] = "text"
    buyer_email: str | None = Field(default=None, max_length=320)
    buyer_company: str | None = Field(default=None, max_length=300)
    buyer_country: str | None = Field(default=None, max_length=100)
    product: str | None = Field(default=None, max_length=1000)
    website: str | None = Field(default=None, max_length=2000)
    platform: str | None = Field(default=None, max_length=100)
    fixture: (
        Literal[
            "case_strong",
            "case_name_collision",
            "case_missing_platform",
            "case_regulation_unknown",
            "case_inferred_email",
            "case_prompt_injection",
            "case_resume_after_failure",
        ]
        | None
    ) = None


class Decision(Input):
    decision: Literal["approve", "approved", "reject", "rejected", "request_changes", "request_evidence"]
    artifact_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_version: int = Field(ge=1)
    comment: str = Field(default="", max_length=4000)


class EditDraft(Input):
    body: str = Field(min_length=1, max_length=50000)
    subject: str = Field(min_length=1, max_length=500)
    case_version: int = Field(ge=1)


class FollowUpInput(Input):
    next_action: str = Field(min_length=1, max_length=4000)
    due_at: datetime | None = None
    assignee: str | None = Field(default=None, max_length=64)

    @field_validator("due_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at requires timezone")
        return value


class Postpone(Input):
    due_at: datetime
    version: int | None = None

    @field_validator("due_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("due_at requires timezone")
        return value


class SendRequest(Input):
    approval_id: str
    artifact_hash: str
    case_version: int


class SendApproval(Input):
    case_version: int
    artifact_hash: str
    target: str = Field(min_length=3, max_length=320)
    channel: Literal["mail", "crm"] = "mail"


class CaseMetadata(Input):
    case_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    priority: int | None = Field(default=None, ge=0, le=100)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value):
        if value is not None and any(not x.strip() or len(x) > 60 for x in value):
            raise ValueError("tags must contain 1–60 characters")
        return sorted(set(x.strip() for x in value)) if value is not None else None


class Reconciliation(Input):
    receipt: str = Field(min_length=1, max_length=4000)
    delivered: bool


class CloseCase(Input):
    case_version: int = Field(ge=1)


class CancelAction(Input):
    case_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
