"""Estado de sessão no Redis.

- refresh:{jti} -> "{user_id}:{family}"  : allowlist de refresh tokens válidos (rotação a cada uso)
- refresh_family_revoked:{family}        : família revogada (logout ou reuso detectado)
- access_denied:{jti}                    : access tokens revogados no logout (até expirarem)
- login_attempts:{email}                 : contador de tentativas de login
- signup_attempts:{ip}                   : contador de cadastros por IP
"""

import time

from redis import Redis

from app.core.config import get_settings
from app.core.security import TokenClaims


def _ttl(exp: int) -> int:
    return max(exp - int(time.time()), 1)


def store_refresh(r: Redis, claims: TokenClaims) -> None:
    r.set(f"refresh:{claims.jti}", f"{claims.sub}:{claims.fam}", ex=_ttl(claims.exp))


def consume_refresh(r: Redis, claims: TokenClaims) -> bool:
    """Consome atomicamente o refresh token. False = já usado/revogado (possível roubo)."""
    if r.exists(f"refresh_family_revoked:{claims.fam}"):
        return False
    return r.getdel(f"refresh:{claims.jti}") is not None


def revoke_family(r: Redis, family: str | None) -> None:
    if family:
        r.set(
            f"refresh_family_revoked:{family}",
            "1",
            ex=get_settings().REFRESH_TOKEN_TTL_DAYS * 86400,
        )


def deny_access_token(r: Redis, claims: TokenClaims) -> None:
    r.set(f"access_denied:{claims.jti}", "1", ex=_ttl(claims.exp))


def is_access_denied(r: Redis, jti: str) -> bool:
    return bool(r.exists(f"access_denied:{jti}"))


def login_attempts_exceeded(r: Redis, email: str) -> bool:
    count = r.get(f"login_attempts:{email}")
    return count is not None and int(count) >= get_settings().LOGIN_MAX_ATTEMPTS


def register_failed_login(r: Redis, email: str) -> None:
    key = f"login_attempts:{email}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, get_settings().LOGIN_WINDOW_SECONDS, nx=True)
    pipe.execute()


def reset_login_attempts(r: Redis, email: str) -> None:
    r.delete(f"login_attempts:{email}")


def signup_limit_exceeded(r: Redis, ip: str) -> bool:
    """Conta a tentativa e diz se o IP passou do limite de cadastros na janela."""
    s = get_settings()
    key = f"signup_attempts:{ip}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, s.SIGNUP_WINDOW_SECONDS, nx=True)
    count, _ = pipe.execute()
    return int(count) > s.SIGNUP_MAX_PER_IP
