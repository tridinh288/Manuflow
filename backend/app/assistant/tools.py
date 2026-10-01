"""The assistant's tools (BR-AI-01): read-only, run as the caller (BR-AI-02).

Each tool checks the same permission as the REST endpoint that shows the same data and
calls the same service, so a user gets from the assistant exactly what the API would
give them, and the same 403 / 404 otherwise. Results are the API's own Pydantic response
models (BR-AI-03): no SQL, no credentials, nothing outside the caller's scope. There is
no tool that writes (BR-AI-04).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.transaction import transaction
from app.domain.errors import NotFoundError, PermissionDeniedError
from app.domain.inventory import Balance
from app.domain.reservation import RequiredLine, decide
from app.domain.scope import work_center_scope
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.master_data_repository import ProductRepository
from app.repositories.production_repository import ProductionOrderRepository
from app.schemas.bom import MaterialRequirementResponse
from app.schemas.dashboard import BottleneckResponse, OrderRiskResponse
from app.schemas.inventory import BalanceResponse
from app.schemas.production import MaterialCheckResponse, OperationResponse, OrderResponse
from app.services.auth_service import AuthenticatedUser
from app.services.bom_service import BomService
from app.services.dashboard_service import DashboardService
from app.services.inventory_service import InventoryService
from app.services.production_service import MaterialCheck, ProductionOrderService
from app.services.risk_service import RiskService, risk_thresholds

ProductCode = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{3,32}$")]
OrderNumber = Annotated[str, StringConstraints(pattern=r"^PO-\d{4}-\d{5}$")]
Quantity = Annotated[int, Field(ge=1, le=100_000)]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductQuantityArgs(_Args):
    product_code: ProductCode = Field(description="Product code, e.g. FRAME-A")
    quantity: Quantity = Field(description="Number of finished units")


class OrderArgs(_Args):
    order_number: OrderNumber = Field(description="Production order number, e.g. PO-2026-00007")


class NoArgs(_Args):
    pass


class MaterialRequirements(BaseModel):
    product_code: str
    quantity: int
    items: list[MaterialRequirementResponse]


class MaterialAvailability(BaseModel):
    """A what-if of the reservation algorithm (B6): nothing is locked or written."""

    product_code: str
    quantity: int
    can_reserve_all: bool
    items: list[MaterialCheckResponse]


class OrderStatusResult(BaseModel):
    order: OrderResponse
    workflow_progress: float
    finished_progress: float
    operations: list[OperationResponse]


class OrderRisks(BaseModel):
    orders: list[OrderRiskResponse]


class Bottlenecks(BaseModel):
    work_centers: list[BottleneckResponse]


class LowStock(BaseModel):
    materials: list[BalanceResponse]


@dataclass(frozen=True)
class ToolContext:
    session: Session
    clock: Clock
    settings: Settings
    user: AuthenticatedUser


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    permissions: tuple[Permission, ...]
    run: Callable[[ToolContext, Any], BaseModel]

    def input_schema(self) -> dict[str, Any]:
        return self.args.model_json_schema()

    def call(self, context: ToolContext, raw_args: dict[str, Any]) -> BaseModel:
        """Validate the model's arguments, check the caller's permissions, run."""
        args = self.args.model_validate(raw_args)
        missing = [p for p in self.permissions if p not in context.user.permissions]
        if missing:
            # The same answer the REST API gives (BR-AI-02).
            raise PermissionDeniedError(
                "FORBIDDEN",
                "You do not have permission to perform this action.",
                [{"permission": p.value} for p in missing],
            )
        return self.run(context, args)


def _product_id(context: ToolContext, code: str) -> int:
    with transaction(context.session):
        product = ProductRepository(context.session).by_code(code)
    if product is None:
        raise NotFoundError("PRODUCT_NOT_FOUND", f"No product with code {code}.")
    return product.id


def calculate_material_requirements(context: ToolContext, args: ProductQuantityArgs) -> BaseModel:
    """Same as POST /products/{id}/bom/explode (master:read)."""
    service = BomService(context.session, context.clock)
    items = service.calculate_material_requirements(
        _product_id(context, args.product_code), args.quantity
    )
    return MaterialRequirements(
        product_code=args.product_code,
        quantity=args.quantity,
        items=[MaterialRequirementResponse.of(item) for item in items],
    )


def check_material_availability(context: ToolContext, args: ProductQuantityArgs) -> BaseModel:
    """B6 steps 4-5 on today's stock, without locks or writes (BR-AI-01)."""
    service = BomService(context.session, context.clock)
    needs = service.calculate_material_requirements(
        _product_id(context, args.product_code), args.quantity
    )
    with transaction(context.session):
        rows = InventoryRepository(context.session).read_balances([n.material_id for n in needs])
    balances = {
        material_id: Balance(on_hand=row.on_hand_quantity, reserved=row.reserved_quantity)
        for material_id, row in rows.items()
    }
    decision = decide([RequiredLine(n.material_id, n.required_quantity) for n in needs], balances)
    by_id = {n.material_id: n for n in needs}
    items = [
        MaterialCheckResponse.of(
            MaterialCheck(
                material_id=check.material_id,
                material_code=by_id[check.material_id].material_code,
                unit=by_id[check.material_id].unit,
                decimal_places=by_id[check.material_id].decimal_places,
                required=check.required,
                available=check.available,
                shortage=check.shortage,
            )
        )
        for check in decision.checks
    ]
    return MaterialAvailability(
        product_code=args.product_code,
        quantity=args.quantity,
        can_reserve_all=decision.reservable,
        items=items,
    )


