import datetime
import uuid
from zoneinfo import ZoneInfo

import pytest

from app.slots.engine import (
    ExceptionWindow,
    Policy,
    Schedule,
    ServiceTiming,
    Slot,
    compute_slots,
    free_starts,
    local_instant,
    merge_spans,
    open_spans,
    subtract_span,
)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
NEW_YORK = ZoneInfo("America/New_York")
UTC = datetime.UTC

MONDAY = datetime.date(2026, 11, 2)
LONG_AGO = datetime.datetime(2026, 1, 1, tzinfo=UTC)
ALL_DAY = [(0, 1440)]
FAR = datetime.timedelta(days=3650)


def at(
    day: datetime.date, hour: int, minute: int = 0, tz: ZoneInfo = SAO_PAULO
) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(UTC)


def schedule(
    weekday: int,
    spans: list[tuple[int, int]],
    *,
    exceptions: dict[datetime.date, list[ExceptionWindow]] | None = None,
    busy: list[tuple[datetime.datetime, datetime.datetime]] | None = None,
) -> Schedule:
    return Schedule(
        resource_id=uuid.uuid4(),
        weekly={weekday: spans},
        exceptions=exceptions or {},
        busy=busy or [],
    )


def slots(
    performers: list[Schedule],
    *,
    days: list[datetime.date],
    service: ServiceTiming,
    tz: ZoneInfo = SAO_PAULO,
    required: dict[str, list[Schedule]] | None = None,
    policy: Policy | None = None,
    now: datetime.datetime = LONG_AGO,
) -> list[Slot]:
    return compute_slots(
        performers=performers,
        required=required or {},
        service=service,
        days=days,
        tz=tz,
        policy=policy or Policy(step_min=30, max_advance=FAR),
        now=now,
    )


def starts(result: list[Slot], tz: ZoneInfo = SAO_PAULO) -> list[str]:
    return [slot.start.astimezone(tz).strftime("%d %H:%M") for slot in result]


# --- intervalos --------------------------------------------------------------------------------


def test_merge_joins_overlapping_and_touching_spans() -> None:
    assert merge_spans([(780, 840), (540, 720), (720, 780), (900, 960)]) == [(540, 840), (900, 960)]


def test_subtract_splits_a_span_around_the_cut() -> None:
    assert subtract_span([(540, 1080)], (720, 780)) == [(540, 720), (780, 1080)]
    assert subtract_span([(540, 1080)], (500, 600)) == [(600, 1080)]
    assert subtract_span([(540, 1080)], (1000, 1200)) == [(540, 1000)]
    assert subtract_span([(540, 1080)], (0, 1440)) == []
    assert subtract_span([(540, 1080)], (1080, 1200)) == [(540, 1080)]


def test_weekly_rules_apply_when_there_is_no_exception() -> None:
    assert open_spans([(540, 720), (780, 1080)], []) == [(540, 720), (780, 1080)]


def test_open_exception_replaces_the_weekly_rules() -> None:
    special = [ExceptionWindow("open", 600, 840)]

    assert open_spans([(540, 1080)], special) == [(600, 840)]


def test_open_exception_can_open_a_day_without_rules() -> None:
    assert open_spans([], [ExceptionWindow("open", 480, 720)]) == [(480, 720)]


def test_closed_exception_without_hours_closes_the_whole_day() -> None:
    assert open_spans([(540, 1080)], [ExceptionWindow("closed")]) == []


def test_partial_closed_exception_removes_only_that_interval() -> None:
    result = open_spans([(540, 1080)], [ExceptionWindow("closed", 720, 780)])

    assert result == [(540, 720), (780, 1080)]


def test_closed_wins_over_open_on_the_same_date() -> None:
    exceptions = [ExceptionWindow("open", 540, 1080), ExceptionWindow("closed", 600, 660)]

    assert open_spans([], exceptions) == [(540, 600), (660, 1080)]


def test_two_open_exceptions_are_combined() -> None:
    exceptions = [ExceptionWindow("open", 480, 600), ExceptionWindow("open", 840, 900)]

    assert open_spans([(0, 1440)], exceptions) == [(480, 600), (840, 900)]


# --- conversão de fuso -------------------------------------------------------------------------


def test_local_midnight_and_noon_in_sao_paulo() -> None:
    assert local_instant(MONDAY, 0, SAO_PAULO) == datetime.datetime(2026, 11, 2, 3, 0, tzinfo=UTC)
    assert local_instant(MONDAY, 720, SAO_PAULO) == datetime.datetime(
        2026, 11, 2, 15, 0, tzinfo=UTC
    )


