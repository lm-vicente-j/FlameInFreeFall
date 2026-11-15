"""Exact unit conversions for run conditions.

Decimal arithmetic keeps the published factors exact. Results are rounded to six
decimals only to drop binary floating-point noise, which is far below the
precision of any source table.

Sources: 1 atm = 101.325 kPa (exact, 1954 CGPM definition); 1 mmHg =
0.133322387415 kPa and 1 psi = 6.894757293168 kPa (NIST SP 811, Appendix B.8);
1 bar = 100 kPa (exact, SI definition).
"""

from decimal import Decimal

_ROUNDING = Decimal("0.000001")

KPA_PER_UNIT: dict[str, Decimal] = {
    "kPa": Decimal(1),
    "atm": Decimal("101.325"),
    "mmHg": Decimal("0.133322387415"),
    "bar": Decimal(100),
    "psi": Decimal("6.894757293168"),
}

MMHG_SOURCE = "NIST SP 811 (1 mmHg = 0.133322387415 kPa)"


class UnknownUnitError(ValueError):
    """Raised for a pressure unit this module has no exact factor for."""


def round_clean(value: Decimal) -> Decimal:
    """Round to six decimals, only to remove floating-point noise."""
    return value.quantize(_ROUNDING)


def to_kpa(value: Decimal, unit: str) -> Decimal:
    try:
        factor = KPA_PER_UNIT[unit]
    except KeyError:
        raise UnknownUnitError(f"no exact conversion to kPa for unit {unit!r}") from None
    return round_clean(value * factor)


def fraction_to_percent(fraction: Decimal) -> Decimal:
    """Convert a mole (or volume) fraction to percent."""
    return round_clean(fraction * 100)
