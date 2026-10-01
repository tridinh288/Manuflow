"""B16: a database error never carries bound values into the error log."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


def test_b16_db_error_message_hides_bound_parameters(db_engine: Engine) -> None:
    secret = "argon2-hash-that-must-not-be-logged"
    with db_engine.connect() as connection, pytest.raises(DBAPIError) as error:
        connection.execute(text("SELECT :value FROM no_such_table"), {"value": secret})

    assert "no_such_table" in str(error.value)  # the message is still useful
    assert secret not in str(error.value)
