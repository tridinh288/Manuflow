from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

# B16: ids in request bodies fit the BIGINT primary keys; larger values are a 422.
MAX_ID = 2**63 - 1

# B13: lists take limit (default 50, max 200) and offset, and return {"items", "total"}.
# Offset is capped too: MySQL fails on an OFFSET beyond 64 bits (was a 500).
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=MAX_ID)]
DEFAULT_LIMIT = 50


class Page[T](BaseModel):
    items: list[T]
    total: int
