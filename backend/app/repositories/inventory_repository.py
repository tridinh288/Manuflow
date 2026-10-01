from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
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

    def read_balances(self, material_ids: Sequence[int]) -> dict[int, Inventory]:
        """Plain read, no lock: for what-if answers that never decide or write anything."""
        if not material_ids:
            return {}
        rows = self._session.scalars(
            select(Inventory)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(
                Inventory.material_id.in_(material_ids),
                Warehouse.code == DEFAULT_WAREHOUSE_CODE,
            )
        ).all()
        return {row.material_id: row for row in rows}

    def lock_balances(self, material_ids: Sequence[int]) -> dict[int, Inventory]:
        """B12: lock balance rows in ascending material_id order before reading them, so
        two orders sharing materials always queue in the same order (no deadlock)."""
        if not material_ids:
            return {}
        rows = self._session.scalars(
            select(Inventory)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(
                Inventory.material_id.in_(material_ids),
                Warehouse.code == DEFAULT_WAREHOUSE_CODE,
            )
            .order_by(Inventory.material_id)
            .with_for_update(of=Inventory)
            .execution_options(populate_existing=True)
        ).all()
        return {row.material_id: row for row in rows}

    def materials_by_id(self, material_ids: Sequence[int]) -> dict[int, Material]:
        if not material_ids:
            return {}
        rows = self._session.scalars(select(Material).where(Material.id.in_(material_ids)))
        return {material.id: material for material in rows}

    def add_transaction(self, line: InventoryTransaction) -> InventoryTransaction:
        self._session.add(line)
        self._session.flush()
        self._session.refresh(line, ["created_at"])  # set by the database
        return line

    # --- Reads ---------------------------------------------------------------------------

    def list_balances(
        self, limit: int, offset: int, low_stock: bool
    ) -> tuple[Sequence[tuple[Inventory, Material]], int]:
        """D-25: low stock means available (on hand - reserved) below minimum stock."""
        conditions = [Warehouse.code == DEFAULT_WAREHOUSE_CODE]
        if low_stock:
            available = Inventory.on_hand_quantity - Inventory.reserved_quantity
            conditions.append(available < Material.minimum_stock)
        base = (
            select(Inventory, Material)
            .join(Material, Material.id == Inventory.material_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(*conditions)
        )
        total = self._session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self._session.execute(
            base.order_by(Material.material_code).limit(limit).offset(offset)
        ).all()
        return [(inventory, material) for inventory, material in rows], total

    def list_transactions(
        self, filters: "TransactionFilter", limit: int, offset: int
    ) -> tuple[Sequence[tuple[InventoryTransaction, Material]], int]:
        conditions = []
        if filters.material_id is not None:
            conditions.append(InventoryTransaction.material_id == filters.material_id)
        if filters.production_order_id is not None:
            conditions.append(
                InventoryTransaction.production_order_id == filters.production_order_id
            )
        if filters.type is not None:
            conditions.append(InventoryTransaction.type == filters.type)
        if filters.created_from is not None:
            conditions.append(InventoryTransaction.created_at >= filters.created_from)
        if filters.created_to is not None:
            conditions.append(InventoryTransaction.created_at < filters.created_to)
        base = (
            select(InventoryTransaction, Material)
            .join(Material, Material.id == InventoryTransaction.material_id)
            .where(*conditions)
        )
        total = self._session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self._session.execute(
            base.order_by(InventoryTransaction.id.desc()).limit(limit).offset(offset)
        ).all()
        return [(line, material) for line, material in rows], total

    def ledger_totals(self) -> Sequence["LedgerTotals"]:
        """BR-INV-04: per balance row, the balance next to the sums of its ledger deltas."""
        sums = (
            select(
                InventoryTransaction.material_id,
                InventoryTransaction.warehouse_id,
                func.sum(InventoryTransaction.on_hand_delta).label("on_hand_sum"),
                func.sum(InventoryTransaction.reserved_delta).label("reserved_sum"),
            )
            .group_by(InventoryTransaction.material_id, InventoryTransaction.warehouse_id)
            .subquery()
        )
        rows = self._session.execute(
            select(
                Material.id,
                Material.material_code,
                Material.decimal_places,
                Inventory.on_hand_quantity,
                Inventory.reserved_quantity,
                func.coalesce(sums.c.on_hand_sum, 0),
                func.coalesce(sums.c.reserved_sum, 0),
            )
            .join(Material, Material.id == Inventory.material_id)
            .outerjoin(
                sums,
                (sums.c.material_id == Inventory.material_id)
                & (sums.c.warehouse_id == Inventory.warehouse_id),
            )
            .order_by(Material.material_code)
        ).all()
        return [LedgerTotals(*row) for row in rows]


@dataclass(frozen=True)
class TransactionFilter:
    material_id: int | None = None
    production_order_id: int | None = None
    type: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


@dataclass(frozen=True)
class LedgerTotals:
    material_id: int
    material_code: str
    decimal_places: int
    on_hand: Decimal
    reserved: Decimal
    on_hand_ledger: Decimal
    reserved_ledger: Decimal
