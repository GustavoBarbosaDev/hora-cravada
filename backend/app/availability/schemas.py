import datetime
import uuid
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

# O cliente fala "HH:MM"; o banco guarda minutos desde a meia-noite, o que permite 24:00 como
# fim de expediente (o tipo `time` não representa esse valor).
ClockTime = Annotated[str, Field(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
Weekday = Annotated[int, Field(ge=0, le=6, description="0 = segunda-feira")]


def to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def to_clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class RuleIn(BaseModel):
    weekday: Weekday
    start: ClockTime
    end: ClockTime

    @model_validator(mode="after")
    def end_after_start(self) -> Self:
        if to_minutes(self.end) <= to_minutes(self.start):
            raise ValueError("O fim precisa ser depois do início.")
        return self


class RuleOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    weekday: int
    start: str
    end: str


class ExceptionIn(BaseModel):
    resource_id: uuid.UUID | None = None
    date: datetime.date
    kind: Literal["closed", "open"]
    start: ClockTime | None = None
    end: ClockTime | None = None
    reason: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @model_validator(mode="after")
    def interval_matches_kind(self) -> Self:
        if (self.start is None) != (self.end is None):
            raise ValueError("Informe início e fim juntos, ou nenhum dos dois.")
        if self.start is None:
            if self.kind == "open":
                raise ValueError("Uma abertura especial precisa de início e fim.")
        elif self.end is not None and to_minutes(self.end) <= to_minutes(self.start):
            raise ValueError("O fim precisa ser depois do início.")
        return self


class ExceptionOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID | None
    date: datetime.date
    kind: str
    start: str | None
    end: str | None
    reason: str | None
