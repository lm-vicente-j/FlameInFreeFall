"""Command line: ``python -m pipeline.review <aliases|extractions|cards> --reviewer NAME``.

PLAN.md requires a person to approve every alias, extracted value and card before
import. There is deliberately no default reviewer, so a decision is always attributed
to someone who typed their own name.
"""

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from pipeline.paths import DATA
from pipeline.review.display import count_run_cells
from pipeline.review.kinds import KINDS, default_files
from pipeline.review.session import Environment, ReviewError, Tally, Validator, review_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline.review", description=__doc__)
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("--reviewer", required=True, help="your name; recorded with every decision")
    parser.add_argument("--path", type=Path, nargs="+", help="files to review instead of the defaults")
    parser.add_argument("--all", action="store_true", help="also revisit approved and rejected items")
    return parser


def _now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: list[str] | None = None,
    *,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    clock: Callable[[], datetime] = _now,
    validator: Validator | None = None,
    runs_dir: Path = DATA / "runs",
    packets_dir: Path = DATA / "evidence",
) -> int:
    args = _parser().parse_args(argv)
    kind = KINDS[args.kind]
    reviewer = args.reviewer.strip()
    if not reviewer:
        say("error: --reviewer must not be blank")
        return 1
    files = args.path or default_files(kind)
    if not files:
        say(f"no {kind.name} files found in {kind.default_dir}")
        return 0
    env = Environment(reviewer, ask, say, clock, validator, packets_dir, cache(lambda: count_run_cells(runs_dir)))
    status = 0
    results: list[tuple[Path, Tally]] = []
    for path in files:
        try:
            tally = review_file(path, kind, env, args.all)
        except ReviewError as error:
            say(f"error: {error}")
            status = 1
            continue
        results.append((path, tally))
        if tally.quit:
            break
    say("")
    say("Summary")
    for path, tally in results:
        say(f"  {path}: {tally.line()}")
    if kind.rebuild_runs and any(tally.decided for _, tally in results):
        say("Run records derive from these files. Next run: python -m pipeline.runs build")
    return status
