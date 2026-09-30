from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.bom import VersionStatus
from app.models.master_data import Product
from app.models.routing import Routing, RoutingStep
from app.models.work_center import WorkCenter


class RoutingRepository:
    """Queries and row locks for routing versions; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, routing_id: int) -> Routing | None:
        return self._session.get(Routing, routing_id, populate_existing=True)

    def get_for_update(self, routing_id: int) -> Routing | None:
        return self._session.get(Routing, routing_id, with_for_update=True, populate_existing=True)

    def list_for_product(self, product_id: int) -> Sequence[Routing]:
        return self._session.scalars(
            select(Routing).where(Routing.product_id == product_id).order_by(Routing.version)
        ).all()

    def active_for_product(self, product_id: int) -> Routing | None:
        return self._session.scalars(
            select(Routing).where(
                Routing.product_id == product_id, Routing.status == VersionStatus.ACTIVE.value
            )
        ).one_or_none()

    def next_version(self, product_id: int) -> int:
        """Call with the product row locked, so two drafts cannot take the same number."""
        current = self._session.scalar(
            select(func.max(Routing.version)).where(Routing.product_id == product_id)
        )
        return (current or 0) + 1

    def add(self, routing: Routing) -> Routing:
        self._session.add(routing)
        self._session.flush()
        return routing

    def replace_steps(self, routing: Routing, steps: list[RoutingStep]) -> None:
        routing.steps.clear()
        self._session.flush()  # delete old rows first to keep the unique sequence key
        routing.steps.extend(steps)
        self._session.flush()

    def work_centers_by_id(self, ids: Sequence[int]) -> dict[int, WorkCenter]:
        if not ids:
            return {}
        rows = self._session.scalars(select(WorkCenter).where(WorkCenter.id.in_(ids)))
        return {work_center.id: work_center for work_center in rows}

    def lock_work_centers(self, ids: Sequence[int]) -> list[WorkCenter]:
        """Lock in id order so activation and work center deactivation are serialized."""
        if not ids:
            return []
        return list(
            self._session.scalars(
                select(WorkCenter)
                .where(WorkCenter.id.in_(ids))
                .order_by(WorkCenter.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def work_center_in_active_routing(self, work_center_id: int) -> list[tuple[str, int]]:
        """(product_code, version) of every ACTIVE routing using the work center (C-07)."""
        rows = self._session.execute(
            select(Product.product_code, Routing.version)
            .join(RoutingStep, RoutingStep.routing_id == Routing.id)
            .join(Product, Product.id == Routing.product_id)
            .where(
                RoutingStep.work_center_id == work_center_id,
                Routing.status == VersionStatus.ACTIVE.value,
            )
            .distinct()
            .order_by(Product.product_code)
        ).all()
        return [(code, version) for code, version in rows]
