"""Admin-editable platform settings (SPEC 5), stored as JSON rows in platform_settings."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models import PlatformSetting

DEFAULTS: dict[str, dict] = {
    "trial": {"enabled": True, "duration_value": 30, "duration_unit": "days", "plan_code": "PRO"},
    "grace_days_default": {"days": 7},
    "gst": {"rate_bps": 1800, "inclusive": True},
    "shipping_markup": {"type": "FIXED", "value_paise": 0},
}


def get(db: Session, key: str) -> dict:
    row = db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
    return {**DEFAULTS.get(key, {}), **(row.value if row else {})}


def validate(key: str, value: dict) -> dict:
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise DomainError(msg, code="invalid_setting")

    need(key in DEFAULTS, f"Unknown setting '{key}'")
    if key == "trial":
        need(isinstance(value.get("enabled"), bool), "trial.enabled must be true/false")
        need(isinstance(value.get("duration_value"), int) and 1 <= value["duration_value"] <= 365, "duration 1-365")
        need(value.get("duration_unit") in ("days", "months"), "duration_unit must be days or months")
        need(value.get("plan_code") in ("BASIC", "PRO", "PREMIUM"), "plan_code must be BASIC, PRO or PREMIUM")
    elif key == "grace_days_default":
        need(isinstance(value.get("days"), int) and 0 <= value["days"] <= 90, "grace days 0-90")
    elif key == "gst":
        need(isinstance(value.get("rate_bps"), int) and 0 <= value["rate_bps"] <= 2800, "GST rate 0-28%")
        need(isinstance(value.get("inclusive"), bool), "gst.inclusive must be true/false")
    elif key == "shipping_markup":
        need(value.get("type") in ("FIXED", "PERCENT") and isinstance(value.get("value_paise"), int), "invalid markup")
    return {k: value[k] for k in DEFAULTS[key]}


def put(db: Session, key: str, value: dict, admin_id: Any) -> tuple[dict, dict]:
    """Returns (old, new). Caller writes the audit entry and commits."""
    clean = validate(key, value)
    old = get(db, key)
    row = db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
    if row is None:
        db.add(PlatformSetting(key=key, value=clean, updated_by_admin_id=admin_id))
    else:
        row.value = clean
        row.updated_by_admin_id = admin_id
    return old, clean
