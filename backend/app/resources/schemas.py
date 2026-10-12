import json
import uuid
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.schemas import PatchModel

MAX_ATTRIBUTES_BYTES = 4096

Kind = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Name = Annotated[str, Field(min_length=1, max_length=120)]
Capacity = Annotated[int, Field(ge=1, le=1000)]


def limit_attributes(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value).encode()) > MAX_ATTRIBUTES_BYTES:
        raise ValueError(f"Os atributos podem ter no máximo {MAX_ATTRIBUTES_BYTES} bytes.")
    return value


Attributes = Annotated[dict[str, Any], AfterValidator(limit_attributes)]


class ResourceIn(BaseModel):
    branch_id: uuid.UUID
    kind: Kind
    name: Name
    capacity: Capacity = 1
    attributes: Attributes = Field(default_factory=dict)


class ResourcePatch(PatchModel):
    branch_id: uuid.UUID | None = None
    kind: Kind | None = None
    name: Name | None = None
    capacity: Capacity | None = None
    attributes: Attributes | None = None
    active: bool | None = None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_id: uuid.UUID
    kind: str
    name: str
    capacity: int
    active: bool
    attributes: dict[str, Any]
