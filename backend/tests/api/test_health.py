"""Phase 1 DoD: /health reports whether the database is reachable."""

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app

UNREACHABLE_DB_URL = "mysql+pymysql://nobody:nothing@127.0.0.1:1/none"


def test_health_reports_database_ok(db_client: TestClient) -> None:
    response = db_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_database_unavailable_without_leaking_details(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"database_url": SecretStr(UNREACHABLE_DB_URL)}))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