def test_minute_1440_is_the_next_local_midnight() -> None:
    assert local_instant(MONDAY, 1440, SAO_PAULO) == local_instant(
        datetime.date(2026, 11, 3), 0, SAO_PAULO
    )


# --- geração de slots --------------------------------------------------------------------------


def test_day_with_a_lunch_break_has_no_slot_during_the_break() -> None:
    barber = schedule(0, [(540, 720), (780, 1080)])

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=30))

    assert starts(result) == [
        *[f"02 {h:02d}:{m}" for h in (9, 10, 11) for m in ("00", "30")],
        *[f"02 {h:02d}:{m}" for h in (13, 14, 15, 16, 17) for m in ("00", "30")],
    ]


def test_service_must_end_inside_the_window() -> None:
    barber = schedule(0, [(540, 570)])

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=45))

    assert starts(result) == []


def test_service_that_fills_the_window_exactly_fits() -> None:
    barber = schedule(0, [(540, 600)])

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=60))

    assert starts(result) == ["02 09:00"]
    assert result[0].end == at(MONDAY, 10)


def test_slot_cannot_straddle_the_lunch_break() -> None:
    barber = schedule(0, [(540, 720), (780, 1080)])

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=60))

    assert "02 11:30" not in starts(result)
    assert "02 11:00" in starts(result)


def test_touching_rules_behave_as_one_continuous_window() -> None:
    barber = schedule(0, [(540, 720), (720, 900)])

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=60))

    assert "02 11:30" in starts(result)


def test_buffers_do_not_need_to_fit_in_the_window() -> None:
    barber = schedule(0, [(540, 600)])
    service = ServiceTiming(duration_min=30, buffer_before_min=15, buffer_after_min=15)

    result = slots([barber], days=[MONDAY], service=service)

    assert starts(result) == ["02 09:00", "02 09:30"]


def test_buffer_blocks_a_start_that_would_touch_an_existing_booking() -> None:
    booked = (at(MONDAY, 10), at(MONDAY, 11))
    barber = schedule(0, [(540, 780)], busy=[booked])
    plain = ServiceTiming(duration_min=30)
    buffered = ServiceTiming(duration_min=30, buffer_before_min=15, buffer_after_min=15)

    without = slots([barber], days=[MONDAY], service=plain)
    with_buffer = slots([barber], days=[MONDAY], service=buffered)

    assert starts(without) == [
        "02 09:00",
        "02 09:30",
        "02 11:00",
        "02 11:30",
        "02 12:00",
        "02 12:30",
    ]
    # 09:30 termina às 10:00, mas o buffer de 15 min depois invade a reserva das 10:00; do mesmo
    # modo, 11:00 só começa a ocupar o recurso às 10:45.
    assert starts(with_buffer) == ["02 09:00", "02 11:30", "02 12:00", "02 12:30"]


def test_booking_adjacent_to_a_slot_does_not_block_it() -> None:
    booked = (at(MONDAY, 10), at(MONDAY, 11))
    barber = schedule(0, [(540, 780)], busy=[booked])

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=60))

    assert "02 09:00" in starts(result)
    assert "02 11:00" in starts(result)
    assert "02 09:30" not in starts(result)
    assert "02 10:30" not in starts(result)


def test_booking_crossing_midnight_blocks_the_start_of_the_next_day() -> None:
    room = Schedule(
        resource_id=uuid.uuid4(),
        weekly={0: [(1320, 1440)], 1: [(0, 180)]},
        busy=[(at(MONDAY, 23), at(datetime.date(2026, 11, 3), 1))],
    )
    tuesday = datetime.date(2026, 11, 3)

    result = slots([room], days=[MONDAY, tuesday], service=ServiceTiming(duration_min=60))

    assert starts(result) == ["02 22:00", "03 01:00", "03 01:30", "03 02:00"]


def test_service_can_cross_midnight_when_the_resource_stays_open() -> None:
    room = Schedule(resource_id=uuid.uuid4(), weekly={0: [(1320, 1440)], 1: [(0, 180)]})
    tuesday = datetime.date(2026, 11, 3)

    result = slots([room], days=[MONDAY, tuesday], service=ServiceTiming(duration_min=90))

    assert "02 23:30" in starts(result)
    assert "03 01:30" in starts(result)
    assert "03 02:00" not in starts(result)


def test_service_cannot_cross_midnight_when_the_resource_closes() -> None:
    room = Schedule(resource_id=uuid.uuid4(), weekly={0: [(1320, 1440)]})
    tuesday = datetime.date(2026, 11, 3)

    result = slots([room], days=[MONDAY, tuesday], service=ServiceTiming(duration_min=90))

    assert starts(result)[-1] == "02 22:30"


