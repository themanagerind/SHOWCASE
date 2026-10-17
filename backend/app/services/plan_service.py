import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden
from app.models import Plan, Subscription
from app.models.enums import LIVE_SUBSCRIPTION_STATUSES


@dataclass(frozen=True)
class PlanFeatures:
    code: str
    max_products: int | None  # None = unlimited
    weekly_swap: bool
    visibility_scope: str
    raw: dict

    @classmethod
    def from_plan(cls, plan: Plan) -> "PlanFeatures":
        f = plan.features or {}
        return cls(
            code=plan.code,
            max_products=f.get("max_products"),
            weekly_swap=bool(f.get("weekly_swap", True)),
            visibility_scope=f.get("visibility_scope", "PINCODE"),
            raw=f,
        )

    def has(self, feature: str) -> bool:
        return bool(self.raw.get(feature))


def get_live_subscription(db: Session, retailer_id: uuid.UUID) -> Subscription | None:
    """Subscription in TRIAL/ACTIVE/GRACE, or None. There is no free plan."""
    return db.scalar(
        select(Subscription).where(
            Subscription.retailer_id == retailer_id, Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES)
        )
    )


def get_live_features(db: Session, retailer_id: uuid.UUID) -> PlanFeatures | None:
    sub = get_live_subscription(db, retailer_id)
    return PlanFeatures.from_plan(sub.plan) if sub else None


def require_live_features(db: Session, retailer_id: uuid.UUID, feature: str | None = None) -> PlanFeatures:
    features = get_live_features(db, retailer_id)
    if features is None:
        raise Forbidden("An active subscription is required", code="subscription_required")
    if feature is not None and not features.has(feature):
        raise Forbidden(f"Your plan does not include '{feature}'", code="plan_feature_missing")
    return features
