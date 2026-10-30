"""Independent visual business domain; no old Case columns changed."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0003"
down_revision = "20261028_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "visual_request_receipts",
        sa.Column("scope", sa.String(length=100), nullable=False, primary_key=False),
        sa.Column("key", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("result", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "scope", "key"),
    )
    op.create_index("ix_visual_request_receipts_tenant_id", "visual_request_receipts", ["tenant_id"])
    op.create_table(
        "visual_products",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("sku", sa.String(length=100), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.UniqueConstraint("tenant_id", "case_id", "sku"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_visual_products_tenant_id", "visual_products", ["tenant_id"])
    op.create_table(
        "product_truth_snapshots",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("product_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("product_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["visual_products.tenant_id", "visual_products.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_product_truth_snapshots_tenant_id", "product_truth_snapshots", ["tenant_id"])
    op.create_table(
        "visual_source_assets",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("product_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=30), nullable=False, primary_key=False),
        sa.Column("source", sa.Text(), nullable=False, primary_key=False),
        sa.Column("authorized", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("external_use", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False, primary_key=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("storage_ref", sa.String(length=300), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["visual_products.tenant_id", "visual_products.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_visual_source_assets_tenant_id", "visual_source_assets", ["tenant_id"])
    op.create_table(
        "visual_tasks",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("product_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("intent", sa.String(length=50), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("plan_id", sa.String(length=64), nullable=True, primary_key=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["visual_products.tenant_id", "visual_products.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.UniqueConstraint("tenant_id", "case_id", "idempotency_key"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_visual_tasks_case_id", "visual_tasks", ["case_id"])
    op.create_index("ix_visual_tasks_tenant_id", "visual_tasks", ["tenant_id"])
    op.create_table(
        "buyer_visual_proposals",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("task_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"], ["visual_tasks.tenant_id", "visual_tasks.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.UniqueConstraint("tenant_id", "case_id", "idempotency_key"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_buyer_visual_proposals_tenant_id", "buyer_visual_proposals", ["tenant_id"])
    op.create_table(
        "visual_plan_snapshots",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("task_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("truth_snapshot_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "truth_snapshot_id"], ["product_truth_snapshots.tenant_id", "product_truth_snapshots.id"]
        ),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"], ["visual_tasks.tenant_id", "visual_tasks.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "task_id", "version"),
    )
    op.create_index("ix_visual_plan_snapshots_tenant_id", "visual_plan_snapshots", ["tenant_id"])
    op.create_table(
        "visual_reviews",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("task_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("scope", sa.String(length=30), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("decision", sa.String(length=30), nullable=False, primary_key=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"], ["visual_tasks.tenant_id", "visual_tasks.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "task_id", "idempotency_key"),
    )
    op.create_index("ix_visual_reviews_tenant_id", "visual_reviews", ["tenant_id"])
    op.create_table(
        "visual_task_events",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("task_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=100), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"], ["visual_tasks.tenant_id", "visual_tasks.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_visual_task_events_tenant_id", "visual_task_events", ["tenant_id"])
    op.create_table(
        "creative_engine_runs",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("task_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("remote_plan_id", sa.String(length=100), nullable=True, primary_key=False),
        sa.Column("batch_id", sa.String(length=100), nullable=True, primary_key=False),
        sa.Column("status", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id"], ["visual_plan_snapshots.tenant_id", "visual_plan_snapshots.id"]
        ),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"], ["visual_tasks.tenant_id", "visual_tasks.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "plan_id"),
    )
    op.create_index("ix_creative_engine_runs_tenant_id", "creative_engine_runs", ["tenant_id"])
    op.create_table(
        "visual_task_assets",
        sa.Column("case_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("task_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("run_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("remote_id", sa.String(length=100), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("storage_ref", sa.String(length=300), nullable=False, primary_key=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False, primary_key=False),
        sa.Column("qa", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"], ["visual_tasks.tenant_id", "visual_tasks.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id"], ["visual_plan_snapshots.tenant_id", "visual_plan_snapshots.id"]
        ),
        sa.ForeignKeyConstraint(["tenant_id", "run_id"], ["creative_engine_runs.tenant_id", "creative_engine_runs.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"]),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "run_id", "remote_id"),
    )
    op.create_index("ix_visual_task_assets_tenant_id", "visual_task_assets", ["tenant_id"])


def downgrade():
    op.drop_table("visual_task_assets")
    op.drop_table("creative_engine_runs")
    op.drop_table("visual_task_events")
    op.drop_table("visual_reviews")
    op.drop_table("visual_plan_snapshots")
    op.drop_table("buyer_visual_proposals")
    op.drop_table("visual_tasks")
    op.drop_table("visual_source_assets")
    op.drop_table("product_truth_snapshots")
    op.drop_table("visual_products")
    op.drop_table("visual_request_receipts")
