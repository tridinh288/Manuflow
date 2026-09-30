from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.permissions import Role
from app.db.base import MYSQL_TABLE_OPTIONS, Base
from app.db.types import UTCDateTime

_ROLE_VALUES = ", ".join(f"'{role.value}'" for role in Role)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="role_valid"),
        # D-18: every worker belongs to exactly one work center.
        CheckConstraint(
            "role <> 'WORKER' OR work_center_id IS NOT NULL", name="worker_has_work_center"
        ),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_non_negative"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(
        # VARCHAR + the CHECK above rather than a MySQL ENUM (B11); loads as ``Role``.
        Enum(
            Role,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    work_center_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("work_centers.id"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))

    # Account lockout state (BR-AUTH-05, C-06).
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    first_failed_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
