"""B15 optional property test: random sequences of receive / adjust / plan / check-materials
/ issue / return / cancel / start, through the API, never break the stock invariants.

After every step:

- no request fails with a 5xx;
- BR-INV-02: 0 <= reserved <= on_hand for every material;
- BR-INV-04: the ledger sums equal the balances;
- reserved stock equals the sum of what the orders' lines still hold;
- on_hand equals a model that only counts successful receipts, adjustments, issues and
  returns (so a rejected request changed nothing);
- every line keeps 0 <= returned <= issued.

Each example gets fresh materials and a fresh product, so examples cannot see each
other's stock even though they share one rolled-back test transaction.
"""

import itertools
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from hypothesis import HealthCheck, event, example, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory
from app.models.production import ProductionOrderMaterial

API = "/api/v1"
_example = itertools.count(1)

ORDER_INDEX = st.integers(0, 7)
LINE_INDEX = st.integers(0, 1)
MATERIAL_INDEX = st.integers(0, 1)
ORDER = st.tuples(st.just("order"), st.integers(1, 60))
ISSUE_ALL = st.tuples(st.just("issue_all"), ORDER_INDEX)
RETURN_ALL = st.tuples(st.just("return_all"), ORDER_INDEX)
# Orders, full issues and full returns are drawn more often, so that sequences reach start, cancel
# after issue, and returns (checked with `pytest --hypothesis-show-statistics`).
OPERATIONS = st.one_of(
    st.tuples(st.just("receive"), MATERIAL_INDEX, st.integers(1, 300)),
    st.tuples(st.just("adjust"), MATERIAL_INDEX, st.integers(-300, 300).filter(bool)),
    ORDER,
    ORDER,
    st.tuples(st.just("check"), ORDER_INDEX),
    st.tuples(st.just("issue"), ORDER_INDEX, LINE_INDEX, st.integers(1, 120)),
    ISSUE_ALL,
    ISSUE_ALL,
    st.tuples(st.just("return"), ORDER_INDEX, LINE_INDEX, st.integers(1, 120)),
    RETURN_ALL,
    st.tuples(st.just("cancel"), ORDER_INDEX),
    st.tuples(st.just("start"), ORDER_INDEX),
)


@dataclass
class Shop:
    client: TestClient
    session: Session
    headers: dict[Role, dict[str, str]]
    materials: list[int] = field(default_factory=list)
    orders: list[int] = field(default_factory=list)
    expected_on_hand: dict[int, Decimal] = field(default_factory=dict)
    product_id: int = 0
    due: str = ""
    outcomes: Counter[str] = field(default_factory=Counter)
    record_events: bool = True

    def call(self, role: Role, method: str, path: str, body: Any = None) -> Any:
        headers = {**self.headers[role], "Idempotency-Key": f"prop-{uuid.uuid4()}"}
        response = self.client.request(method, f"{API}{path}", json=body, headers=headers)
        assert response.status_code < 500, (method, path, response.text)
        if method == "POST":  # coverage, see `pytest --hypothesis-show-statistics`
            outcome = f"{re.sub(r'/[0-9]+', '/{id}', path)} -> {response.status_code}"
            self.outcomes[outcome] += 1
            if self.record_events:
                event(outcome)
        return response

    def ok(self, role: Role, method: str, path: str, body: Any = None) -> Any:
        response = self.call(role, method, path, body)
        assert response.status_code in (200, 201), (method, path, response.text)
        return response.json()


def setup_example(shop: Shop, clock: FixedClock, opening_stock: int) -> None:
    n = next(_example)
    center = shop.ok(Role.ADMIN, "POST", "/work-centers", {"code": f"PW-{n}", "name": "W"})
    for code, unit, places in ((f"PA-{n}", "pcs", 0), (f"PB-{n}", "kg", 3)):
        material = shop.ok(
            Role.PRODUCTION_MANAGER,
            "POST",
            "/materials",
            {
                "material_code": code,
                "name": code,
                "unit": unit,
                "decimal_places": places,
            },
        )
        shop.materials.append(material["id"])
        shop.expected_on_hand[material["id"]] = Decimal(0)
    product = shop.ok(
        Role.PRODUCTION_MANAGER, "POST", "/products", {"product_code": f"PP-{n}", "name": "P"}
    )
    bom = shop.ok(Role.PRODUCTION_MANAGER, "POST", f"/products/{product['id']}/boms")
    shop.ok(
        Role.PRODUCTION_MANAGER,
        "PUT",
        f"/boms/{bom['id']}/items",
        {
            "items": [
                {"material_id": shop.materials[0], "qty_per_unit": "2"},
                {"material_id": shop.materials[1], "qty_per_unit": "0.5"},
            ]
        },
    )
    shop.ok(Role.PRODUCTION_MANAGER, "POST", f"/boms/{bom['id']}/activate")
    routing = shop.ok(Role.PRODUCTION_MANAGER, "POST", f"/products/{product['id']}/routings")
    shop.ok(
        Role.PRODUCTION_MANAGER,
        "PUT",
        f"/routings/{routing['id']}/steps",
        {"steps": [{"sequence": 10, "operation_type": "QC", "work_center_id": center["id"]}]},
    )
    shop.ok(Role.PRODUCTION_MANAGER, "POST", f"/routings/{routing['id']}/activate")
    # Opening stock, so that plans succeed often enough to reach issue/start/return.
    for material in shop.materials:
        apply(shop, ("receive", shop.materials.index(material), opening_stock))
    shop.product_id = product["id"]
    shop.due = (clock.now() + timedelta(days=7)).isoformat()


