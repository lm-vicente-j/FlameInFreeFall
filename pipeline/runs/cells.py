"""Parse one table cell into a quantity, a null, or "not a number".

Only three shapes are numeric: a plain number, an approximate number ("~ 21.5")
and a range ("21.5 - 21.7", "22.1 to 22.0"; endpoints are sorted). An optional
unit suffix is accepted only if it equals the expected unit. Anything else is
reported as not a number so the caller keeps the original text instead of
guessing. Signs are not accepted: no run-table quantity is negative, and a
leading "-" is the null placeholder.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

NULL_TOKENS = frozenset({"", "n/a", "none", "-", "\N{EN DASH}", "\N{EM DASH}"})
"""Placeholders for "no value". The en and em dash appear in FLEX (cp1252 0x96)."""

_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_PATTERN = re.compile(
    rf"^(?P<approx>~\s*)?(?P<low>{_NUMBER})(?:\s*(?:-|to)\s*(?P<high>{_NUMBER}))?(?:\s*(?P<unit>[^\d\s].*?))?$"
)

Qualifier = Literal["approximate"]


@dataclass(frozen=True)
class NullCell:
    text: str


@dataclass(frozen=True)
class NumberCell:
    minimum: Decimal
    maximum: Decimal
    qualifier: Qualifier | None
    had_unit: bool


@dataclass(frozen=True)
class NotNumber:
    reason: str


CellParse = NullCell | NumberCell | NotNumber


def parse_cell(text: str, expected_unit: str | None = None) -> CellParse:
    stripped = " ".join(text.split())
    if stripped.lower() in NULL_TOKENS:
        return NullCell(stripped)
    match = _PATTERN.match(stripped)
    if match is None:
        return NotNumber("not a plain number, approximate number or range")
    unit = match.group("unit")
    if unit is not None and unit != expected_unit:
        wanted = f"expected unit {expected_unit!r}" if expected_unit else "no unit expected"
        return NotNumber(f"unit {unit!r} does not match: {wanted}")
    low = Decimal(match.group("low"))
    high = Decimal(match.group("high")) if match.group("high") is not None else low
    qualifier: Qualifier | None = "approximate" if match.group("approx") else None
    return NumberCell(min(low, high), max(low, high), qualifier, had_unit=unit is not None)
