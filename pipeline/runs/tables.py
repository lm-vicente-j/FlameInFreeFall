"""Read an experimental-table CSV without altering its content.

Cells keep their exact text and headers keep their exact spelling. Rows are
numbered from 1 counting every record after the header, so a row number matches
the file even though all-empty rows are skipped (and counted separately).
"""

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pipeline.storage import sha256_bytes

Encoding = Literal["utf-8", "utf-8-sig", "cp1252"]
_BOM = b"\xef\xbb\xbf"


class TableError(ValueError):
    """The CSV cannot be read faithfully; the message names the file and row."""


def collapse(text: str) -> str:
    """Strip and collapse inner whitespace (used to compare headers and alias keys)."""
    return " ".join(text.split())


@dataclass(frozen=True)
class Row:
    number: int
    cells: dict[str, str]
    """Every cell keyed by its exact header; short rows are padded with ''."""


@dataclass(frozen=True)
class Table:
    filename: str
    sha256: str
    encoding: Encoding
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    empty_rows_skipped: int

    def find_column(self, *names: str) -> str | None:
        """Exact header whose whitespace-collapsed text equals the first matching name."""
        by_name = {collapse(column): column for column in self.columns}
        for name in names:
            if collapse(name) in by_name:
                return by_name[collapse(name)]
        return None

    def require_column(self, *names: str) -> str:
        column = self.find_column(*names)
        if column is None:
            raise TableError(
                f"{self.filename}: none of the columns {list(names)} exists; header is {list(self.columns)}"
            )
        return column


def detect_encoding(content: bytes, filename: str) -> Encoding:
    if content.startswith(_BOM):
        return "utf-8-sig"
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        content.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError as error:
        raise TableError(f"{filename}: not valid utf-8 or cp1252 ({error})") from error


def parse_table(content: bytes, filename: str) -> Table:
    encoding = detect_encoding(content, filename)
    reader = csv.reader(io.StringIO(content.decode(encoding), newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise TableError(f"{filename}: file has no header row") from None
    duplicates = sorted({cell for cell in header if header.count(cell) > 1})
    if duplicates:
        raise TableError(f"{filename}: duplicate header cells {duplicates}")
    rows: list[Row] = []
    skipped = 0
    for number, cells in enumerate(reader, start=1):
        if len(cells) > len(header):
            raise TableError(f"{filename}: row {number} has {len(cells)} cells but the header has {len(header)}")
        if not any(cell.strip() for cell in cells):
            skipped += 1
            continue
        padded = cells + [""] * (len(header) - len(cells))
        rows.append(Row(number, dict(zip(header, padded, strict=True))))
    return Table(filename, sha256_bytes(content), encoding, tuple(header), tuple(rows), skipped)


def read_table(path: Path) -> Table:
    return parse_table(path.read_bytes(), path.name)