def test_step_defines_the_start_grid() -> None:
    barber = schedule(0, [(540, 600)])

    result = slots(
        [barber],
        days=[MONDAY],
        service=ServiceTiming(duration_min=20),
        policy=Policy(step_min=15, max_advance=FAR),
    )

    assert starts(result) == ["02 09:00", "02 09:15", "02 09:30"]


def test_grid_starts_at_the_first_multiple_of_the_step_inside_the_window() -> None:
    barber = schedule(0, [(545, 620)])

    result = slots(
        [barber],
        days=[MONDAY],
        service=ServiceTiming(duration_min=15),
        policy=Policy(step_min=15, max_advance=FAR),
    )

    assert starts(result) == ["02 09:15", "02 09:30", "02 09:45", "02 10:00"]


def test_days_without_rules_produce_nothing() -> None:
    barber = schedule(0, [(540, 600)])

    result = slots(
        [barber],
        days=[datetime.date(2026, 11, 3)],
        service=ServiceTiming(duration_min=30),
    )

    assert result == []


def test_closed_exception_removes_a_date() -> None:
    barber = schedule(0, [(540, 600)], exceptions={MONDAY: [ExceptionWindow("closed")]})

    result = slots([barber], days=[MONDAY], service=ServiceTiming(duration_min=30))

    assert result == []


# --- antecedência ------------------------------------------------------------------------------


def test_slots_in_the_past_are_dropped() -> None:
    barber = schedule(0, [(540, 720)])

    result = slots(
        [barber], days=[MONDAY], service=ServiceTiming(duration_min=30), now=at(MONDAY, 10)
    )

    assert starts(result) == ["02 10:00", "02 10:30", "02 11:00", "02 11:30"]


def test_minimum_notice_pushes_the_first_slot_forward() -> None:
    barber = schedule(0, [(540, 720)])

    result = slots(
        [barber],
        days=[MONDAY],
        service=ServiceTiming(duration_min=30),
        policy=Policy(step_min=30, min_notice=datetime.timedelta(hours=2)),
        now=at(MONDAY, 8),
    )

    assert starts(result) == ["02 10:00", "02 10:30", "02 11:00", "02 11:30"]


def test_maximum_advance_cuts_the_far_end() -> None:
    barber = schedule(0, [(540, 720)])

    result = slots(
        [barber],
        days=[MONDAY],
        service=ServiceTiming(duration_min=30),
        policy=Policy(step_min=30, max_advance=datetime.timedelta(hours=3)),
        now=at(MONDAY, 7),
    )

    assert starts(result) == ["02 09:00", "02 09:30", "02 10:00"]


# --- horário de verão --------------------------------------------------------------------------


def test_new_york_spring_forward_day_has_23_hours_of_slots() -> None:
    day = datetime.date(2026, 3, 8)
    shop = schedule(day.weekday(), ALL_DAY)

    result = slots(
        [shop],
        days=[day],
        service=ServiceTiming(duration_min=60),
        tz=NEW_YORK,
        policy=Policy(step_min=60, max_advance=FAR),
    )

    assert len(result) == 23
    assert result[0].start == at(day, 0, tz=NEW_YORK)
    assert result[-1].end == at(datetime.date(2026, 3, 9), 0, tz=NEW_YORK)
    # 02:00 não existe: depois de 01:00 EST vem 03:00 EDT.
    assert starts(result, NEW_YORK)[1:3] == ["08 01:00", "08 03:00"]


def test_new_york_fall_back_day_has_25_hours_of_slots() -> None:
    day = datetime.date(2026, 11, 1)
    shop = schedule(day.weekday(), ALL_DAY)

    result = slots(
        [shop],
        days=[day],
        service=ServiceTiming(duration_min=60),
        tz=NEW_YORK,
        policy=Policy(step_min=60, max_advance=FAR),
    )

    assert len(result) == 25
    # A hora das 01:00 acontece duas vezes e as duas têm slot.
    assert [slot.start.hour for slot in result[:4]] == [4, 5, 6, 7]
    assert result[-1].end == at(datetime.date(2026, 11, 2), 0, tz=NEW_YORK)


