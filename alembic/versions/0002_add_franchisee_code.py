"""Add code column to franchisees

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "franchisees",
        sa.Column(
            "code",
            sa.String(20),
            nullable=True,
        ),
    )
    # Back-fill existing rows from slug (take first segment, uppercase)
    op.execute("""
        UPDATE franchisees
        SET code = UPPER(SPLIT_PART(slug, '-', 1))
        WHERE code IS NULL
    """)


def downgrade() -> None:
    op.drop_column("franchisees", "code")
