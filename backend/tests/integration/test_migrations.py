"""Schema built by Alembic matches B2 / B11 / D-01."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse


def test_b2_mysql_version_enforces_check_constraints(db_session: Session) -> None:
    version = db_session.execute(text("SELECT VERSION()")).scalar_one()
    major, minor, patch = (int(part) for part in version.split("-")[0].split(".")[:3])
    assert (major, minor, patch) >= (8, 0, 16)


def test_d01_migration_seeds_single_default_warehouse(db_session: Session) -> None:
    warehouses = db_session.scalars(select(Warehouse)).all()
    assert [w.code for w in warehouses] == [DEFAULT_WAREHOUSE_CODE]


def test_b11_tables_are_innodb_utf8mb4(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name, engine, table_collation FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name <> 'alembic_version'"
        )
    ).all()
    assert rows, "expected at least one application table"
    for table_name, engine, collation in rows:
        assert engine == "InnoDB", table_name
        assert collation.startswith("utf8mb4"), table_name


def test_d23_session_time_zone_is_utc(db_session: Session) -> None:
    assert db_session.execute(text("SELECT @@session.time_zone")).scalar_one() == "+00:00"


def test_b16_application_user_cannot_run_ddl(db_session: Session) -> None:
    grants = [row[0] for row in db_session.execute(text("SHOW GRANTS")).all()]
    schema_grants = [g for g in grants if "manuflow" in g]
    assert schema_grants, grants
    for grant in schema_grants:
        assert "ALL PRIVILEGES" not in grant
        assert "CREATE" not in grant
        assert "DROP" not in grant
        assert "ALTER" not in grant


INSERT_USER = text(
    "INSERT INTO users (username, password_hash, full_name, role, work_center_id) "
    "VALUES (:username, 'x', 'Test', :role, NULL)"
)


def test_d18_worker_without_work_center_rejected_by_db(db_session: Session) -> None:
    with pytest.raises(DBAPIError, match="worker_has_work_center"), db_session.begin():
        db_session.execute(INSERT_USER, {"username": "worker-x", "role": "WORKER"})


def test_d17_unknown_role_rejected_by_db(db_session: Session) -> None:
    with pytest.raises(DBAPIError, match="role_valid"), db_session.begin():
        db_session.execute(INSERT_USER, {"username": "root-x", "role": "SUPERUSER"})


@pytest.mark.parametrize("code", ["wc-weld", "WC", "WC WELD", "WC_WELD"])
def test_br_md_01_work_center_code_format_enforced_by_db(db_session: Session, code: str) -> None:
    with pytest.raises(DBAPIError, match="code_format"), db_session.begin():
        db_session.execute(
            text("INSERT INTO work_centers (code, name) VALUES (:code, 'x')"), {"code": code}
        )


# --- Phase 3: products, materials, inventory ----------------------------------------------


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        (
            "INSERT INTO materials (material_code, name, unit, decimal_places) "
            "VALUES ('BOLT-X', 'Bolt', 'pcs', 2)",
            "pcs_whole_units",
        ),
        (
            "INSERT INTO materials (material_code, name, unit, decimal_places) "
            "VALUES ('BOX-X', 'Box', 'box', 0)",
            "unit_valid",
        ),
        (
            "INSERT INTO materials (material_code, name, unit, decimal_places, minimum_stock) "
            "VALUES ('NEG-X', 'Neg', 'kg', 3, -1)",
            "minimum_stock_non_negative",
        ),
        (
            "INSERT INTO products (product_code, name, unit) VALUES ('KG-PROD', 'X', 'kg')",
            "unit_pcs",
        ),
    ],
    ids=["pcs-decimals", "unit", "minimum-stock", "product-unit"],
)
def test_br_md_02_material_and_product_rules_enforced_by_db(
    db_session: Session, sql: str, constraint: str
) -> None:
    with pytest.raises(DBAPIError, match=constraint), db_session.begin():
        db_session.execute(text(sql))


@pytest.mark.parametrize(
    ("on_hand", "reserved", "constraint"),
    [
        ("-1", "0", "on_hand_non_negative"),
        ("10", "-1", "reserved_non_negative"),
        ("10", "10.0001", "reserved_within_on_hand"),
    ],
)
def test_br_inv_02_available_can_never_go_negative_at_db_level(
    db_session: Session, material_factory, on_hand: str, reserved: str, constraint: str
) -> None:
    material = material_factory()
    with pytest.raises(DBAPIError, match=constraint), db_session.begin():
        db_session.execute(
            text(
                "UPDATE inventory SET on_hand_quantity = :on_hand, reserved_quantity = :reserved "
                "WHERE material_id = :material_id"
            ),
            {"on_hand": on_hand, "reserved": reserved, "material_id": material.id},
        )


# --- Tests 3 and 4 of B15: BOM integrity enforced by the database -----------------------


def test_br_bom_02_duplicate_material_in_a_version_rejected_by_db(
    db_session: Session, product_factory, material_factory, bom_factory
) -> None:
    bolt = material_factory("BOLT-M8", unit="pcs", decimal_places=0)
    header = bom_factory(product_factory(), [(bolt, "8", "0")])
    with pytest.raises(DBAPIError, match="Duplicate entry"), db_session.begin():
        db_session.execute(
            text(
                "INSERT INTO bom_items (bom_header_id, material_id, qty_per_unit) "
                "VALUES (:header, :material, 2)"
            ),
            {"header": header.id, "material": bolt.id},
        )


def test_br_bom_04_db_allows_only_one_active_version_per_product(
    db_session: Session, product_factory, material_factory, bom_factory
) -> None:
    product = product_factory()
    steel = material_factory()
    bom_factory(product, [(steel, "2", "0")], version=1, status="ACTIVE")
    second = bom_factory(product, [(steel, "3", "0")], version=2, status="DRAFT")
    with pytest.raises(DBAPIError, match="active_flag"), db_session.begin():
        db_session.execute(
            text("UPDATE bom_headers SET status = 'ACTIVE' WHERE id = :id"), {"id": second.id}
        )


@pytest.mark.parametrize(
    ("qty", "scrap", "constraint"),
    [("0", "0", "qty_per_unit_positive"), ("1", "1", "scrap_rate_range")],
)
def test_br_bom_01_line_ranges_enforced_by_db(
    db_session: Session,
    product_factory,
    material_factory,
    bom_factory,
    qty: str,
    scrap: str,
    constraint: str,
) -> None:
    header = bom_factory(product_factory(), [])
    material = material_factory()
    with pytest.raises(DBAPIError, match=constraint), db_session.begin():
        db_session.execute(
            text(
                "INSERT INTO bom_items (bom_header_id, material_id, qty_per_unit, scrap_rate) "
                "VALUES (:header, :material, :qty, :scrap)"
            ),
            {"header": header.id, "material": material.id, "qty": qty, "scrap": scrap},
        )


# --- Routing integrity enforced by the database -----------------------------------------


def test_br_rt_01_duplicate_sequence_rejected_by_db(
    db_session: Session, product_factory, work_center_factory, routing_factory
) -> None:
    station = work_center_factory()
    routing = routing_factory(product_factory(), [(10, "QC", station)])
    with pytest.raises(DBAPIError, match="Duplicate entry"), db_session.begin():
        db_session.execute(
            text(
                "INSERT INTO routing_steps (routing_id, sequence, operation_type, work_center_id) "
                "VALUES (:routing, 10, 'CNC', :station)"
            ),
            {"routing": routing.id, "station": station.id},
        )


def test_br_rt_02_unknown_operation_type_rejected_by_db(
    db_session: Session, product_factory, work_center_factory, routing_factory
) -> None:
    station = work_center_factory()
    routing = routing_factory(product_factory(), [])
    with pytest.raises(DBAPIError, match="operation_type_valid"), db_session.begin():
        db_session.execute(
            text(
                "INSERT INTO routing_steps (routing_id, sequence, operation_type, work_center_id) "
                "VALUES (:routing, 10, 'POLISHING', :station)"
            ),
            {"routing": routing.id, "station": station.id},
        )


def test_d03_db_allows_only_one_active_routing_per_product(
    db_session: Session, product_factory, work_center_factory, routing_factory
) -> None:
    product, station = product_factory(), work_center_factory()
    routing_factory(product, [(10, "QC", station)], version=1, status="ACTIVE")
    second = routing_factory(product, [(10, "QC", station)], version=2)
    with pytest.raises(DBAPIError, match="active_flag"), db_session.begin():
        db_session.execute(
            text("UPDATE routings SET status = 'ACTIVE' WHERE id = :id"), {"id": second.id}
        )


# --- BR-INV-03: the ledger is append-only and self-consistent ---------------------------

LEDGER_INSERT = text(
    "INSERT INTO inventory_transactions (type, material_id, warehouse_id, on_hand_delta, "
    "reserved_delta, on_hand_after, reserved_after) VALUES (:type, :material, "
    "(SELECT id FROM warehouses WHERE code = 'MAIN'), :dh, :dr, :ah, :ar)"
)


def test_br_inv_03_ledger_lines_cannot_be_updated_or_deleted(
    db_session: Session, material_factory
) -> None:
    material = material_factory()
    with db_session.begin():
        db_session.execute(
            LEDGER_INSERT,
            {"type": "RECEIVE", "material": material.id, "dh": 5, "dr": 0, "ah": 5, "ar": 0},
        )
    for statement in (
        "UPDATE inventory_transactions SET on_hand_delta = 50",
        "DELETE FROM inventory_transactions",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db_session.begin():
            db_session.execute(text(statement))


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"type": "GIFT", "dh": 1, "dr": 0, "ah": 1, "ar": 0}, "type_valid"),
        ({"type": "RECEIVE", "dh": 0, "dr": 0, "ah": 0, "ar": 0}, "moves_something"),
        ({"type": "ADJUSTMENT", "dh": -1, "dr": 0, "ah": -1, "ar": 0}, "on_hand_after"),
        ({"type": "RESERVE", "dh": 0, "dr": 5, "ah": 3, "ar": 5}, "reserved_after_within"),
    ],
    ids=["type", "no-movement", "negative-on-hand", "reserved-above-on-hand"],
)
def test_br_inv_03_impossible_ledger_lines_rejected_by_db(
    db_session: Session, material_factory, values: dict[str, object], constraint: str
) -> None:
    material = material_factory()
    with pytest.raises(DBAPIError, match=constraint), db_session.begin():
        db_session.execute(LEDGER_INSERT, {"material": material.id, **values})
