"""Motor de slots: função pura, sem banco nem relógio.

Recebe regras, exceções, intervalos ocupados, o serviço e uma janela de datas locais; devolve os
horários em que o serviço cabe. O carregamento dos dados fica em `app.slots.service`.

Duas unidades convivem aqui, e não se misturam:

- minutos locais: o que está nas regras e exceções (`Span`), contados desde a meia-noite da
  filial, no intervalo [início, fim);
- instantes em UTC: tudo que é comparado com reservas, com o relógio ou devolvido ao chamador.

A conversão é `local_instant`. Durações são sempre somadas em UTC, então um dia de horário de
verão (23 ou 25 horas) não distorce o tamanho do serviço.
"""

import datetime
import uuid
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

MINUTES_PER_DAY = 1440
UTC = datetime.UTC

Span = tuple[int, int]
Interval = tuple[datetime.datetime, datetime.datetime]
# Recursos que atendem um slot: quem executa primeiro, depois um por tipo exigido (na ordem
# alfabética do tipo).
Assignment = tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class ExceptionWindow:
    kind: Literal["closed", "open"]
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class Schedule:
    """Agenda de um recurso: regras semanais, exceções por data local e o que já está ocupado."""

    resource_id: uuid.UUID
    weekly: Mapping[int, Sequence[Span]] = field(default_factory=dict)
    exceptions: Mapping[datetime.date, Sequence[ExceptionWindow]] = field(default_factory=dict)
    busy: Sequence[Interval] = ()


@dataclass(frozen=True)
class ServiceTiming:
    duration_min: int
    buffer_before_min: int = 0
    buffer_after_min: int = 0


@dataclass(frozen=True)
class Policy:
    step_min: int = 15
    min_notice: datetime.timedelta = datetime.timedelta(0)
    max_advance: datetime.timedelta = datetime.timedelta(days=90)


@dataclass(frozen=True)
class Slot:
    start: datetime.datetime
    end: datetime.datetime
    assignments: tuple[Assignment, ...]


