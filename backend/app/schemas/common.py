from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

# B13: lists take limit (default 50, max 200) and offset, and return {"items", "total"}.
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
DEFAULT_LIMIT = 50


class Page[T](BaseModel):
    items: list[T]
    total: int
