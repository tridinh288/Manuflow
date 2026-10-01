"""Order risk (B9, D-24, C-09): deterministic rules, no I/O, ``now`` passed in.

The first matching rule decides, for orders that are not COMPLETED or CANCELLED:

| Status                                   | Rule                              | Risk     |
| any open                                 | now > due_date                    | OVERDUE  |
| MATERIAL_SHORTAGE                        | due within SHORTAGE_ALERT_DAYS    | AT_RISK  |
| DRAFT, READY_TO_PRODUCE, MATERIAL_SHORTAGE | due within DUE_SOON_HOURS       | AT_RISK  |
| IN_PROGRESS                              | time_ratio - progress > RISK_GAP  | AT_RISK  |
| otherwise                                |                                   | ON_TRACK |
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.domain.order_state import TERMINAL_STATUSES, OrderStatus


class RiskLevel(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    OVERDUE = "OVERDUE"


class RiskReason(StrEnum):
    PAST_DUE = "PAST_DUE"
    MATERIAL_SHORTAGE = "MATERIAL_SHORTAGE"
    NOT_STARTED_DUE_SOON = "NOT_STARTED_DUE_SOON"
    BEHIND_SCHEDULE = "BEHIND_SCHEDULE"


NOT_STARTED = frozenset(
    {OrderStatus.DRAFT, OrderStatus.READY_TO_PRODUCE, OrderStatus.MATERIAL_SHORTAGE}
)


@dataclass(frozen=True)
class RiskThresholds:
    """D-24: configuration constants."""

    gap: Decimal = Decimal("0.20")
    due_soon: timedelta = timedelta(hours=48)
    shortage_alert: timedelta = timedelta(days=3)


@dataclass(frozen=True)
class OrderFacts:
    status: OrderStatus
    due_date: datetime
    started_at: datetime | None
    workflow_progress: Decimal


@dataclass(frozen=True)
class Assessment:
    risk: RiskLevel
    reason: RiskReason | None
    time_ratio: Decimal | None


def time_ratio(now: datetime, started_at: datetime, due_date: datetime) -> Decimal:
    """Share of the planned time used: (now - start) / (due - start), clamped to [0, 1].

    C-09: a non-positive window (due at or before the start) counts as all time used.
    """
    window = (due_date - started_at).total_seconds()
    if window <= 0:
        return Decimal(1)
    used = Decimal(str((now - started_at).total_seconds())) / Decimal(str(window))
    return min(Decimal(1), max(Decimal(0), used))


def assess(facts: OrderFacts, now: datetime, thresholds: RiskThresholds) -> Assessment | None:
    """``None`` for COMPLETED and CANCELLED orders, which carry no risk."""
    if facts.status in TERMINAL_STATUSES:
        return None
    ratio = (
        time_ratio(now, facts.started_at, facts.due_date)
        if facts.status is OrderStatus.IN_PROGRESS and facts.started_at is not None
        else None
    )
    remaining = facts.due_date - now
    if now > facts.due_date:
        return Assessment(RiskLevel.OVERDUE, RiskReason.PAST_DUE, ratio)
    if facts.status is OrderStatus.MATERIAL_SHORTAGE and remaining <= thresholds.shortage_alert:
        return Assessment(RiskLevel.AT_RISK, RiskReason.MATERIAL_SHORTAGE, ratio)
    if facts.status in NOT_STARTED and remaining <= thresholds.due_soon:
        return Assessment(RiskLevel.AT_RISK, RiskReason.NOT_STARTED_DUE_SOON, ratio)
    if ratio is not None and ratio - facts.workflow_progress > thresholds.gap:
        return Assessment(RiskLevel.AT_RISK, RiskReason.BEHIND_SCHEDULE, ratio)
    return Assessment(RiskLevel.ON_TRACK, None, ratio)


def percent(value: Decimal) -> int:
    return int((value * 100).to_integral_value())


def message(assessment: Assessment, facts: OrderFacts) -> str:
    """A sentence for the dashboard (B9 example wording)."""
    if assessment.reason is RiskReason.PAST_DUE:
        return "Lệnh đã quá hạn giao."
    if assessment.reason is RiskReason.MATERIAL_SHORTAGE:
        return "Lệnh đang thiếu vật tư và sắp đến hạn."
    if assessment.reason is RiskReason.NOT_STARTED_DUE_SOON:
        return "Lệnh chưa bắt đầu sản xuất nhưng sắp đến hạn."
    if assessment.reason is RiskReason.BEHIND_SCHEDULE and assessment.time_ratio is not None:
        return (
            f"Đã dùng {percent(assessment.time_ratio)}% thời gian nhưng lệnh mới đi được "
            f"{percent(facts.workflow_progress)}% quy trình."
        )
    return "Lệnh đang đúng tiến độ."
