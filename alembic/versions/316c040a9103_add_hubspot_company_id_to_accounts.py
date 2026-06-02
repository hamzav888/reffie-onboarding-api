"""add hubspot_company_id to accounts

Revision ID: 316c040a9103
Revises: de8ead4140ea
Create Date: 2026-06-02 16:09:30.557993

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "316c040a9103"
down_revision: str | None = "de8ead4140ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("hubspot_company_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "hubspot_company_id")
