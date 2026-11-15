"""Build backend artifacts from saved, validated inputs without downloading data."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from backend.catalog import build_catalog
from backend.graph import RunGraph

ROOT = Path(__file__).resolve().parents[1]


def build(data_dir: Path, res_dir: Path, catalog_path: Path, graph_path: Path,
          allow_pending: bool = True) -> dict[str, Any]:
    """Publish prepared artifacts only after their source validation succeeds."""
    graph = RunGraph(data_dir, res_dir)
    graph_health = graph.health()
    if graph_health["state"] != "available":
        raise ValueError("No validated prepared run tables are available.")
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=graph_path.name + ".candidate-", dir=graph_path.parent)
    os.close(descriptor)
    candidate = Path(name)
    try:
        graph.graph.serialize(destination=str(candidate), format="turtle")
        catalog = build_catalog(catalog_path, data_dir, res_dir, allow_pending=allow_pending)
        os.replace(candidate, graph_path)
    finally:
        candidate.unlink(missing_ok=True)
    return {"catalog_path": str(catalog_path), "graph_path": str(graph_path),
            "catalog": catalog, "graph": graph_health, "triples": len(graph.graph)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--res-dir", type=Path, default=ROOT / "res")
    parser.add_argument("--catalog-path", type=Path)
    parser.add_argument("--graph-path", type=Path)
    parser.add_argument("--approved-only", action="store_true",
                        help="Reject cards that still await scientific review.")
    args = parser.parse_args()
    result = build(args.data_dir, args.res_dir, args.catalog_path or args.res_dir / "catalog.sqlite",
                   args.graph_path or args.res_dir / "runs.ttl", allow_pending=not args.approved_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
