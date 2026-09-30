"""D-23 / D-24: time is UTC and injectable."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.clock import FixedClock, SystemClock


def test_d23_system_clock_returns_aware_utc() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)


def test_d24_fixed_clock_is_deterministic_and_advances() -> None:
    clock = FixedClock(datetime(2026, 10, 1, 14, 0, tzinfo=UTC))
    assert clock.now() == clock.now()
    clock.advance(timedelta(hours=2))
    assert clock.now() == datetime(2026, 10, 1, 16, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 10, 1, 14, 0),  # noqa: DTZ001  (naive on purpose)
        datetime(2026, 10, 1, 14, 0, tzinfo=timezone(timedelta(hours=7))),
    ],
)
def test_d23_fixed_clock_rejects_non_utc(value: datetime) -> None:
    with pytest.raises(ValueError, match="UTC"):
        FixedClock(value)
