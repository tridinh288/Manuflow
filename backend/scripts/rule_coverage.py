"""Business rule -> test traceability report (B15).

Lists every ``BR-xx`` code defined in docs/requirements.md and the tests whose name
cites it (``BR-AUTH-05`` <-> ``test_br_auth_05_...``). With ``--require PREFIX`` (a prefix such
as ``BR-AUTH`` or one rule such as ``BR-INV-04``) it exits non-zero when a matching rule
has no test; the list must be empty for every
completed phase.

    python scripts/rule_coverage.py
    python scripts/rule_coverage.py --require BR-AUTH --require BR-AUD
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# In the API container only backend/ is at /app and docs/ is mounted at /docs.
SPEC_CANDIDATES = [
    BACKEND_DIR.parent / "docs" / "requirements.md",
    Path("/docs/requirements.md"),
]
RULE_DEFINITION = re.compile(r"\*\*(BR-[A-Z]+-\d{2})\*\*")
TEST_NAME = re.compile(r"def (test_\w+)")
RULE_IN_TEST_NAME = re.compile(r"br_([a-z]+)_(\d{2})")


def find_spec() -> Path:
    for candidate in SPEC_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit(f"requirements.md not found in: {', '.join(map(str, SPEC_CANDIDATES))}")


def defined_rules(spec: Path) -> list[str]:
    return sorted(set(RULE_DEFINITION.findall(spec.read_text(encoding="utf-8"))))


def tested_rules(tests_dir: Path) -> dict[str, list[str]]:
    covered: dict[str, list[str]] = defaultdict(list)
    for path in sorted(tests_dir.rglob("test_*.py")):
        for test_name in TEST_NAME.findall(path.read_text(encoding="utf-8")):
            for area, number in RULE_IN_TEST_NAME.findall(test_name):
                covered[f"BR-{area.upper()}-{number}"].append(test_name)
    return covered


def missing_rules(prefixes: list[str]) -> list[str]:
    covered = tested_rules(BACKEND_DIR / "tests")
    return [
        rule
        for rule in defined_rules(find_spec())
        if any(rule == prefix or rule.startswith(f"{prefix}-") for prefix in prefixes)
        and rule not in covered
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--require", action="append", default=[], metavar="PREFIX")
    args = parser.parse_args(argv)

    covered = tested_rules(BACKEND_DIR / "tests")
    for rule in defined_rules(find_spec()):
        tests = covered.get(rule, [])
        print(f"{rule:12} {len(tests):3} {'OK' if tests else 'MISSING'}")

    missing = missing_rules(args.require) if args.require else []
    if missing:
        print(f"\nRules without a test: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
