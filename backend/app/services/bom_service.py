"""Versioned BOMs (BR-BOM-01..04, D-02, D-03, BR-MD-04, BR-AUD-01).

Lock order (B12): product row -> BOM header -> material rows (material_id ascending).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import transaction
from app.domain.audit import AuditAction, AuditEntity
from app.domain.bom import BomLine, VersionStatus, ensure_editable, validate_lines
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.explode import (
    ExplosionLine,
    MaterialRequirement,
    explode,
    validate_order_quantity,
)
from app.models.bom import BomHeader, BomItem
from app.models.master_data import Material, Product
from app.repositories.bom_repository import BomRepository
from app.repositories.master_data_repository import ProductRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext


def _items_payload(header: BomHeader) -> list[dict[str, Any]]:
    return [
        {"material_id": i.material_id, "qty_per_unit": i.qty_per_unit, "scrap_rate": i.scrap_rate}
        for i in header.items
    ]


@dataclass(frozen=True)
class BomView:
    """A BOM version plus the materials its lines reference (for codes and units)."""

    header: BomHeader
    materials: dict[int, Material] = field(default_factory=dict)


class BomService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._boms = BomRepository(session)
        self._products = ProductRepository(session)
        self._audit = AuditService(session)

    # --- Reads ---------------------------------------------------------------------------

    def list_versions(self, product_id: int) -> list[BomView]:
        with transaction(self._session):
            if self._products.get(product_id) is None:
                raise _product_not_found()
            headers: Sequence[BomHeader] = self._boms.list_for_product(product_id)
            material_ids = sorted({i.material_id for h in headers for i in h.items})
            materials = self._boms.materials_by_id(material_ids)
            return [BomView(header, materials) for header in headers]

    def calculate_material_requirements(
        self, product_id: int, quantity: int, bom_header_id: int | None = None
    ) -> list[MaterialRequirement]:
        """BR-BOM-05: explode the product's ACTIVE BOM (or the given version) for
        ``quantity`` units. Read-only: nothing is written or locked."""
        validate_order_quantity(quantity)
        with transaction(self._session):
            product = self._products.get(product_id)
            if product is None:
                raise _product_not_found()
            if not product.active:
                raise ConflictError("PRODUCT_INACTIVE", "The product is inactive.")
            header = self._explosion_header(product.id, bom_header_id)
            materials = self._boms.materials_by_id([item.material_id for item in header.items])
            inactive = sorted(
                materials[item.material_id].material_code
                for item in header.items
                if not materials[item.material_id].active
            )
            if inactive:
                raise _materials_inactive(inactive)
            return explode(
                (
                    ExplosionLine(
                        material_id=item.material_id,
                        material_code=materials[item.material_id].material_code,
                        unit=materials[item.material_id].unit,
                        decimal_places=materials[item.material_id].decimal_places,
                        qty_per_unit=item.qty_per_unit,
                        scrap_rate=item.scrap_rate,
                    )
                    for item in header.items
                ),
                quantity,
            )

    def _explosion_header(self, product_id: int, bom_header_id: int | None) -> BomHeader:
        if bom_header_id is None:
            header = self._boms.active_for_product(product_id)
            if header is None:
                raise ConflictError("NO_ACTIVE_BOM", "The product has no ACTIVE BOM.")
            return header
        header = self._boms.get(bom_header_id)
        if header is None or header.product_id != product_id:
            raise _bom_not_found()
        return header

    # --- Commands ------------------------------------------------------------------------

    def create_draft(self, product_id: int, actor: Actor, context: RequestContext) -> BomView:
        with transaction(self._session):
            product = self._lock_usable_product(product_id)
            header = self._boms.add(
                BomHeader(
                    product_id=product.id,
                    version=self._boms.next_version(product.id),
                    status=VersionStatus.DRAFT.value,
                    created_by=actor.user_id,
                )
            )
            self._record(
                AuditAction.BOM_CREATED, header, actor, context, {"version": header.version}
            )
        return BomView(header)

    def replace_items(
        self, bom_id: int, lines: list[BomLine], actor: Actor, context: RequestContext
    ) -> BomView:
        validate_lines(lines)
        with transaction(self._session):
            header = self._get_for_update(bom_id)
            ensure_editable(VersionStatus(header.status))
            materials = self._boms.materials_by_id(sorted({line.material_id for line in lines}))
            _ensure_usable_materials(lines, materials)

            old_items = _items_payload(header)
            self._boms.replace_items(
                header,
                [
                    BomItem(
                        material_id=line.material_id,
                        qty_per_unit=line.qty_per_unit,
                        scrap_rate=line.scrap_rate,
                    )
                    for line in sorted(lines, key=lambda line: line.material_id)
                ],
            )
            self._audit.record(
                action=AuditAction.BOM_ITEMS_REPLACED,
                entity_type=AuditEntity.BOM,
                entity_id=header.id,
                actor=actor,
                context=context,
                old_value={"items": old_items},
                new_value={"items": _items_payload(header)},
            )
        return BomView(header, materials)

    def activate(self, bom_id: int, actor: Actor, context: RequestContext) -> BomView:
        """BR-BOM-03/04: DRAFT with lines and active materials becomes the only ACTIVE
        version of its product; the previous ACTIVE one is RETIRED in the same transaction."""
        with transaction(self._session):
            peek = self._boms.get(bom_id)
            if peek is None:
                raise _bom_not_found()
            # Lock order: product -> header -> materials.
            self._lock_usable_product(peek.product_id)
            header = self._get_for_update(bom_id)
            ensure_editable(VersionStatus(header.status))
            if not header.items:
                raise ConflictError("BOM_EMPTY", "A BOM version needs at least one line.")
            materials = self._boms.lock_materials([i.material_id for i in header.items])
            inactive = [m.material_code for m in materials if not m.active]
            if inactive:
                raise _materials_inactive(inactive)

            previous = self._boms.active_for_product(header.product_id)
            if previous is not None:
                previous.status = VersionStatus.RETIRED.value
                self._session.flush()  # free the ACTIVE slot before taking it
            header.status = VersionStatus.ACTIVE.value
            header.activated_at = self._clock.now()
            self._session.flush()
            self._record(
                AuditAction.BOM_ACTIVATED,
                header,
                actor,
                context,
                {
                    "version": header.version,
                    "retired_version": previous.version if previous else None,
                },
            )
        return BomView(header, {material.id: material for material in materials})

    # --- Helpers -------------------------------------------------------------------------

    def _lock_usable_product(self, product_id: int) -> Product:
        """BR-BOM-04: the product row lock serializes version numbering and activation."""
        product = self._products.get_for_update(product_id)
        if product is None:
            raise _product_not_found()
        if not product.active:  # BR-MD-04
            raise ConflictError("PRODUCT_INACTIVE", "The product is inactive.")
        return product

    def _get_for_update(self, bom_id: int) -> BomHeader:
        header = self._boms.get_for_update(bom_id)
        if header is None:
            raise _bom_not_found()
        return header

    def _record(
        self,
        action: AuditAction,
        header: BomHeader,
        actor: Actor,
        context: RequestContext,
        new_value: dict[str, Any],
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=AuditEntity.BOM,
            entity_id=header.id,
            actor=actor,
            context=context,
            new_value={"product_id": header.product_id, **new_value},
        )


def _ensure_usable_materials(lines: list[BomLine], materials: dict[int, Material]) -> None:
    missing = sorted({line.material_id for line in lines} - set(materials))
    if missing:
        raise BusinessValidationError(
            "MATERIAL_NOT_FOUND",
            "Some materials do not exist.",
            [{"material_id": material_id} for material_id in missing],
        )
    inactive = sorted(m.material_code for m in materials.values() if not m.active)
    if inactive:
        raise _materials_inactive(inactive)


def _materials_inactive(codes: list[str]) -> ConflictError:
    return ConflictError(
        "MATERIAL_INACTIVE",
        "Inactive materials cannot be used in a BOM.",
        [{"material_code": code} for code in codes],
    )


def _product_not_found() -> NotFoundError:
    return NotFoundError("PRODUCT_NOT_FOUND", "Product not found.")


def _bom_not_found() -> NotFoundError:
    return NotFoundError("BOM_NOT_FOUND", "BOM version not found.")
