"""Queues of free-text cells and the application of reviewed model extractions.

Queue files. ``data/extractions/<name>.queue.json`` is a JSON list, one object per cell
that needs reading, ``{"record_id": ..., "column": ..., "source_text": ...}``. It is the
input of the extraction step; ``source_text`` is the cell exactly as written. Queues are
rewritten by every build and carry no review state.

Result files. ``data/extractions/<name>.json`` follows ``llm-extraction.schema.json``
and is produced by a model and reviewed by a person. When it exists, the build applies
it and stops with an ``ExtractionError`` naming the record when anything does not hold:
the file fails the schema, its name differs, a record id does not exist, ``source_text``
is not the current cell text (the source changed), a quote is not an exact substring of
``source_text``, a record has two items for one cell, or an air-display reading is given
for a record whose flow is already established.

Application. An item with review status "approved" or "pending" adds its outcomes to
its record with method "llm", the item's review status, the quote and the source column;
"pending" values keep the record's own status pending, so they are visible but flagged.
"rejected" items add nothing. Readings of instrument ``air_display`` set flow_cm_s to the
min/max of the readings x 1.0066 (the fan calibration factor) with method "llm". Readings
of ``fan_display`` are validated but not converted: there is no calibration for them.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from pipeline.runs.common import QueueItem
from pipeline.runs.normalizers.bass_common import (
    AIR_DISPLAY_TO_CM_S,
    CALIBRATION_NOTE,
    SWEEP_NOTE,
    air_display_to_cm_s,
)
from pipeline.runs.values import (
    Category,
    Outcome,
    Provenance,
    Quantity,
    Record,
    ReviewStatus,
)
from pipeline.schema import schema_errors
from pipeline.storage import read_json


class ExtractionError(ValueError):
    """A reviewed extraction file does not match the data it is applied to."""


@dataclass(frozen=True)
class QueueCell:
    record_id: str
    column: str
    source_text: str

    def to_json(self) -> QueueItem:
        return {"record_id": self.record_id, "column": self.column, "source_text": self.source_text}


def queue_json(cells: list[QueueCell]) -> list[QueueItem]:
    return [cell.to_json() for cell in cells]


def _fail(path: Path, record_id: str | None, message: str) -> ExtractionError:
    where = f" record {record_id}:" if record_id else ""
    return ExtractionError(f"{path}:{where} {message}")


def _provenance(item: dict[str, Any], column: str, quote: str, note: str) -> Provenance:
    status: ReviewStatus = item["review"]["status"]
    return Provenance("llm", (column,), status, quote, note)


def _outcome(item: dict[str, Any], column: str, proposed: dict[str, Any]) -> Outcome:
    model = item["model"] or "manual entry"
    note = f"proposed by {item['proposed_by']} ({model}); status as reviewed"
    provenance = _provenance(item, column, proposed["quote"], note)
    result = proposed["result"]
    value: Quantity | Category
    if result["kind"] == "quantity":
        value = Quantity(float(result["min"]), float(result["max"]), result["unit"], result["qualifier"], provenance)
    else:
        value = Category(result["value"], provenance)
    return Outcome(proposed["type"], proposed["gravity"], value)


def _flow(item: dict[str, Any], column: str, readings: list[dict[str, Any]]) -> Quantity:
    low = min(Decimal(repr(reading["min"])) for reading in readings)
    high = max(Decimal(repr(reading["max"])) for reading in readings)
    quote = readings[0]["quote"] if len(readings) == 1 else item["source_text"]
    note = f"{CALIBRATION_NOTE} (x {AIR_DISPLAY_TO_CM_S}); {SWEEP_NOTE}; air display readings proposed by model"
    return Quantity(
        air_display_to_cm_s(low), air_display_to_cm_s(high), "cm/s", None, _provenance(item, column, quote, note)
    )


def _check_item(path: Path, item: dict[str, Any], cells: list[QueueCell]) -> QueueCell:
    record_id = item["record_id"]
    text = item["source_text"]
    matching = [cell for cell in cells if cell.source_text == text]
    if not cells:
        raise _fail(path, record_id, "the queue has no free-text cell for this record")
    if not matching:
        current = [cell.source_text for cell in cells]
        raise _fail(path, record_id, f"source_text {text!r} is not the current cell text {current}; source changed")
    if len(matching) > 1:
        raise _fail(path, record_id, f"source_text {text!r} appears in several cells {[c.column for c in matching]}")
    proposal = item["proposal"]
    quotes = [outcome["quote"] for outcome in proposal["outcomes"]] + [
        reading["quote"] for reading in proposal["readings"]
    ]
    for quote in quotes:
        if quote not in text:
            raise _fail(path, record_id, f"quote {quote!r} is not an exact substring of source_text {text!r}")
    return matching[0]


def apply_extractions(records: list[Record], directory: Path | None, name: str, queue: list[QueueCell]) -> list[Record]:
    """The records with the reviewed extraction ``<name>.json`` applied; unchanged when absent."""
    if directory is None or not (directory / f"{name}.json").exists():
        return records
    path = directory / f"{name}.json"
    document = read_json(path)
    errors = schema_errors(document, "llm-extraction")
    if errors:
        raise _fail(path, None, f"invalid llm-extraction document: {'; '.join(errors[:5])}")
    if document["name"] != name:
        raise _fail(path, None, f"name {document['name']!r} must equal the file name {name!r}")
    by_id = {record.id: record for record in records}
    cells_by_id: dict[str, list[QueueCell]] = {}
    for cell in queue:
        cells_by_id.setdefault(cell.record_id, []).append(cell)
    seen: set[tuple[str, str]] = set()
    updated = dict(by_id)
    for item in document["items"]:
        record_id = item["record_id"]
        if record_id not in by_id:
            raise _fail(path, record_id, "no such record in the run table")
        cell = _check_item(path, item, cells_by_id.get(record_id, []))
        if (record_id, cell.column) in seen:
            raise _fail(path, record_id, f"more than one item for column {cell.column!r}")
        seen.add((record_id, cell.column))
        status = item["review"]["status"]
        if status == "rejected":
            continue
        if status not in ("approved", "pending"):
            raise _fail(path, record_id, f"review status {status!r} is not valid for a model extraction")
        record = updated[record_id]
        for proposed in item["proposal"]["outcomes"]:
            result = proposed["result"]
            if result["kind"] == "quantity" and result["min"] > result["max"]:
                raise _fail(path, record_id, f"outcome {proposed['type']!r} has min greater than max")
        outcomes = tuple(_outcome(item, cell.column, proposed) for proposed in item["proposal"]["outcomes"])
        conditions = record.conditions
        air = [r for r in item["proposal"]["readings"] if r["instrument"] == "air_display"]
        if air:
            if conditions.flow_cm_s.provenance.method != "unknown":
                raise _fail(path, record_id, "air display readings given but flow_cm_s is already established")
            if any(reading["min"] > reading["max"] for reading in air):
                raise _fail(path, record_id, "a reading has min greater than max")
            conditions = replace(conditions, flow_cm_s=_flow(item, cell.column, air))
        updated[record_id] = replace(record, conditions=conditions, outcomes=record.outcomes + outcomes)
    return [updated[record.id] for record in records]
