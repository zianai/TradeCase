"""Tenant and permission-scoped read cache, no business scheduling state."""

from alembic import op
import sqlalchemy as sa

revision = "20261028_0002"
down_revision = "20261028_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_cache",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("object_ref", sa.String(300)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("tenant_id", "cache_key"),
    )
    op.create_index("ix_source_cache_tenant_id", "source_cache", ["tenant_id"])


def downgrade():
    op.drop_index("ix_source_cache_tenant_id", table_name="source_cache")
    op.drop_table("source_cache")
