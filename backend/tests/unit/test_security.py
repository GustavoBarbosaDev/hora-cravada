import uuid

import pytest

from app.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    Principal,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    tenant_of_refresh_token,
    verify_password,
)

SETTINGS = Settings(jwt_secret="segredo-de-teste-com-tamanho-suficiente")


def test_password_hash_verifies_only_the_original_password() -> None:
    hashed = hash_password("cabelo-e-barba-42")

    assert hashed != "cabelo-e-barba-42"
    assert verify_password(hashed, "cabelo-e-barba-42")
    assert not verify_password(hashed, "cabelo-e-barba-43")


def test_verifying_without_a_stored_hash_always_fails() -> None:
    assert not verify_password(None, "qualquer-coisa")


def test_access_token_round_trips_the_principal() -> None:
    principal = Principal(uuid.uuid4(), uuid.uuid4(), "reception")

    token = create_access_token(principal, SETTINGS)

    assert decode_access_token(token, SETTINGS) == principal


def test_expired_access_token_is_rejected() -> None:
    expired = Settings(jwt_secret=SETTINGS.jwt_secret, access_token_ttl_minutes=-1)
    token = create_access_token(Principal(uuid.uuid4(), uuid.uuid4(), "owner"), expired)

    with pytest.raises(UnauthorizedError):
        decode_access_token(token, SETTINGS)


def test_access_token_signed_with_another_secret_is_rejected() -> None:
    other = Settings(jwt_secret="outro-segredo-de-teste-com-tamanho-suficiente")
    token = create_access_token(Principal(uuid.uuid4(), uuid.uuid4(), "owner"), other)

    with pytest.raises(UnauthorizedError):
        decode_access_token(token, SETTINGS)


def test_refresh_token_carries_its_tenant_and_is_hashed_for_storage() -> None:
    tenant_id = uuid.uuid4()

    token = new_refresh_token(tenant_id)

    assert tenant_of_refresh_token(token) == tenant_id
    assert hash_refresh_token(token) != token
    assert hash_refresh_token(token) == hash_refresh_token(token)


@pytest.mark.parametrize("token", ["", "sem-separador", "nao-e-uuid.segredo"])
def test_malformed_refresh_token_is_rejected(token: str) -> None:
    with pytest.raises(UnauthorizedError):
        tenant_of_refresh_token(token)


def test_production_refuses_the_development_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production")


def test_production_refuses_a_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(environment="production", jwt_secret="x" * 31)


def test_production_accepts_a_jwt_secret_of_32_bytes() -> None:
    assert Settings(environment="production", jwt_secret="x" * 32).jwt_secret == "x" * 32
