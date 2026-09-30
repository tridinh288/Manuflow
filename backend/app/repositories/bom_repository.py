from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.bom import VersionStatus
from app.models.bom import BomHeader, BomItem
from app.models.master_data import Material, Product


class BomRepository:
    """Queries and row locks for BOM versions; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, bom_id: int) -> BomHeader | None:
        return self._session.get(BomHeader, bom_id, populate_existing=True)

    def get_for_update(self, bom_id: int) -> BomHeader | None:
        return self._session.get(BomHeader, bom_id, with_for_update=True, populate_existing=True)

    def list_for_product(self, product_id: int) -> Sequence[BomHeader]:
        return self._session.scalars(
            select(BomHeader).where(BomHeader.product_id == product_id).order_by(BomHeader.version)
        ).all()

    def active_for_product(self, product_id: int) -> BomHeader | None:
        return self._session.scalars(
            select(BomHeader).where(
                BomHeader.product_id == product_id,
                BomHeader.status == VersionStatus.ACTIVE.value,
            )
        ).one_or_none()

    def next_version(self, product_id: int) -> int:
        """Call with the product row locked, so two drafts cannot take the same number."""
        current = self._session.scalar(
            select(func.max(BomHeader.version)).where(BomHeader.product_id == product_id)
        )
        return (current or 0) + 1

    def add(self, header: BomHeader) -> BomHeader:
        self._session.add(header)
        self._session.flush()
        return header

    def replace_items(self, header: BomHeader, items: list[BomItem]) -> None:
        header.items.clear()
        self._session.flush()  # delete old rows before inserting, keeping the unique key
        header.items.extend(items)
        self._session.flush()

    def lock_materials(self, material_ids: Sequence[int]) -> list[Material]:
        """Lock materials in ``material_id`` order (B12) so activation and deactivation
        of the same material are serialized."""
        if not material_ids:
            return []
        return list(
            self._session.scalars(
                select(Material)
                .where(Material.id.in_(material_ids))
                .order_by(Material.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def materials_by_id(self, material_ids: Sequence[int]) -> dict[int, Material]:
        if not material_ids:
            return {}
        rows = self._session.scalars(select(Material).where(Material.id.in_(material_ids)))
        return {material.id: material for material in rows}

    def material_in_active_bom(self, material_id: int) -> list[tuple[str, int]]:
        """(product_code, version) of every ACTIVE BOM using the material (D-19)."""
        rows = self._session.execute(
            select(Product.product_code, BomHeader.version)
            .join(BomItem, BomItem.bom_header_id == BomHeader.id)
            .join(Product, Product.id == BomHeader.product_id)
            .where(
                BomItem.material_id == material_id,
                BomHeader.status == VersionStatus.ACTIVE.value,
            )
            .order_by(Product.product_code)
        ).all()
        return [(code, version) for code, version in rows]
