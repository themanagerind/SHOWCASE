"""sessions: refresh_tokens.session_started_at (device list, admin max session)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        UPDATE refresh_tokens t SET session_started_at = f.started
        FROM (SELECT family_id, min(created_at) AS started FROM refresh_tokens GROUP BY family_id) f
        WHERE f.family_id = t.family_id
    """)
    op.alter_column("refresh_tokens", "session_started_at", nullable=False)


def downgrade() -> None:
    op.drop_column("refresh_tokens", "session_started_at")
