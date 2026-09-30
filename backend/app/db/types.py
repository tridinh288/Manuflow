from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """``DATETIME(6)`` holding UTC (D-23).

    Only timezone-aware datetimes are accepted on write; values read back are aware UTC.
    """

    impl = DATETIME
    cache_ok = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(fsp=6, **kwargs)

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("naive datetime cannot be stored; use an aware UTC datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)
