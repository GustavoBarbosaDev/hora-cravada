import uuid
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator

Slug = Annotated[str, Field(min_length=3, max_length=40, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class SignupRequest(BaseModel):
    tenant_name: Annotated[str, Field(min_length=2, max_length=120)]
    slug: Slug
    timezone: str = "America/Sao_Paulo"
    owner_email: EmailStr
    owner_password: Password

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Fuso horário desconhecido.") from exc
        return value

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
