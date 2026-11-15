"""FLEX (PSI-69): isolated fuel droplets burning in microgravity on the ISS.

Source quirks handled here, none repaired in the data:
- The file is cp1252. Several headers lost their subscripts: the "O" composition
  column is O2 and the "CO" column is CO2.
- The flame extinction diameter is often a lone en dash (no value), treated as null.
- Pressure 0 mmHg (test 114) is not a physical reading and becomes unknown.
- Flow velocity is not recorded in this table.
"""

from decimal import Decimal

from pipeline.runs.cells import NotNumber, NullCell, NumberCell, parse_cell
from pipeline.runs.common import (
    Context,
    Normalizer,
    constant,
    outcome_from_cell,
    unknown_reason,
)
from pipeline.runs.tables import Row, Table, TableError, collapse
from pipeline.runs.units import MMHG_SOURCE, fraction_to_percent, to_kpa
from pipeline.runs.values import (
    Category,
    Conditions,
    Outcome,
    Quantity,
    Record,
    parsed_category,
    parsed_quantity,
    unknown_category,
    unknown_quantity,
)

FUEL = "Fuel"
PRESSURE = "Ambient pressure; mmHg"
O2 = "O initial ambient composition; mole fraction"
DILUENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("N initial ambient composition; mole fraction", "N2"),
    ("CO initial ambient composition; mole fraction", "CO2"),
    ("He initial ambient composition; mole fraction", "He"),
)
EXTINCTION_DIAMETER = "Visible flame extinction diameter; mm"
BURNING_RATE = "Burning rate; mm"
BURN_TIME = "Burn time; s"
TEST_END = "Test end"

FUEL_CLASS = constant("droplet", "FLEX burns isolated fuel droplets")
GEOMETRY = constant("droplet", "FLEX burns isolated fuel droplets")


def _pressure(text: str, column: str) -> Quantity:
    result = parse_cell(text, None)
    if isinstance(result, NullCell):
        return unknown_quantity("kPa", unknown_reason(text), (column,))
    if isinstance(result, NotNumber):
        return unknown_quantity("kPa", f'source text "{collapse(text)}" is not a number: {result.reason}', (column,))
    if result.minimum <= 0:
        note = f'source reads "{collapse(text)}" mmHg, which is not a valid pressure reading'
        return unknown_quantity("kPa", note, (column,))
    low, high = (float(to_kpa(value, "mmHg")) for value in (result.minimum, result.maximum))
    return parsed_quantity(low, high, "kPa", result.qualifier, (column,), f"converted from mmHg; {MMHG_SOURCE}")


def _o2(text: str, column: str) -> Quantity:
    result = parse_cell(text, None)
    if isinstance(result, NullCell):
        return unknown_quantity("percent", unknown_reason(text), (column,))
    if isinstance(result, NotNumber):
        return unknown_quantity(
            "percent", f'source text "{collapse(text)}" is not a number: {result.reason}', (column,)
        )
    if result.maximum > 1:
        return unknown_quantity("percent", f'mole fraction "{collapse(text)}" exceeds 1', (column,))
    low, high = (float(fraction_to_percent(value)) for value in (result.minimum, result.maximum))
    return parsed_quantity(low, high, "percent", result.qualifier, (column,), "mole fraction x 100")


def _diluent(row: Row) -> Category:
    columns = tuple(column for column, _ in DILUENT_COLUMNS)
    present: list[str] = []
    for column, species in DILUENT_COLUMNS:
        result = parse_cell(row.cells[column], None)
        if not isinstance(result, NumberCell):
            return unknown_category(f'cannot read "{column}": {collapse(row.cells[column])!r}', columns)
        if result.maximum > Decimal(0):
            present.append(species)
    if not present:
        return unknown_category("no diluent species has a nonzero mole fraction", columns)
    note = 'species with nonzero mole fraction; the "CO" column is CO2 (subscript lost in source)'
    return parsed_category("+".join(present), columns, note)


def _outcomes(row: Row) -> tuple[Outcome, ...]:
    candidates = (
        outcome_from_cell(
            row.cells[EXTINCTION_DIAMETER], EXTINCTION_DIAMETER, "extinction_diameter", "microgravity", "mm"
        ),
        Outcome("burning_rate", "microgravity", unknown_quantity(
            "unknown", "Source header 'Burning rate; mm' does not establish a rate unit; original cell retained",
            (BURNING_RATE,),
        )),
        outcome_from_cell(row.cells[BURN_TIME], BURN_TIME, "burn_time", "microgravity", "s"),
    )
    outcomes = [outcome for outcome in candidates if outcome is not None]
    if collapse(row.cells[TEST_END]):
        outcomes.append(
            Outcome("test_end", "microgravity", parsed_category(collapse(row.cells[TEST_END]), (TEST_END,)))
        )
    return tuple(outcomes)


def normalize(context: Context) -> list[Record]:
    table = context.table
    expected = (FUEL, PRESSURE, O2, EXTINCTION_DIAMETER, BURNING_RATE, BURN_TIME, TEST_END)
    missing = [column for column in (*expected, *(c for c, _ in DILUENT_COLUMNS)) if column not in table.columns]
    if missing:
        raise TableError(f"{table.filename}: FLEX normalizer expects exact header cells {missing}")
    materials = context.aliases["materials"]
    records: list[Record] = []
    for row in table.rows:
        conditions = Conditions(
            fuel_class=FUEL_CLASS,
            material=materials.resolve(row.cells[FUEL], (FUEL,)),
            geometry=GEOMETRY,
            o2_percent=_o2(row.cells[O2], O2),
            pressure_kpa=_pressure(row.cells[PRESSURE], PRESSURE),
            flow_cm_s=unknown_quantity("cm/s", "flow is not recorded in this table"),
            flow_direction=unknown_category("flow is not recorded in this table"),
            diluent=_diluent(row),
        )
        records.append(Record(context.record_id(row), "run", row.number, dict(row.cells), conditions, _outcomes(row)))
    return records


def alias_sources(table: Table) -> dict[str, list[str]]:
    return {"materials": [row.cells[FUEL] for row in table.rows]}


NORMALIZER = Normalizer(normalize, alias_sources)
