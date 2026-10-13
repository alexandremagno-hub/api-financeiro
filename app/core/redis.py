from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
