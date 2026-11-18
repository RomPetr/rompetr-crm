"""make the latest asset primary

Revision ID: d4e8a1b2c3f5
Revises: 7b2f4c9d1a6e
Create Date: 2026-11-18
"""

from alembic import op

revision = "d4e8a1b2c3f5"
down_revision = "7b2f4c9d1a6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE assets SET is_primary = "
        "(id = (SELECT MAX(b.id) FROM assets b WHERE b.post_id = assets.post_id))"
    )


def downgrade() -> None:
    # Data repair only; the previous primary flags cannot be reconstructed reliably.
    pass
