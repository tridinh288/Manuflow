"""B12: deadlocks and lock-wait timeouts retry the whole transaction, then 503."""

import pytest
from sqlalchemy.exc import OperationalError

from app.db.retry import MYSQL_DEADLOCK, MYSQL_LOCK_WAIT_TIMEOUT, run_with_lock_retry
from app.domain.errors import ConcurrencyConflictError


def mysql_error(code: int) -> OperationalError:
    return OperationalError("UPDATE inventory ...", {}, Exception(code, "simulated"))


class Flaky:
    def __init__(self, failures: list[int]) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise mysql_error(self.failures.pop(0))
        return "committed"


@pytest.mark.parametrize("code", [MYSQL_DEADLOCK, MYSQL_LOCK_WAIT_TIMEOUT])
def test_b12_lock_conflict_is_retried(code: int) -> None:
    operation, pauses = Flaky([code, code]), []
    assert run_with_lock_retry(operation, sleep=pauses.append) == "committed"
    assert operation.calls == 3
    assert len(pauses) == 2


def test_b12_gives_up_with_503_after_three_attempts() -> None:
    operation = Flaky([MYSQL_DEADLOCK] * 3)
    with pytest.raises(ConcurrencyConflictError) as exc_info:
        run_with_lock_retry(operation, sleep=lambda _: None)
    assert exc_info.value.code == "CONCURRENCY_CONFLICT"
    assert operation.calls == 3


def test_b12_other_database_errors_are_not_retried() -> None:
    operation = Flaky([1146])  # table does not exist
    with pytest.raises(OperationalError):
        run_with_lock_retry(operation, sleep=lambda _: None)
    assert operation.calls == 1
