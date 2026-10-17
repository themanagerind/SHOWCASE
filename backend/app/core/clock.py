"""Single source of "now" for all business rules, so tests can control time."""
from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)
