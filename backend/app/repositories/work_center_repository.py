from sqlalchemy.orm import Session

from app.models.work_center import WorkCenter


class WorkCenterRepository:
    """Queries only; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, work_center_id: int) -> WorkCenter | None:
        return self._session.get(WorkCenter, work_center_id)
