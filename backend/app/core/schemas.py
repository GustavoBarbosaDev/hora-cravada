from typing import ClassVar, Self

from pydantic import BaseModel, model_validator


class PatchModel(BaseModel):
    """Base das atualizações parciais: campo omitido não muda, e `null` só vale nos campos
    listados em `nullable` (os demais são NOT NULL no banco)."""

    nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_null_on_required_fields(self) -> Self:
        for field in self.model_fields_set - self.nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} não pode ser nulo.")
        return self
