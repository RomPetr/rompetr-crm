"""platform toggles

Revision ID: c3e06824bb4a
Revises: d155a0956dc1
Create Date: 2026-11-16 22:02:40.370117
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3e06824bb4a"
down_revision: str | None = "d155a0956dc1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_ENABLED = (
    '{"telegram": true, "instagram": true, "x": true, "tiktok": true, "vk": true}'
)


def upgrade() -> None:
    op.add_column("posts", sa.Column("platforms_enabled", sa.JSON(), nullable=True))
    op.add_column(
        "posts",
        sa.Column("image_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        sa.text("UPDATE posts SET platforms_enabled = CAST(:value AS json)").bindparams(
            value=ALL_ENABLED
        )
    )
    op.alter_column("posts", "platforms_enabled", nullable=False)


def downgrade() -> None:
    op.drop_column("posts", "image_enabled")
    op.drop_column("posts", "platforms_enabled")
