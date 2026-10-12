import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.schemas import PatchModel
from app.resources.schemas import Kind, Name

# Um dia inteiro; serviços ou buffers maiores que isso são erro de digitação.
Minutes = Annotated[int, Field(ge=0, le=1440)]
Duration = Annotated[int, Field(ge=1, le=1440)]
Price = Annotated[int, Field(ge=0, le=100_000_000)]


def unique_kinds(kinds: list[str]) -> list[str]:
    return sorted(set(kinds))


# Sem ordem relevante; normalizar evita duplicatas e deixa a resposta estável.
Kinds = Annotated[list[Kind], Field(max_length=10), AfterValidator(unique_kinds)]


class ServiceIn(BaseModel):
    name: Name
    duration_min: Duration
    buffer_before_min: Minutes = 0
    buffer_after_min: Minutes = 0
    price_cents: Price = 0
    required_resource_kinds: Kinds = Field(default_factory=list)


class ServicePatch(PatchModel):
    name: Name | None = None
    duration_min: Duration | None = None
    buffer_before_min: Minutes | None = None
    buffer_after_min: Minutes | None = None
    price_cents: Price | None = None
    required_resource_kinds: Kinds | None = None
    active: bool | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    duration_min: int
    buffer_before_min: int
    buffer_after_min: int
    price_cents: int
    active: bool
    required_resource_kinds: list[str]


class ServiceResources(BaseModel):
    resource_ids: Annotated[list[uuid.UUID], Field(max_length=200)]
