"""Application logging: plain ``key=value`` lines that always carry the request ID."""

import logging
from typing import Any

from app.core.request_id import get_request_id

LOG_FORMAT = "%(asctime)s level=%(levelname)s logger=%(name)s request_id=%(request_id)s %(message)s"

_configured = False


def configure_logging(level: str) -> None:
    """Idempotent: the record factory and handler are installed once per process."""
    global _configured
    logging.getLogger().setLevel(level)
    if _configured:
        return

    base_factory = logging.getLogRecordFactory()

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        record.request_id = get_request_id() or "-"
        return record

    logging.setLogRecordFactory(record_factory)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    _configured = True
