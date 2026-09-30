"""Business errors with a fixed ``code`` (B14).

The domain layer only states the *category* of an error; ``app.api.errors`` is the one
place that maps categories to HTTP status codes and the error body of B13.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import ClassVar

# Quantities go into details as strings, never floats (B13).
ErrorDetail = Mapping[str, str | int | None]


class ErrorCategory(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION = "VALIDATION"
    CONCURRENCY = "CONCURRENCY"


class DomainError(Exception):
    category: ClassVar[ErrorCategory] = ErrorCategory.CONFLICT

    def __init__(self, code: str, message: str, details: Sequence[ErrorDetail] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = [dict(detail) for detail in details]


class AuthenticationError(DomainError):
    category = ErrorCategory.UNAUTHENTICATED


class PermissionDeniedError(DomainError):
    category = ErrorCategory.FORBIDDEN


class NotFoundError(DomainError):
    category = ErrorCategory.NOT_FOUND


class ConflictError(DomainError):
    category = ErrorCategory.CONFLICT


class BusinessValidationError(DomainError):
    category = ErrorCategory.VALIDATION


class ConcurrencyConflictError(DomainError):
    category = ErrorCategory.CONCURRENCY
