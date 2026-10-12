import uuid
from typing import Annotated, Self

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

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
    resource_id: uuid.UUID | None


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: Password
    role: Role
    resource_id: uuid.UUID | None = None

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def resource_only_for_professionals(self) -> Self:
        if self.resource_id is not None and self.role != Role.professional:
            raise ValueError("Só profissionais podem ser vinculados a um recurso.")
        return self
