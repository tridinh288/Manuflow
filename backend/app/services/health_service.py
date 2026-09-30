import logging

from sqlalchemy import literal, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def database_is_available(self) -> bool:
        try:
            with self._session.begin():
                self._session.execute(select(literal(1)))
        except SQLAlchemyError:
            # The DB error text may contain host names; keep it in the log only.
            logger.warning("Database health check failed", exc_info=True)
            return False
        return True
