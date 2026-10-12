import uuid
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.timezones import Timezone

Slug = Annotated[str, Field(min_length=3, max_length=40, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class SignupRequest(BaseModel):
    tenant_name: Annotated[str, Field(min_length=2, max_length=120)]
    slug: Slug
    timezone: Timezone = "America/Sao_Paulo"
    owner_email: EmailStr
    owner_password: Password

    @field_validator("owner_email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    timezone_default: str


class SignupResponse(BaseModel):
    tenant: TenantOut
    owner_id: uuid.UUID
