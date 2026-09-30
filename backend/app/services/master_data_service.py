"""Products, materials and work centers (BR-MD-01..04, D-19, C-07, C-13, C-14).

Codes, a material's unit and its decimal places never change after creation. DELETE
only deactivates. Every change is audited in its own transaction (BR-AUD-01).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.transaction import transaction
from app.domain.audit import AuditAction, AuditEntity, changed_fields
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.quantities import ensure_scale
from app.models.master_data import Material, MaterialUnit, Product
from app.models.work_center import WorkCenter
from app.repositories.bom_repository import BomRepository
from app.repositories.master_data_repository import (
    MaterialRepository,
    ProductRepository,
    WorkCenterRepository,
)
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext


@dataclass(frozen=True)
class NewProduct:
    product_code: str
    name: str
    description: str | None = None


@dataclass(frozen=True)
class ProductChanges:
    name: str
    description: str | None


@dataclass(frozen=True)
class NewMaterial:
    material_code: str
    name: str
    unit: MaterialUnit
    decimal_places: int
    minimum_stock: Decimal = Decimal(0)


@dataclass(frozen=True)
class MaterialChanges:
    name: str
    minimum_stock: Decimal


@dataclass(frozen=True)
class NewWorkCenter:
    code: str
    name: str


@dataclass(frozen=True)
class WorkCenterChanges:
    name: str


def _snapshot(row: object, fields: Sequence[str]) -> dict[str, Any]:
    return {name: getattr(row, name) for name in fields}


def _validate_material(unit: MaterialUnit, decimal_places: int, minimum_stock: Decimal) -> None:
    """BR-MD-02: pcs are whole units; minimum stock >= 0 within the material's scale."""
    if unit is MaterialUnit.PCS and decimal_places != 0:
        raise BusinessValidationError(
            "INVALID_DECIMAL_PLACES", "Materials counted in pcs must have 0 decimal places."
        )
    if minimum_stock < 0:
        raise BusinessValidationError("INVALID_QUANTITY", "minimum_stock cannot be negative.")
    ensure_scale(minimum_stock, decimal_places, field="minimum_stock")


class _MasterDataService:
    entity: AuditEntity
    audited_fields: tuple[str, ...]
    not_found_code: str
    code_taken_code: str

    def __init__(self, session: Session) -> None:
        self._session = session
        self._audit = AuditService(session)

    def _not_found(self) -> NotFoundError:
        return NotFoundError(self.not_found_code, f"{self.entity.value} not found.")

    def _code_taken(self) -> ConflictError:
        return ConflictError(self.code_taken_code, "Code is already in use.")

    def _record(
        self,
        action: AuditAction,
        row_id: int,
        actor: Actor,
        context: RequestContext,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=self.entity,
            entity_id=row_id,
            actor=actor,
            context=context,
            old_value=old,
            new_value=new,
        )

    def _create[M: (Product, Material, WorkCenter)](
        self,
        repository: ProductRepository | MaterialRepository | WorkCenterRepository,
        code: str,
        row: M,
        actor: Actor,
        context: RequestContext,
    ) -> M:
        try:
            with transaction(self._session):
                if repository.code_exists(code):
                    raise self._code_taken()
                self._session.add(row)
                self._session.flush()
                if isinstance(repository, MaterialRepository) and isinstance(row, Material):
                    repository.add_zero_balance(row)
                self._record(
                    AuditAction.MASTER_CREATED,
                    row.id,
                    actor,
                    context,
                    None,
                    _snapshot(row, self.audited_fields),
                )
        except IntegrityError as exc:
            # A concurrent request created the same code after our check.
            raise self._code_taken() from exc
        return row


class ProductService(_MasterDataService):
    entity = AuditEntity.PRODUCT
    audited_fields = ("product_code", "name", "description", "active")
    not_found_code = "PRODUCT_NOT_FOUND"
    code_taken_code = "PRODUCT_CODE_TAKEN"

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self._products = ProductRepository(session)

    def list(self, limit: int, offset: int, active: bool | None) -> tuple[Sequence[Product], int]:
        with transaction(self._session):
            return self._products.list_page(limit, offset, active)

    def get(self, product_id: int) -> Product:
        with transaction(self._session):
            product = self._products.get(product_id)
            if product is None:
                raise self._not_found()
            return product

    def create(self, data: NewProduct, actor: Actor, context: RequestContext) -> Product:
        product = Product(
            product_code=data.product_code,
            name=data.name,
            description=data.description,
            unit="pcs",  # BR-MD-03
            active=True,
        )
        return self._create(self._products, data.product_code, product, actor, context)

    def update(
        self, product_id: int, changes: ProductChanges, actor: Actor, context: RequestContext
    ) -> Product:
        with transaction(self._session):
            product = self._products.get_for_update(product_id)
            if product is None:
                raise self._not_found()
            before = _snapshot(product, self.audited_fields)
            product.name = changes.name
            product.description = changes.description
            self._session.flush()
            old, new = changed_fields(before, _snapshot(product, self.audited_fields))
            if new:
                self._record(AuditAction.MASTER_UPDATED, product.id, actor, context, old, new)
        return product

    def deactivate(self, product_id: int, actor: Actor, context: RequestContext) -> None:
        """D-19 as refined by C-13: blocked only by open production orders (Phase 5).

        The product's BOM and routing versions stay; an inactive product cannot be
        exploded, planned or ordered (BR-MD-04).
        """
        with transaction(self._session):
            product = self._products.get_for_update(product_id)
            if product is None:
                raise self._not_found()
            if not product.active:
                return
            product.active = False
            self._session.flush()
            self._record(
                AuditAction.MASTER_DEACTIVATED,
                product.id,
                actor,
                context,
                {"active": True},
                {"active": False},
            )


