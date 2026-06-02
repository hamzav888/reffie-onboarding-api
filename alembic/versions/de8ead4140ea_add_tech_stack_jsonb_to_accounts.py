"""add tech_stack jsonb to accounts

Revision ID: de8ead4140ea
Revises: 91bc8da8274e
Create Date: 2026-06-02 14:28:57.886265

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "de8ead4140ea"
down_revision: str | None = "91bc8da8274e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "tech_stack",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "tech_stack")
