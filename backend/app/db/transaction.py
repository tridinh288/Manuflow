"""Transaction ownership (B12): one use case = one DB transaction.

Service methods open their transaction with ``transaction(session)``. Normally that is
simply ``session.begin()``. The only exception is the idempotency wrapper (C-03): it
opens the transaction with ``joinable_transaction(session)`` so the idempotency key, the
business change and the stored response commit or roll back together, and the service
method it calls *joins* that transaction instead of opening its own.

Joining is opt-in through an explicit flag, never inferred from ``in_transaction()``:
an accidental autobegun transaction must still fail loudly in ``session.begin()``.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

_JOINABLE = "manuflow_joinable_transaction"


@contextmanager
def transaction(session: Session) -> Iterator[None]:
    if session.info.get(_JOINABLE):
        yield
        return
    with session.begin():
        yield


@contextmanager
def joinable_transaction(session: Session) -> Iterator[None]:
    with session.begin():
        session.info[_JOINABLE] = True
        try:
            yield
        finally:
            session.info.pop(_JOINABLE, None)
