"""Small, schema-valid development fixtures derived from the real prepared data.

The backend and dashboard develop against these files before the full data set
is reviewed. They are cut from ``data/`` rather than written by hand, so they
always match the current contracts, and every fixture is validated before it is
written:

- two investigations: FLEX (PSI-69, document evidence with findings) and
  Saffire-II (PSI-99, metadata-only), each with its card and a packet trimmed to
  the passages the card cites;
- run tables: a FLEX subset covering each diluent mix, the invalid 0 mmHg
  reading, approximate values and every run the fixture card cites as a table
  row (so a card citation and its run record can be followed in the fixtures),
  plus the complete Saffire-II table with its note rows and its 1 g versus
  microgravity outcomes.

A trimmed packet keeps the ``documents`` and ``tables`` lists of the full packet,
so ``tables[].rows`` and ``documents[].page_count`` describe the source files, not
the number of passages kept.

    python -m pipeline.fixtures [--data data] [--out data/fixtures]
"""
import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.cards import validate
from pipeline.schema import schema_errors
from pipeline.storage import read_json, write_json_atomic

INVESTIGATIONS = ("PSI-69", "PSI-99")
FLEX_ROWS_PER_DILUENT = 2
FLEX_EXTRA_ROWS = (114, 223)
"""Test 114 records an invalid 0 mmHg pressure; row 223 has an approximate burn time."""


class FixtureError(ValueError):
    """A fixture could not be derived or does not validate."""


def trim_packet(packet: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    cited = {item["passage_id"] for item in card["evidence"]}
    return {**packet, "passages": [p for p in packet["passages"] if p["id"] in cited]}


def cited_record_ids(card: dict[str, Any]) -> set[str]:
    """Run record ids the card cites through table-row evidence."""
    return {
        item["locator"]["record_id"]
        for item in card["evidence"]
        if item["locator"]["kind"] == "table" and "record_id" in item["locator"]
    }


def _flex_rows(records: list[dict[str, Any]], cited: set[str]) -> set[int]:
    chosen: set[int] = set(FLEX_EXTRA_ROWS)
    chosen.update(record["row"] for record in records if record["id"] in cited)
    per_diluent: dict[str, int] = {}
    for record in records:
        diluent = record["conditions"]["diluent"]["value"] or "unknown"
        if per_diluent.get(diluent, 0) < FLEX_ROWS_PER_DILUENT:
            per_diluent[diluent] = per_diluent.get(diluent, 0) + 1
            chosen.add(record["row"])
    return chosen


def subset_table(table: dict[str, Any], keep: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """Keep the chosen records and recompute counts so the subset stays truthful."""
    records = [record for record in table["records"] if keep(record)]
    kinds = [record["kind"] for record in records]
    counts = {
        "runs": kinds.count("run"),
        "ranges": kinds.count("range"),
        "sessions": kinds.count("session"),
        "notes": kinds.count("note"),
        "duplicate_rows": sum(any(f["code"] == "duplicate_row" for f in r["flags"]) for r in records),
        "empty_rows_skipped": 0,
    }
    return {**table, "counts": counts, "records": records}


def build(data_dir: Path) -> dict[str, Any]:
    """Return {relative path: document} for every fixture, all validated."""
    outputs: dict[str, Any] = {}
    for accession in INVESTIGATIONS:
        card = read_json(data_dir / "cards" / f"{accession}.json")
        packet = trim_packet(read_json(data_dir / "evidence" / f"{accession}.json"), card)
        problems = schema_errors(packet, "evidence-packet") + validate(card, packet)
        if problems:
            raise FixtureError(f"{accession}: " + "; ".join(problems))
        outputs[f"cards/{accession}.json"] = card
        outputs[f"evidence/{accession}.json"] = packet

    flex = read_json(data_dir / "runs" / "flex.json")
    rows = _flex_rows(flex["records"], cited_record_ids(outputs["cards/PSI-69.json"]))
    outputs["runs/flex.json"] = subset_table(flex, lambda record: record["row"] in rows)
    outputs["runs/saffire-2.json"] = read_json(data_dir / "runs" / "saffire-2.json")
    for name in ("runs/flex.json", "runs/saffire-2.json"):
        problems = schema_errors(outputs[name], "run-table")
        if problems:
            raise FixtureError(f"{name}: " + "; ".join(problems))
    present = {
        record["id"] for name in ("runs/flex.json", "runs/saffire-2.json") for record in outputs[name]["records"]
    }
    for accession in INVESTIGATIONS:
        missing = sorted(cited_record_ids(outputs[f"cards/{accession}.json"]) - present)
        if missing:
            raise FixtureError(f"{accession}: the card cites runs missing from the run fixtures: {', '.join(missing)}")
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive development fixtures from the prepared data.")
    parser.add_argument("--data", type=Path, default=paths.DATA)
    parser.add_argument("--out", type=Path, default=paths.DATA / "fixtures")
    args = parser.parse_args(argv)
    try:
        outputs = build(args.data)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for name, document in outputs.items():
        write_json_atomic(args.out / name, document)
        part = next(key for key in ("records", "passages", "evidence") if key in document)
        print(f"{name}: {len(document[part])} {part}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
