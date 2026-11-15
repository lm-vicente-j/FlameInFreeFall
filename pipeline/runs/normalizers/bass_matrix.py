"""The BASS as-run test matrix workbook and its join to the BASS experimental table.

The workbook "PSI-26_Science Documents_As Run_Test Matrix.xlsx", sheet "as run matrix",
holds what the official BASS CSV lacks: flow settings, O2, pressure and the operators'
observations. Its header is on the third row. The key is "As run test no.", but the
sheet reuses numbers (24, 85, 89, 90 and 91 each appear twice, and 89-91 belong to two
different days) and stores some numbers as text ("72"). A CSV row therefore joins only
when the number matches and, among several candidates, the "Test #" and "Sample #" text
also matches; with one candidate they must match as well, so a wrong row is never joined
silently. Unmatched rows keep their values unknown with the reason.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

from pipeline.runs.tables import Row, TableError, collapse

SHEET = "as run matrix"
HEADER_SEARCH_ROWS = 10
RUN_NUMBER = "As run test no."
TEST_NUMBER = "Test no."
SAMPLE_NUMBER = "Sample no."
FAN_DISPLAY = "Fan display"
AIR_DISPLAY = "Air display"
O2_FRACTION = "O2 % by volume"
PRESSURE_ATM = "pressure, atm"
OBSERVATIONS = "Test Observations and Anomalies (ignited, spread, extinguished, burn time, color, etc.)"
REQUIRED = (RUN_NUMBER, TEST_NUMBER, SAMPLE_NUMBER, FAN_DISPLAY, AIR_DISPLAY, O2_FRACTION, PRESSURE_ATM, OBSERVATIONS)


class MatrixError(TableError):
    """The as-run workbook is not in the expected layout."""


def cell_text(value: Any) -> str:
    """A cell as the text a reader sees: integers without ".0", empty for no value."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def column_label(header: str) -> str:
    """Name used in provenance for a column of the as-run sheet."""
    return f"{SHEET}!{collapse(header)}"


@dataclass(frozen=True)
class MatrixRow:
    sheet_row: int
    run_number: int
    test_number: str
    sample_number: str
    cells: dict[str, Any]
    """Raw cell values keyed by collapsed header."""

    def text(self, header: str) -> str:
        return cell_text(self.cells[header])


@dataclass(frozen=True)
class Matrix:
    filename: str
    rows: tuple[MatrixRow, ...]

    def candidates(self, run_number: int) -> list[MatrixRow]:
        return [row for row in self.rows if row.run_number == run_number]


def _run_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def read_matrix(path: Path) -> Matrix:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET not in workbook.sheetnames:
            raise MatrixError(f"{path.name}: no sheet {SHEET!r}; sheets are {workbook.sheetnames}")
        grid = list(workbook[SHEET].iter_rows(values_only=True))
    finally:
        workbook.close()
    for header_index, cells in enumerate(grid[:HEADER_SEARCH_ROWS]):  # noqa: B007 - used after the loop
        headers = [collapse(cell_text(cell)) for cell in cells]
        if RUN_NUMBER in headers:
            break
    else:
        raise MatrixError(
            f"{path.name}: no header row containing {RUN_NUMBER!r} in the first {HEADER_SEARCH_ROWS} rows"
        )
    missing = [name for name in REQUIRED if name not in headers]
    if missing:
        raise MatrixError(f"{path.name}: sheet {SHEET!r} lacks columns {missing}; header is {headers}")
    rows: list[MatrixRow] = []
    for offset, cells in enumerate(grid[header_index + 1 :], start=header_index + 2):
        values = dict(zip(headers, cells, strict=False))
        number = _run_number(values[RUN_NUMBER])
        if number is None:
            continue  # setup notes, "STOW", camera settings footers
        rows.append(
            MatrixRow(
                offset,
                number,
                collapse(cell_text(values[TEST_NUMBER])),
                collapse(cell_text(values[SAMPLE_NUMBER])),
                values,
            )
        )
    return Matrix(path.name, tuple(rows))


@dataclass(frozen=True)
class Join:
    row: MatrixRow | None
    reason: str
    """Why there is no row (empty when joined)."""


def join_row(row: Row, matrix: Matrix | None, run_column: str, test_column: str, sample_column: str) -> Join:
    if matrix is None:
        return Join(None, "as-run workbook not available to this build")
    run_text = collapse(row.cells[run_column])
    if not run_text.isdigit():
        return Join(None, f'"As Run Test #" is "{run_text}", not a number')
    candidates = matrix.candidates(int(run_text))
    if not candidates:
        return Join(None, f"no as-run matrix row with As run test no. {run_text}")
    test, sample = collapse(row.cells[test_column]), collapse(row.cells[sample_column])
    agreeing = [c for c in candidates if (c.test_number, c.sample_number) == (test, sample)]
    if len(agreeing) == 1:
        return Join(agreeing[0], "")
    found = [(c.sheet_row, c.test_number, c.sample_number) for c in candidates]
    kind = "several matrix rows share" if len(agreeing) > 1 else "no matrix row agrees on Test # and Sample # for"
    return Join(
        None, f'{kind} As run test no. {run_text} (CSV Test # "{test}", Sample # "{sample}"; matrix rows {found})'
    )
