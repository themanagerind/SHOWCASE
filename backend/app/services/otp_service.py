import hmac
import secrets

from redis import Redis
from redis.exceptions import WatchError

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import RateLimited, Unauthorized
from app.core.phone import normalize_indian_mobile
from app.core.security import hash_otp
from app.services.sms import SmsSender


class OtpService:
    def __init__(self, redis: Redis, sms: SmsSender, settings: Settings):
        self.redis = redis
        self.sms = sms
        self.settings = settings

    @staticmethod
    def _key(phone: str) -> str:
        return f"otp:{phone}"

    def request(self, raw_phone: str, ip: str) -> str:
        phone = normalize_indian_mobile(raw_phone)
        s = self.settings
        rate_limit.hit(self.redis, "otp_ip", ip, s.otp_send_limit_per_ip_hour, 3600)
        rate_limit.hit(self.redis, "otp_phone_10m", phone, s.otp_send_limit_per_phone_10min, 600)
        rate_limit.hit(self.redis, "otp_phone_day", phone, s.otp_send_limit_per_phone_day, 86400)

        code = "".join(secrets.choice("0123456789") for _ in range(s.otp_length))
        key = self._key(phone)
        pipe = self.redis.pipeline()
        pipe.delete(key)
        pipe.hset(key, mapping={"hash": hash_otp(phone, code), "attempts": 0})
        pipe.expire(key, s.otp_ttl_seconds)
        pipe.execute()
        self.sms.send_otp(phone, code)
        return phone

    def verify(self, raw_phone: str, code: str, ip: str = "unknown") -> str:
        """Returns the normalised phone on success. Each OTP can be used once.

        Check-and-count is one optimistic transaction (WATCH/MULTI): parallel guesses cannot get more than
        otp_max_verify_attempts comparisons, the counter can never re-create a deleted key, and a correct code
        succeeds only once even if sent twice at the same moment.
        """
        phone = normalize_indian_mobile(raw_phone)
        # Per-IP cap on guesses across all phones (also limits locking other people's OTPs out).
        rate_limit.hit(self.redis, "otp_verify_ip", ip, self.settings.otp_verify_limit_per_ip_10min, 600)
        key = self._key(phone)
        expected = hash_otp(phone, code)
        while True:
            with self.redis.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    stored = pipe.hgetall(key)
                    if not stored or "hash" not in stored:
                        pipe.unwatch()
                        raise Unauthorized("OTP expired or not requested", code="otp_expired")
                    attempts = int(stored.get("attempts", 0)) + 1
                    pipe.multi()
                    if attempts > self.settings.otp_max_verify_attempts:
                        pipe.delete(key)
                        pipe.execute()
                        raise RateLimited("Too many wrong attempts, request a new OTP")
                    if hmac.compare_digest(stored["hash"], expected):
                        pipe.delete(key)
                        pipe.execute()
                        return phone
                    pipe.hset(key, "attempts", attempts)
                    pipe.execute()
                    raise Unauthorized("Wrong OTP", code="otp_invalid")
                except WatchError:
                    continue  # someone else touched this OTP in between: re-read and decide again