class MaterialService(_MasterDataService):
    entity = AuditEntity.MATERIAL
    audited_fields = ("material_code", "name", "unit", "decimal_places", "minimum_stock", "active")
    not_found_code = "MATERIAL_NOT_FOUND"
    code_taken_code = "MATERIAL_CODE_TAKEN"

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self._materials = MaterialRepository(session)

    def list(self, limit: int, offset: int, active: bool | None) -> tuple[Sequence[Material], int]:
        with transaction(self._session):
            return self._materials.list_page(limit, offset, active)

    def get(self, material_id: int) -> Material:
        with transaction(self._session):
            material = self._materials.get(material_id)
            if material is None:
                raise self._not_found()
            return material

    def create(self, data: NewMaterial, actor: Actor, context: RequestContext) -> Material:
        _validate_material(data.unit, data.decimal_places, data.minimum_stock)
        material = Material(
            material_code=data.material_code,
            name=data.name,
            unit=data.unit.value,
            decimal_places=data.decimal_places,
            minimum_stock=data.minimum_stock,
            active=True,
        )
        return self._create(self._materials, data.material_code, material, actor, context)

    def update(
        self, material_id: int, changes: MaterialChanges, actor: Actor, context: RequestContext
    ) -> Material:
        """C-14: only name and minimum stock change; code, unit and decimal places never."""
        with transaction(self._session):
            material = self._materials.get_for_update(material_id)
            if material is None:
                raise self._not_found()
            _validate_material(
                MaterialUnit(material.unit), material.decimal_places, changes.minimum_stock
            )
            before = _snapshot(material, self.audited_fields)
            material.name = changes.name
            material.minimum_stock = changes.minimum_stock
            self._session.flush()
            old, new = changed_fields(before, _snapshot(material, self.audited_fields))
            if new:
                self._record(AuditAction.MASTER_UPDATED, material.id, actor, context, old, new)
        return material

    def deactivate(self, material_id: int, actor: Actor, context: RequestContext) -> None:
        """D-19: refused while an ACTIVE BOM uses the material.

        The material row lock is the same one BOM activation takes, so a material cannot
        be deactivated while a BOM using it is being activated, or the reverse.
        """
        with transaction(self._session):
            material = self._materials.get_for_update(material_id)
            if material is None:
                raise self._not_found()
            if not material.active:
                return
            used_by = BomRepository(self._session).material_in_active_bom(material.id)
            if used_by:
                raise ConflictError(
                    "MATERIAL_IN_USE",
                    "The material is used by an ACTIVE BOM.",
                    [{"product_code": code, "bom_version": version} for code, version in used_by],
                )
            material.active = False
            self._session.flush()
            self._record(
                AuditAction.MASTER_DEACTIVATED,
                material.id,
                actor,
                context,
                {"active": True},
                {"active": False},
            )


class WorkCenterService(_MasterDataService):
    entity = AuditEntity.WORK_CENTER
    audited_fields = ("code", "name", "active")
    not_found_code = "WORK_CENTER_NOT_FOUND"
    code_taken_code = "WORK_CENTER_CODE_TAKEN"

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self._work_centers = WorkCenterRepository(session)

    def list(
        self, limit: int, offset: int, active: bool | None
    ) -> tuple[Sequence[WorkCenter], int]:
        with transaction(self._session):
            return self._work_centers.list_page(limit, offset, active)

    def get(self, work_center_id: int) -> WorkCenter:
        with transaction(self._session):
            work_center = self._work_centers.get(work_center_id)
            if work_center is None:
                raise self._not_found()
            return work_center

    def create(self, data: NewWorkCenter, actor: Actor, context: RequestContext) -> WorkCenter:
        work_center = WorkCenter(code=data.code, name=data.name, active=True)
        return self._create(self._work_centers, data.code, work_center, actor, context)

    def update(
        self,
        work_center_id: int,
        changes: WorkCenterChanges,
        actor: Actor,
        context: RequestContext,
    ) -> WorkCenter:
        with transaction(self._session):
            work_center = self._work_centers.get_for_update(work_center_id)
            if work_center is None:
                raise self._not_found()
            before = _snapshot(work_center, self.audited_fields)
            work_center.name = changes.name
            self._session.flush()
            old, new = changed_fields(before, _snapshot(work_center, self.audited_fields))
            if new:
                self._record(AuditAction.MASTER_UPDATED, work_center.id, actor, context, old, new)
        return work_center

    def deactivate(self, work_center_id: int, actor: Actor, context: RequestContext) -> None:
        """D-19 + C-07: refused while active WORKERs are assigned to it (and, once
        routings exist, while an ACTIVE routing uses it)."""
        with transaction(self._session):
            work_center = self._work_centers.get_for_update(work_center_id)
            if work_center is None:
                raise self._not_found()
            if not work_center.active:
                return
            workers = self._work_centers.count_active_workers(work_center.id)
            if workers:
                raise ConflictError(
                    "WORK_CENTER_IN_USE",
                    "Active workers are still assigned to this work center.",
                    [{"reason": "ACTIVE_WORKERS", "count": workers}],
                )
            work_center.active = False
            self._session.flush()
            self._record(
                AuditAction.MASTER_DEACTIVATED,
                work_center.id,
                actor,
                context,
                {"active": True},
                {"active": False},
            )
