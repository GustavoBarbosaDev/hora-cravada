import uuid
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth.models import Role
from app.tenants.schemas import Password, Slug

# Os refresh tokens têm cerca de 80 caracteres; o teto só barra corpos absurdos.
RefreshTokenStr = Annotated[str, Field(min_length=1, max_length=512)]


class LoginRequest(BaseModel):
    tenant_slug: Slug
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()


class RefreshRequest(BaseModel):
    refresh_token: RefreshTokenStr


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    active: bool


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: Password
    role: Role

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()
