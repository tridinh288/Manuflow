"""Importing this package registers every model on ``Base.metadata`` (used by Alembic)."""

from app.models.audit_log import AuditLog
from app.models.bom import BomHeader, BomItem
from app.models.idempotency_key import IdempotencyKey
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material, Product
from app.models.routing import Routing, RoutingStep
from app.models.user import User
from app.models.warehouse import Warehouse
from app.models.work_center import WorkCenter

__all__ = [
    "AuditLog",
    "BomHeader",
    "BomItem",
    "IdempotencyKey",
    "Inventory",
    "InventoryTransaction",
    "Material",
    "Product",
    "Routing",
    "RoutingStep",
    "User",
    "Warehouse",
    "WorkCenter",
]
