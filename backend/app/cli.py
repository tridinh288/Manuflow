"""Operator commands.

``create-user`` bootstraps the first ADMIN, which the API cannot do by design.
``purge-idempotency-keys`` deletes keys past their TTL (C-08); expired keys are already
ignored on use, so this only reclaims space and can run at any time (e.g. from cron).

    docker compose exec api python -m app.cli create-user --username admin \\
        --full-name "System Admin" --role ADMIN

The password is read from the environment variable named by ``--password-env`` or
prompted for; it is never accepted as a command-line argument (shell history, ``ps``).
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.db.session import build_engine, build_session_factory
from app.domain.errors import DomainError
from app.services.context import Actor, RequestContext
from app.services.idempotency_service import IdempotencyService
from app.services.user_service import NewUser, UserService

CLI_ACTOR = Actor(user_id=None, username="cli")


def _default_session_factory() -> sessionmaker[Session]:
    return build_session_factory(build_engine(get_settings().database_url.get_secret_value()))


def _read_password(env_name: str | None) -> str:
    if env_name:
        password = os.environ.get(env_name)
        if not password:
            raise SystemExit(f"environment variable {env_name} is empty or not set")
        return password
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("passwords do not match")
    return password


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="create a user (audited as 'cli')")
    create.add_argument("--username", required=True)
    create.add_argument("--full-name", required=True)
    create.add_argument("--role", required=True, choices=[role.value for role in Role])
    create.add_argument("--work-center-id", type=int)
    create.add_argument("--password-env", help="read the password from this env variable")
    commands.add_parser("purge-idempotency-keys", help="delete idempotency keys past their TTL")
    args = parser.parse_args(argv)

    factory = session_factory or _default_session_factory()
    if args.command == "purge-idempotency-keys":
        ttl = timedelta(hours=get_settings().idempotency_ttl_hours)
        with factory() as session:
            deleted = IdempotencyService(session, SystemClock(), ttl).purge_expired()
        print(f"deleted {deleted} expired idempotency keys")
        return 0

    with factory() as session:
        try:
            user = UserService(session, PasswordHasher()).create_user(
                NewUser(
                    username=args.username,
                    password=_read_password(args.password_env),
                    full_name=args.full_name,
                    role=Role(args.role),
                    work_center_id=args.work_center_id,
                ),
                CLI_ACTOR,
                RequestContext(),
            )
        except DomainError as exc:
            print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
            return 1
    print(f"created user {user.username} (id={user.id}, role={user.role.value})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