def lines(shop: Shop, order_id: int) -> list[dict[str, Any]]:
    body = shop.ok(Role.WAREHOUSE, "GET", f"/production-orders/{order_id}/materials")
    return list(body["items"] if isinstance(body, dict) else body)


def apply(shop: Shop, step: tuple[Any, ...]) -> None:
    kind = step[0]
    if kind == "receive":
        material, quantity = shop.materials[step[1]], step[2]
        response = shop.call(
            Role.WAREHOUSE,
            "POST",
            "/inventory/receipts",
            {"material_id": material, "quantity": str(quantity)},
        )
        if response.status_code == 201:
            shop.expected_on_hand[material] += quantity
        return
    if kind == "adjust":
        material, delta = shop.materials[step[1]], step[2]
        response = shop.call(
            Role.WAREHOUSE,
            "POST",
            "/inventory/adjustments",
            {
                "material_id": material,
                "quantity_delta": str(delta),
                "reason": "stock count",
            },
        )
        if response.status_code == 201:
            shop.expected_on_hand[material] += delta
        return
    if kind == "order":
        order = shop.ok(
            Role.PRODUCTION_MANAGER,
            "POST",
            "/production-orders",
            {
                "product_id": shop.product_id,
                "planned_quantity": step[1],
                "due_date": shop.due,
            },
        )
        shop.orders.append(order["id"])
        shop.call(Role.PRODUCTION_MANAGER, "POST", f"/production-orders/{order['id']}/plan")
        return
    if not shop.orders:
        return
    order_id = shop.orders[step[1] % len(shop.orders)]
    if kind == "check":
        shop.call(Role.WAREHOUSE, "POST", f"/production-orders/{order_id}/check-materials")
    elif kind == "cancel":
        shop.call(
            Role.PRODUCTION_MANAGER,
            "POST",
            f"/production-orders/{order_id}/cancel",
            {"reason": "property test"},
        )
    elif kind == "start":
        shop.call(Role.PRODUCTION_MANAGER, "POST", f"/production-orders/{order_id}/start")
    elif kind == "issue_all":
        for line in lines(shop, order_id):
            _move(shop, "issues", line, Decimal(line["reserved_quantity"]))
    elif kind == "return_all":
        for line in lines(shop, order_id):
            outstanding = Decimal(line["issued_quantity"]) - Decimal(line["returned_quantity"])
            _move(shop, "returns", line, outstanding)
    else:  # issue / return a part of one line
        line = lines(shop, order_id)[step[2]]
        _move(shop, "issues" if kind == "issue" else "returns", line, Decimal(step[3]))


def _move(shop: Shop, endpoint: str, line: dict[str, Any], quantity: Decimal) -> None:
    if quantity <= 0:
        return
    response = shop.call(
        Role.WAREHOUSE,
        "POST",
        f"/inventory/{endpoint}",
        {"order_material_id": line["id"], "quantity": format(quantity, "f")},
    )
    if response.status_code == 201:
        sign = -1 if endpoint == "issues" else 1
        shop.expected_on_hand[line["material_id"]] += sign * quantity