def test_service_duration_is_elapsed_time_across_the_fall_back() -> None:
    day = datetime.date(2026, 11, 1)
    shop = schedule(day.weekday(), [(0, 240)])

    result = slots(
        [shop],
        days=[day],
        service=ServiceTiming(duration_min=120),
        tz=NEW_YORK,
        policy=Policy(step_min=60, max_advance=FAR),
    )

    # 00:00-04:00 locais são cinco horas reais; cabem quatro serviços de duas horas.
    assert len(result) == 4
    assert all(slot.end - slot.start == datetime.timedelta(hours=2) for slot in result)


def test_new_york_dates_outside_the_transition_have_24_hours() -> None:
    day = datetime.date(2026, 3, 9)
    shop = schedule(day.weekday(), ALL_DAY)

    result = slots(
        [shop],
        days=[day],
        service=ServiceTiming(duration_min=60),
        tz=NEW_YORK,
        policy=Policy(step_min=60, max_advance=FAR),
    )

    assert len(result) == 24


def test_sao_paulo_historical_dst_start_has_23_hours() -> None:
    # Em 4/11/2018 os relógios foram de 00:00 para 01:00.
    day = datetime.date(2018, 11, 4)
    shop = schedule(day.weekday(), ALL_DAY)

    result = slots(
        [shop],
        days=[day],
        service=ServiceTiming(duration_min=60),
        policy=Policy(step_min=60, max_advance=datetime.timedelta(days=36500)),
        now=datetime.datetime(2018, 1, 1, tzinfo=UTC),
    )

    assert len(result) == 23
    assert result[0].start.astimezone(SAO_PAULO).hour == 1


def test_sao_paulo_historical_dst_end_has_25_hours() -> None:
    # Em 17/02/2019 à meia-noite os relógios voltaram para 23:00 de 16/02.
    day = datetime.date(2019, 2, 16)
    shop = schedule(day.weekday(), ALL_DAY)

    result = slots(
        [shop],
        days=[day],
        service=ServiceTiming(duration_min=60),
        policy=Policy(step_min=60, max_advance=datetime.timedelta(days=36500)),
        now=datetime.datetime(2019, 1, 1, tzinfo=UTC),
    )

    assert len(result) == 25


def test_sao_paulo_today_has_no_dst_shift() -> None:
    shop = schedule(0, [(540, 600)])

    result = slots([shop], days=[MONDAY], service=ServiceTiming(duration_min=60))

    assert result[0].start == datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


# --- mais de um recurso ------------------------------------------------------------------------


def test_slot_lists_every_performer_that_is_free() -> None:
    first = schedule(0, [(540, 600)])
    second = schedule(0, [(540, 570)])

    result = slots([first, second], days=[MONDAY], service=ServiceTiming(duration_min=30))

    assert starts(result) == ["02 09:00", "02 09:30"]
    assert result[0].assignments == ((first.resource_id,), (second.resource_id,))
    assert result[1].assignments == ((first.resource_id,),)


def test_a_busy_performer_leaves_the_slot_to_the_other() -> None:
    first = schedule(0, [(540, 600)], busy=[(at(MONDAY, 9), at(MONDAY, 9, 30))])
    second = schedule(0, [(540, 600)])

    result = slots([first, second], days=[MONDAY], service=ServiceTiming(duration_min=30))

    assert result[0].assignments == ((second.resource_id,),)
    assert result[1].assignments == ((first.resource_id,), (second.resource_id,))


def test_service_with_two_resources_needs_both_free() -> None:
    doctor = schedule(0, [(540, 660)])
    room_one = schedule(0, [(540, 660)], busy=[(at(MONDAY, 9), at(MONDAY, 10))])
    room_two = schedule(0, [(600, 660)])

    result = slots(
        [doctor],
        days=[MONDAY],
        service=ServiceTiming(duration_min=60),
        required={"sala": [room_one, room_two]},
    )

    # Às 09:00 a sala 1 está ocupada e a sala 2 ainda não abriu; só a partir das 10:00 há sala.
    assert starts(result) == ["02 10:00"]
    assert result[0].assignments == ((doctor.resource_id, room_one.resource_id),)


def test_only_one_of_two_rooms_free_still_makes_a_slot() -> None:
    doctor = schedule(0, [(540, 600)])
    room_one = schedule(0, [(540, 600)], busy=[(at(MONDAY, 9), at(MONDAY, 10))])
    room_two = schedule(0, [(540, 600)])

    result = slots(
        [doctor],
        days=[MONDAY],
        service=ServiceTiming(duration_min=60),
        required={"sala": [room_one, room_two]},
    )

    assert result[0].assignments == ((doctor.resource_id, room_two.resource_id),)


