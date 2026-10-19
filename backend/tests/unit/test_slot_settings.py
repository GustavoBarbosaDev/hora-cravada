import pytest

from app.slots.schemas import SlotPolicySettings


def test_missing_settings_use_the_defaults() -> None:
    policy = SlotPolicySettings.from_tenant({})

    assert (policy.min_notice_min, policy.max_advance_days) == (0, 90)


def test_configured_values_are_read() -> None:
    policy = SlotPolicySettings.from_tenant(
        {"slots": {"min_notice_min": 120, "max_advance_days": 30}}
    )

    assert (policy.min_notice_min, policy.max_advance_days) == (120, 30)


def test_a_partial_block_keeps_the_default_for_the_rest() -> None:
    policy = SlotPolicySettings.from_tenant({"slots": {"min_notice_min": 60}})

    assert (policy.min_notice_min, policy.max_advance_days) == (60, 90)


@pytest.mark.parametrize(
    "settings",
    [
        {"slots": "invalid"},
        {"slots": {"min_notice_min": -5}},
        {"slots": {"max_advance_days": 0}},
        {"slots": {"max_advance_days": "tomorrow"}},
        {"slots": None},
    ],
)
def test_invalid_settings_fall_back_to_the_defaults(settings: dict[str, object]) -> None:
    policy = SlotPolicySettings.from_tenant(settings)

    assert (policy.min_notice_min, policy.max_advance_days) == (0, 90)