def check_invariants(shop: Shop, step: tuple[Any, ...]) -> None:
    shop.session.expire_all()
    for material_id in shop.materials:
        balance = shop.session.scalars(
            select(Inventory).where(Inventory.material_id == material_id)
        ).one()
        on_hand, reserved = balance.on_hand_quantity, balance.reserved_quantity
        assert 0 <= reserved <= on_hand, ("BR-INV-02", step)

        ledger_on_hand, ledger_reserved = shop.session.execute(
            select(
                func.coalesce(func.sum(InventoryTransaction.on_hand_delta), 0),
                func.coalesce(func.sum(InventoryTransaction.reserved_delta), 0),
            ).where(InventoryTransaction.material_id == material_id)
        ).one()
        assert (ledger_on_hand, ledger_reserved) == (on_hand, reserved), ("BR-INV-04", step)

        order_lines = shop.session.scalars(
            select(ProductionOrderMaterial).where(
                ProductionOrderMaterial.material_id == material_id
            )
        ).all()
        assert reserved == sum((ln.reserved_quantity for ln in order_lines), Decimal(0)), step
        for line in order_lines:
            assert 0 <= line.returned_quantity <= line.issued_quantity, step
            # The line's counters agree with the ledger lines written for it (BR-INV-03).
            moved = dict(
                shop.session.execute(
                    select(InventoryTransaction.type, func.sum(InventoryTransaction.on_hand_delta))
                    .where(InventoryTransaction.order_material_id == line.id)
                    .group_by(InventoryTransaction.type)
                ).all()
            )
            assert -moved.get("ISSUE", 0) == line.issued_quantity, ("issued", step)
            assert moved.get("RETURN", 0) == line.returned_quantity, ("returned", step)
        assert on_hand == shop.expected_on_hand[material_id], ("model", step)


# Sequences that must always run, whatever the random draw: a release after an
# over-issue is refused, a cancel after a partial issue followed by returns (the last
# one refused), and a shortage cured by a receipt after a stock-count decrease.
RELEASE = [("order", 10), ("issue", 0, 0, 30), ("issue_all", 0), ("start", 0)]
CANCEL_AND_RETURN = [
    ("order", 10),
    ("issue", 0, 0, 7),
    ("cancel", 0),
    ("return", 0, 0, 3),
    ("return_all", 0),
    ("return", 0, 0, 1),
]
SHORTAGE_CURED = [
    ("order", 60),
    ("adjust", 1, -5),
    ("receive", 0, 300),
    ("receive", 1, 300),
    ("check", 0),
    ("issue_all", 0),
    ("start", 0),
]


@settings(
    max_examples=60,
    deadline=None,
    # The DB fixtures are shared by the examples on purpose: each example uses fresh
    # materials and a fresh product, and the whole test rolls back at the end.
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@example(opening_stock=100, steps=RELEASE)
@example(opening_stock=100, steps=CANCEL_AND_RETURN)
@example(opening_stock=50, steps=SHORTAGE_CURED)
@given(opening_stock=st.integers(1, 300), steps=st.lists(OPERATIONS, min_size=8, max_size=30))
def test_br_inv_02_and_br_inv_04_hold_for_random_stock_sequences(
    db_client: TestClient,
    db_session: Session,
    login_as,
    clock: FixedClock,
    opening_stock: int,
    steps: list[tuple[Any, ...]],
) -> None:
    roles = (Role.ADMIN, Role.PRODUCTION_MANAGER, Role.WAREHOUSE)
    shop = Shop(db_client, db_session, {role: login_as(role) for role in roles})
    setup_example(shop, clock, opening_stock)
    for step in steps:
        apply(shop, step)
        check_invariants(shop, step)


def test_fixed_sequences_reach_every_stock_movement(
    db_client: TestClient, db_session: Session, login_as, clock: FixedClock
) -> None:
    """Guards the property test: its fixed examples really issue, start, cancel and return."""
    outcomes: Counter[str] = Counter()
    for opening_stock, steps in ((100, RELEASE), (100, CANCEL_AND_RETURN), (50, SHORTAGE_CURED)):
        roles = (Role.ADMIN, Role.PRODUCTION_MANAGER, Role.WAREHOUSE)
        shop = Shop(db_client, db_session, {r: login_as(r) for r in roles}, record_events=False)
        setup_example(shop, clock, opening_stock)
        for step in steps:
            apply(shop, step)
            check_invariants(shop, step)
        outcomes += shop.outcomes
    assert outcomes["/inventory/issues -> 201"] == 2 + 1 + 2
    assert outcomes["/inventory/issues -> 409"] == 1  # 30 > 20 still reserved, though 100 on hand
    assert outcomes["/inventory/adjustments -> 201"] == 1
    assert outcomes["/production-orders/{id}/start -> 200"] == 2
    assert outcomes["/production-orders/{id}/cancel -> 200"] == 1
    assert outcomes["/inventory/returns -> 201"] == 2  # 3, then the remaining 4
    assert outcomes["/inventory/returns -> 409"] == 1  # nothing left to return
    assert outcomes["/production-orders/{id}/check-materials -> 200"] == 1
