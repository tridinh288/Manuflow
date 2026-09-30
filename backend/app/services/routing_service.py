"""Versioned routings (BR-RT-01..03, D-03, C-07, BR-MD-04, BR-AUD-01).

Lock order (B12): product row -> routing -> work center rows (id ascending).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import transaction
from app.domain.audit import AuditAction, AuditEntity
from app.domain.bom import VersionStatus, ensure_editable
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.routing import (
    OperationType,
    RoutingStepSpec,
    ensure_activatable,
    validate_steps,
)
from app.models.master_data import Product
from app.models.routing import Routing, RoutingStep
from app.models.work_center import WorkCenter
from app.repositories.master_data_repository import ProductRepository
from app.repositories.routing_repository import RoutingRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext


@dataclass(frozen=True)
class RoutingView:
    """A routing version plus the work centers its steps reference (for codes)."""

    routing: Routing
    work_centers: dict[int, WorkCenter] = field(default_factory=dict)


def _specs(routing: Routing) -> list[RoutingStepSpec]:
    return [
        RoutingStepSpec(s.sequence, OperationType(s.operation_type), s.work_center_id)
        for s in routing.steps
    ]


def _steps_payload(routing: Routing) -> list[dict[str, Any]]:
    return [
        {
            "sequence": s.sequence,
            "operation_type": s.operation_type,
            "work_center_id": s.work_center_id,
        }
        for s in routing.steps
    ]


class RoutingService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._routings = RoutingRepository(session)
        self._products = ProductRepository(session)
        self._audit = AuditService(session)

    def list_versions(self, product_id: int) -> list[RoutingView]:
        with transaction(self._session):
            if self._products.get(product_id) is None:
                raise NotFoundError("PRODUCT_NOT_FOUND", "Product not found.")
            routings: Sequence[Routing] = self._routings.list_for_product(product_id)
            ids = sorted({s.work_center_id for r in routings for s in r.steps})
            work_centers = self._routings.work_centers_by_id(ids)
            return [RoutingView(routing, work_centers) for routing in routings]

    def create_draft(self, product_id: int, actor: Actor, context: RequestContext) -> RoutingView:
        with transaction(self._session):
            product = self._lock_usable_product(product_id)
            routing = self._routings.add(
                Routing(
                    product_id=product.id,
                    version=self._routings.next_version(product.id),
                    status=VersionStatus.DRAFT.value,
                    created_by=actor.user_id,
                )
            )
            self._record(
                AuditAction.ROUTING_CREATED, routing, actor, context, {"version": routing.version}
            )
        return RoutingView(routing)

    def replace_steps(
        self,
        routing_id: int,
        steps: list[RoutingStepSpec],
        actor: Actor,
        context: RequestContext,
    ) -> RoutingView:
        validate_steps(steps)
        with transaction(self._session):
            routing = self._get_for_update(routing_id)
            ensure_editable(VersionStatus(routing.status))
            ids = sorted({step.work_center_id for step in steps})
            work_centers = self._routings.work_centers_by_id(ids)
            _ensure_usable_work_centers(ids, work_centers)

            old_steps = _steps_payload(routing)
            self._routings.replace_steps(
                routing,
                [
                    RoutingStep(
                        sequence=step.sequence,
                        operation_type=step.operation_type.value,
                        work_center_id=step.work_center_id,
                    )
                    for step in sorted(steps, key=lambda step: step.sequence)
                ],
            )
            self._audit.record(
                action=AuditAction.ROUTING_STEPS_REPLACED,
                entity_type=AuditEntity.ROUTING,
                entity_id=routing.id,
                actor=actor,
                context=context,
                old_value={"steps": old_steps},
                new_value={"steps": _steps_payload(routing)},
            )
        return RoutingView(routing, work_centers)

    def activate(self, routing_id: int, actor: Actor, context: RequestContext) -> RoutingView:
        """BR-RT-01/03: a DRAFT with steps ending in QC, on active work centers, becomes
        the product's only ACTIVE routing; the previous one is RETIRED atomically."""
        with transaction(self._session):
            peek = self._routings.get(routing_id)
            if peek is None:
                raise _routing_not_found()
            self._lock_usable_product(peek.product_id)
            routing = self._get_for_update(routing_id)
            ensure_editable(VersionStatus(routing.status))
            ensure_activatable(_specs(routing))
            locked = self._routings.lock_work_centers(
                sorted({s.work_center_id for s in routing.steps})
            )
            inactive = [wc.code for wc in locked if not wc.active]
            if inactive:
                raise _work_centers_inactive(inactive)

            previous = self._routings.active_for_product(routing.product_id)
            if previous is not None:
                previous.status = VersionStatus.RETIRED.value
                self._session.flush()  # free the ACTIVE slot before taking it
            routing.status = VersionStatus.ACTIVE.value
            routing.activated_at = self._clock.now()
            self._session.flush()
            self._record(
                AuditAction.ROUTING_ACTIVATED,
                routing,
                actor,
                context,
                {
                    "version": routing.version,
                    "retired_version": previous.version if previous else None,
                },
            )
        return RoutingView(routing, {wc.id: wc for wc in locked})

    def _lock_usable_product(self, product_id: int) -> Product:
        product = self._products.get_for_update(product_id)
        if product is None:
            raise NotFoundError("PRODUCT_NOT_FOUND", "Product not found.")
        if not product.active:  # BR-MD-04
            raise ConflictError("PRODUCT_INACTIVE", "The product is inactive.")
        return product

    def _get_for_update(self, routing_id: int) -> Routing:
        routing = self._routings.get_for_update(routing_id)
        if routing is None:
            raise _routing_not_found()
        return routing

    def _record(
        self,
        action: AuditAction,
        routing: Routing,
        actor: Actor,
        context: RequestContext,
        new_value: dict[str, Any],
    ) -> None:
        self._audit.record(
            action=action,
            entity_type=AuditEntity.ROUTING,
            entity_id=routing.id,
            actor=actor,
            context=context,
            new_value={"product_id": routing.product_id, **new_value},
        )


def _ensure_usable_work_centers(ids: list[int], work_centers: dict[int, WorkCenter]) -> None:
    missing = sorted(set(ids) - set(work_centers))
    if missing:
        raise BusinessValidationError(
            "WORK_CENTER_NOT_FOUND",
            "Some work centers do not exist.",
            [{"work_center_id": work_center_id} for work_center_id in missing],
        )
    inactive = sorted(wc.code for wc in work_centers.values() if not wc.active)
    if inactive:
        raise _work_centers_inactive(inactive)


def _work_centers_inactive(codes: list[str]) -> ConflictError:
    """BR-RT-02: every step needs an active work center."""
    return ConflictError(
        "WORK_CENTER_INACTIVE",
        "Inactive work centers cannot be used in a routing.",
        [{"work_center_code": code} for code in codes],
    )


def _routing_not_found() -> NotFoundError:
    return NotFoundError("ROUTING_NOT_FOUND", "Routing version not found.")
