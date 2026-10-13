"""Hash de senha (Argon2id) e emissão/validação de tokens JWE."""

import json
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jwcrypto import jwk, jwt
from jwcrypto.common import JWException

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]

# Tamanho mínimo de senha (cadastro, criação de usuário e CLI).
SENHA_MIN_CARACTERES = 6

_JWE_HEADER = {"alg": "dir", "enc": "A256GCM", "typ": "JWT"}

_hasher = PasswordHasher()
# Usado para gastar o mesmo tempo quando o usuário não existe (evita enumeração por timing).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    sub: int  # id do usuário
    tid: int  # id do tenant
    role: str
    typ: TokenType
    jti: str
    exp: int
    fam: str | None = None  # família de refresh tokens (detecção de reuso)


@lru_cache
def _key(token_type: TokenType) -> jwk.JWK:
    s = get_settings()
    raw = s.JWE_ACCESS_KEY if token_type == "access" else s.JWE_REFRESH_KEY
    return jwk.JWK(kty="oct", k=raw)


def create_token(
    *, user_id: int, tenant_id: int, role: str, token_type: TokenType, family: str | None = None
) -> tuple[str, TokenClaims]:
    s = get_settings()
    now = int(time.time())
    ttl = (
        s.ACCESS_TOKEN_TTL_MINUTES * 60
        if token_type == "access"
        else s.REFRESH_TOKEN_TTL_DAYS * 86400
    )
    claims = TokenClaims(
        sub=user_id,
        tid=tenant_id,
        role=role,
        typ=token_type,
        jti=uuid.uuid4().hex,
        exp=now + ttl,
        fam=family if token_type == "refresh" else None,
    )
    payload = {k: v for k, v in claims.__dict__.items() if v is not None}
    payload["iat"] = now
    payload["sub"] = str(user_id)

    token = jwt.JWT(header=_JWE_HEADER, claims=payload)
    token.make_encrypted_token(_key(token_type))
    return token.serialize(), claims


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    try:
        t = jwt.JWT(
            jwt=token,
            key=_key(expected_type),
            # exp é verificado pelo jwcrypto; tipos de algoritmo restritos explicitamente.
            check_claims={"exp": None, "typ": expected_type},
            expected_type="JWE",
            algs=["dir", "A256GCM"],
        )
        data = json.loads(t.claims)
        return TokenClaims(
            sub=int(data["sub"]),
            tid=int(data["tid"]),
            role=str(data["role"]),
            typ=data["typ"],
            jti=str(data["jti"]),
            exp=int(data["exp"]),
            fam=data.get("fam"),
        )
    except (JWException, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc
