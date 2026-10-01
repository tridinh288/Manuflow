"""All-or-nothing reservation (B6, BR-INV-05, D-08): pure decision, no I/O.

Given each line's required quantity and the locked balances, either every line can be
reserved in full, or nothing is reserved and every shortage is reported.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.domain.inventory import Balance


@dataclass(frozen=True)
class RequiredLine:
    material_id: int
    required: Decimal


@dataclass(frozen=True)
class LineCheck:
    material_id: int
    required: Decimal
    available: Decimal
    shortage: Decimal  # max(0, required - available)


@dataclass(frozen=True)
class ReservationDecision:
    checks: list[LineCheck]

    @property
    def reservable(self) -> bool:
        return all(check.shortage == 0 for check in self.checks)


def decide(lines: Sequence[RequiredLine], balances: Mapping[int, Balance]) -> ReservationDecision:
    """B6 steps 4-5: per line ``shortage = max(0, required - available)``."""
    checks = []
    for line in sorted(lines, key=lambda line: line.material_id):
        available = balances[line.material_id].available
        checks.append(
            LineCheck(
                material_id=line.material_id,
                required=line.required,
                available=available,
                shortage=max(Decimal(0), line.required - available),
            )
        )
    return ReservationDecision(checks)
