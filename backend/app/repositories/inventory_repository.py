from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse


class InventoryRepository:
    """Balance rows, the ledger and their locks; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_material_for_share(self, material_id: int) -> Material | None:
        """Shared lock: a concurrent deactivation (FOR UPDATE) waits for us, and we see
        its committed result instead of a stale snapshot (C-15)."""
        return self._session.scalars(
            select(Material)
            .where(Material.id == material_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).one_or_none()

    def lock_balance(self, material_id: int) -> Inventory:
        """Row lock on the balance before reading it to decide anything (B12)."""
        return self._session.scalars(
            select(Inventory)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(Inventory.material_id == material_id, Warehouse.code == DEFAULT_WAREHOUSE_CODE)
            .with_for_update(of=Inventory)
            .execution_options(populate_existing=True)
        ).one()

    def add_transaction(self, line: InventoryTransaction) -> InventoryTransaction:
        self._session.add(line)
        self._session.flush()
        self._session.refresh(line, ["created_at"])  # set by the database
        return line
