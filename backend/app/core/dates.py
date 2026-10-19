import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar months; the day is clamped (31 Jan + 1 month = 28/29 Feb).

    Aware datetimes are moved in Indian time (deep audit): 1 May 01:00 IST + 1 month = 1 June 01:00 IST, even though
    in UTC that instant is still 30 April. The result has the input's timezone.
    """
    local = dt.astimezone(IST) if dt.tzinfo else dt
    total = local.month - 1 + months
    year, month = local.year + total // 12, total % 12 + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    moved = local.replace(year=year, month=month, day=day)
    return moved.astimezone(dt.tzinfo) if dt.tzinfo else moved
