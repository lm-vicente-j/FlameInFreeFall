"""Command line: ``python -m pipeline.runs build | missing-aliases | propose-aliases``."""

import argparse
from pathlib import Path

from pipeline.catalog import SnapshotMissingError
from pipeline.paths import DATA, EXPERIMENTAL_TABLES, RES
from pipeline.runs.aliases import AliasError, add_proposals
from pipeline.runs.build import BuildError, build_all, collect_sources, missing_aliases
from pipeline.runs.normalizers import bass_common
from pipeline.runs.normalizers.bass_extractions import ExtractionError
from pipeline.runs.proposals import MATERIAL_PROPOSALS
from pipeline.runs.registry import RegistryError
from pipeline.runs.tables import TableError
from pipeline.storage import write_json_atomic

_PROPOSALS = {
    "materials": {**MATERIAL_PROPOSALS, **bass_common.MATERIAL_PROPOSALS},
    "geometries": bass_common.GEOMETRY_PROPOSALS,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline.runs", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("build", "normalize every experimental table into data/runs"),
        ("missing-aliases", "list source strings that have no alias entry"),
        ("propose-aliases", "add pending model proposals for new source strings; reviewed entries are kept"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--tables", type=Path, default=EXPERIMENTAL_TABLES)
        command.add_argument("--aliases", type=Path, default=DATA / "aliases")
        if name == "build":
            command.add_argument("--out", type=Path, default=DATA / "runs")
            command.add_argument(
                "--extractions",
                type=Path,
                default=DATA / "extractions",
                help="reviewed extraction results to apply; extraction queues are written here",
            )
            command.add_argument(
                "--res", type=Path, default=RES, help="saved PSI snapshot; runs are linked to its remote files"
            )
    return parser


def _build(args: argparse.Namespace) -> int:
    summaries = build_all(args.tables, args.aliases, args.out, args.extractions, args.res)
    for summary in summaries:
        print(
            f"{summary.slug}: runs={summary.runs} ranges={summary.ranges} sessions={summary.sessions} "
            f"notes={summary.notes} duplicate_rows={summary.duplicate_rows} "
            f"links_confirmed={summary.links_confirmed} links_ambiguous={summary.links_ambiguous} "
            f"empty_rows_skipped={summary.empty_rows_skipped}"
        )
    records = sum(s.runs + s.ranges + s.sessions + s.notes for s in summaries)
    print(f"{len(summaries)} tables, {records} records -> {args.out}")
    return 0


def _missing(args: argparse.Namespace) -> int:
    missing = missing_aliases(args.tables, args.aliases)
    for name, sources in missing.items():
        print(f"{name}: {len(sources)} source string(s) without an entry")
        for source in sources:
            print(f"  {source}")
    return 0


def _propose(args: argparse.Namespace) -> int:
    for name, sources in collect_sources(args.tables).items():
        document, unproposed = add_proposals(args.aliases, name, sources, _PROPOSALS[name])
        write_json_atomic(args.aliases / f"{name}.json", document)
        print(f"{name}: {len(document['entries'])} entries; no proposal known for {len(unproposed)}")
        for source in unproposed:
            print(f"  {source}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {"build": _build, "missing-aliases": _missing, "propose-aliases": _propose}
    try:
        return handlers[args.command](args)
    except (TableError, RegistryError, AliasError, BuildError, ExtractionError, SnapshotMissingError) as error:
        print(f"error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
