"""Shared fixtures.

Unit tests need no database. Integration and API tests run against the real MySQL
schema built by Alembic (B15: no SQLite, no ``create_all``). Each DB test runs inside an
outer transaction that is rolled back at the end; the session joins it with SAVEPOINTs,
so service code can still use ``with session.begin():`` normally.
"""

import itertools
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_session
from app.core.clock import FixedClock
from app.core.config import Environment, Settings
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.db.session import build_engine
from app.domain.errors import (
    BusinessValidationError,
    ConcurrencyConflictError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from app.main import create_app
from app.models.bom import BomHeader, BomItem
from app.models.master_data import Inventory, Material, Product
from app.models.routing import Routing, RoutingStep
from app.models.user import User
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse
from app.models.work_center import WorkCenter

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-0123456789abcdef"
# Port 1 refuses connections immediately: used where no database is expected.
UNREACHABLE_DB_URL = "mysql+pymysql://nobody:nothing@127.0.0.1:1/none"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run concurrency tests last.

    They must commit real data, and audit rows they cause can never be deleted
    (BR-AUD-06), so they run after every test that counts rows.
    """
    items.sort(key=lambda item: item.get_closest_marker("concurrency") is not None)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(
            f"{name} is not set. DB tests need MySQL: run `docker compose exec api pytest`.",
            pytrace=False,
        )
    return value


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env=Environment.TEST,
        database_url=os.environ.get("TEST_DATABASE_URL", UNREACHABLE_DB_URL),
        migration_database_url=os.environ.get("TEST_MIGRATION_DATABASE_URL", UNREACHABLE_DB_URL),
        jwt_secret=TEST_JWT_SECRET,
        cors_origins=[],
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 30, 8, 0, tzinfo=UTC))


@pytest.fixture
def app(settings: Settings, clock: FixedClock) -> FastAPI:
    return create_app(settings, clock=clock)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Rebuild the test schema from scratch once per run; also proves downgrade works."""
    migration_url = _require_env("TEST_MIGRATION_DATABASE_URL")
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return _require_env("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def db_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = build_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    with db_engine.connect() as connection:
        outer_transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            outer_transaction.rollback()


@pytest.fixture
def db_client(app: FastAPI, db_session: Session, clock: FixedClock) -> Iterator[TestClient]:
    def request_session() -> Iterator[Session]:
        # Production gives every request a fresh session. Mirror that: close whatever
        # transaction the test body opened while reading (only a SAVEPOINT here).
        if db_session.in_transaction():
            db_session.commit()
        yield db_session

    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_clock] = lambda: clock
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Data factories -------------------------------------------------------------------

DEFAULT_PASSWORD = "correct-horse-battery-staple"
_hasher = PasswordHasher()
_hash_cache: dict[str, str] = {}


def hash_password(password: str) -> str:
    # Argon2 is slow on purpose; hash each distinct test password once per run.
    if password not in _hash_cache:
        _hash_cache[password] = _hasher.hash(password)
    return _hash_cache[password]


def insert(session: Session, *rows: object) -> None:
    """Commit test data through the same SAVEPOINT-per-transaction path services use."""
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.add_all(rows)


ProductFactory = Callable[..., Product]
MaterialFactory = Callable[..., Material]
WorkCenterFactory = Callable[..., WorkCenter]
BomFactory = Callable[..., BomHeader]
RoutingFactory = Callable[..., Routing]


@pytest.fixture
def routing_factory(db_session: Session) -> RoutingFactory:
    """A routing version with steps ``(sequence, operation_type, work_center)``."""

    def create(
        product: Product,
        steps: list[tuple[int, str, WorkCenter]],
        *,
        version: int = 1,
        status: str = "DRAFT",
    ) -> Routing:
        routing = Routing(
            product_id=product.id,
            version=version,
            status=status,
            steps=[
                RoutingStep(sequence=seq, operation_type=op, work_center_id=wc.id)
                for seq, op, wc in steps
            ],
        )
        insert(db_session, routing)
        return routing

    return create


@pytest.fixture
def bom_factory(db_session: Session) -> BomFactory:
    """A BOM version with lines ``(material, qty_per_unit, scrap_rate)``."""

    def create(
        product: Product,
        lines: list[tuple[Material, str, str]],
        *,
        version: int = 1,
        status: str = "DRAFT",
    ) -> BomHeader:
        header = BomHeader(
            product_id=product.id,
            version=version,
            status=status,
            items=[
                BomItem(material_id=m.id, qty_per_unit=Decimal(q), scrap_rate=Decimal(s))
                for m, q, s in lines
            ],
        )
        insert(db_session, header)
        return header

    return create


@pytest.fixture
def product_factory(db_session: Session) -> ProductFactory:
    sequence = itertools.count(1)

    def create(code: str | None = None, *, name: str = "Product", active: bool = True) -> Product:
        product = Product(
            product_code=code or f"PRD-T{next(sequence):03d}", name=name, unit="pcs", active=active
        )
        insert(db_session, product)
        return product

    return create


@pytest.fixture
def material_factory(db_session: Session) -> MaterialFactory:
    """Material plus its zero balance row, as the service creates them (BR-INV-01)."""
    sequence = itertools.count(1)

    def create(
        code: str | None = None,
        *,
        unit: str = "kg",
        decimal_places: int = 3,
        minimum_stock: Decimal = Decimal(0),
        active: bool = True,
    ) -> Material:
        material = Material(
            material_code=code or f"MAT-T{next(sequence):03d}",
            name="Material",
            unit=unit,
            decimal_places=decimal_places,
            minimum_stock=minimum_stock,
            active=active,
        )
        insert(db_session, material)
        with db_session.begin():
            warehouse_id = db_session.scalars(
                select(Warehouse.id).where(Warehouse.code == DEFAULT_WAREHOUSE_CODE)
            ).one()
            db_session.add(Inventory(warehouse_id=warehouse_id, material_id=material.id))
        return material

    return create


UserFactory = Callable[..., User]


@pytest.fixture
def work_center_factory(db_session: Session) -> WorkCenterFactory:
    sequence = itertools.count(1)

    def create(code: str | None = None, name: str = "Work center") -> WorkCenter:
        work_center = WorkCenter(code=code or f"WC-T{next(sequence):03d}", name=name)
        insert(db_session, work_center)
        return work_center

    return create


@pytest.fixture
def user_factory(db_session: Session, work_center_factory: WorkCenterFactory) -> UserFactory:
    sequence = itertools.count(1)

    def create(
        username: str | None = None,
        *,
        role: Role = Role.PRODUCTION_MANAGER,
        password: str = DEFAULT_PASSWORD,
        active: bool = True,
        work_center_id: int | None = None,
    ) -> User:
        if role is Role.WORKER and work_center_id is None:
            work_center_id = work_center_factory().id
        user = User(
            username=username or f"user{next(sequence):03d}",
            password_hash=hash_password(password),
            full_name="Test User",
            role=role,
            work_center_id=work_center_id,
            active=active,
        )
        insert(db_session, user)
        return user

    return create


# --- Probe routes: exercise middleware and error handling without business endpoints ---

PROBE_LOGGER = "tests.probe"

DOMAIN_ERRORS: dict[str, DomainError] = {
    "not_found": NotFoundError("PRODUCT_NOT_FOUND", "Product not found."),
    "conflict": ConflictError(
        "INSUFFICIENT_STOCK",
        "Not enough available stock for 1 material.",
        [{"material_code": "BOLT-M8", "required": "840", "available": "500", "shortage": "340"}],
    ),
    "validation": BusinessValidationError(
        "INVALID_QUANTITY", "Quantity must be a positive integer."
    ),
    "concurrency": ConcurrencyConflictError("CONCURRENCY_CONFLICT", "Please retry the request."),
}


class ProbeBody(BaseModel):
    password: str
    quantity: int = Field(gt=0)


@pytest.fixture
def probe_client(app: FastAPI) -> Iterator[TestClient]:
    @app.get("/_probe/ok")
    def probe_ok() -> dict[str, str]:
        logging.getLogger(PROBE_LOGGER).info("probe handled")
        return {"status": "ok"}

    @app.get("/_probe/domain/{kind}")
    def probe_domain_error(kind: str) -> None:
        raise DOMAIN_ERRORS[kind]

    @app.get("/_probe/crash")
    def probe_crash() -> None:
        raise RuntimeError("internal detail: SELECT password_hash FROM users")

    @app.post("/_probe/validate")
    def probe_validate(body: ProbeBody) -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


LoginAs = Callable[..., dict[str, str]]


@pytest.fixture
def login_as(db_client: TestClient, user_factory: UserFactory) -> LoginAs:
    """Create a user with the given role, log in, and return the Authorization header."""

    def login(role: Role = Role.ADMIN, **user_fields: object) -> dict[str, str]:
        user = user_factory(role=role, **user_fields)
        response = db_client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return login
