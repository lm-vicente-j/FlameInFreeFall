"""Saffire-I, -II and -III (PSI-98, 99, 100): large flat solid samples burned on a free-flying vehicle.

One module serves all three tables because they share a layout. Columns are
found by their whitespace-collapsed header, since the sources carry stray
trailing spaces and a typo ("Samle Thickness") that are not repaired.

Source quirks handled here:
- Note rows ("Note 1 ...") and flow-visualization rows ("F1C1/F1C2") annotate
  other rows. They become kind "note" with every condition unknown.
- In Saffire-II the "?-g" columns are microgravity (the mu was lost in the
  source) and the "1-g" columns are normal-gravity ground comparisons.
- "?-g Spread Length" holds values in mm/s, so it is read as a spread rate.
- Thickness, length and width are not run conditions, and typos in them
  ("037 mm") are left in the original row only.
"""

import re
from dataclasses import dataclass

from pipeline.runs.common import (
    Context,
    Normalizer,
    all_unknown_conditions,
    constant,
    flow_direction,
    outcome_from_cell,
    quantity_from_cell,
)
from pipeline.runs.tables import Row, Table, collapse
from pipeline.runs.values import (
    Conditions,
    Gravity,
    Outcome,
    Record,
    unknown_category,
    unknown_quantity,
)

FUEL_CLASS = constant("solid", "Saffire burns solid fuel samples")
GEOMETRY = constant("sheet", "Saffire burns flat sheet and fabric samples")

_FLOW_VISUALIZATION = re.compile(r"^F\d+C\d+\s*/\s*F\d+C\d+$")
_MICRO = ("?", "µ", "μ")  # the lost mu appears as "?"; accept the real symbols too

_HEADER_UNIT = "unit taken from the column header"
_NEIGHBOUR_UNIT = "unit not stated in this cell or header; taken from the other cells of the column"
_SPREAD_NOTE = "header reads Spread Length but values carry mm/s; read as spread_rate"


@dataclass(frozen=True)
class OutcomeSpec:
    names: tuple[str, ...]
    outcome_type: str
    gravity: Gravity
    unit: str
    bare_unit_note: str
    extra_note: str | None = None


OUTCOME_SPECS: tuple[OutcomeSpec, ...] = (
    OutcomeSpec(("Burn Time (s)", "Burn Time"), "burn_time", "microgravity", "s", _HEADER_UNIT),
    OutcomeSpec(tuple(f"{m}-g Burn Length" for m in _MICRO), "burn_length", "microgravity", "cm", _NEIGHBOUR_UNIT),
    OutcomeSpec(
        tuple(f"{m}-g Spread Length" for m in _MICRO),
        "spread_rate",
        "microgravity",
        "mm/s",
        _NEIGHBOUR_UNIT,
        _SPREAD_NOTE,
    ),
    OutcomeSpec(("1-g Burn Length",), "burn_length", "normal", "cm", _NEIGHBOUR_UNIT),
    OutcomeSpec(("1-g Spread Rate",), "spread_rate", "normal", "mm/s", _NEIGHBOUR_UNIT),
)


def row_kind(first_cell: str) -> str | None:
    """'note' annotation, 'flow' visualization reference, or None for a run."""
    text = collapse(first_cell)
    if text.startswith("Note"):
        return "annotation row (note), not a run"
    if _FLOW_VISUALIZATION.match(text):
        return "pre-test flow visualization reference row, not a run"
    return None


def _run_conditions(row: Row, table: Table, context: Context) -> Conditions:
    material = table.require_column("Material")
    o2 = table.find_column("Percent O2 (Note 1)", "Percent O2")
    flow = table.find_column("Air Flow (cm/s)", "Air Flow")
    direction = table.find_column("Flow Direction", "Direction")
    return Conditions(
        fuel_class=FUEL_CLASS,
        material=context.aliases["materials"].resolve(row.cells[material], (material,)),
        geometry=GEOMETRY,
        o2_percent=(
            quantity_from_cell(row.cells[o2], o2, "percent", None)
            if o2
            else unknown_quantity("percent", "table has no oxygen column")
        ),
        pressure_kpa=unknown_quantity("kPa", "table has no pressure column"),
        flow_cm_s=(
            quantity_from_cell(row.cells[flow], flow, "cm/s", "cm/s", _HEADER_UNIT)
            if flow
            else unknown_quantity("cm/s", "table has no air flow column")
        ),
        flow_direction=flow_direction(row.cells[direction], direction)
        if direction
        else unknown_category("table has no flow direction column"),
        diluent=unknown_category("table has no diluent column"),
    )


def _outcomes(row: Row, table: Table) -> tuple[Outcome, ...]:
    outcomes: list[Outcome] = []
    for spec in OUTCOME_SPECS:
        column = table.find_column(*spec.names)
        if column is None:
            continue
        outcome = outcome_from_cell(
            row.cells[column], column, spec.outcome_type, spec.gravity, spec.unit, spec.bare_unit_note, spec.extra_note
        )
        if outcome is not None:
            outcomes.append(outcome)
    return tuple(outcomes)


def normalize(context: Context) -> list[Record]:
    table = context.table
    first = table.require_column("Sample Number")
    records: list[Record] = []
    for row in table.rows:
        note = row_kind(row.cells[first])
        if note is not None:
            records.append(
                Record(context.record_id(row), "note", row.number, dict(row.cells), all_unknown_conditions(note), ())
            )
            continue
        conditions = _run_conditions(row, table, context)
        records.append(
            Record(context.record_id(row), "run", row.number, dict(row.cells), conditions, _outcomes(row, table))
        )
    return records


def alias_sources(table: Table) -> dict[str, list[str]]:
    first = table.require_column("Sample Number")
    material = table.require_column("Material")
    return {"materials": [row.cells[material] for row in table.rows if row_kind(row.cells[first]) is None]}


NORMALIZER = Normalizer(normalize, alias_sources)
