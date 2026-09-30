"""BR-AUD-04: which incoming request IDs are accepted."""

import uuid

import pytest

from app.core.request_id import resolve_request_id


@pytest.mark.parametrize("incoming", ["7f3c2a", "abc-123_DEF.9", "a" * 128])
def test_br_aud_04_well_formed_id_is_kept(incoming: str) -> None:
    assert resolve_request_id(incoming) == incoming


@pytest.mark.parametrize("incoming", [None, "", "a" * 129, "has space", "semi;colon", "ünï"])
def test_br_aud_04_missing_or_malformed_id_is_replaced_by_uuid4(incoming: str | None) -> None:
    generated = resolve_request_id(incoming)
    assert generated != incoming
    assert uuid.UUID(generated).version == 4
