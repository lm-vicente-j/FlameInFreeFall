"""Command line: ``python -m pipeline.runs build | missing-aliases | propose-aliases``."""

import argparse
from pathlib import Path

from pipeline.paths import DATA, EXPERIMENTAL_TABLES
from pipeline.runs.aliases import AliasError, add_proposals
from pipeline.runs.build import BuildError, build_all, collect_sources, missing_aliases
from pipeline.runs.proposals import MATERIAL_PROPOSALS
from pipeline.runs.registry import RegistryError
from pipeline.runs.tables import TableError
from pipeline.storage import write_json_atomic

_PROPOSALS = {"materials": MATERIAL_PROPOSALS}


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
    return parser


def _build(args: argparse.Namespace) -> int:
    summaries = build_all(args.tables, args.aliases, args.out)
    for summary in summaries:
        print(
            f"{summary.slug}: runs={summary.runs} notes={summary.notes} empty_rows_skipped={summary.empty_rows_skipped}"
        )
    print(f"{len(summaries)} tables, {sum(s.runs + s.notes for s in summaries)} records -> {args.out}")
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
    except (TableError, RegistryError, AliasError, BuildError) as error:
        print(f"error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
