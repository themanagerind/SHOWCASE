"""wallet discount on products, drop advance and credit tables

SPEC 4.4/4.5 changed to the wallet-points model (owner decision 2026-10-17):
- every product gets a mandatory wallet_discount_paise (0 < discount <= price)
- real-money advance (retailers.advance_*), store credit and payment-confirmation tables are removed
- bookings is dropped here and recreated for the points flow in step 6

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ENUMS = ("advance_type", "booking_status", "payment_method", "credit_status", "ledger_entry_type")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM products)")).scalar():
        # No safe default exists for a business price; the retailer must set it.
        raise RuntimeError("products already exist: set wallet_discount_paise for them manually before migrating")
    op.add_column("products", sa.Column("wallet_discount_paise", sa.BigInteger(), nullable=False))
    op.create_check_constraint(
        "wallet_discount_range", "products", "wallet_discount_paise > 0 AND wallet_discount_paise <= price_paise"
    )
    op.drop_column("retailers", "advance_type")
    op.drop_column("retailers", "advance_value")
    op.drop_table("credit_ledger")
    op.drop_table("customer_credits")
    op.drop_table("payment_confirmations")
    op.drop_table("bookings")
    for name in OLD_ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")


def downgrade() -> None:
    raise NotImplementedError("0002 is one-way: the real-money advance/credit model was removed from SPEC")
