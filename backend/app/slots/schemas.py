import datetime
import uuid
from typing import Annotated, Self

from pydantic import BaseModel, Field, ValidationError, model_validator

MAX_RANGE_DAYS = 31
STEPS = (5, 10, 15, 20, 30, 60)
DEFAULT_STEP = 15


class SlotPolicySettings(BaseModel):
    """Antecedência lida de `tenants.settings["slots"]`. Valor ausente ou inválido cai no padrão,
    para que uma configuração quebrada não tire a agenda do ar."""

    min_notice_min: Annotated[int, Field(ge=0, le=60 * 24 * 365)] = 0
    max_advance_days: Annotated[int, Field(ge=1, le=730)] = 90

    @classmethod
    def from_tenant(cls, settings: dict[str, object]) -> Self:
        raw = settings.get("slots")
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except ValidationError:
            return cls()


class SlotQuery(BaseModel):
    service_id: uuid.UUID
    date_from: datetime.date
    date_to: datetime.date
    branch_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    step_min: int = DEFAULT_STEP

    @model_validator(mode="after")
    def valid_range_and_step(self) -> Self:
        if self.date_to < self.date_from:
            raise ValueError("date_to não pode ser anterior a date_from.")
        if (self.date_to - self.date_from).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"O período pode ter no máximo {MAX_RANGE_DAYS} dias.")
        if self.step_min not in STEPS:
            raise ValueError(f"step_min deve ser um destes valores: {', '.join(map(str, STEPS))}.")
        return self


class SlotOut(BaseModel):
    start: datetime.datetime
    end: datetime.datetime
    resource_ids: list[uuid.UUID]


class SlotsOut(BaseModel):
    branch_id: uuid.UUID
    timezone: str
    service_id: uuid.UUID
    duration_min: int
    slots: list[SlotOut]