def test_no_slot_when_the_required_resource_is_busy() -> None:
    doctor = schedule(0, [(540, 600)])
    room = schedule(0, [(540, 600)], busy=[(at(MONDAY, 9), at(MONDAY, 10))])

    result = slots(
        [doctor],
        days=[MONDAY],
        service=ServiceTiming(duration_min=60),
        required={"sala": [room]},
    )

    assert result == []


def test_every_required_kind_must_have_a_free_resource() -> None:
    doctor = schedule(0, [(540, 600)])
    room = schedule(0, [(540, 600)])
    equipment = schedule(0, [(540, 600)], busy=[(at(MONDAY, 9), at(MONDAY, 10))])

    result = slots(
        [doctor],
        days=[MONDAY],
        service=ServiceTiming(duration_min=60),
        required={"sala": [room], "equipamento": [equipment]},
    )

    assert result == []


def test_required_resources_are_picked_in_the_order_given() -> None:
    doctor = schedule(0, [(540, 600)])
    rooms = [schedule(0, [(540, 600)]) for _ in range(3)]

    result = slots(
        [doctor],
        days=[MONDAY],
        service=ServiceTiming(duration_min=60),
        required={"sala": rooms},
    )

    assert result[0].assignments == ((doctor.resource_id, rooms[0].resource_id),)


def test_a_performer_of_the_required_kind_is_not_used_twice() -> None:
    first = schedule(0, [(540, 600)])
    second = schedule(0, [(540, 600)])

    result = slots(
        [first],
        days=[MONDAY],
        service=ServiceTiming(duration_min=60),
        required={"sala": [first, second]},
    )

    assert result[0].assignments == ((first.resource_id, second.resource_id),)


def test_buffers_also_apply_to_the_required_resource() -> None:
    doctor = schedule(0, [(540, 660)])
    room = schedule(0, [(540, 660)], busy=[(at(MONDAY, 10, 5), at(MONDAY, 10, 30))])
    service = ServiceTiming(duration_min=30, buffer_after_min=10)

    result = slots([doctor], days=[MONDAY], service=service, required={"sala": [room]})

    assert starts(result) == ["02 09:00", "02 10:30"]


def test_free_starts_ignores_days_outside_the_window() -> None:
    barber = Schedule(resource_id=uuid.uuid4(), weekly={0: [(540, 600)], 1: [(540, 600)]})

    result = free_starts(
        barber,
        service=ServiceTiming(duration_min=30),
        days=[MONDAY],
        tz=SAO_PAULO,
        step_min=30,
    )

    assert len(result) == 2


@pytest.mark.parametrize("step", [5, 10, 15, 20, 30, 60])
def test_every_supported_step_yields_aligned_starts(step: int) -> None:
    barber = schedule(0, [(540, 720)])

    result = slots(
        [barber],
        days=[MONDAY],
        service=ServiceTiming(duration_min=step),
        policy=Policy(step_min=step, max_advance=FAR),
    )

    assert len(result) == 180 // step
    assert all(slot.start.minute % step == 0 for slot in result)


def room(capacity: int, *seats: list[tuple[datetime.datetime, datetime.datetime]]) -> Schedule:
    return Schedule(
        resource_id=uuid.uuid4(),
        weekly={0: [(540, 660)]},
        capacity=capacity,
        busy_by_seat=list(seats),
    )


def starts_of(found: list[Slot]) -> list[datetime.datetime]:
    return [slot.start for slot in found]


def test_a_room_with_an_unused_seat_is_free_even_if_other_seats_are_taken() -> None:
    hour = (at(MONDAY, 9), at(MONDAY, 10))

    found = slots([room(3, [hour], [hour])], days=[MONDAY], service=ServiceTiming(60))

    assert at(MONDAY, 9) in starts_of(found)


def test_a_room_with_every_seat_taken_is_busy() -> None:
    hour = (at(MONDAY, 9), at(MONDAY, 10))

    found = slots([room(2, [hour], [hour])], days=[MONDAY], service=ServiceTiming(60))

    assert starts_of(found) == [at(MONDAY, 10)]


def test_a_seat_free_for_the_whole_interval_is_needed_not_just_free_at_each_instant() -> None:
    # Cada vaga tem uma reserva em pontos diferentes do intervalo candidato (09:00-11:00): em
    # nenhum instante as duas estão ocupadas, mas nenhuma vaga fica livre o tempo todo, e é assim
    # que o banco decide (a restrição é por vaga).
    first = [(at(MONDAY, 9), at(MONDAY, 9, 30))]
    second = [(at(MONDAY, 10, 30), at(MONDAY, 11))]

    found = slots([room(2, first, second)], days=[MONDAY], service=ServiceTiming(120))

    assert found == []
