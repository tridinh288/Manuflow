"""Shared fixtures for integration tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.services.context import Actor, RequestContext
from app.services.user_service import NewUser, UserService
from seed.demo import seed_demo

PASSWORD = "demo-password-for-tests"


@pytest.fixture
def seeded(
    db_client: TestClient, db_session: Session, clock: FixedClock
) -> Iterator[dict[str, int]]:
    def create_admin(username: str, password: str) -> None:
        UserService(db_session, PasswordHasher()).create_user(
            NewUser(
                username=username,
                password=password,
                full_name="Demo Admin",
                role=Role.ADMIN,
                work_center_id=None,
            ),
            Actor(user_id=None, username="seed"),
            RequestContext(),
        )

    now = clock.now()
    orders = seed_demo(db_client, clock, PASSWORD, create_admin)
    assert clock.now() == now  # the story ends at "now"
    yield orders
