from typing import Literal

from pydantic import BaseModel

ComponentStatus = Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: ComponentStatus
    database: ComponentStatus
