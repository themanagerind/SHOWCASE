import re

from app.core.errors import DomainError

_INDIAN_MOBILE = re.compile(r"^[6-9][0-9]{9}$")  # ASCII digits only: "९८७…" must not make a second account


def normalize_indian_mobile(raw: str) -> str:
    """Accepts 9876543210 / 09876543210 / 919876543210 / +91 98765-43210 and returns +919876543210."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not _INDIAN_MOBILE.match(digits):
        raise DomainError("Invalid Indian mobile number", code="invalid_phone")
    return f"+91{digits}"
