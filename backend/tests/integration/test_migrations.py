"""Schema built by Alembic matches B2 / B11 / D-01."""

from sqlalchemy import select, text
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
