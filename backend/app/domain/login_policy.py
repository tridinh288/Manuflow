"""Account lockout rule (BR-AUTH-05, C-06): pure functions, time passed in.

Five failed logins within 15 minutes lock the account for 15 minutes. The window starts
at the first failure; a failure after the window has passed starts a new window.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)


@dataclass(frozen=True)
class LoginAttemptState:
    failed_count: int = 0
    first_failed_at: datetime | None = None
    locked_until: datetime | None = None


CLEAN_STATE = LoginAttemptState()


def is_locked(state: LoginAttemptState, now: datetime) -> bool:
    return state.locked_until is not None and now < state.locked_until


def register_failure(state: LoginAttemptState, now: datetime) -> LoginAttemptState:
    window_open = state.first_failed_at is not None and now - state.first_failed_at < FAILURE_WINDOW
    failed_count = state.failed_count + 1 if window_open else 1
    first_failed_at = state.first_failed_at if window_open else now
    if failed_count >= MAX_FAILED_ATTEMPTS:
        # Lock and start counting afresh once the lock expires.
        return LoginAttemptState(locked_until=now + LOCK_DURATION)
    return LoginAttemptState(failed_count=failed_count, first_failed_at=first_failed_at)


def register_success() -> LoginAttemptState:
    return CLEAN_STATE
