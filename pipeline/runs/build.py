"""Build the run-table documents and write them after validating every one.

Output is deterministic: the same inputs give byte-identical files.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.catalog import RemoteFile, load_files
from pipeline.runs.aliases import AliasDictionary, AliasSet, load_aliases
from pipeline.runs.common import Context, QueueItem
from pipeline.runs.flags import add_flags
from pipeline.runs.kinds import classify_kinds
from pipeline.runs.links import add_links
from pipeline.runs.registry import TableSource, discover
from pipeline.runs.tables import collapse, read_table
from pipeline.schema import schema_errors
from pipeline.storage import write_json_atomic

ALIAS_NAMES = ("materials", "geometries")
KIND_COUNTS = (("run", "runs"), ("range", "ranges"), ("session", "sessions"), ("note", "notes"))


class BuildError(ValueError):
    """Output failed validation or identity checks; nothing was written."""


@dataclass(frozen=True)
class TableSummary:
    slug: str
    runs: int
    notes: int
    empty_rows_skipped: int
    ranges: int = 0
    sessions: int = 0
    duplicate_rows: int = 0
    links_confirmed: int = 0
    links_ambiguous: int = 0


def build_document(
    source: TableSource,
    aliases: AliasSet,
    tables_dir: Path | None = None,
    extractions_dir: Path | None = None,
    files: Sequence[RemoteFile] = (),
) -> dict[str, Any]:
    return build_with_queues(source, aliases, tables_dir, extractions_dir, files)[0]


def build_with_queues(
    source: TableSource,
    aliases: AliasSet,
    tables_dir: Path | None = None,
    extractions_dir: Path | None = None,
    files: Sequence[RemoteFile] = (),
) -> tuple[dict[str, Any], dict[str, list[QueueItem]]]:
    """The run-table document and the extraction queues the normalizer produces.

    Stages: normalize, give each row its kind, flag data-quality problems, link to ``files``
    (the remote files of the investigation; none means no links)."""
    table = read_table(source.path)
    context = Context(source.accession, source.slug, table, aliases, tables_dir, extractions_dir)
    records = source.normalizer.normalize(context)
    records = classify_kinds(source.slug, records)
    records = add_flags(source.slug, records)
    records = add_links(source.slug, records, files)
    queues = source.normalizer.queues(context) if source.normalizer.queues is not None else {}
    kinds: Counter[str] = Counter(record.kind for record in records)
    duplicates = sum(1 for record in records if any(flag.code == "duplicate_row" for flag in record.flags))
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
            **{name: kinds[kind] for kind, name in KIND_COUNTS},
            "duplicate_rows": duplicates,
            "empty_rows_skipped": table.empty_rows_skipped,
        },
        "records": [record.to_json() for record in records],
    }
    return document, queues


def check_document(document: Mapping[str, Any]) -> None:
    name = document["table"]
    errors = schema_errors(document, "run-table")
    if errors:
        raise BuildError(f"{name}: invalid run-table output: {'; '.join(errors[:5])}")
    ids = [record["id"] for record in document["records"]]
    if len(ids) != len(set(ids)):
        raise BuildError(f"{name}: duplicate record ids")
    counts = document["counts"]
    counted = sum(counts[name] for _, name in KIND_COUNTS)
    if len(ids) != counted:
        raise BuildError(f"{name}: {len(ids)} records but the counts add up to {counted}")
    for kind, count_name in KIND_COUNTS:
        actual = sum(1 for record in document["records"] if record["kind"] == kind)
        if actual != counts[count_name]:
            raise BuildError(f"{name}: counts.{count_name} is {counts[count_name]} but {actual} records are {kind}")


def summarize(document: Mapping[str, Any]) -> TableSummary:
    counts = document["counts"]
    links = Counter(link["status"] for record in document["records"] for link in record["links"])
    return TableSummary(
        document["table"],
        counts["runs"],
        counts["notes"],
        counts["empty_rows_skipped"],
        counts["ranges"],
        counts["sessions"],
        counts["duplicate_rows"],
        links["confirmed"],
        links["ambiguous"],
    )


def build_all(
    tables_dir: Path,
    aliases_dir: Path,
    out_dir: Path,
    extractions_dir: Path | None = None,
    res_dir: Path | None = None,
) -> list[TableSummary]:
    """Normalize every table. With ``extractions_dir``, reviewed extractions found there are
    applied and the extraction queues of the normalizers are written there. With ``res_dir``
    (the saved PSI snapshot), runs are linked to the remote files of their investigation."""
    aliases: dict[str, AliasDictionary] = load_aliases(aliases_dir, ALIAS_NAMES)
    documents: list[dict[str, Any]] = []
    queues: dict[str, list[QueueItem]] = {}
    expected_rows: dict[str, int] = {}
    for source in discover(tables_dir):
        files = load_files(res_dir, source.accession) if res_dir is not None else []
        document, table_queues = build_with_queues(source, aliases, tables_dir, extractions_dir, files)
        queues.update(table_queues)
        check_document(document)
        documents.append(document)
        expected_rows[source.slug] = len(read_table(source.path).rows)
        if len(document["records"]) != expected_rows[source.slug]:
            raise BuildError(f"{source.slug}: {len(document['records'])} records for {expected_rows[source.slug]} rows")
    for document in documents:
        write_json_atomic(out_dir / f"{document['table']}.json", document)
    if extractions_dir is not None:
        for name, items in sorted(queues.items()):
            write_json_atomic(extractions_dir / f"{name}.queue.json", items)
    return [summarize(document) for document in documents]


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