def get_production_order_status(context: ToolContext, args: OrderArgs) -> BaseModel:
    """Same as GET /production-orders/{id} and .../operations (order:read, WORKER scope)."""
    user = context.user
    scope = work_center_scope(user.role, user.work_center_id)
    with transaction(context.session):
        order_id = ProductionOrderRepository(context.session).id_by_number(args.order_number)
    if order_id is None:
        raise NotFoundError("ORDER_NOT_FOUND", "Production order not found.")
    service = ProductionOrderService(context.session, context.clock)
    view = service.get_order(order_id, scope)  # 404 outside a worker's scope (BR-AUTH-03)
    operations = service.list_operations(order_id, scope)
    return OrderStatusResult(
        order=OrderResponse.of(view, user.permissions),
        workflow_progress=float(round(operations.workflow_progress, 2)),
        finished_progress=float(round(operations.finished_progress, 2)),
        operations=[OperationResponse.of(row) for row in operations.rows],
    )


def _risks(context: ToolContext) -> RiskService:
    return RiskService(context.session, context.clock, risk_thresholds(context.settings))


def get_order_risks(context: ToolContext, _: NoArgs) -> BaseModel:
    """Same as GET /dashboard/risks (dashboard:read): AT_RISK and OVERDUE orders."""
    return OrderRisks(orders=[OrderRiskResponse.of(r) for r in _risks(context).order_risks()])


def get_bottlenecks(context: ToolContext, _: NoArgs) -> BaseModel:
    """Same as GET /dashboard/bottlenecks (dashboard:read)."""
    service = DashboardService(context.session, context.clock, _risks(context))
    return Bottlenecks(work_centers=[BottleneckResponse.of(load) for load in service.bottlenecks()])


def get_low_stock_materials(context: ToolContext, _: NoArgs) -> BaseModel:
    """Same as GET /inventory?low_stock=true (inventory:read), D-25."""
    rows, _total = InventoryService(context.session).list_balances(200, 0, low_stock=True)
    return LowStock(materials=[BalanceResponse.of(row, material) for row, material in rows])


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "calculate_material_requirements",
            "Material needs for N units of a product from its ACTIVE BOM, rounded up per material.",
            ProductQuantityArgs,
            (Permission.MASTER_READ,),
            calculate_material_requirements,
        ),
        Tool(
            "check_material_availability",
            "Whether today's available stock covers N units of a product (all-or-nothing), "
            "with required, available and shortage per material. Reserves nothing.",
            ProductQuantityArgs,
            (Permission.MASTER_READ, Permission.INVENTORY_READ),
            check_material_availability,
        ),
        Tool(
            "get_production_order_status",
            "Status, due date, progress and operations of one production order.",
            OrderArgs,
            (Permission.ORDER_READ,),
            get_production_order_status,
        ),
        Tool(
            "get_order_risks",
            "Open orders that are AT_RISK or OVERDUE, with the reason, progress and "
            "current operation.",
            NoArgs,
            (Permission.DASHBOARD_READ,),
            get_order_risks,
        ),
        Tool(
            "get_bottlenecks",
            "Work centers with their queue and at-risk orders; flags bottlenecks.",
            NoArgs,
            (Permission.DASHBOARD_READ,),
            get_bottlenecks,
        ),
        Tool(
            "get_low_stock_materials",
            "Materials whose available stock is below their minimum.",
            NoArgs,
            (Permission.INVENTORY_READ,),
            get_low_stock_materials,
        ),
    )
}
