"""Shared pieces of the BASS and BASS-II normalizers: flow conversion, O2, alias proposals.

Fan calibration. The ISS flow was set by a fan whose "Air display" reading maps to a
velocity by the footnote of the PSI-25 workbook "Fan calibration data.xlsx":
"*U =1.0066(AIR)", based on SPICE fan calibration at 56 mm downstream, 36 mm from the
bottom (centerline). So velocity in cm/s = 1.0066 x Air display, and Air display 0 is
fan off (velocity 0 is a valid reading).

What is parsed deterministically. An Air display cell is converted only when it is a
pure numeric list: numbers separated by commas, ">", ";" or whitespace ("20,10,5,2,1",
"5  3  2"). A sweep is recorded as min/max of the readings; the order and timing are
not kept. Any other text ("5 down to ext", "10 max", "<1", "2 (pot .9)", "etc") is not
interpreted: flow stays unknown and the cell goes to a reviewed extraction queue.

What is not done, on purpose. The optional fallback that interpolates Air display from a
Fan display value was not implemented: the calibration workbook holds blocks for 2014
dates only (BASS flew in 2012-2013) and every BASS-II row has an Air display cell, so
the fallback would never fire on the real data; its blocks are laid out as side-by-side
date columns with ad hoc restrictor headings, which cannot be read without guessing.

O2 range. BASS-II records a calibrated initial and final O2 (% by vol); the run covers
the interval, so o2_percent is the min/max of both. A "none" cell leaves that end
unknown. Five rows have a final value that cannot be the same atmosphere (1.6, 0.6,
39.1, 0.9, 40.4 against an initial of about 20); a pair spanning more than
``MAX_O2_SPAN`` percentage points is not trusted and the value is left unknown, with
both cells quoted in the note. The cells themselves are never changed.

Geometry vocabulary. ``GEOMETRY_VOCABULARY`` is closed: rod (cylinder), film (thin
sheet, thickness in micrometres or the word "film"), slab (thicker flat PMMA or wax,
millimetres), sphere, spherical section (a cut sphere), fabric sheet (SIBAL, Nomex),
sheet (rigid flat sheet, Ultem) and candle. Alias proposals below are suggestions for
review (proposed_by "llm", pending); several rest on the sample family rather than the
words of the cell and are marked in ``INFERRED_PROPOSALS``.
"""

import re
from decimal import Decimal

from pipeline.runs.cells import NotNumber, NullCell, NumberCell, parse_cell
from pipeline.runs.common import constant
from pipeline.runs.tables import collapse
from pipeline.runs.units import round_clean
from pipeline.runs.values import (
    Quantity,
    parsed_quantity,
    unknown_quantity,
)

FUEL_CLASS = constant("solid", "BASS and BASS-II burn solid fuel samples")

AIR_DISPLAY_TO_CM_S = Decimal("1.0066")
CALIBRATION_NOTE = (
    "velocity = 1.0066 x air display, from the footnote '*U =1.0066(AIR)' of the PSI-25 workbook "
    "'Fan calibration data.xlsx' (SPICE fan calibration at 56 mm downstream, 36 mm from bottom, centerline)"
)
SWEEP_NOTE = "a sweep is recorded as the min and max of its readings"
FREE_TEXT_NOTE = "free text; queued for reviewed extraction"

MAX_O2_SPAN = Decimal(10)
"""Percentage points; larger initial-to-final gaps are treated as transcription errors."""

_NUMBER = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)$")
_LIST_SEPARATORS = re.compile(r"[,>;\s]+")


def numeric_list(text: str) -> list[Decimal] | None:
    """The numbers of a pure numeric list, or None when the cell holds anything else."""
    tokens = [token for token in _LIST_SEPARATORS.split(text) if token]
    if not tokens or not all(_NUMBER.match(token) for token in tokens):
        return None
    return [Decimal(token) for token in tokens]


