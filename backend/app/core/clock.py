"""Injectable clock (D-23, D-24): business code never reads the system time directly."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FixedClock:
    """Deterministic clock for tests."""

    current: datetime

    def __post_init__(self) -> None:
        if self.current.utcoffset() != timedelta(0):
            raise ValueError("FixedClock requires a timezone-aware UTC datetime")

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta
