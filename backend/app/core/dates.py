import calendar
from datetime import datetime


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar months; the day is clamped (31 Jan + 1 month = 28/29 Feb)."""
    total = dt.month - 1 + months
    year, month = dt.year + total // 12, total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
