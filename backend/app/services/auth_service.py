"""Login, lockout and token authentication (BR-AUTH-01, 04, 05; C-01, C-06)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.permissions import Permission, Role, permissions_for
from app.core.security import InvalidTokenError, IssuedToken, PasswordHasher, TokenService
from app.db.transaction import transaction
from app.domain import login_policy
from app.domain.audit import AuditAction, AuditEntity
from app.domain.errors import AuthenticationError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext

# One message for every failure: wrong password, unknown user, disabled or locked account.
INVALID_CREDENTIALS_MESSAGE = "Invalid username or password."
INVALID_TOKEN_MESSAGE = "Invalid or expired access token."  # noqa: S105  (error text)


class LoginOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    UNKNOWN_USER = "UNKNOWN_USER"
    INACTIVE = "INACTIVE"
    LOCKED = "LOCKED"
    BAD_PASSWORD = "BAD_PASSWORD"  # noqa: S105  (outcome label, not a password)


@dataclass(frozen=True)
class AuthenticatedUser:
    """The caller as loaded from the DB on this request (C-01: role never from the token)."""

    id: int
    username: str
    full_name: str
    role: Role
    work_center_id: int | None

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.role)

    @property
    def actor(self) -> Actor:
        return Actor(user_id=self.id, username=self.username)


class AuthService:
    def __init__(
        self,
        session: Session,
        clock: Clock,
        tokens: TokenService,
        passwords: PasswordHasher,
    ) -> None:
        self._session = session
        self._clock = clock
        self._tokens = tokens
        self._passwords = passwords
        self._users = UserRepository(session)
        self._audit = AuditService(session)

    def login(self, username: str, password: str, context: RequestContext) -> IssuedToken:
        now = self._clock.now()
        with transaction(self._session):
            user = self._users.get_by_username_for_update(username)
            outcome = self._evaluate_attempt(user, password, now)
            self._audit_attempt(user, username, outcome, context)
        # Committed first: failure counters and the audit row persist even though we reject.
        if user is None or outcome is not LoginOutcome.SUCCESS:
            raise AuthenticationError("INVALID_CREDENTIALS", INVALID_CREDENTIALS_MESSAGE)
        return self._tokens.issue(user.id, now)

    def authenticate(self, token: str) -> AuthenticatedUser:
        """Resolve a bearer token to a currently active user (BR-AUTH-01, BR-AUTH-04)."""
        try:
            user_id = self._tokens.verify(token, self._clock.now())
        except InvalidTokenError as exc:
            raise AuthenticationError("INVALID_TOKEN", INVALID_TOKEN_MESSAGE) from exc
        with transaction(self._session):
            user = self._users.get(user_id)
            if user is None or not user.active:
                raise AuthenticationError("INVALID_TOKEN", INVALID_TOKEN_MESSAGE)
            return AuthenticatedUser(
                id=user.id,
                username=user.username,
                full_name=user.full_name,
                role=user.role,
                work_center_id=user.work_center_id,
            )

    def _evaluate_attempt(self, user: User | None, password: str, now: datetime) -> LoginOutcome:
        if user is None:
            self._passwords.burn_verification_time(password)
            return LoginOutcome.UNKNOWN_USER
        # Verify before any other check so every path costs one hash verification.
        password_ok = self._passwords.verify(password, user.password_hash)
        if not user.active:
            return LoginOutcome.INACTIVE

        state = login_policy.LoginAttemptState(
            failed_count=user.failed_login_count,
            first_failed_at=user.first_failed_login_at,
            locked_until=user.locked_until,
        )
        if login_policy.is_locked(state, now):
            return LoginOutcome.LOCKED
        if password_ok:
            self._apply_state(user, login_policy.register_success())
            return LoginOutcome.SUCCESS
        self._apply_state(user, login_policy.register_failure(state, now))
        return LoginOutcome.BAD_PASSWORD

    @staticmethod
    def _apply_state(user: User, state: login_policy.LoginAttemptState) -> None:
        user.failed_login_count = state.failed_count
        user.first_failed_login_at = state.first_failed_at
        user.locked_until = state.locked_until

    def _audit_attempt(
        self,
        user: User | None,
        attempted_username: str,
        outcome: LoginOutcome,
        context: RequestContext,
    ) -> None:
        succeeded = outcome is LoginOutcome.SUCCESS
        self._audit.record(
            action=AuditAction.LOGIN_SUCCESS if succeeded else AuditAction.LOGIN_FAILED,
            entity_type=AuditEntity.USER,
            entity_id=user.id if user else None,
            actor=Actor(
                user_id=user.id if user else None,
                username=user.username if user else attempted_username,
            ),
            context=context,
            new_value=None
            if succeeded
            else {
                "outcome": outcome,
                "failed_login_count": user.failed_login_count if user else None,
                "locked_until": user.locked_until if user else None,
            },
        )
