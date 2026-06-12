"""add upcoming_deals table

Revision ID: c9d1e2f3a4b5
Revises: b7e2d4f1a9c3
Create Date: 2026-06-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d1e2f3a4b5"
down_revision: str | None = "b7e2d4f1a9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upcoming_deals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hubspot_deal_id", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("deal_stage", sa.String(), nullable=False),
        sa.Column(
            "tech_stack",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sales_rep_name", sa.String(), nullable=True),
        sa.Column("arr", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hubspot_deal_id", name="uq_upcoming_deals_hubspot_deal_id"),
    )


def downgrade() -> None:
    op.drop_table("upcoming_deals")
