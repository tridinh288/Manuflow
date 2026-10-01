"""B15 / B18 Definition of Done: every rule of a completed phase has a test.

Add the rule prefixes of each phase here when that phase is finished.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

COMPLETED_PHASE_PREFIXES = [
    "BR-AUTH",  # Phase 2
    "BR-AUD",
    "BR-MD",  # Phase 3
    "BR-BOM",
    "BR-RT",
    "BR-INV",  # Phase 4 (01-04) and Phase 5 reservations (05-06)
    "BR-PO",  # Phase 5
    "BR-OP",  # Phase 6
]


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "rule_coverage.py"
    spec = importlib.util.spec_from_file_location("rule_coverage", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_b15_rule_list_is_read_from_the_spec() -> None:
    script = _load_script()
    rules = script.defined_rules(script.find_spec())
    assert "BR-AUTH-01" in rules
    assert "BR-INV-05" in rules
    assert len(rules) >= 40


def test_b15_every_rule_of_completed_phases_has_a_test() -> None:
    assert _load_script().missing_rules(COMPLETED_PHASE_PREFIXES) == []