def is_blank_cell(text: str) -> bool:
    return isinstance(parse_cell(text), NullCell)


def is_free_text(text: str) -> bool:
    """A non-blank cell that is not a pure numeric list."""
    return not is_blank_cell(text) and numeric_list(text) is None


def air_display_to_cm_s(reading: Decimal) -> float:
    return float(round_clean(reading * AIR_DISPLAY_TO_CM_S))


def flow_from_air_display(text: str, column: str) -> Quantity:
    """Flow from one Air display cell: parsed when numeric, otherwise unknown with the reason."""
    columns = (column,)
    readings = numeric_list(text)
    if readings is None:
        if is_blank_cell(text):
            blank = "blank in source" if not collapse(text) else f'source cell reads "{collapse(text)}"'
            return unknown_quantity("cm/s", blank, columns)
        return unknown_quantity("cm/s", FREE_TEXT_NOTE, columns)
    note = f"{CALIBRATION_NOTE}; {SWEEP_NOTE}"
    return parsed_quantity(
        air_display_to_cm_s(min(readings)), air_display_to_cm_s(max(readings)), "cm/s", None, columns, note
    )


def percent_from_fraction(value: float, column: str, origin: str) -> Quantity:
    """O2 percent from a mole fraction cell of the as-run matrix (fraction x 100)."""
    fraction = Decimal(repr(value))
    if not Decimal(0) < fraction <= Decimal(1):
        return unknown_quantity("percent", f"{origin}: O2 fraction {value!r} is outside (0, 1]", (column,))
    percent = float(round_clean(fraction * 100))
    note = f"{origin}; fraction x 100"
    return parsed_quantity(percent, percent, "percent", None, (column,), note)


def o2_initial_final(initial: str, final: str, initial_column: str, final_column: str) -> Quantity:
    """Min/max of the calibrated initial and final O2 cells of BASS-II, with the reason when unknown."""
    columns = (initial_column, final_column)
    ends: list[Decimal] = []
    qualifier = None
    missing: list[str] = []
    for label, text in (("initial", initial), ("final", final)):
        result = parse_cell(text, None)
        if isinstance(result, NotNumber):
            note = f'{label} O2 cell "{collapse(text)}" is not a number: {result.reason}'
            return unknown_quantity("percent", note, columns)
        if isinstance(result, NullCell):
            missing.append(label)
            continue
        assert isinstance(result, NumberCell)
        ends.extend((result.minimum, result.maximum))
        qualifier = result.qualifier or qualifier
    if not ends:
        return unknown_quantity("percent", "initial and final O2 are blank or none in source", columns)
    if max(ends) - min(ends) > MAX_O2_SPAN:
        note = (
            f'initial "{collapse(initial)}" and final "{collapse(final)}" O2 differ by more than '
            f"{MAX_O2_SPAN} points; probable transcription error, not used"
        )
        return unknown_quantity("percent", note, columns)
    note = "initial to final during the test"
    if missing:
        recorded = "final" if missing == ["initial"] else "initial"
        note = f"only the {recorded} O2 is recorded ({missing[0]} is blank or none)"
    return parsed_quantity(float(min(ends)), float(max(ends)), "percent", qualifier, columns, note)


GEOMETRY_VOCABULARY = frozenset(
    {"rod", "film", "slab", "sphere", "spherical section", "fabric sheet", "sheet", "candle"}
)

_SIBAL = "cotton-fiberglass fabric (sibal)"

