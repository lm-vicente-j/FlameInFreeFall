"""What one row of each table stands for: a test (run), a range, a session or a note.

Normalizers decide run versus note for the rows they understand (Saffire notes, the BASS
"SOOT Cleaning" row). This module re-classifies the rows they leave as ``run`` for the
tables whose rows are not individual tests, so that only ``kind == "run"`` counts as a test.
Every rule carries the reason, so an auditor can check each classification against the
source table in one place. Tables without a rule keep their rows as runs.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from pipeline.runs.values import Kind, Record


@dataclass(frozen=True)
class KindRule:
    kind: Kind
    why: str
    """One line: what a row of this table is, from the source."""
    note_when: Callable[[Mapping[str, str]], bool] | None = None
    note_why: str = ""
    """Rows matching ``note_when`` are notes instead, for this reason."""

    def classify(self, original: Mapping[str, str]) -> Kind:
        if self.note_when is not None and self.note_when(original):
            return "note"
        return self.kind


def _blank(original: Mapping[str, str], column: str) -> bool:
    return not original.get(column, "").strip()


KIND_RULES: dict[str, KindRule] = {
    "flex2": KindRule(
        "range",
        "each row gives condition ranges per fuel (e.g. oxygen '0.17; 0.21;0.25; 0.3'), shared by many tests",
    ),
    "acme-bre": KindRule(
        "session", "each row is one test day with a list of oxygen concentrations and a count of flames"
    ),
    "cld-flame": KindRule("session", "each row is one test day with a fuel concentration range and a count of flames"),
    "acme-e-field-flames": KindRule(
        "session",
        "each row is one test day with the number of flames ignited",
        lambda original: _blank(original, "Test Type") and _blank(original, "Test Day"),
        "a row with no test type or test day only continues the fuel concentration list of the row above",
    ),
    "acme-s-flame": KindRule("session", "each row is one test day with the atmosphere, fuel bottle and flames ignited"),
    "slice": KindRule("session", "each row is one test day with the fuel used that day"),
    "daft": KindRule("session", "each row is a session (D1, D2) with its hardware and sampled location"),
    "data-summary-table": KindRule(
        "note", "each row points to a figure of a publication that reports the data; it is not a test"
    ),
}


def classify_kinds(slug: str, records: list[Record]) -> list[Record]:
    """The records with the table's row kind applied to every row the normalizer left as a run."""
    rule = KIND_RULES.get(slug)
    if rule is None:
        return records
    return [
        replace(record, kind=rule.classify(record.original)) if record.kind == "run" else record for record in records
    ]
