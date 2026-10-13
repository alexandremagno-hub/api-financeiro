from redis import Redis

from app.core.redis import get_redis_client


def get_redis() -> Redis:
    return get_redis_client()