_MATERIAL_GROUPS: dict[str, tuple[str, ...]] = {
    "pmma": (
        # BASS
        "1 cm sphere",
        "1 cm sphere wake",
        "1 cm wake sphere",
        "2 cm pmma sphere",
        "2 cm sphere",
        "2 cm sphere wake ign",
        "PMMA 1 cm",
        "PMMA 2 cm",
        "PMMA slab",
        "PMMA sphere 1 cm",
        "PMMA sphere 2 cm",
        "pmma 1 cm",
        "pmma 2 cm",
        "pmma slab",
        "pmma slab opposed",
        "pmma slab oppsed",
        "pmma sphere",
        # BASS-II films, slabs and clear rods
        "1 cm 0.2 mm PMMA film",
        "1 cm wide 200 micron thick PMMA",
        "1 cm wide PMMA 1 mm thick",
        "1 cm wide PMMA 2 mm thick",
        "1 cm wide PMMA 3 mm thick",
        "1 cm wide PMMA 5 mm thick",
        "1 mm thick PMMA 1 sided 2 cm",
        "1 mm thick PMMA 2 cm wide",
        '1/2" clear PMMA rod',
        '1/2" clear rod',
        "1/4 clear rod",
        '1/4" clear rod',
        "100 micron PMMA film 2 cm wide",
        "100 micron film 2 cm wide",
        "2 cm 0.1 mm PMMA film",
        "2 cm 0.2 mm PMMA film",
        "2 cm 0.4 mm thick film",
        "2 cm 100 micron thick PMMA",
        "2 cm 4 mm 1 sided PMMA slab",
        "2 cm wide 5 mm thick 1 sided PMMA",
        "2 cm wide PMMA 2 mm thick",
        "2 cm wide PMMA 3 mm thick",
        "2 mm thick PMMA 2 cm wide",
        "200 micron 2 cm wide",
        "200 micron PMMA film 2 cm wide",
        "2mm thick PMMA 1 sided 2 cm wide",
        "3 mm thick PMMA 1 sided 2 cm wide",
        "3 mm thick PMMA 2 sided 2 cm thick",
        '3/8" clear rod',
        '3/8"clear rod',
        "300 micron PMMA film 2 cm wide",
        "300 micron film 2 cm wide",
        "4 mm thick 1 cm wide PMMA slab",
        "4 mm thick 2 cm 2ide PMMA slab",
        "4 mm thick PMMA 2 cm wide",
        "400 micron film 2 cm wide",
        "5 mm thick PMMA 2 cm wide",
    ),
    "pmma (black)": (
        '0.5" black rod',
        "1/4 blac rod",
        "1/4 black rod",
        '1/4" black rod',
        '3/8" black rod',
    ),
    _SIBAL: (
        "SIBAL 1 cm",
        "SIBAL 2 cm",
        "SIBAL 2 cm opposed flow",
        "1 cm SIBAL",
        "1 cm SIBAL top side ign",
        "2 cm SIBAL",
        "2 cm Sibal moved igniter",
    ),
    "nomex": ("Nomex III Natural", "nomex natural III", "Nomex natural (nomex III)"),
    "nomex blend": ("Nomex blend 2 cm",),
    "japan wax": ("Japan Wax Candle wake", "candle Japan wax", "Japan Wax candle"),
    "paraffin wax": (
        "candle paraffin wake",
        "paraffin wax candle",
        "parrafin wax candle",
        "paraffin wax slab",
        "parrafin wax slab",
    ),
    "ultem": ("ultem sheet",),
}

