"""BR-AUD-04: the request ID is on every response, every error body and every log line."""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.request_id import REQUEST_ID_HEADER

PROBE_LOGGER = "tests.probe"


def test_br_aud_04_request_id_generated_when_missing(probe_client: TestClient) -> None:
    response = probe_client.get("/_probe/ok")
    assert response.status_code == 200
    assert uuid.UUID(response.headers[REQUEST_ID_HEADER]).version == 4


def test_br_aud_04_request_id_propagated_from_header(probe_client: TestClient) -> None:
    response = probe_client.get("/_probe/ok", headers={REQUEST_ID_HEADER: "client-req-42"})
    assert response.headers[REQUEST_ID_HEADER] == "client-req-42"


def test_br_aud_04_malformed_request_id_is_replaced(probe_client: TestClient) -> None:
    response = probe_client.get("/_probe/ok", headers={REQUEST_ID_HEADER: "bad id!"})
    assert uuid.UUID(response.headers[REQUEST_ID_HEADER]).version == 4


@pytest.mark.parametrize("path", ["/_probe/domain/conflict", "/_probe/crash", "/no-such-route"])
def test_br_aud_04_error_body_carries_same_request_id(probe_client: TestClient, path: str) -> None:
    response = probe_client.get(path, headers={REQUEST_ID_HEADER: "err-req-1"})
    assert response.status_code >= 400
    assert response.headers[REQUEST_ID_HEADER] == "err-req-1"
    assert response.json()["error"]["request_id"] == "err-req-1"


def test_br_aud_04_log_records_carry_request_id(
    probe_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=PROBE_LOGGER):
        probe_client.get("/_probe/ok", headers={REQUEST_ID_HEADER: "log-req-7"})
    records = [r for r in caplog.records if r.name == PROBE_LOGGER]
    assert [r.request_id for r in records] == ["log-req-7"]  # type: ignore[attr-defined]


def test_br_aud_04_unhandled_error_log_carries_request_id(
    probe_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        probe_client.get("/_probe/crash", headers={REQUEST_ID_HEADER: "crash-req-9"})
    records = [r for r in caplog.records if r.name == "app.api.errors"]
    assert [r.request_id for r in records] == ["crash-req-9"]  # type: ignore[attr-defined]
