"""BASS (PSI-26) and BASS-II (PSI-25): small solid samples burned in a flow on the ISS.

BASS-II (``bass-ii``). The official table carries the material, the flow restrictor,
the fan and air displays and the calibrated initial and final O2. O2 is the min/max of
the two ends; pressure is not recorded in this table and stays unknown (cabin pressure
is not assumed); flow comes from the Air display cell (see ``bass_common``); material
and geometry go through the alias dictionaries, keyed by the material cell text.

BASS (``bass``). The official CSV has only identifiers and the material. Each row is
joined to the as-run matrix workbook (see ``bass_matrix``) for the flow displays, O2
fraction (x 100 = percent), pressure (atm x 101.325 = kPa) and the observations column.
A row without a unique match keeps those values unknown, with the reason in the note.
The "SOOT Cleaning" row has no run number and is a note, not a run.

Neither table records the flow direction per row, so it stays unknown. No outcome is
read from free text here: the observation texts and the free-text flow cells are
written to extraction queues, and reviewed results are applied by ``bass_extractions``.

Queues written by a build (``data/extractions/<name>.queue.json``, a list of
``{"record_id", "column", "source_text"}``):
- ``bass-observations``: the as-run observations of every joined run with text.
- ``bass-flow-text``: BASS Fan/Air display cells that are free text (not numeric lists).
- ``bass-ii-flow-text``: BASS-II Fan display and Air display cells that are free text.
"""

from decimal import Decimal

from pipeline.runs.common import Context, Normalizer, QueueItem, all_unknown_conditions
from pipeline.runs.normalizers.bass_common import (
    FUEL_CLASS,
    flow_from_air_display,
    is_free_text,
    o2_initial_final,
    percent_from_fraction,
)
from pipeline.runs.normalizers.bass_extractions import QueueCell, apply_extractions, queue_json
from pipeline.runs.normalizers.bass_matrix import (
    AIR_DISPLAY,
    FAN_DISPLAY,
    O2_FRACTION,
    OBSERVATIONS,
    PRESSURE_ATM,
    Join,
    Matrix,
    MatrixRow,
    cell_text,
    column_label,
    join_row,
    read_matrix,
)
from pipeline.runs.tables import Row, Table, collapse
from pipeline.runs.units import to_kpa
from pipeline.runs.values import (
    Conditions,
    Quantity,
    Record,
    parsed_quantity,
    unknown_category,
    unknown_quantity,
)

MATRIX_FILENAME = "PSI-26_Science Documents_As Run_Test Matrix.xlsx"

BASS_OBSERVATIONS = "bass-observations"
BASS_FLOW_TEXT = "bass-flow-text"
BASS_II_FLOW_TEXT = "bass-ii-flow-text"

_MATERIAL = "Fuel Sample Material"
_NOT_RECORDED = "not recorded in this table"


# --- BASS-II -----------------------------------------------------------------------------------


def _bass_ii_records(context: Context) -> tuple[list[Record], dict[str, list[QueueCell]]]:
    table = context.table
    material = table.require_column(_MATERIAL)
    fan = table.require_column(FAN_DISPLAY)
    air = table.require_column(AIR_DISPLAY)
    initial = table.require_column("Calibrated initial O2 % by vol")
    final = table.require_column("Calibrated final O2 % by vol")
    records: list[Record] = []
    queue: list[QueueCell] = []
    for row in table.rows:
        record_id = context.record_id(row)
        queue.extend(
            QueueCell(record_id, column, row.cells[column]) for column in (fan, air) if is_free_text(row.cells[column])
        )
        conditions = Conditions(
            fuel_class=FUEL_CLASS,
            material=context.aliases["materials"].resolve(row.cells[material], (material,)),
            geometry=context.aliases["geometries"].resolve(row.cells[material], (material,)),
            o2_percent=o2_initial_final(row.cells[initial], row.cells[final], initial, final),
            pressure_kpa=unknown_quantity("kPa", f"{_NOT_RECORDED}; cabin pressure is not assumed"),
            flow_cm_s=flow_from_air_display(row.cells[air], air),
            flow_direction=unknown_category(f"flow direction {_NOT_RECORDED}"),
            diluent=unknown_category(f"diluent {_NOT_RECORDED}"),
        )
        records.append(Record(record_id, "run", row.number, dict(row.cells), conditions, ()))
    return records, {BASS_II_FLOW_TEXT: queue}


def normalize_bass_ii(context: Context) -> list[Record]:
    records, queues = _bass_ii_records(context)
    return apply_extractions(records, context.extractions_dir, BASS_II_FLOW_TEXT, queues[BASS_II_FLOW_TEXT])


def queues_bass_ii(context: Context) -> dict[str, list[QueueItem]]:
    return {name: queue_json(cells) for name, cells in _bass_ii_records(context)[1].items()}


def alias_sources_bass_ii(table: Table) -> dict[str, list[str]]:
    texts = [row.cells[table.require_column(_MATERIAL)] for row in table.rows]
    return {"materials": texts, "geometries": texts}


# --- BASS --------------------------------------------------------------------------------------


def _load_matrix(context: Context) -> Matrix | None:
    if context.tables_dir is None:
        return None
    path = context.tables_dir / MATRIX_FILENAME
    return read_matrix(path) if path.exists() else None