_GEOMETRY_GROUPS: dict[str, tuple[str, ...]] = {
    "sphere": (
        "1 cm sphere",
        "1 cm sphere wake",
        "1 cm wake sphere",
        "2 cm pmma sphere",
        "2 cm sphere",
        "2 cm sphere wake ign",
        "PMMA sphere 1 cm",
        "PMMA sphere 2 cm",
        "pmma sphere",
    ),
    "slab": (
        "PMMA slab",
        "pmma slab",
        "pmma slab opposed",
        "pmma slab oppsed",
        "flat wax slab",
        "paraffin wax slab",
        "parrafin wax slab",
        "1 cm wide PMMA 1 mm thick",
        "1 cm wide PMMA 2 mm thick",
        "1 cm wide PMMA 3 mm thick",
        "1 cm wide PMMA 5 mm thick",
        "1 mm thick PMMA 1 sided 2 cm",
        "1 mm thick PMMA 2 cm wide",
        "2 cm 4 mm 1 sided PMMA slab",
        "2 cm wide 5 mm thick 1 sided PMMA",
        "2 cm wide PMMA 2 mm thick",
        "2 cm wide PMMA 3 mm thick",
        "2 mm thick PMMA 2 cm wide",
        "2mm thick PMMA 1 sided 2 cm wide",
        "3 mm thick PMMA 1 sided 2 cm wide",
        "3 mm thick PMMA 2 sided 2 cm thick",
        "4 mm thick 1 cm wide PMMA slab",
        "4 mm thick 2 cm 2ide PMMA slab",
        "4 mm thick PMMA 2 cm wide",
        "5 mm thick PMMA 2 cm wide",
    ),
    "candle": (
        "Japan Wax Candle wake",
        "candle",
        "candle Japan wax",
        "candle paraffin wake",
        "paraffin wax candle",
        "parrafin wax candle",
        "Japan Wax candle",
    ),
    "fabric sheet": (
        "Nomex III Natural",
        "Nomex blend 2 cm",
        "nomex natural III",
        "SIBAL 1 cm",
        "SIBAL 2 cm",
        "SIBAL 2 cm opposed flow",
        "1 cm SIBAL",
        "1 cm SIBAL top side ign",
        "2 cm SIBAL",
        "2 cm Sibal moved igniter",
        "Nomex natural (nomex III)",
    ),
    "sheet": ("ultem sheet",),
    "film": (
        "1 cm 0.2 mm PMMA film",
        "1 cm wide 200 micron thick PMMA",
        "100 micron PMMA film 2 cm wide",
        "100 micron film 2 cm wide",
        "2 cm 0.1 mm PMMA film",
        "2 cm 0.2 mm PMMA film",
        "2 cm 0.4 mm thick film",
        "2 cm 100 micron thick PMMA",
        "200 micron 2 cm wide",
        "200 micron PMMA film 2 cm wide",
        "300 micron PMMA film 2 cm wide",
        "300 micron film 2 cm wide",
        "400 micron film 2 cm wide",
    ),
    "rod": (
        '0.5" black rod',
        '1/2" clear PMMA rod',
        '1/2" clear rod',
        "1/4 blac rod",
        "1/4 black rod",
        "1/4 clear rod",
        '1/4" black rod',
        '1/4" clear rod',
        '3/8" black rod',
        '3/8" clear rod',
        '3/8"clear rod',
    ),
    "spherical section": ("4 cm spherical section",),
}


def _invert(groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    inverted: dict[str, str] = {}
    for canonical, sources in groups.items():
        for source in sources:
            if source in inverted:
                raise ValueError(f"{source!r} is proposed twice: {inverted[source]!r} and {canonical!r}")
            inverted[source] = canonical
    return inverted


MATERIAL_PROPOSALS: dict[str, str] = _invert(_MATERIAL_GROUPS)
GEOMETRY_PROPOSALS: dict[str, str] = _invert(_GEOMETRY_GROUPS)

INFERRED_PROPOSALS: tuple[str, ...] = (
    "1 cm sphere",
    "1 cm sphere wake",
    "1 cm wake sphere",
    "2 cm sphere",
    "2 cm sphere wake ign",
    "100 micron film 2 cm wide",
    "200 micron 2 cm wide",
    "2 cm 0.4 mm thick film",
    "300 micron film 2 cm wide",
    "400 micron film 2 cm wide",
    '1/2" clear rod',
    "1/4 clear rod",
    '1/4" clear rod',
    '3/8" clear rod',
    '3/8"clear rod',
    '0.5" black rod',
    "1/4 blac rod",
    "1/4 black rod",
    '1/4" black rod',
    '3/8" black rod',
)
"""Material proposals whose cell names no substance; the family (PMMA spheres, films, rods) is assumed."""
