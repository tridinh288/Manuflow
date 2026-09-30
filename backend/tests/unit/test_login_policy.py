"""BR-AUTH-05 / C-06: 5 failures within 15 minutes lock the account for 15 minutes."""

from datetime import UTC, datetime, timedelta

from app.domain.login_policy import (
    CLEAN_STATE,
    LOCK_DURATION,
    LoginAttemptState,
    is_locked,
    register_failure,
    register_success,
)

T0 = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


def _fail(
    times: int, start: datetime = T0, step: timedelta = timedelta(minutes=1)
) -> LoginAttemptState:
    state = CLEAN_STATE
    for i in range(times):
        state = register_failure(state, start + i * step)
    return state


def test_br_auth_05_four_failures_do_not_lock() -> None:
    state = _fail(4)
    assert state.failed_count == 4
    assert not is_locked(state, T0 + timedelta(minutes=4))


def test_br_auth_05_fifth_failure_within_window_locks_for_15_minutes() -> None:
    state = _fail(5)  # failures at T0 .. T0+4min
    locked_at = T0 + timedelta(minutes=4)
    assert state.locked_until == locked_at + LOCK_DURATION
    assert is_locked(state, locked_at + LOCK_DURATION - timedelta(microseconds=1))
    assert not is_locked(state, locked_at + LOCK_DURATION)


def test_br_auth_05_failures_spread_beyond_window_do_not_lock() -> None:
    # One failure every 4 minutes: the 5th is 16 minutes after the first.
    state = _fail(5, step=timedelta(minutes=4))
    assert state.locked_until is None
    assert state.failed_count == 1  # the 5th failure opened a new window


def test_br_auth_05_window_boundary_is_exclusive() -> None:
    state = _fail(4)
    state = register_failure(state, T0 + timedelta(minutes=15))
    assert state.locked_until is None
    assert state.first_failed_at == T0 + timedelta(minutes=15)


def test_br_auth_05_counter_starts_fresh_after_lock() -> None:
    locked = _fail(5)
    assert locked.failed_count == 0
    assert locked.first_failed_at is None


def test_br_auth_05_success_resets_state() -> None:
    assert register_success() == CLEAN_STATE
