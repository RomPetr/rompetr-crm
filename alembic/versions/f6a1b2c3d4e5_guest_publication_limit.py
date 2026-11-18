"""guest publication limit

Revision ID: f6a1b2c3d4e5
Revises: d4e8a1b2c3f5
Create Date: 2026-11-18
"""

import sqlalchemy as sa

from alembic import op

revision = "f6a1b2c3d4e5"
down_revision = "d4e8a1b2c3f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("guest_publication_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "guest_publication_limit")
