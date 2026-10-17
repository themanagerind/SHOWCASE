import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Model, SoftDelete
from app.models.enums import JoinSource
from app.models.types import geo_point, pg_enum
from app.models.user import User


class Retailer(Model, SoftDelete):
    __tablename__ = "retailers"
    __table_args__ = (
        Index("ix_retailers_location_gist", "location", postgresql_using="gist"),
        Index("ix_retailers_pincode", "pincode"),
        Index("ix_retailers_city", "city"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    shop_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    address_line: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    pincode: Mapped[str] = mapped_column(String(6))
    location = mapped_column(geo_point(), nullable=False)
    timings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    phone: Mapped[str | None] = mapped_column(String(15))
    whatsapp_number: Mapped[str | None] = mapped_column(String(15))
    payment_link: Mapped[str | None] = mapped_column(Text)
    upi_id: Mapped[str | None] = mapped_column(String(80))
    products_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_swap_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    rating_avg: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=0, server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    user: Mapped[User] = relationship(back_populates="retailer")


class RetailerCustomer(Model):
    __tablename__ = "retailer_customers"
    __table_args__ = (UniqueConstraint("retailer_id", "customer_id"),)

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    source: Mapped[JoinSource] = mapped_column(pg_enum(JoinSource, "join_source"))
    is_favourite: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Product(Model, SoftDelete):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_retailer_id_is_active", "retailer_id", "is_active"),
        CheckConstraint("price_paise >= 0", name="price_non_negative"),
        CheckConstraint("stock_qty >= 0", name="stock_non_negative"),
        CheckConstraint(
            "wallet_discount_paise > 0 AND wallet_discount_paise <= price_paise", name="wallet_discount_range"
        ),
    )

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(60))
    price_paise: Mapped[int] = mapped_column(BigInteger)
    mrp_paise: Mapped[int | None] = mapped_column(BigInteger)
    # Mandatory wallet-points discount set by the retailer (SPEC 4.4); also the points needed to reserve.
    wallet_discount_paise: Mapped[int] = mapped_column(BigInteger)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    photos: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductSwap(Model):
    """Append-only swap history."""

    __tablename__ = "product_swaps"

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    performed_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_product_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    removed_product_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    plan_code: Mapped[str] = mapped_column(String(20))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