def local_instant(day: datetime.date, minute: int, tz: datetime.tzinfo) -> datetime.datetime:
    """Instante UTC de `minute` minutos após a meia-noite local de `day`.

    `minute` vai de 0 a 1440; 1440 é a meia-noite seguinte. Em horário que não existe (salto do
    horário de verão) o relógio avança pelo deslocamento anterior ao salto; em horário repetido
    vale a primeira ocorrência.
    """
    if minute == MINUTES_PER_DAY:
        day += datetime.timedelta(days=1)
        minute = 0
    hours, minutes = divmod(minute, 60)
    local = datetime.datetime(day.year, day.month, day.day, hours, minutes, tzinfo=tz)
    return local.astimezone(UTC)


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """Une intervalos que se sobrepõem ou se encostam."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_span(spans: Iterable[Span], cut: Span) -> list[Span]:
    cut_start, cut_end = cut
    remaining: list[Span] = []
    for start, end in spans:
        if cut_end <= start or cut_start >= end:
            remaining.append((start, end))
            continue
        if cut_start > start:
            remaining.append((start, cut_start))
        if cut_end < end:
            remaining.append((cut_end, end))
    return remaining


def open_spans(rules: Iterable[Span], exceptions: Iterable[ExceptionWindow]) -> list[Span]:
    """Horário aberto de um recurso numa data, em minutos locais.

    Se há exceção `open`, as janelas dela substituem as regras semanais; depois, toda exceção
    `closed` retira o que sobrou (sem horário, o dia inteiro).
    """
    exceptions = list(exceptions)
    special = [(e.start, e.end) for e in exceptions if e.kind == "open"]
    if special:
        spans = merge_spans((s, e) for s, e in special if s is not None and e is not None)
    else:
        spans = merge_spans(rules)
    for item in exceptions:
        if item.kind != "closed":
            continue
        if item.start is None or item.end is None:
            return []
        spans = subtract_span(spans, (item.start, item.end))
    return spans


def _open_windows(
    schedule: Schedule, days: Sequence[datetime.date], tz: datetime.tzinfo
) -> tuple[list[tuple[datetime.date, Span]], list[Interval]]:
    """Janelas abertas por dia local e as mesmas janelas em UTC, com as que se encostam unidas.

    A união em UTC deixa um serviço atravessar a meia-noite quando o recurso abre até 24:00 e
    volta a abrir às 00:00 do dia seguinte.
    """
    by_day: list[tuple[datetime.date, Span]] = []
    instants: list[Interval] = []
    for day in days:
        exceptions = schedule.exceptions.get(day, ())
        for span in open_spans(schedule.weekly.get(day.weekday(), ()), exceptions):
            by_day.append((day, span))
            instants.append((local_instant(day, span[0], tz), local_instant(day, span[1], tz)))
    instants.sort()
    merged: list[Interval] = []
    for start, end in instants:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return by_day, merged


def _is_free(busy: Sequence[Interval], start: datetime.datetime, end: datetime.datetime) -> bool:
    return not any(busy_start < end and start < busy_end for busy_start, busy_end in busy)


def free_starts(
    schedule: Schedule,
    *,
    service: ServiceTiming,
    days: Sequence[datetime.date],
    tz: datetime.tzinfo,
    step_min: int,
) -> list[datetime.datetime]:
    """Inícios possíveis do serviço neste recurso, na grade de `step_min` desde a meia-noite local.

    O serviço (sem os buffers) precisa caber numa janela aberta. Os buffers não precisam: eles
    só ocupam o recurso, então são conferidos contra o que já está reservado.
    """
    by_day, windows = _open_windows(schedule, days, tz)
    window_starts = [start for start, _ in windows]
    duration = datetime.timedelta(minutes=service.duration_min)
    before = datetime.timedelta(minutes=service.buffer_before_min)
    after = datetime.timedelta(minutes=service.buffer_after_min)

    step = datetime.timedelta(minutes=step_min)
    starts: list[datetime.datetime] = []
    for day, (span_start, span_end) in by_day:
        # A grade conta tempo decorrido desde a meia-noite local, não horário de relógio: num dia
        # de 25 horas a hora repetida também tem slots.
        midnight = local_instant(day, 0, tz)
        first = -(-(local_instant(day, span_start, tz) - midnight) // step)
        last = -(-(local_instant(day, span_end, tz) - midnight) // step)
        for count in range(first, last):
            start = midnight + count * step
            index = bisect_right(window_starts, start) - 1
            if index < 0 or start + duration > windows[index][1]:
                continue
            if _is_free(schedule.busy, start - before, start + duration + after):
                starts.append(start)
    return sorted(set(starts))


def compute_slots(
    *,
    performers: Sequence[Schedule],
    required: Mapping[str, Sequence[Schedule]],
    service: ServiceTiming,
    days: Sequence[datetime.date],
    tz: datetime.tzinfo,
    policy: Policy,
    now: datetime.datetime,
) -> list[Slot]:
    """Slots em que o serviço pode ser feito.

    Um início só vira slot se algum `performers` está livre e, para cada tipo em `required`,
    existe outro recurso daquele tipo livre no mesmo instante. A escolha é determinística: o
    primeiro livre na ordem recebida (o chamador ordena). Um slot lista uma atribuição por
    executor possível, na ordem dos `performers`.
    """
    earliest = now + policy.min_notice
    latest = now + policy.max_advance
    kinds = sorted(required)

    def starts_of(schedule: Schedule) -> set[datetime.datetime]:
        return set(
            free_starts(schedule, service=service, days=days, tz=tz, step_min=policy.step_min)
        )

    free: dict[uuid.UUID, set[datetime.datetime]] = {}
    for schedule in [*performers, *(s for group in required.values() for s in group)]:
        free.setdefault(schedule.resource_id, starts_of(schedule))

    assignments: dict[datetime.datetime, list[Assignment]] = {}
    for performer in performers:
        for start in sorted(free[performer.resource_id]):
            if start < earliest or start > latest:
                continue
            chosen: list[uuid.UUID] = [performer.resource_id]
            for kind in kinds:
                match = next(
                    (
                        s.resource_id
                        for s in required[kind]
                        if s.resource_id != performer.resource_id and start in free[s.resource_id]
                    ),
                    None,
                )
                if match is None:
                    break
                chosen.append(match)
            else:
                assignments.setdefault(start, []).append(tuple(chosen))

    duration = datetime.timedelta(minutes=service.duration_min)
    return [
        Slot(start=start, end=start + duration, assignments=tuple(found))
        for start, found in sorted(assignments.items())
    ]
