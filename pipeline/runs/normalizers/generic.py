"""Fallback normalizer: every row becomes a record with all conditions unknown.

This is the extension point for tables that are not deeply normalized yet (BASS,
BASS-II and the rest). To normalize one, add a module next to this one that
returns a ``Normalizer`` and register it by table slug in ``pipeline.runs.registry``.
The original row text and source row number are already preserved here.
"""

from pipeline.runs.common import (
    Context,
    Normalizer,
    all_unknown_conditions,
    no_alias_sources,
)
from pipeline.runs.values import Record

NOTE = "table not normalized yet; conditions not extracted"


def normalize(context: Context) -> list[Record]:
    conditions = all_unknown_conditions(NOTE)
    return [
        Record(context.record_id(row), "run", row.number, dict(row.cells), conditions, ()) for row in context.table.rows
    ]


NORMALIZER = Normalizer(normalize, no_alias_sources)
