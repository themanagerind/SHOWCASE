from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.core.errors import RateLimited, Unauthorized
from app.services.otp_service import OtpService

PHONE = "+919876543210"


@pytest.fixture
def otp(redis, sms):
    return OtpService(redis, sms, get_settings())


def test_correct_code_verifies_once(otp, sms):
    otp.request("9876543210", "1.1.1.1")
    code = sms.last_code(PHONE)
    assert otp.verify("9876543210", code) == PHONE
    with pytest.raises(Unauthorized):
        otp.verify("9876543210", code)  # single use


def test_otp_is_not_stored_in_plain_text(otp, sms, redis):
    otp.request("9876543210", "1.1.1.1")
    stored = redis.hgetall(f"otp:{PHONE}")
    assert sms.last_code(PHONE) not in stored.values()


def test_wrong_code_rejected(otp, sms):
    otp.request("9876543210", "1.1.1.1")
    real = sms.last_code(PHONE)
    wrong = "000000" if real != "000000" else "111111"
    with pytest.raises(Unauthorized):
        otp.verify("9876543210", wrong)
    assert otp.verify("9876543210", real) == PHONE


def test_too_many_wrong_attempts_burns_the_code(otp, sms):
    otp.request("9876543210", "1.1.1.1")
    real = sms.last_code(PHONE)
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(get_settings().otp_max_verify_attempts):
        with pytest.raises(Unauthorized):
            otp.verify("9876543210", wrong)
    with pytest.raises(RateLimited):
        otp.verify("9876543210", real)
    with pytest.raises(Unauthorized):  # code was deleted
        otp.verify("9876543210", real)


def test_new_request_replaces_old_code(otp, sms, frozen):
    otp.request("9876543210", "1.1.1.1")
    first = sms.last_code(PHONE)
    otp.request("9876543210", "1.1.1.1")
    second = sms.last_code(PHONE)
    if first != second:
        with pytest.raises(Unauthorized):
            otp.verify("9876543210", first)
    assert otp.verify("9876543210", second) == PHONE


def test_send_limit_per_phone_per_10_minutes(otp, frozen):
    limit = get_settings().otp_send_limit_per_phone_10min
    for _ in range(limit):
        otp.request("9876543210", "1.1.1.1")
    with pytest.raises(RateLimited):
        otp.request("9876543210", "1.1.1.1")
    # A different phone is not affected
    otp.request("9123456789", "1.1.1.1")


def test_send_limit_resets_in_next_window(otp, frozen):
    limit = get_settings().otp_send_limit_per_phone_10min
    for _ in range(limit):
        otp.request("9876543210", "1.1.1.1")
    frozen.tick(timedelta(minutes=10))
    otp.request("9876543210", "1.1.1.1")


def test_send_limit_per_ip(otp, frozen):
    limit = get_settings().otp_send_limit_per_ip_hour
    phones = [f"9{n:09d}" for n in range(limit + 1)]
    for p in phones[:limit]:
        otp.request(p, "2.2.2.2")
    with pytest.raises(RateLimited):
        otp.request(phones[limit], "2.2.2.2")
