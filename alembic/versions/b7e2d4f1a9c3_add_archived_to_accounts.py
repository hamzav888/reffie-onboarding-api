"""add archived to accounts

Revision ID: b7e2d4f1a9c3
Revises: 316c040a9103
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d4f1a9c3"
down_revision: str | None = "316c040a9103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("accounts", "archived")
