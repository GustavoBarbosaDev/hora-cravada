import uuid

from pydantic import BaseModel, EmailStr, field_validator

from app.auth.models import Role
from app.tenants.schemas import Password, Slug


class LoginRequest(BaseModel):
    tenant_slug: Slug
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()


class RefreshRequest(BaseModel):
    refresh_token: str


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
