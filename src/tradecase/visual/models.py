"""Separate tenant-scoped Product Truth, planning and presentation records."""

from sqlalchemy import JSON, Boolean, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from tradecase.platform.db import Base, Scoped, case_fk, scoped_constraints


class Product(Scoped, Base):
    __tablename__ = "visual_products"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "sku"))
    case_id: Mapped[str] = mapped_column(String(64))
    sku: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class TruthSnapshot(Scoped, Base):
    __tablename__ = "product_truth_snapshots"
    __table_args__ = scoped_constraints(case_fk())
    case_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[str] = mapped_column(String(64))
    product_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class SourceAsset(Scoped, Base):
    __tablename__ = "visual_source_assets"
    __table_args__ = scoped_constraints(case_fk())
    case_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(Text)
    authorized: Mapped[bool] = mapped_column(Boolean)
    external_use: Mapped[bool] = mapped_column(Boolean)
    mime_type: Mapped[str] = mapped_column(String(50))
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_ref: Mapped[str] = mapped_column(String(300))


class VisualTask(Scoped, Base):
    __tablename__ = "visual_tasks"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "idempotency_key"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[str] = mapped_column(String(64))
    intent: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(40), default="awaiting_plan_approval")
    version: Mapped[int] = mapped_column(Integer, default=1)
    plan_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PlanSnapshot(Scoped, Base):
    __tablename__ = "visual_plan_snapshots"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "task_id", "version"))
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    truth_snapshot_id: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class EngineRun(Scoped, Base):
    __tablename__ = "creative_engine_runs"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "plan_id"))
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    plan_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    remote_plan_id: Mapped[str | None] = mapped_column(String(100))
    batch_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class VisualAsset(Scoped, Base):
    __tablename__ = "visual_task_assets"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "run_id", "remote_id"))
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(64))
    plan_id: Mapped[str] = mapped_column(String(64))
    remote_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="awaiting_review")
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_ref: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(50))
    qa: Mapped[dict] = mapped_column(JSON, default=dict)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class VisualReview(Scoped, Base):
    __tablename__ = "visual_reviews"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "task_id", "idempotency_key"))
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(64))
    subject_hash: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(30))
    reviewer_id: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class VisualEvent(Scoped, Base):
    __tablename__ = "visual_task_events"
    __table_args__ = scoped_constraints(case_fk())
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class BuyerProposal(Scoped, Base):
    __tablename__ = "buyer_visual_proposals"
    __table_args__ = scoped_constraints(case_fk(), UniqueConstraint("tenant_id", "case_id", "idempotency_key"))
    case_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


for _type in (TruthSnapshot, PlanSnapshot, VisualReview, VisualEvent, BuyerProposal, SourceAsset):

    @event.listens_for(_type, "before_update")
    def _immutable(*args):
        raise ValueError("Immutable visual record; create a new revision")


class RequestReceipt(Scoped, Base):
    __tablename__ = "visual_request_receipts"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "scope", "key"))
    scope: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


# Every cross-domain reference carries the tenant as part of its database key.
for _model, _column, _target in (
    (TruthSnapshot, "product_id", Product),
    (SourceAsset, "product_id", Product),
    (VisualTask, "product_id", Product),
    (PlanSnapshot, "task_id", VisualTask),
    (PlanSnapshot, "truth_snapshot_id", TruthSnapshot),
    (EngineRun, "task_id", VisualTask),
    (EngineRun, "plan_id", PlanSnapshot),
    (VisualAsset, "task_id", VisualTask),
    (VisualAsset, "run_id", EngineRun),
    (VisualAsset, "plan_id", PlanSnapshot),
    (VisualReview, "task_id", VisualTask),
    (VisualEvent, "task_id", VisualTask),
    (BuyerProposal, "task_id", VisualTask),
):
    _model.__table__.append_constraint(
        ForeignKeyConstraint(
            ["tenant_id", _column], [f"{_target.__tablename__}.tenant_id", f"{_target.__tablename__}.id"]
        )
    )
