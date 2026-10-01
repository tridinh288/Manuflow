"""Demo data for a small metal-working shop (B1, B18 Phase 7).

The seed replays ten days of shop history **through the HTTP API**, so every row it
leaves behind went through the same permission checks, services, ledger and audit as real
use. A FixedClock starts ten days ago and is moved forward between steps; the run ends at
"now", so risk and due dates on the dashboard are live when the demo starts.

At the end the shop has (B18 Phase 7 DoD):

- an order in every status (DRAFT ... CANCELLED);
- PO 7 in MATERIAL_SHORTAGE, short of steel only: the 5-minute demo receives steel,
  runs check-materials and carries it through to COMPLETED;
- PO 3 AT_RISK and PO 4 OVERDUE, both stuck at welding, so WC-WELD is a bottleneck;
- steel and bolts below their minimum stock (low-stock alerts, D-25).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core.clock import FixedClock

HISTORY = timedelta(days=10)

WORK_CENTERS = [
    ("WC-CUT", "Laser cutting"),
    ("WC-CNC", "CNC machining"),
    ("WC-WELD", "Welding"),
    ("WC-PAINT", "Powder coating"),
    ("WC-QC", "Quality control"),
]
# code, name, unit, decimal places, minimum stock, received at the start
MATERIALS = [
    ("STEEL-001", "Steel sheet 2 mm", "kg", 3, "1000", "1500"),
    ("BOLT-M8", "Bolt M8x20", "pcs", 0, "4500", "6000"),
    ("PAINT-01", "Powder coat RAL 7016", "l", 2, "20", "120"),
]
# product: (name, [(material, qty per unit, scrap rate)], [(sequence, operation, center)])
PRODUCTS = {
    "FRAME-A": (
        "Welded machine frame",
        [("STEEL-001", "2.5", "0.04"), ("BOLT-M8", "8", "0"), ("PAINT-01", "0.15", "0.1")],
        [
            (10, "CUTTING", "WC-CUT"),
            (20, "WELDING", "WC-WELD"),
            (30, "PAINTING", "WC-PAINT"),
            (40, "QC", "WC-QC"),
        ],
    ),
    "BRACKET-B": (
        "Machined mounting bracket",
        [("STEEL-001", "0.8", "0"), ("BOLT-M8", "4", "0")],
        [(10, "CUTTING", "WC-CUT"), (20, "CNC", "WC-CNC"), (30, "QC", "WC-QC")],
    ),
}
# username, full name, role, work center
USERS = [
    ("demo.manager", "Linh Tran", "PRODUCTION_MANAGER", None),
    ("demo.warehouse", "Minh Pham", "WAREHOUSE", None),
    ("demo.cut", "An Nguyen", "WORKER", "WC-CUT"),
    ("demo.cnc", "Bao Le", "WORKER", "WC-CNC"),
    ("demo.weld", "Chi Vo", "WORKER", "WC-WELD"),
    ("demo.paint", "Dung Ho", "WORKER", "WC-PAINT"),
    ("demo.qc", "Hanh Do", "WORKER", "WC-QC"),
]
ADMIN_USERNAME = "demo.admin"


class SeedError(RuntimeError):
    pass


@dataclass
class Shop:
    """Drives the API as the demo users; every call must succeed."""

    client: TestClient
    clock: FixedClock
    password: str
    ids: dict[str, int] = field(default_factory=dict)

    def at(self, moment: datetime) -> None:
        if moment < self.clock.now():
            raise SeedError(f"the story went back in time: {moment} < {self.clock.now()}")
        self.clock.current = moment

    def call(self, user: str, method: str, path: str, body: Any = None) -> Any:
        # Log in for every call: tokens last 30 minutes and the clock jumps by days.
        login = self.client.post(
            "/api/v1/auth/login", json={"username": user, "password": self.password}
        )
        if login.status_code != 200:
            raise SeedError(f"login as {user} failed: {login.status_code} {login.text}")
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "Idempotency-Key": f"seed-{uuid.uuid4()}",
        }
        response = self.client.request(method, f"/api/v1{path}", json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            raise SeedError(f"{method} {path} as {user}: {response.status_code} {response.text}")
        return response.json() if response.content else None


def _items(body: Any) -> list[dict[str, Any]]:
    return list(body["items"]) if isinstance(body, dict) else list(body)


def seed_demo(
    client: TestClient,
    clock: FixedClock,
    password: str,
    create_admin: Callable[[str, str], None],
) -> dict[str, int]:
    """Replay the shop history up to clock.now(). Returns order numbers -> ids."""
    now = clock.now()
    start = now - HISTORY
    clock.current = start
    shop = Shop(client, clock, password)

    create_admin(ADMIN_USERNAME, password)
    _master_data(shop)
    _stock(shop)
    orders = _orders(shop, now)
    shop.at(now)
    return orders


def _master_data(shop: Shop) -> None:
    for code, name in WORK_CENTERS:
        body = shop.call(ADMIN_USERNAME, "POST", "/work-centers", {"code": code, "name": name})
        shop.ids[code] = body["id"]
    for username, full_name, role, center in USERS:
        shop.call(
            ADMIN_USERNAME,
            "POST",
            "/users",
            {
                "username": username,
                "password": shop.password,
                "full_name": full_name,
                "role": role,
                "work_center_id": shop.ids[center] if center else None,
            },
        )
    for code, name, unit, places, minimum, _ in MATERIALS:
        body = shop.call(
            "demo.manager",
            "POST",
            "/materials",
            {
                "material_code": code,
                "name": name,
                "unit": unit,
                "decimal_places": places,
                "minimum_stock": minimum,
            },
        )
        shop.ids[code] = body["id"]
    for code, (name, items, steps) in PRODUCTS.items():
        product = shop.call(
            "demo.manager", "POST", "/products", {"product_code": code, "name": name}
        )
        shop.ids[code] = product["id"]
        bom = shop.call("demo.manager", "POST", f"/products/{product['id']}/boms")
        shop.call(
            "demo.manager",
            "PUT",
            f"/boms/{bom['id']}/items",
            {
                "items": [
                    {"material_id": shop.ids[m], "qty_per_unit": q, "scrap_rate": s}
                    for m, q, s in items
                ]
            },
        )
        shop.call("demo.manager", "POST", f"/boms/{bom['id']}/activate")
        routing = shop.call("demo.manager", "POST", f"/products/{product['id']}/routings")
        shop.call(
            "demo.manager",
            "PUT",
            f"/routings/{routing['id']}/steps",
            {
                "steps": [
                    {"sequence": seq, "operation_type": op, "work_center_id": shop.ids[wc]}
                    for seq, op, wc in steps
                ]
            },
        )
        shop.call("demo.manager", "POST", f"/routings/{routing['id']}/activate")


def _stock(shop: Shop) -> None:
    shop.at(shop.clock.now() + timedelta(hours=2))
    for code, _, _, _, _, received in MATERIALS:
        shop.call(
            "demo.warehouse",
            "POST",
            "/inventory/receipts",
            {
                "material_id": shop.ids[code],
                "quantity": received,
                "reference": f"GRN-{code}",
            },
        )


# --- Orders -------------------------------------------------------------------------------


def _create(shop: Shop, product: str, quantity: int, due: datetime, notes: str) -> int:
    body = shop.call(
        "demo.manager",
        "POST",
        "/production-orders",
        {
            "product_id": shop.ids[product],
            "planned_quantity": quantity,
            "due_date": due.isoformat(),
            "notes": notes,
        },
    )
    return int(body["id"])


def _plan(shop: Shop, order_id: int) -> bool:
    return bool(
        shop.call("demo.manager", "POST", f"/production-orders/{order_id}/plan")["reserved"]
    )


def issue_all(shop: Shop, order_id: int) -> None:
    lines = _items(shop.call("demo.warehouse", "GET", f"/production-orders/{order_id}/materials"))
    for line in lines:
        shop.call(
            "demo.warehouse",
            "POST",
            "/inventory/issues",
            {
                "order_material_id": line["id"],
                "quantity": line["reserved_quantity"],
            },
        )


def _release(shop: Shop, order_id: int) -> None:
    """Plan, issue everything and start: the order is IN_PROGRESS afterwards."""
    if not _plan(shop, order_id):
        raise SeedError(f"order {order_id} could not reserve its materials")
    issue_all(shop, order_id)
    shop.call("demo.manager", "POST", f"/production-orders/{order_id}/start")


def report(shop: Shop, order_id: int, sequence: int, good: int, rejected: int = 0) -> None:
    operations = _items(
        shop.call("demo.manager", "GET", f"/production-orders/{order_id}/operations")
    )
    operation = next(op for op in operations if op["sequence"] == sequence)
    worker = next(u for u, _, _, wc in USERS if wc == operation["work_center_code"])
    shop.call(
        worker,
        "POST",
        f"/production-operations/{operation['id']}/progress",
        {
            "good_delta": good,
            "rejected_delta": rejected,
        },
    )


def _orders(shop: Shop, now: datetime) -> dict[str, int]:
    t0 = shop.clock.now()
    day = timedelta(days=1)
    orders: dict[str, int] = {}

    # PO 1: a finished batch, one frame scrapped at QC -> COMPLETED with 19.
    shop.at(t0 + timedelta(hours=3))
    po1 = _create(shop, "FRAME-A", 20, t0 + 5 * day, "Customer pilot batch")
    _release(shop, po1)
    for offset, sequence, good, rejected in [
        (1, 10, 20, 0),
        (2, 20, 20, 0),
        (3, 30, 20, 0),
        (3.2, 40, 19, 1),
    ]:
        shop.at(t0 + offset * day)
        report(shop, po1, sequence, good, rejected)
    orders["completed"] = po1

    # PO 2: planned, then the customer withdrew -> CANCELLED, reservation released.
    shop.at(t0 + 3.5 * day)
    po2 = _create(shop, "FRAME-A", 30, t0 + 9 * day, "Withdrawn by customer")
    _plan(shop, po2)
    shop.at(t0 + 4 * day)
    shop.call(
        "demo.manager",
        "POST",
        f"/production-orders/{po2}/cancel",
        {"reason": "Customer withdrew the order"},
    )
    orders["cancelled"] = po2

    # PO 4 (due yesterday, still at welding -> OVERDUE) and PO 3 (due in 8 hours, 96 % of
    # its time used, welding 40/100 -> AT_RISK) overlap; steps follow the calendar.
    po4 = _create(shop, "FRAME-A", 60, now - day, "Repeat order, tight date")
    shop.at(now - 5 * day)
    _release(shop, po4)
    po3 = _create(shop, "FRAME-A", 100, now + timedelta(hours=8), "Large frame order")
    shop.at(now - 4 * day)
    report(shop, po4, 10, 60)
    shop.at(now - 4 * day + timedelta(hours=1))
    _release(shop, po3)
    shop.at(now - 2 * day)
    report(shop, po4, 20, 20)
    shop.at(now - 2 * day + timedelta(hours=2))
    report(shop, po3, 10, 100)

    # PO 5: brackets on schedule at CNC -> ON_TRACK.
    shop.at(now - 2 * day + timedelta(hours=4))
    po5 = _create(shop, "BRACKET-B", 50, now + 5 * day, "Brackets for FRAME-A line")
    shop.at(now - day)
    report(shop, po3, 20, 38, 2)
    shop.at(now - day + timedelta(hours=1))
    _release(shop, po5)
    shop.at(now - timedelta(hours=12))
    report(shop, po5, 10, 50)
    shop.at(now - timedelta(hours=3))
    report(shop, po5, 20, 20)
    orders["overdue"] = po4
    orders["at_risk"] = po3
    orders["on_track"] = po5

    # PO 6: materials reserved, waiting for the warehouse -> READY_TO_PRODUCE.
    shop.at(now - timedelta(hours=2))
    po6 = _create(shop, "FRAME-A", 40, now + 6 * day, "Next week's frames")
    _plan(shop, po6)
    orders["ready"] = po6

    # PO 7: needs more steel than is left -> MATERIAL_SHORTAGE (the 5-minute demo).
    shop.at(now - timedelta(hours=1))
    po7 = _create(shop, "FRAME-A", 400, now + 10 * day, "Distributor order")
    if _plan(shop, po7):
        raise SeedError("PO 7 was meant to be short of steel")
    orders["shortage"] = po7

    # PO 8: just entered -> DRAFT.
    shop.at(now - timedelta(minutes=30))
    orders["draft"] = _create(shop, "BRACKET-B", 120, now + 14 * day, "Quote accepted, not planned")
    return orders
