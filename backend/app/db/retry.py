"""Retry a whole transaction on MySQL deadlock or lock-wait timeout (B12).

Safe because the failed transaction has already been rolled back in full. After the
last attempt the caller gets 503 CONCURRENCY_CONFLICT.
"""

import random
import time
from collections.abc import Callable

from sqlalchemy.exc import OperationalError

from app.domain.errors import ConcurrencyConflictError

MYSQL_DEADLOCK = 1213
MYSQL_LOCK_WAIT_TIMEOUT = 1205
RETRYABLE_ERRORS = frozenset({MYSQL_DEADLOCK, MYSQL_LOCK_WAIT_TIMEOUT})
MAX_ATTEMPTS = 3


def is_lock_conflict(exc: OperationalError) -> bool:
    args: tuple[object, ...] = getattr(exc.orig, "args", ())
    return bool(args) and args[0] in RETRYABLE_ERRORS


def run_with_lock_retry[T](
    operation: Callable[[], T],
    *,
    attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError as exc:
            if not is_lock_conflict(exc):
                raise
            if attempt == attempts:
                raise ConcurrencyConflictError(
                    "CONCURRENCY_CONFLICT",
                    "The request conflicted with concurrent changes; please retry.",
                ) from exc
            # Short exponential backoff with jitter: 50-100 ms, 100-200 ms, ...
            base = 0.05 * 2 ** (attempt - 1)
            sleep(base + random.uniform(0, base))  # noqa: S311  (not cryptographic)
    raise AssertionError("unreachable")  # pragma: no cover
