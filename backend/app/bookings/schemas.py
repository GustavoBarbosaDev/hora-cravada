import datetime
import re
import uuid
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, EmailStr, Field

PHONE_CHARS = re.compile(r"^\+?[\d\s().-]+$")
MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 15


def normalize_phone(value: str) -> str:
    """Guarda só dígitos (e o `+` inicial), para que o mesmo número digitado de formas
    diferentes seja o mesmo cliente."""
    value = value.strip()
    if not PHONE_CHARS.match(value):
        raise ValueError("Telefone inválido.")
    digits = re.sub(r"\D", "", value)
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        raise ValueError("Telefone inválido.")
    return f"+{digits}" if value.startswith("+") else digits


Phone = Annotated[str, AfterValidator(normalize_phone)]


class CustomerIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    phone: Phone
    email: EmailStr | None = None


class BookingIn(BaseModel):
    service_id: uuid.UUID
    start: AwareDatetime
    branch_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    customer: CustomerIn
    notes: Annotated[str | None, Field(max_length=500)] = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    phone: str
    email: str | None


class PublicBookingOut(BaseModel):
    """O que o cliente anônimo recebe: sem dados de outros clientes e sem os do painel."""

    id: uuid.UUID
    service_id: uuid.UUID
    branch_id: uuid.UUID
    resource_ids: list[uuid.UUID]
    start: datetime.datetime
    end: datetime.datetime
    status: str


class BookingOut(PublicBookingOut):
    customer: CustomerOut
    price_cents: int
    notes: str | None
    created_at: datetime.datetime
    cancelled_at: datetime.datetime | None
