"""Engine and session factory.

Sessions are synchronous on purpose (B2): each service method owns exactly one
transaction via ``with session.begin():`` and repositories never commit (B12).
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        isolation_level="REPEATABLE READ",
        pool_pre_ping=True,
        pool_recycle=1800,
        # B16: DB errors are logged with their traceback; bound values (password hashes,
        # usernames) must not end up in that log.
        hide_parameters=True,
        connect_args={
            # All timestamps are UTC (D-23), regardless of the server default.
            "init_command": "SET time_zone = '+00:00'",
            "connect_timeout": 5,
        },
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
