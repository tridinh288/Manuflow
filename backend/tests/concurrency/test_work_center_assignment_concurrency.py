"""C-07 under concurrency: assigning a worker locks the work center row.

Deactivation counts active workers while holding the work center's row lock. If
assignment did not take the same lock, a worker could be assigned to a work center
that is being deactivated at the same moment, leaving an inactive work center with an
active worker.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.user import User
from app.models.work_center import WorkCenter
from app.services.context import Actor, RequestContext
from app.services.user_service import NewUser, UserService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 10


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def work_center_id(factory: sessionmaker[Session]) -> Iterator[int]:
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        work_center = WorkCenter(code=f"WC-C{marker}", name="Concurrency", active=True)
        session.add(work_center)
        session.flush()
        new_id = work_center.id
    yield new_id
    # The audit row has no actor and no FK to the user, so both rows can be removed.
    with factory() as session, session.begin():
        session.execute(delete(User).where(User.work_center_id == new_id))
        session.execute(delete(WorkCenter).where(WorkCenter.id == new_id))


def create_worker(factory: sessionmaker[Session], work_center_id: int) -> str:
    with factory() as session:
        try:
            _create(session, work_center_id)
        except DomainError as exc:
            return exc.code
    return "OK"


def _create(session: Session, work_center_id: int) -> None:
    UserService(session, PasswordHasher()).create_user(
        NewUser(
            username=f"conc-worker-{uuid.uuid4().hex[:8]}",
            password="concurrency-password",
            full_name="Concurrency Worker",
            role=Role.WORKER,
            work_center_id=work_center_id,
        ),
        Actor(user_id=None, username="conc"),
        RequestContext(),
    )


def test_c07_assignment_sees_a_concurrent_deactivation(
    factory: sessionmaker[Session], work_center_id: int
) -> None:
    """The harmful interleaving: assignment starts while a deactivation is uncommitted.

    With a plain read, assignment sees the committed snapshot (still active), and its
    INSERT merely waits on the FK check until the deactivation commits, then succeeds.
    With the locking read it waits first and then sees the work center is inactive.
    """
    with factory() as holder, holder.begin():
        holder.execute(
            text("SELECT id FROM work_centers WHERE id = :id FOR UPDATE"), {"id": work_center_id}
        )
        holder.execute(
            text("UPDATE work_centers SET active = 0 WHERE id = :id"), {"id": work_center_id}
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(create_worker, factory, work_center_id)
            time.sleep(0.5)
            assert not pending.done(), "assignment must wait for the deactivation to finish"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "WORK_CENTER_INACTIVE"
