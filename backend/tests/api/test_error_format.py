"""B13: one error body format for every failure, with no internals leaked."""

import pytest
from fastapi.testclient import TestClient


def _error(response_json: dict[str, object]) -> dict[str, object]:
    assert set(response_json) == {"error"}
    error = response_json["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "details", "request_id"}
    return error


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("not_found", 404, "PRODUCT_NOT_FOUND"),
        ("conflict", 409, "INSUFFICIENT_STOCK"),
        ("validation", 422, "INVALID_QUANTITY"),
        ("concurrency", 503, "CONCURRENCY_CONFLICT"),
    ],
)
def test_b13_domain_error_maps_to_status_and_code(
    probe_client: TestClient, kind: str, status: int, code: str
) -> None:
    response = probe_client.get(f"/_probe/domain/{kind}")
    assert response.status_code == status
    assert _error(response.json())["code"] == code


def test_b13_domain_error_details_keep_quantities_as_strings(probe_client: TestClient) -> None:
    error = _error(probe_client.get("/_probe/domain/conflict").json())
    assert error["details"] == [
        {"material_code": "BOLT-M8", "required": "840", "available": "500", "shortage": "340"}
    ]


def test_b13_request_validation_returns_422_without_echoing_input(
    probe_client: TestClient,
) -> None:
    response = probe_client.post(
        "/_probe/validate", json={"password": "hunter2-super-secret", "quantity": 0}
    )
    assert response.status_code == 422
    error = _error(response.json())
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == [
        {
            "field": "body.quantity",
            "message": "Input should be greater than 0",
            "type": "greater_than",
        }
    ]
    assert "hunter2-super-secret" not in response.text


def test_b13_unhandled_error_returns_500_without_internals(probe_client: TestClient) -> None:
    response = probe_client.get("/_probe/crash")
    assert response.status_code == 500
    error = _error(response.json())
    assert error["code"] == "INTERNAL_ERROR"
    assert error["details"] == []
    for leaked in ("RuntimeError", "SELECT", "password_hash", "Traceback"):
        assert leaked not in response.text


def test_b13_unknown_route_uses_error_format(probe_client: TestClient) -> None:
    response = probe_client.get("/no-such-route")
    assert response.status_code == 404
    assert _error(response.json())["code"] == "NOT_FOUND"


def test_b13_wrong_method_uses_error_format(probe_client: TestClient) -> None:
    response = probe_client.delete("/_probe/ok")
    assert response.status_code == 405
    assert _error(response.json())["code"] == "METHOD_NOT_ALLOWED"