def _is_soot_cleaning(row: Row, columns: tuple[str, str, str]) -> bool:
    return not any(collapse(row.cells[column]) for column in columns)


def _origin(source: MatrixRow, matrix: Matrix, header: str) -> tuple[str, str]:
    column = column_label(header)
    origin = f"as-run matrix row {source.sheet_row} of {matrix.filename} (As run test no. {source.run_number})"
    return column, origin


def _bass_o2(source: MatrixRow, matrix: Matrix) -> Quantity:
    column, origin = _origin(source, matrix, O2_FRACTION)
    value = source.cells[O2_FRACTION]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return unknown_quantity("percent", f"{origin}: O2 cell {cell_text(value)!r} is not a number", (column,))
    return percent_from_fraction(float(value), column, origin)


def _bass_pressure(source: MatrixRow, matrix: Matrix) -> Quantity:
    column, origin = _origin(source, matrix, PRESSURE_ATM)
    value = source.cells[PRESSURE_ATM]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return unknown_quantity("kPa", f"{origin}: pressure cell {cell_text(value)!r} is not a number", (column,))
    atm = Decimal(repr(float(value)))
    if atm <= 0:
        return unknown_quantity("kPa", f"{origin}: pressure {value!r} atm is not a physical reading", (column,))
    kpa = float(to_kpa(atm, "atm"))
    return parsed_quantity(kpa, kpa, "kPa", None, (column,), f"{origin}; atm x 101.325")


def _bass_flow(source: MatrixRow, matrix: Matrix) -> Quantity:
    column, origin = _origin(source, matrix, AIR_DISPLAY)
    flow = flow_from_air_display(source.text(AIR_DISPLAY), column)
    if flow.minimum is None:
        return flow
    note = f"{origin}; {flow.provenance.note}"
    return parsed_quantity(flow.minimum, flow.maximum or flow.minimum, "cm/s", None, (column,), note)


def _bass_conditions(context: Context, row: Row, join: Join, matrix: Matrix | None) -> Conditions:
    material = context.table.require_column(_MATERIAL)
    reason = f"no as-run matrix row joined: {join.reason}"
    source = join.row
    if source is None or matrix is None:
        o2 = unknown_quantity("percent", reason)
        pressure = unknown_quantity("kPa", reason)
        flow = unknown_quantity("cm/s", reason)
    else:
        o2, pressure, flow = _bass_o2(source, matrix), _bass_pressure(source, matrix), _bass_flow(source, matrix)
    return Conditions(
        fuel_class=FUEL_CLASS,
        material=context.aliases["materials"].resolve(row.cells[material], (material,)),
        geometry=context.aliases["geometries"].resolve(row.cells[material], (material,)),
        o2_percent=o2,
        pressure_kpa=pressure,
        flow_cm_s=flow,
        flow_direction=unknown_category(f"flow direction {_NOT_RECORDED}"),
        diluent=unknown_category(f"diluent {_NOT_RECORDED}"),
    )


def _bass_records(context: Context) -> tuple[list[Record], dict[str, list[QueueCell]]]:
    table = context.table
    run = table.require_column("As Run Test #")
    test = table.require_column("Test #")
    sample = table.require_column("Sample #")
    matrix = _load_matrix(context)
    queues: dict[str, list[QueueCell]] = {BASS_OBSERVATIONS: [], BASS_FLOW_TEXT: []}
    records: list[Record] = []
    for row in table.rows:
        record_id = context.record_id(row)
        if _is_soot_cleaning(row, (run, test, sample)):
            note = "table row without run, test or sample number; not a run"
            records.append(Record(record_id, "note", row.number, dict(row.cells), all_unknown_conditions(note), ()))
            continue
        join = join_row(row, matrix, run, test, sample)
        if join.row is not None:
            for header in (FAN_DISPLAY, AIR_DISPLAY):
                text = join.row.text(header)
                if is_free_text(text):
                    queues[BASS_FLOW_TEXT].append(QueueCell(record_id, column_label(header), text))
            observation = join.row.text(OBSERVATIONS)
            if collapse(observation):
                queues[BASS_OBSERVATIONS].append(QueueCell(record_id, column_label(OBSERVATIONS), observation))
        conditions = _bass_conditions(context, row, join, matrix)
        records.append(Record(record_id, "run", row.number, dict(row.cells), conditions, ()))
    return records, queues


def normalize_bass(context: Context) -> list[Record]:
    records, queues = _bass_records(context)
    for name in (BASS_OBSERVATIONS, BASS_FLOW_TEXT):
        records = apply_extractions(records, context.extractions_dir, name, queues[name])
    return records


def queues_bass(context: Context) -> dict[str, list[QueueItem]]:
    return {name: queue_json(cells) for name, cells in _bass_records(context)[1].items()}


def alias_sources_bass(table: Table) -> dict[str, list[str]]:
    run = table.require_column("As Run Test #")
    test = table.require_column("Test #")
    sample = table.require_column("Sample #")
    material = table.require_column(_MATERIAL)
    texts = [row.cells[material] for row in table.rows if not _is_soot_cleaning(row, (run, test, sample))]
    return {"materials": texts, "geometries": texts}


BASS_NORMALIZER = Normalizer(normalize_bass, alias_sources_bass, queues_bass)
BASS_II_NORMALIZER = Normalizer(normalize_bass_ii, alias_sources_bass_ii, queues_bass_ii)
