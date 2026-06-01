"""create accounts pocs checklist_state tables

Revision ID: 91bc8da8274e
Revises:
Create Date: 2026-06-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "91bc8da8274e"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("hubspot_deal_id", sa.String(), nullable=True),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("property_type", sa.String(), nullable=False),
        sa.Column("arr", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("contract_length", sa.String(), nullable=True),
        sa.Column("success_metrics", sa.String(), nullable=True),
        sa.Column("cs_rep", sa.String(), nullable=False),
        sa.Column("onboarding_stage", sa.String(), nullable=False),
        sa.Column("kickoff_call_date", sa.Date(), nullable=True),
        sa.Column(
            "skipped_stages",
            postgresql.ARRAY(sa.String()),
            server_default="'{}'",
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
    )

    op.create_table(
        "pocs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "checklist_state",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column(
            "done",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "note",
            sa.String(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("first_touched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "step_id", name="uq_checklist_account_step"),
    )


def downgrade() -> None:
    op.drop_table("checklist_state")
    op.drop_table("pocs")
    op.drop_table("accounts")
