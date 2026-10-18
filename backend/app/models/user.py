import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Model, SoftDelete
from app.models.enums import AdminRole, SignupSource
from app.models.types import geo_point, pg_enum


class User(Model, SoftDelete):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(15), unique=True)
    name: Mapped[str | None] = mapped_column(String(120))
    preferred_language: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped["Customer | None"] = relationship(back_populates="user", uselist=False)
    retailer: Mapped["Retailer | None"] = relationship(back_populates="user", uselist=False)  # noqa: F821
    admin: Mapped["AdminUser | None"] = relationship(back_populates="user", uselist=False)

    @property
    def roles(self) -> list[str]:
        roles = []
        if self.customer is not None:
            roles.append("customer")
        if self.retailer is not None and self.retailer.deleted_at is None:
            roles.append("retailer")
        if self.admin is not None and self.admin.is_active:
            roles.append("admin")
        return roles


class RefreshToken(Model):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    # When this login (family) started; copied on every rotation. Used for the admin max-session rule.
    session_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdminUser(Model):
    __tablename__ = "admin_users"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    role: Mapped[AdminRole] = mapped_column(pg_enum(AdminRole, "admin_role"), default=AdminRole.SUPPORT)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    user: Mapped[User] = relationship(back_populates="admin")


class Customer(Model, SoftDelete):
    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    pincode: Mapped[str | None] = mapped_column(String(6))
    city: Mapped[str | None] = mapped_column(String(80))
    location = mapped_column(geo_point(), nullable=True)
    search_radius_km: Mapped[int] = mapped_column(SmallInteger, default=5, server_default="5")
    contact_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Optional home address (filled from THE-MANAGER prefill or typed; SPEC 4.12). No email is stored.
    society_name: Mapped[str | None] = mapped_column(String(120))
    address_line: Mapped[str | None] = mapped_column(String(200))
    flat_number: Mapped[str | None] = mapped_column(String(20))
    floor: Mapped[str | None] = mapped_column(String(10))
    state: Mapped[str | None] = mapped_column(String(60))
    signup_source: Mapped[SignupSource] = mapped_column(
        pg_enum(SignupSource, "signup_source"), default=SignupSource.DIRECT, server_default="DIRECT"
    )

    user: Mapped[User] = relationship(back_populates="customer")
