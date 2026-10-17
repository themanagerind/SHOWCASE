from redis import Redis

from app.core import clock
from app.core.errors import RateLimited


def hit(redis: Redis, scope: str, identity: str, limit: int, window_seconds: int) -> None:
    """Fixed-window counter. Raises RateLimited when the limit for the current window is exceeded."""
    window = int(clock.now().timestamp()) // window_seconds
    key = f"rl:{scope}:{identity}:{window}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window_seconds)
    if count > limit:
        raise RateLimited("Too many requests, please try again later")
