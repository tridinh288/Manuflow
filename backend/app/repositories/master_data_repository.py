"""Queries for coded master data (products, materials, work centers). Never commits."""

from collections.abc import Sequence
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.permissions import Role
from app.models.master_data import Inventory, Material, Product
from app.models.user import User
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse
from app.models.work_center import WorkCenter


class _CodedRepository[M: (Product, Material, WorkCenter)]:
    model: ClassVar[type[Product | Material | WorkCenter]]
    code_column: ClassVar[InstrumentedAttribute[str]]

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, row_id: int) -> M | None:
        row = self._session.get(self.model, row_id, populate_existing=True)
        return row  # type: ignore[return-value]

    def get_for_update(self, row_id: int) -> M | None:
        row = self._session.get(self.model, row_id, with_for_update=True, populate_existing=True)
        return row  # type: ignore[return-value]

    def by_code(self, code: str) -> M | None:
        row = self._session.scalars(
            select(self.model).where(type(self).code_column == code)
        ).first()
        return row  # type: ignore[return-value]

    def code_exists(self, code: str) -> bool:
        count = self._session.scalar(select(func.count()).where(type(self).code_column == code))
        return (count or 0) > 0

    def list_page(self, limit: int, offset: int, active: bool | None) -> tuple[Sequence[M], int]:
        condition = [self.model.active.is_(active)] if active is not None else []
        total = self._session.scalar(select(func.count()).select_from(self.model).where(*condition))
        rows = self._session.scalars(
            select(self.model)
            .where(*condition)
            .order_by(type(self).code_column)
            .limit(limit)
            .offset(offset)
        ).all()
        return rows, total or 0  # type: ignore[return-value]

    def add(self, row: M) -> M:
        self._session.add(row)
        self._session.flush()
        return row


class ProductRepository(_CodedRepository[Product]):
    model = Product
    code_column = Product.product_code


class MaterialRepository(_CodedRepository[Material]):
    model = Material
    code_column = Material.material_code

    def add_zero_balance(self, material: Material) -> Inventory:
        """BR-INV-01: the balance row is created with the material, in its transaction."""
        warehouse_id = self._session.scalars(
            select(Warehouse.id).where(Warehouse.code == DEFAULT_WAREHOUSE_CODE)
        ).one()
        balance = Inventory(warehouse_id=warehouse_id, material_id=material.id)
        self._session.add(balance)
        self._session.flush()
        return balance


class WorkCenterRepository(_CodedRepository[WorkCenter]):
    model = WorkCenter
    code_column = WorkCenter.code

    def count_active_workers(self, work_center_id: int) -> int:
        count = self._session.scalar(
            select(func.count()).where(
                User.work_center_id == work_center_id,
                User.role == Role.WORKER,
                User.active.is_(True),
            )
        )
        return count or 0
