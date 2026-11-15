"""Data-quality flags: every detection rule in one table (``RULES``), in the order they run.

A flag says that a source row has a problem. It never changes a value: invalid readings
are already unknown in the conditions, and suspected typos stay as written. Each rule has
a name, the flag code it raises, the tables it applies to (``None`` means every table) and
a one-line reason, so an auditor can read the whole policy here. Detectors only look at
the records of one table (their original cells), so a rule can be tested without files.

Rows that are notes are never inspected: they annotate other rows and carry no readings.
"""

import datetime
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from pipeline.runs.cells import NumberCell, parse_cell
from pipeline.runs.normalizers.bass_common import MAX_O2_SPAN
from pipeline.runs.tables import collapse
from pipeline.runs.values import Flag, FlagCode, Record

Detector = Callable[[Sequence[Record]], Iterator[tuple[str, Flag]]]
"""Yields (record id, flag) pairs for the records of one table."""

_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_JOINING_WORDS = re.compile(r"\b(?:to|and)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Rule:
    name: str
    code: FlagCode
    tables: frozenset[str] | None
    why: str
    detect: Detector


def _tests(records: Sequence[Record]) -> Iterator[Record]:
    return (record for record in records if record.kind != "note")


def _each(check: Callable[[Record], Iterable[Flag]]) -> Detector:
    """A detector that looks at one record at a time."""

    def detect(records: Sequence[Record]) -> Iterator[tuple[str, Flag]]:
        for record in _tests(records):
            for flag in check(record):
                yield record.id, flag

    return detect


def _find(record: Record, *names: str) -> str | None:
    """The exact header whose collapsed text equals one of ``names``."""
    wanted = {collapse(name) for name in names}
    return next((column for column in record.original if collapse(column) in wanted), None)


def _cell(record: Record, *names: str) -> tuple[str, str] | None:
    column = _find(record, *names)
    return None if column is None else (column, record.original[column])


def _number(text: str) -> Decimal | None:
    result = parse_cell(text, None)
    return result.minimum if isinstance(result, NumberCell) and result.minimum == result.maximum else None


# --- every table -------------------------------------------------------------------------------

_O2_HEADER = re.compile(r"(?<![a-z0-9])x?o2?(?![a-z0-9])|oxygen")


def _o2_out_of_range(record: Record) -> Iterator[Flag]:
    for column, text in record.original.items():
        header = collapse(column).lower()
        if not _O2_HEADER.search(header) or "flow" in header:  # "O2 flow rate (mg/s)" is not a concentration
            continue
        fraction = "mole fraction" in header or header.startswith("x")
        limit, unit = (Decimal(1), "mole fraction") if fraction else (Decimal(100), "percent")
        if re.search(r"[A-Za-z]", _JOINING_WORDS.sub("", text)):
            continue  # words such as "LOW O2" hold no reading; digits inside them are not values
        for token in _NUMBER.findall(text):
            if Decimal(token) > limit:
                yield Flag(
                    "invalid_reading",
                    (column,),
                    f'cell "{collapse(text)}": {token} is above the maximum possible {unit} of {limit} for oxygen',
                )
                break


def _duplicates(records: Sequence[Record]) -> Iterator[tuple[str, Flag]]:
    seen: dict[tuple[str, ...], Record] = {}
    for record in _tests(records):
        key = tuple(record.original.values())
        earlier = seen.setdefault(key, record)
        if earlier is not record:
            detail = f"every cell equals row {earlier.row} ({earlier.id})"
            yield record.id, Flag("duplicate_row", tuple(record.original), detail)


_SAME_AS = re.compile(r"same conditions as", re.IGNORECASE)


def _same_conditions(record: Record) -> Iterator[Flag]:
    for column, text in record.original.items():
        if _SAME_AS.search(text):
            yield Flag("references_other_rows", (column,), f'cell "{collapse(text)}" defers to other rows')


# --- FLEX --------------------------------------------------------------------------------------

_FLEX_PRESSURE = "Ambient pressure; mmHg"
_FLEX_FRACTIONS = (
    "O initial ambient composition; mole fraction",
    "N initial ambient composition; mole fraction",
    "CO initial ambient composition; mole fraction",
    "He initial ambient composition; mole fraction",
)
FLEX_SUM_TOLERANCE = Decimal("0.005")


def _flex_pressure(record: Record) -> Iterator[Flag]:
    found = _cell(record, _FLEX_PRESSURE)
    if found is None:
        return
    column, text = found
    value = _number(text)
    if value is not None and value <= 0:
        yield Flag("invalid_reading", (column,), f'cell "{collapse(text)}": a pressure of {value} mmHg is not possible')


def _flex_composition(record: Record) -> Iterator[Flag]:
    cells = [_cell(record, name) for name in _FLEX_FRACTIONS]
    if any(cell is None for cell in cells):
        return
    pairs = [(column, text) for column, text in (cell for cell in cells if cell is not None)]
    values = [_number(text) for _, text in pairs]
    if any(value is None for value in values):
        return
    total = sum((value for value in values if value is not None), Decimal(0))
    if abs(total - 1) > FLEX_SUM_TOLERANCE:
        quoted = ", ".join(f'"{column}" = {collapse(text)}' for column, text in pairs)
        yield Flag(
            "inconsistent_values",
            tuple(column for column, _ in pairs),
            f"mole fractions sum to {total}, not 1 within {FLEX_SUM_TOLERANCE}: {quoted}",
        )


# --- Saffire -----------------------------------------------------------------------------------

_NOTE_REFERENCE = re.compile(r"note\s+(\d+)", re.IGNORECASE)
_LEADING_ZERO = re.compile(r"^0\d")
_CAMERA = re.compile(r"^S(\d+)C(\d)$", re.IGNORECASE)


def _note_targets(records: Sequence[Record]) -> dict[str, Record]:
    targets: dict[str, Record] = {}
    for record in records:
        if record.kind != "note" or not record.original:
            continue
        match = re.match(r"note\s+(\d+)\b", collapse(next(iter(record.original.values()))), re.IGNORECASE)
        if match:
            targets.setdefault(match.group(1), record)
    return targets


def _saffire_note_references(records: Sequence[Record]) -> Iterator[tuple[str, Flag]]:
    targets = _note_targets(records)

    def where(number: str) -> str:
        target = targets.get(number)
        return f"Note {number} ({target.id})" if target else f"Note {number} (no such note row)"

    for record in _tests(records):
        for column, text in record.original.items():
            for source, label in ((column, "column header"), (text, "cell")):
                for match in _NOTE_REFERENCE.finditer(source):
                    detail = f'{label} "{collapse(source)}" cites {where(match.group(1))}'
                    yield record.id, Flag("references_other_rows", (column,), detail)


def _saffire_thickness(record: Record) -> Iterator[Flag]:
    for column, text in record.original.items():
        is_thickness = "thickness" in column.lower() or "samle" in column.lower()  # source typo "Samle Thickness"
        if is_thickness and _LEADING_ZERO.match(collapse(text)):
            detail = f'cell "{collapse(text)}" has a leading zero and no decimal point; possibly 0.{collapse(text)[1:]}'
            yield Flag("suspected_typo", (column,), detail)


def _saffire_cameras(record: Record) -> Iterator[Flag]:
    first = collapse(next(iter(record.original.values()), ""))
    sample = re.search(r"(\d+)$", first)
    if sample is None:
        return
    for column, text in record.original.items():
        number = re.fullmatch(r"camera\s+(\d)", collapse(column).lower())
        if number is None or not collapse(text) or collapse(text).lower() == "n/a":
            continue
        match = _CAMERA.match(collapse(text))
        expected = f"S{sample.group(1)}C{number.group(1)}"
        if match is None or collapse(text).upper() != expected:
            detail = f'cell "{collapse(text)}" does not read {expected} for sample "{first}"'
            yield Flag("suspected_typo", (column,), detail)


# --- BASS-II -----------------------------------------------------------------------------------

_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_FAN_RUN_TOGETHER = re.compile(r"^\d{4,}$")


def _bass_ii_o2_span(record: Record) -> Iterator[Flag]:
    initial, final = _cell(record, "Calibrated initial O2 % by vol"), _cell(record, "Calibrated final O2 % by vol")
    if initial is None or final is None:
        return
    start, end = _number(initial[1]), _number(final[1])
    if start is not None and end is not None and abs(start - end) > MAX_O2_SPAN:
        detail = (
            f'initial "{collapse(initial[1])}" and final "{collapse(final[1])}" O2 differ by more than '
            f"{MAX_O2_SPAN} points; the oxygen condition is left unknown"
        )
        yield Flag("inconsistent_values", (initial[0], final[0]), detail)


def _bass_ii_date_gmt(record: Record) -> Iterator[Flag]:
    date, gmt = _cell(record, "Date"), _cell(record, "GMT")
    if date is None or gmt is None:
        return
    match = _DATE.match(collapse(date[1]))
    if match is None or not collapse(gmt[1]).isdigit():
        return
    month, day, year = (int(part) for part in match.groups())
    try:
        day_of_year = datetime.date(year, month, day).timetuple().tm_yday
    except ValueError:
        return
    if day_of_year != int(collapse(gmt[1])):
        detail = f'date "{collapse(date[1])}" is day {day_of_year} of the year but GMT reads "{collapse(gmt[1])}"'
        yield Flag("inconsistent_values", (date[0], gmt[0]), detail)


def _bass_ii_fan_display(record: Record) -> Iterator[Flag]:
    found = _cell(record, "Fan display")
    if found is not None and _FAN_RUN_TOGETHER.match(collapse(found[1])):
        detail = f'cell "{collapse(found[1])}" is one long number; probably two readings run together'
        yield Flag("suspected_typo", (found[0],), detail)


BASS_II_DOCUMENTED_YEARS = frozenset({"2014", "2016"})
"""BASS-II flew in 2014. The Olson sheet of PSI-25_Science Documents_BASS-II_Test.Matrices.xlsx
states 'GMT 2014- (except last 3 tests from 2016)', so 2016 dates are documented, not typos."""


def _bass_ii_year(records: Sequence[Record]) -> Iterator[tuple[str, Flag]]:
    documented = ", ".join(sorted(BASS_II_DOCUMENTED_YEARS))
    for record in _tests(records):
        found = _cell(record, "Date")
        match = _DATE.match(collapse(found[1])) if found else None
        if found and match and match.group(3) not in BASS_II_DOCUMENTED_YEARS:
            detail = f'date "{collapse(found[1])}" is in {match.group(3)}; BASS-II tests are documented in {documented}'
            yield record.id, Flag("suspected_typo", (found[0],), detail)


_SAFFIRE = frozenset({"saffire-1", "saffire-2", "saffire-3"})
_BASS_II = frozenset({"bass-ii"})
_FLEX = frozenset({"flex"})

RULES: tuple[Rule, ...] = (
    Rule(
        "o2_out_of_range",
        "invalid_reading",
        None,
        "oxygen above 100 percent or a mole fraction above 1",
        _each(_o2_out_of_range),
    ),
    Rule(
        "flex_pressure", "invalid_reading", _FLEX, "a pressure of zero or less is not a reading", _each(_flex_pressure)
    ),
    Rule("duplicate_rows", "duplicate_row", None, "every cell equals an earlier row of the table", _duplicates),
    Rule(
        "same_conditions",
        "references_other_rows",
        None,
        "'same conditions as 1-4' defers to other rows",
        _each(_same_conditions),
    ),
    Rule(
        "saffire_notes",
        "references_other_rows",
        _SAFFIRE,
        "a run cites Note n, a note row of the table",
        _saffire_note_references,
    ),
    Rule(
        "bass_ii_o2_span",
        "inconsistent_values",
        _BASS_II,
        "initial and final O2 differ by more than 10 points",
        _each(_bass_ii_o2_span),
    ),
    Rule(
        "bass_ii_date_gmt",
        "inconsistent_values",
        _BASS_II,
        "the date and the GMT day of the year disagree",
        _each(_bass_ii_date_gmt),
    ),
    Rule(
        "flex_composition",
        "inconsistent_values",
        _FLEX,
        "O2+N2+CO2+He mole fractions do not sum to 1",
        _each(_flex_composition),
    ),
    Rule(
        "saffire_thickness",
        "suspected_typo",
        _SAFFIRE,
        "thickness with a leading zero and no decimal point",
        _each(_saffire_thickness),
    ),
    Rule(
        "saffire_cameras",
        "suspected_typo",
        _SAFFIRE,
        "a camera id that does not match the sample and column",
        _each(_saffire_cameras),
    ),
    Rule(
        "bass_ii_fan_display",
        "suspected_typo",
        _BASS_II,
        "a fan display that is one very long number",
        _each(_bass_ii_fan_display),
    ),
    Rule(
        "bass_ii_year", "suspected_typo", _BASS_II, "a date in a year other than the table's usual year", _bass_ii_year
    ),
)


def add_flags(slug: str, records: list[Record]) -> list[Record]:
    """The records with the flags of every rule that applies to the table ``slug``."""
    found: dict[str, list[Flag]] = {}
    for rule in RULES:
        if rule.tables is not None and slug not in rule.tables:
            continue
        for record_id, flag in rule.detect(records):
            if flag.code != rule.code:
                raise ValueError(f"rule {rule.name} raised a {flag.code} flag but declares {rule.code}")
            found.setdefault(record_id, []).append(flag)
    return [replace(record, flags=tuple(found.get(record.id, ()))) for record in records]
