"""guest limit overrides

Revision ID: 7b2f4c9d1a6e
Revises: c3e06824bb4a
Create Date: 2026-11-18
"""

import sqlalchemy as sa

from alembic import op

revision = "7b2f4c9d1a6e"
down_revision = "c3e06824bb4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("guest_compose_limit", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("guest_image_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "guest_image_limit")
    op.drop_column("users", "guest_compose_limit")
