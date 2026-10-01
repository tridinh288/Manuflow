"""B16 "Validate": out-of-range numbers are a 422, never a database error."""

import pytest
from fastapi.testclient import TestClient

from app.core.permissions import Role

BEYOND_BIGINT = 2**64


@pytest.mark.parametrize("path", ["/api/v1/users", "/api/v1/production-orders"])
def test_b16_offset_beyond_bigint_is_422_not_500(
    db_client: TestClient, login_as, path: str
) -> None:
    response = db_client.get(f"{path}?offset={BEYOND_BIGINT}", headers=login_as(Role.ADMIN))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_b16_body_id_beyond_bigint_is_rejected_before_the_service(
    db_client: TestClient, login_as
) -> None:
    headers = {**login_as(Role.WAREHOUSE), "Idempotency-Key": "b16-huge-id-0001"}
    response = db_client.post(
        "/api/v1/inventory/receipts",
        json={"material_id": BEYOND_BIGINT, "quantity": "1"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
