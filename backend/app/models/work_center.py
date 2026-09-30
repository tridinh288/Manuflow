from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, String, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_OPTIONS, Base


class WorkCenter(Base):
    """Created in Phase 2 because users reference it (D-18); CRUD arrives in Phase 3."""

    __tablename__ = "work_centers"
    __table_args__ = (
        CheckConstraint("REGEXP_LIKE(code, '^[A-Z0-9-]{3,32}$', 'c')", name="code_format"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
