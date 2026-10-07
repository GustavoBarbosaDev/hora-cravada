import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import Settings
from app.core.errors import UnauthorizedError

JWT_ALGORITHM = "HS256"

_hasher = PasswordHasher()
# Verificar contra um hash fixo quando o usuário não existe evita que o tempo de resposta
# revele quais e-mails estão cadastrados.
_dummy_hash = _hasher.hash("senha-que-nunca-sera-usada")


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _dummy_hash, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(principal: Principal, settings: Settings) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(principal.user_id),
        "tid": str(principal.tenant_id),
        "role": principal.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> Principal:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "tid", "role", "exp"]},
        )
        return Principal(
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(claims["tid"]),
            role=claims["role"],
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise UnauthorizedError("Token inválido ou expirado.") from exc


def new_refresh_token(tenant_id: uuid.UUID) -> str:
    """O tenant vai no próprio token para que o RLS já possa ser configurado ao consultá-lo."""
    return f"{tenant_id}.{secrets.token_urlsafe(32)}"


def tenant_of_refresh_token(token: str) -> uuid.UUID:
    prefix, separator, _ = token.partition(".")
    try:
        if not separator:
            raise ValueError
        return uuid.UUID(prefix)
    except ValueError as exc:
        raise UnauthorizedError("Refresh token inválido.") from exc


def hash_refresh_token(token: str) -> str:
    # O token já tem 256 bits de entropia, então SHA-256 basta (sem necessidade de hash lento).
    return hashlib.sha256(token.encode()).hexdigest()
