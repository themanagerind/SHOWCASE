import pytest

from app.core.errors import DomainError
from app.core.phone import normalize_indian_mobile


@pytest.mark.parametrize(
    "raw", ["9876543210", "09876543210", "919876543210", "+919876543210", "+91 98765-43210"]
)
def test_valid_formats_normalise(raw):
    assert normalize_indian_mobile(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["", "12345", "5876543210", "98765432101", "+14155550100", "abcdefghij"])
def test_invalid_numbers_rejected(raw):
    with pytest.raises(DomainError):
        normalize_indian_mobile(raw)
