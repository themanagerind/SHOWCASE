"""product search: pg_trgm + trigram indexes on product name/category (SPEC 4.8a)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_products_name_trgm ON products USING gin (lower(name) gin_trgm_ops) "
        "WHERE is_active AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_products_category_lower ON products (lower(category)) "
        "WHERE is_active AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_category_lower")
    op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
