"""step 5: yearly prices, billing cycle, richer payment records, trial/GST defaults

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

billing = postgresql.ENUM("MONTHLY", "YEARLY", name="billing_period", create_type=False)
YEARLY = {"BASIC": 159900, "PRO": 319900, "PREMIUM": 799900}  # "4 months free", GST-inclusive


def upgrade() -> None:
    # plans: monthly base price + yearly price (billing period now lives on the subscription)
    op.add_column("plans", sa.Column("yearly_price_paise", sa.BigInteger(), nullable=True))
    for code, price in YEARLY.items():
        op.execute(sa.text("UPDATE plans SET yearly_price_paise = :p WHERE code = :c").bindparams(p=price, c=code))
    op.execute("UPDATE plans SET yearly_price_paise = base_price_paise * 8 WHERE yearly_price_paise IS NULL")
    op.alter_column("plans", "yearly_price_paise", nullable=False)
    op.drop_column("plans", "billing_period")

    op.add_column("subscriptions", sa.Column("billing_cycle", billing, server_default="MONTHLY", nullable=False))
    op.add_column("retailer_offers", sa.Column("billing_cycle", billing, nullable=True))

    p = "subscription_payments"
    op.add_column(p, sa.Column("plan_id", sa.UUID(), sa.ForeignKey("plans.id", name="fk_subscription_payments_plan_id_plans")))
    op.add_column(p, sa.Column("billing_cycle", billing))
    op.add_column(p, sa.Column("gst_paise", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column(p, sa.Column("price_source", sa.String(20)))
    op.add_column(p, sa.Column("gateway_order_id", sa.String(64)))
    op.add_column(p, sa.Column("reference", sa.String(120)))
    op.add_column(p, sa.Column("recorded_by_admin_id", sa.UUID(),
                               sa.ForeignKey("admin_users.id", name="fk_subscription_payments_recorded_by_admin_id_admin_users")))
    op.execute("DELETE FROM subscription_payments")  # no real payments exist before step 5
    op.alter_column(p, "plan_id", nullable=False)
    op.alter_column(p, "billing_cycle", nullable=False)
    op.alter_column(p, "price_source", nullable=False)
    op.alter_column(p, "period_start", nullable=True)
    op.alter_column(p, "period_end", nullable=True)
    op.create_unique_constraint("uq_subscription_payments_gateway_order_id", p, ["gateway_order_id"])
    op.create_index("ix_subscription_payments_subscription_id_status", p, ["subscription_id", "status"])

    # Owner defaults: trial on, 30 days, PRO; GST 18% included in prices.
    op.execute("""UPDATE platform_settings SET value = '{"enabled": true, "duration_value": 30, "duration_unit": "days", "plan_code": "PRO"}'
                  WHERE key = 'trial'""")
    op.execute("""INSERT INTO platform_settings (key, value) VALUES ('gst', '{"rate_bps": 1800, "inclusive": true}')
                  ON CONFLICT (key) DO NOTHING""")


def downgrade() -> None:
    raise NotImplementedError("0004 is one-way")
