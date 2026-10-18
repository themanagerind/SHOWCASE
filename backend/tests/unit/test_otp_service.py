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


# ---- security audit: parallel guesses (real Redis, real threads) --------------------------------------

@pytest.fixture
def real_otp(sms):
    import redis as redis_lib

    r = redis_lib.Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    r.flushdb()
    yield OtpService(r, sms, get_settings()), r
    r.flushdb()


def _parallel(n, fn):
    from concurrent.futures import ThreadPoolExecutor

    def run(i):
        try:
            return fn(i)
        except (Unauthorized, RateLimited) as e:
            return getattr(e, "code", "rate_limited")
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(run, range(n)))


def test_parallel_wrong_guesses_never_exceed_the_attempt_limit(real_otp, sms):
    otp, r = real_otp
    otp.request("9876543210", "1.1.1.1")
    real = sms.last_code(PHONE)
    guesses = [f"{i:06d}" for i in range(60) if f"{i:06d}" != real][:40]
    out = _parallel(40, lambda i: otp.verify("9876543210", guesses[i], f"10.0.0.{i}"))
    assert out.count("otp_invalid") <= get_settings().otp_max_verify_attempts
    assert not r.exists(f"otp:{PHONE}")  # burnt, and never re-created without a hash (no 500 afterwards)
    with pytest.raises(Unauthorized):
        otp.verify("9876543210", real, "1.1.1.1")


def test_correct_code_sent_twice_in_parallel_logs_in_once(real_otp, sms):
    otp, _ = real_otp
    otp.request("9876543210", "1.1.1.1")
    code = sms.last_code(PHONE)
    out = _parallel(10, lambda i: otp.verify("9876543210", code, f"10.0.1.{i}"))
    assert out.count(PHONE) == 1


def test_verify_is_rate_limited_per_ip(otp, sms):
    otp.request("9876543210", "1.1.1.1")
    limit = get_settings().otp_verify_limit_per_ip_10min
    for i in range(limit):
        try:
            otp.verify(f"98765{i:05d}", "000000", "6.6.6.6")
        except (Unauthorized, RateLimited):
            pass
    with pytest.raises(RateLimited):
        otp.verify("9876543210", "000000", "6.6.6.6")
