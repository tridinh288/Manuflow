"""Work center bottlenecks (B9): where work piles up, not true capacity utilization.

A work center is a BOTTLENECK when at least 2 at-risk orders are currently there, or when
it has the largest queue and at least 1 at-risk order. With no capacity data this shows
where work is stuck, not how loaded the machines really are (README limitation).
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class WorkCenterLoad:
    work_center_id: int
    code: str
    queue_units: int  # sum of limit(n) - processed(n) over unfinished operations here
    at_risk_orders: int  # AT_RISK or OVERDUE orders whose current operation is here
    bottleneck: bool = False


def flag_bottlenecks(loads: list[WorkCenterLoad]) -> list[WorkCenterLoad]:
    """Flag and sort: most at-risk orders first, then the largest queue, then code."""
    largest = max((load.queue_units for load in loads), default=0)
    flagged = [
        replace(
            load,
            bottleneck=load.at_risk_orders >= 2
            or (largest > 0 and load.queue_units == largest and load.at_risk_orders >= 1),
        )
        for load in loads
    ]
    return sorted(flagged, key=lambda load: (-load.at_risk_orders, -load.queue_units, load.code))
