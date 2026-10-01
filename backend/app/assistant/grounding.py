"""BR-AI-03: the final answer may only quote numbers the tools returned.

Pure functions. A number in the answer is grounded when it equals a number in the
question or in a tool result, a ratio from a tool shown as a percentage (0.92 -> 92), or
the length of a list a tool returned (a count such as "2 orders"). Identifier fields
(``id``, ``*_id``) are ignored: an id of 3 must not ground "3 days".

It is a heuristic: it catches figures the model made up, not a small number that happens
to equal a count or a value elsewhere in the results. The evaluation (BR-AI-05) checks
the facts of each answer separately.
"""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*")


def _canonical(text: str) -> set[str]:
    """Readings of one token: 1040.000 / 1040,000 / 1.040 (vi thousands) / 00007."""
    readings = {text.replace(",", "."), text.replace(",", "").replace(".", "")}
    if text.count(",") == 1 and "." not in text:
        readings.add(text.replace(",", "."))
    found = set()
    for reading in readings:
        try:
            found.add(format(Decimal(reading).normalize(), "f"))
        except InvalidOperation:
            continue
    return found


def _walk(value: Any, numbers: set[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "id" or key.endswith("_id"):
                continue  # identifiers are not facts to quote
            _walk(nested, numbers)
    elif isinstance(value, list):
        numbers |= _canonical(str(len(value)))
        for nested in value:
            _walk(nested, numbers)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        numbers |= _canonical(str(value))
        if isinstance(value, float) and 0 <= value <= 1:
            numbers |= _canonical(str(round(value * 100)))
    elif isinstance(value, str):
        for token in _NUMBER.findall(value):
            numbers |= _canonical(token)


def allowed_numbers(question: str, tool_results: list[dict[str, Any]]) -> set[str]:
    numbers: set[str] = set()
    _walk(question, numbers)
    for result in tool_results:
        _walk(json.loads(json.dumps(result)), numbers)
    return numbers


def ungrounded_numbers(answer: str, allowed: set[str]) -> list[str]:
    return [token for token in _NUMBER.findall(answer) if not (_canonical(token) & allowed)]
