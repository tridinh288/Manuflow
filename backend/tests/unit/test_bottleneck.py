"""B9 bottleneck rule: 2+ at-risk orders, or the largest queue with 1+ at-risk order."""

from app.domain.bottleneck import WorkCenterLoad, flag_bottlenecks


def load(code: str, queue: int, at_risk: int) -> WorkCenterLoad:
    return WorkCenterLoad(
        work_center_id=hash(code) % 1000, code=code, queue_units=queue, at_risk_orders=at_risk
    )


def flagged(loads: list[WorkCenterLoad]) -> dict[str, bool]:
    return {item.code: item.bottleneck for item in flag_bottlenecks(loads)}


def test_b9_two_at_risk_orders_make_a_bottleneck_whatever_the_queue() -> None:
    assert flagged([load("WC-WELD", 5, 2), load("WC-QC", 100, 0)]) == {
        "WC-WELD": True,
        "WC-QC": False,
    }


def test_b9_largest_queue_needs_at_least_one_at_risk_order() -> None:
    assert flagged([load("WC-QC", 100, 1), load("WC-CUT", 40, 1)]) == {
        "WC-QC": True,
        "WC-CUT": False,  # one at-risk order, but not the largest queue
    }
    assert flagged([load("WC-QC", 100, 0), load("WC-CUT", 40, 1)]) == {
        "WC-QC": False,  # largest queue, but nothing at risk there
        "WC-CUT": False,
    }


def test_b9_every_work_center_tied_for_the_largest_queue_counts() -> None:
    assert flagged([load("WC-A", 30, 1), load("WC-B", 30, 1), load("WC-C", 10, 1)]) == {
        "WC-A": True,
        "WC-B": True,
        "WC-C": False,
    }


def test_b9_an_idle_shop_has_no_bottleneck() -> None:
    assert flagged([load("WC-A", 0, 0), load("WC-B", 0, 1)]) == {"WC-A": False, "WC-B": False}


def test_b9_sorted_by_at_risk_orders_then_queue() -> None:
    result = flag_bottlenecks(
        [load("WC-A", 90, 0), load("WC-B", 10, 2), load("WC-C", 50, 1), load("WC-D", 80, 1)]
    )
    assert [item.code for item in result] == ["WC-B", "WC-D", "WC-C", "WC-A"]
