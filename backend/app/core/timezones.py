from functools import lru_cache
from importlib.resources import files
from typing import Annotated

from pydantic import AfterValidator


@lru_cache
def _iana_names() -> frozenset[str]:
    return frozenset(files("tzdata").joinpath("zones").read_text().split())


def validate_timezone(value: str) -> str:
    # ZoneInfo aceita apelidos do sistema ("localtime") e `available_timezones()` os lista; a
    # lista do pacote tzdata só tem nomes da base IANA.
    if value not in _iana_names():
        raise ValueError("Fuso horário desconhecido.")
    return value


Timezone = Annotated[str, AfterValidator(validate_timezone)]
