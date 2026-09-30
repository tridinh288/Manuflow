"""Importing this package registers every model on ``Base.metadata`` (used by Alembic)."""

from app.models.warehouse import Warehouse

__all__ = ["Warehouse"]
