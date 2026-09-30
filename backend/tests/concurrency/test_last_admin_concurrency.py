"""C-12 under concurrency: demoting an ADMIN waits for every other active ADMIN row.

Without that lock, two admins deactivating each other at the same moment would each
still see the other as active, and both would succeed, leaving no admin at all.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.db.session import build_session_factory
from app.models.user import User
from app.services.context import Actor, RequestContext
from app.services.user_service import UserService, UserUpdate

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 10


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def two_admins(factory: sessionmaker[Session]) -> Iterator[tuple[int, int]]:
    marker = uuid.uuid4().hex[:8]
    with factory() as session, session.begin():
        admins = [
            User(
                username=f"conc-admin-{marker}-{n}",
                password_hash="not-used",
                full_name="Concurrency Admin",
                role=Role.ADMIN,
                active=True,
            )
            for n in (1, 2)
        ]
        session.add_all(admins)
        session.flush()
        ids = (admins[0].id, admins[1].id)
    yield ids
    # Audit rows now reference these users and can never be deleted (BR-AUD-06), so
    # neutralize the users instead of deleting them.
    with factory() as session, session.begin():
        session.execute(
            update(User).where(User.id.in_(ids)).values(active=False, role=Role.WAREHOUSE)
        )


def active_admin_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        count = session.scalar(
            text("SELECT COUNT(*) FROM users WHERE role = 'ADMIN' AND active = 1")
        )
    return int(count or 0)


def deactivate(factory: sessionmaker[Session], target_id: int) -> str:
    """Deactivate ``target_id``. The actor has no user row: an audit FK to a locked admin
    row would block on its own and hide whether the guard's lock is what waits."""
    with factory() as session:
        service = UserService(session, PasswordHasher())
        try:
            service.update_user(
                target_id,
                UserUpdate(provided=frozenset({"active"}), active=False),
                Actor(user_id=None, username="conc"),
                RequestContext(),
            )
        except Exception as exc:
            return getattr(exc, "code", type(exc).__name__)
        return "OK"


def test_c12_demotion_waits_for_locks_on_the_other_active_admins(
    factory: sessionmaker[Session], two_admins: tuple[int, int]
) -> None:
    admin_1, admin_2 = two_admins
    with factory() as holder, holder.begin():
        # Another transaction holds admin 1's row, e.g. while deciding to demote admin 2.
        holder.execute(text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": admin_1})
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(deactivate, factory, admin_2)
            time.sleep(0.5)
            # Deactivating admin 2 must wait on admin 1's row, not just lock admin 2.
            assert not pending.done(), "the guard must lock every other active ADMIN"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "OK"


def test_c12_two_admins_deactivating_each_other_leave_one_admin(
    factory: sessionmaker[Session], two_admins: tuple[int, int]
) -> None:
    admin_1, admin_2 = two_admins
    assert active_admin_count(factory) == 2, "precondition: these are the only admins"
    start = threading.Barrier(2)

    def race(target: int) -> str:
        start.wait(WAIT_SECONDS)
        return deactivate(factory, target)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(
            f.result(WAIT_SECONDS) for f in [pool.submit(race, admin_2), pool.submit(race, admin_1)]
        )

    assert results == ["LAST_ADMIN", "OK"]
    assert active_admin_count(factory) == 1
