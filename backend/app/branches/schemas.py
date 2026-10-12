import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import PatchModel
from app.core.timezones import Timezone

Name = Annotated[str, Field(min_length=1, max_length=120)]
Address = Annotated[str, Field(min_length=1, max_length=300)]


class BranchIn(BaseModel):
    name: Name
    timezone: Timezone
    address: Address | None = None


class BranchPatch(PatchModel):
    nullable = frozenset({"address"})

    name: Name | None = None
    timezone: Timezone | None = None
    address: Address | None = None


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    timezone: str
    address: str | None
