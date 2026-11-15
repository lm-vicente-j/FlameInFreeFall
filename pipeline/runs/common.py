"""Building blocks shared by the table normalizers.

A normalizer turns one ``Table`` into ``Record`` objects. Anything it cannot
establish from the cells stays unknown with a note, and the original row text is
always kept.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.runs.aliases import AliasSet
from pipeline.runs.cells import NotNumber, NullCell, parse_cell
from pipeline.runs.tables import Row, Table, collapse
from pipeline.runs.values import (
    Category,
    Conditions,
    Gravity,
    Outcome,
    Quantity,
    Record,
    manual_category,
    parsed_category,
    parsed_quantity,
    unknown_category,
    unknown_quantity,
)

VERBATIM_NOTE = "not normalized; verbatim source text"


@dataclass(frozen=True)
class Context:
    accession: str
    slug: str
    table: Table
    aliases: AliasSet
    tables_dir: Path | None = None
    """Directory holding the experimental tables; BASS reads its as-run workbook from here."""
    extractions_dir: Path | None = None
    """Directory with reviewed extraction results (``<name>.json``); None means none are applied."""

    def record_id(self, row: Row) -> str:
        return f"{self.accession}:{self.slug}:{row.number}"


QueueItem = dict[str, str]
"""One free-text cell awaiting reviewed extraction: record_id, column, source_text."""


@dataclass(frozen=True)
class Normalizer:
    normalize: Callable[[Context], list[Record]]
    alias_sources: Callable[[Table], dict[str, list[str]]]
    """Source strings per alias dictionary name; used to find aliases still missing."""
    queues: Callable[[Context], dict[str, list[QueueItem]]] | None = None
    """Extraction queues per queue name; build writes them to ``<name>.queue.json``."""


def no_alias_sources(table: Table) -> dict[str, list[str]]:
    return {}


def unknown_reason(text: str) -> str:
    stripped = collapse(text)
    return "blank in source" if not stripped else f'source cell reads "{stripped}"; no value recorded'


def all_unknown_conditions(note: str) -> Conditions:
    return Conditions(
        fuel_class=unknown_category(note),
        material=unknown_category(note),
        geometry=unknown_category(note),
        o2_percent=unknown_quantity("percent", note),
        pressure_kpa=unknown_quantity("kPa", note),
        flow_cm_s=unknown_quantity("cm/s", note),
        flow_direction=unknown_category(note),
        diluent=unknown_category(note),
    )


def constant(value: str, basis: str) -> Category:
    return manual_category(value, f"Investigation-level constant: {basis}")


def flow_direction(text: str, column: str | None) -> Category:
    if column is None:
        return unknown_category("table has no flow direction column")
    key = collapse(text).lower()
    if key in ("concurrent", "opposed"):
        return parsed_category(key, (column,))
    if not key:
        return unknown_category("blank in source", (column,))
    return unknown_category(f'unrecognized flow direction "{collapse(text)}"', (column,))


def quantity_from_cell(
    text: str,
    column: str,
    unit: str,
    cell_unit: str | None,
    bare_unit_note: str | None = None,
) -> Quantity:
    """A condition quantity read directly from one cell, or unknown with the reason.

    ``cell_unit`` is the unit suffix the cell may carry; a bare number is accepted
    and gets ``bare_unit_note`` to say where its unit comes from.
    """
    result = parse_cell(text, cell_unit)
    if isinstance(result, NullCell):
        return unknown_quantity(unit, unknown_reason(text), (column,))
    if isinstance(result, NotNumber):
        return unknown_quantity(unit, f'source text "{collapse(text)}" is not a number: {result.reason}', (column,))
    note = bare_unit_note if not result.had_unit else None
    return parsed_quantity(float(result.minimum), float(result.maximum), unit, result.qualifier, (column,), note)


def outcome_from_cell(
    text: str,
    column: str,
    outcome_type: str,
    gravity: Gravity,
    unit: str,
    bare_unit_note: str | None = None,
    extra_note: str | None = None,
) -> Outcome | None:
    """An outcome from one cell: None when empty, a quantity when numeric, else verbatim text."""
    result = parse_cell(text, unit)
    if isinstance(result, NullCell):
        return None
    if isinstance(result, NotNumber):
        verbatim = "; ".join(part for part in (VERBATIM_NOTE, extra_note) if part)
        return Outcome(outcome_type, gravity, parsed_category(collapse(text), (column,), verbatim))
    parts = [] if result.had_unit or bare_unit_note is None else [bare_unit_note]
    if extra_note:
        parts.append(extra_note)
    note = "; ".join(parts) or None
    quantity = parsed_quantity(float(result.minimum), float(result.maximum), unit, result.qualifier, (column,), note)
    return Outcome(outcome_type, gravity, quantity)
