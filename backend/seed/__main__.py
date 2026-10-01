"""Load the demo shop into an empty development database.

    # SEED_DEMO_PASSWORD set in .env (see .env.example), then:
    docker compose exec api python -m seed

Refuses to run outside ENV=dev, without SEED_DEMO_PASSWORD (at least 10 characters,
shared by every demo account), or when the database already holds business data.
The password is never accepted as an argument (shell history, ``ps``) and never printed.
"""

import logging
import os
import sys
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import FixedClock
from app.core.config import Environment, get_settings
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.domain.users import MIN_PASSWORD_LENGTH
from app.main import create_app
from app.models.master_data import Material, Product
from app.models.production import ProductionOrder
from app.models.user import User
from app.services.context import Actor, RequestContext
from app.services.user_service import NewUser, UserService
from seed.demo import ADMIN_USERNAME, USERS, SeedError, seed_demo

SEED_ACTOR = Actor(user_id=None, username="seed")
PASSWORD_ENV = "SEED_DEMO_PASSWORD"  # noqa: S105 - the variable name, not a password


def business_data_present(session: Session) -> list[str]:
    """Names of what is already there; the seed only runs on an empty shop."""
    found = []
    for label, model in (
        ("products", Product),
        ("materials", Material),
        ("production orders", ProductionOrder),
    ):
        if session.scalar(select(func.count()).select_from(model)):
            found.append(label)
    demo_users = [ADMIN_USERNAME, *(username for username, *_ in USERS)]
    if session.scalar(select(func.count()).where(User.username.in_(demo_users))):
        found.append("demo users")
    return found


class AdminCreator:
    """The API cannot create the first ADMIN (by design); do it like ``app.cli``."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def __call__(self, username: str, password: str) -> None:
        with self._factory() as session:
            UserService(session, PasswordHasher()).create_user(
                NewUser(
                    username=username,
                    password=password,
                    full_name="Demo Admin",
                    role=Role.ADMIN,
                    work_center_id=None,
                ),
                SEED_ACTOR,
                RequestContext(),
            )


def main() -> int:
    settings = get_settings()
    if settings.env is not Environment.DEV:
        print("refusing to seed: ENV must be dev", file=sys.stderr)
        return 1
    password = os.environ.get(PASSWORD_ENV, "")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"set {PASSWORD_ENV} (at least {MIN_PASSWORD_LENGTH} characters)", file=sys.stderr)
        return 1

    clock = FixedClock(datetime.now(UTC).replace(microsecond=0))
    app = create_app(settings, clock=clock)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per in-process call
    factory: sessionmaker[Session] = app.state.session_factory
    with factory() as session:
        present = business_data_present(session)
    if present:
        print(f"refusing to seed: database already has {', '.join(present)}", file=sys.stderr)
        return 1

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            orders = seed_demo(client, clock, password, AdminCreator(factory))
    except SeedError as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1
    print("demo shop loaded:")
    for label, order_id in orders.items():
        print(f"  {label:10} production order id {order_id}")
    print(f"accounts: {ADMIN_USERNAME}, " + ", ".join(u for u, *_ in USERS))
    print(f"password: the value of {PASSWORD_ENV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
