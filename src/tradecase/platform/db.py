"""Business persistence; workflow checkpoints and queues are never business truth.

PostgreSQL is the deployment backend. SQLite is intentionally supported for
repeatable offline tests and a single-machine demonstration. IDs are opaque;
every service query must include tenant_id, even though IDs are globally unique.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


def uid() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Preserve aware UTC values on SQLite as well as PostgreSQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Scoped(Record):
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), index=True)


def scoped_constraints(*constraints):
    return (UniqueConstraint("tenant_id", "id"), *constraints)


def case_fk():
    return ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"])


class Organization(Record, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Scoped, Base):
    __tablename__ = "users"
    __table_args__ = scoped_constraints(UniqueConstraint("token_hash"))
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Inquiry(Scoped, Base):
    __tablename__ = "inquiries"
    __table_args__ = scoped_constraints()
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    raw_content_ref: Mapped[str] = mapped_column(String(300), default="")
    raw_hash: Mapped[str] = mapped_column(String(64), default="")
    parsing_version: Mapped[str] = mapped_column(String(32), default="1")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class BuyerEntity(Scoped, Base):
    __tablename__ = "buyer_entities"
    __table_args__ = scoped_constraints()
    legal_name: Mapped[str | None] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    country: Mapped[str | None] = mapped_column(String(100))
    registry_id: Mapped[str | None] = mapped_column(String(200))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Case(Scoped, Base):
    __tablename__ = "cases"
    __table_args__ = scoped_constraints(
        UniqueConstraint("tenant_id", "idempotency_key"),
        ForeignKeyConstraint(["tenant_id", "inquiry_id"], ["inquiries.tenant_id", "inquiries.id"]),
        ForeignKeyConstraint(["tenant_id", "buyer_entity_id"], ["buyer_entities.tenant_id", "buyer_entities.id"]),
        CheckConstraint("version >= 1"),
    )
    inquiry_id: Mapped[str] = mapped_column(String(64))
    buyer_entity_id: Mapped[str | None] = mapped_column(String(64))
    workflow_run_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300), default="Untitled inquiry")
    status: Mapped[str] = mapped_column(String(40), default="NEW", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class WorkflowRun(Scoped, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("thread_id"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(100), default=uid)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    version: Mapped[int] = mapped_column(Integer, default=1)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Task(Scoped, Base):
    __tablename__ = "case_tasks"
    __table_args__ = scoped_constraints(
        case_fk(), UniqueConstraint("tenant_id", "case_id", "task_type", "input_fingerprint"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0"),
        Index("ix_task_ready", "status", "next_attempt_at", "priority"),
    )
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    task_type: Mapped[str] = mapped_column(String(100))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    artifact_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_class: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class TaskAttempt(Scoped, Base):
    __tablename__ = "task_attempts"
    __table_args__ = scoped_constraints(
        case_fk(), ForeignKeyConstraint(["tenant_id", "task_id"], ["case_tasks.tenant_id", "case_tasks.id"]),
        UniqueConstraint("tenant_id", "task_id", "attempt_number"),
        UniqueConstraint("lease_token"),
    )
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    lease_token: Mapped[str] = mapped_column(String(64))
    worker: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_class: Mapped[str | None] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentRun(Scoped, Base):
    __tablename__ = "agent_runs"
    __table_args__ = scoped_constraints(
        case_fk(), ForeignKeyConstraint(["tenant_id", "attempt_id"], ["task_attempts.tenant_id", "task_attempts.id"]),
        ForeignKeyConstraint(["tenant_id", "task_id"], ["case_tasks.tenant_id", "case_tasks.id"]),
        UniqueConstraint("tenant_id", "attempt_id"),
    )
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    attempt_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100), default="")
    runtime_id: Mapped[str | None] = mapped_column(String(200))
    session_ref: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    cost: Mapped[float] = mapped_column(Float, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(100))
    error_class: Mapped[str | None] = mapped_column(String(100))
    tool_events: Mapped[list] = mapped_column(JSON, default=list)
    artifact_refs: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Source(Scoped, Base):
    __tablename__ = "sources"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "fingerprint"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default=uid)
    url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(60), default="user_provided")
    title: Mapped[str] = mapped_column(String(500), default="")
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    license_status: Mapped[str] = mapped_column(String(60), default="UNKNOWN")
    status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    snapshot_ref: Mapped[str | None] = mapped_column(String(300))
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Claim(Scoped, Base):
    __tablename__ = "claims"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "fingerprint"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default=uid)
    subject: Mapped[str] = mapped_column(String(300), default="")
    predicate: Mapped[str] = mapped_column(String(200), default="")
    statement: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    status: Mapped[str] = mapped_column(String(40), default="UNVERIFIED")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ClaimEvidenceLink(Scoped, Base):
    __tablename__ = "claim_evidence_links"
    __table_args__ = scoped_constraints(
        case_fk(), ForeignKeyConstraint(["tenant_id", "claim_id"], ["claims.tenant_id", "claims.id"]),
        ForeignKeyConstraint(["tenant_id", "source_id"], ["sources.tenant_id", "sources.id"]),
        UniqueConstraint("tenant_id", "claim_id", "source_id", "relation"),
    )
    case_id: Mapped[str] = mapped_column(String(64))
    claim_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    relation: Mapped[str] = mapped_column(String(32), default="supports")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    locator: Mapped[str | None] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class RiskFinding(Scoped, Base):
    __tablename__ = "risk_findings"
    __table_args__ = scoped_constraints(case_fk())
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    jurisdiction: Mapped[str | None] = mapped_column(String(100))
    rule_id: Mapped[str | None] = mapped_column(String(100))
    rule_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="NEEDS_REVIEW")
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class LeadAssessment(Scoped, Base):
    __tablename__ = "lead_assessments"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "version"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Artifact(Scoped, Base):
    __tablename__ = "artifacts"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "kind"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ArtifactVersion(Scoped, Base):
    __tablename__ = "artifact_versions"
    __table_args__ = scoped_constraints(
        case_fk(), ForeignKeyConstraint(["tenant_id", "artifact_id"], ["artifacts.tenant_id", "artifacts.id"]),
        UniqueConstraint("tenant_id", "artifact_id", "version"),
    )
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_ref: Mapped[str] = mapped_column(String(300))
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Approval(Scoped, Base):
    __tablename__ = "approvals"
    __table_args__ = scoped_constraints(
        case_fk(), ForeignKeyConstraint(["tenant_id", "artifact_version_id"], ["artifact_versions.tenant_id", "artifact_versions.id"]),
        UniqueConstraint("tenant_id", "artifact_version_id", "action_scope", "case_version"),
        UniqueConstraint("tenant_id", "idempotency_key"),
    )
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_version_id: Mapped[str] = mapped_column(String(64))
    artifact_hash: Mapped[str] = mapped_column(String(64))
    case_version: Mapped[int] = mapped_column(Integer)
    action_scope: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    decision: Mapped[str | None] = mapped_column(String(40))
    reviewer_id: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class OutboundAction(Scoped, Base):
    __tablename__ = "outbound_actions"
    __table_args__ = scoped_constraints(
        case_fk(), ForeignKeyConstraint(["tenant_id", "approval_id"], ["approvals.tenant_id", "approvals.id"]),
        UniqueConstraint("tenant_id", "idempotency_key"), UniqueConstraint("tenant_id", "approval_id"),
        UniqueConstraint("tenant_id", "case_id", "logical_fingerprint"),
    )
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    approval_id: Mapped[str] = mapped_column(String(64))
    artifact_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    logical_fingerprint: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(40), default="mail")
    target: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    receipt: Mapped[dict | None] = mapped_column(JSON)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class FollowUp(Scoped, Base):
    __tablename__ = "follow_up_tasks"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "fingerprint"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default=uid)
    assignee: Mapped[str | None] = mapped_column(String(64))
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    trigger: Mapped[str | None] = mapped_column(String(200))
    next_action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (case_fk(), UniqueConstraint("tenant_id", "idempotency_key"))
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(64), unique=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64))
    agent_run_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    data_redacted: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Scoped, Base):
    __tablename__ = "audit_log"
    __table_args__ = scoped_constraints(case_fk())
    case_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    data_redacted: Mapped[dict] = mapped_column(JSON, default=dict)


def row_dict(row) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}


@event.listens_for(ArtifactVersion, "before_update")
def _immutable_artifact(_mapper, _connection, target):
    if any(attribute.history.has_changes() for attribute in inspect(target).attrs):
        raise ValueError("artifact versions are immutable; create a new version")


@event.listens_for(Inquiry, "before_update")
def _immutable_original(_mapper, _connection, target):
    state = inspect(target)
    if any(state.attrs[name].history.has_changes() for name in ("raw_content_ref", "raw_hash")):
        raise ValueError("original inquiry is immutable")


class Database:
    def __init__(self, url: str, *, echo: bool = False):
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url.endswith(":memory:") or url in {"sqlite://", "sqlite+pysqlite://"}:
                kwargs["poolclass"] = StaticPool
        elif url.startswith("postgresql"):
            kwargs["connect_args"] = {"connect_timeout": 5}
        self.engine = create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def _sqlite_setup(connection, _record):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self):
        with self.sessions.begin() as session:
            yield session

    def create_schema(self) -> None:
        """For tests/demo only. Deployment uses Alembic migrations."""
        from tradecase.platform import source_cache  # noqa: F401
        from tradecase.visual import models as visual_models  # noqa: F401
        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1

    def close(self) -> None:
        self.engine.dispose()
