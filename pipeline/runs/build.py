"""Build the run-table documents and write them after validating every one.

Output is deterministic: the same inputs give byte-identical files.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.runs.aliases import AliasDictionary, AliasSet, load_aliases
from pipeline.runs.common import Context, QueueItem
from pipeline.runs.registry import TableSource, discover
from pipeline.runs.tables import collapse, read_table
from pipeline.schema import schema_errors
from pipeline.storage import write_json_atomic

ALIAS_NAMES = ("materials", "geometries")


class BuildError(ValueError):
    """Output failed validation or identity checks; nothing was written."""


@dataclass(frozen=True)
class TableSummary:
    slug: str
    runs: int
    notes: int
    empty_rows_skipped: int


def build_document(
    source: TableSource, aliases: AliasSet, tables_dir: Path | None = None, extractions_dir: Path | None = None
) -> dict[str, Any]:
    return build_with_queues(source, aliases, tables_dir, extractions_dir)[0]


def build_with_queues(
    source: TableSource, aliases: AliasSet, tables_dir: Path | None = None, extractions_dir: Path | None = None
) -> tuple[dict[str, Any], dict[str, list[QueueItem]]]:
    """The run-table document and the extraction queues the normalizer produces."""
    table = read_table(source.path)
    context = Context(source.accession, source.slug, table, aliases, tables_dir, extractions_dir)
    records = source.normalizer.normalize(context)
    queues = source.normalizer.queues(context) if source.normalizer.queues is not None else {}
    notes = sum(1 for record in records if record.kind == "note")
    document = {
        "table": source.slug,
        "investigation": source.accession,
        "source": {
            "filename": table.filename,
            "sha256": table.sha256,
            "encoding": table.encoding,
            "columns": list(table.columns),
        },
        "counts": {
            "runs": len(records) - notes,
            "notes": notes,
            "empty_rows_skipped": table.empty_rows_skipped,
        },
        "records": [record.to_json() for record in records],
    }
    return document, queues


def check_document(document: Mapping[str, Any], expected_rows: int) -> None:
    name = document["table"]
    errors = schema_errors(document, "run-table")
    if errors:
        raise BuildError(f"{name}: invalid run-table output: {'; '.join(errors[:5])}")
    ids = [record["id"] for record in document["records"]]
    if len(ids) != len(set(ids)):
        raise BuildError(f"{name}: duplicate record ids")
    if len(ids) != expected_rows:
        raise BuildError(f"{name}: {len(ids)} records for {expected_rows} non-empty rows")


def build_all(
    tables_dir: Path, aliases_dir: Path, out_dir: Path, extractions_dir: Path | None = None
) -> list[TableSummary]:
    """Normalize every table. With ``extractions_dir``, reviewed extractions found there are
    applied and the extraction queues of the normalizers are written there."""
    aliases: dict[str, AliasDictionary] = load_aliases(aliases_dir, ALIAS_NAMES)
    documents: list[dict[str, Any]] = []
    queues: dict[str, list[QueueItem]] = {}
    for source in discover(tables_dir):
        document, table_queues = build_with_queues(source, aliases, tables_dir, extractions_dir)
        queues.update(table_queues)
        counts = document["counts"]
        check_document(document, counts["runs"] + counts["notes"])
        documents.append(document)
    for document in documents:
        write_json_atomic(out_dir / f"{document['table']}.json", document)
    if extractions_dir is not None:
        for name, items in sorted(queues.items()):
            write_json_atomic(extractions_dir / f"{name}.queue.json", items)
    return [
        TableSummary(d["table"], d["counts"]["runs"], d["counts"]["notes"], d["counts"]["empty_rows_skipped"])
        for d in documents
    ]


def missing_aliases(tables_dir: Path, aliases_dir: Path) -> dict[str, list[str]]:
    """Source strings per dictionary that have no entry (of any review status)."""
    aliases = load_aliases(aliases_dir, ALIAS_NAMES)
    return {
        name: sorted(set(sources) - set(aliases[name].entries)) for name, sources in collect_sources(tables_dir).items()
    }


def collect_sources(tables_dir: Path) -> dict[str, set[str]]:
    collected: dict[str, set[str]] = {"materials": set()}  # always present; other names appear when reported
    for source in discover(tables_dir):
        table = read_table(source.path)
        for name, texts in source.normalizer.alias_sources(table).items():
            collected.setdefault(name, set()).update(collapse(text) for text in texts if collapse(text))
    return collected
