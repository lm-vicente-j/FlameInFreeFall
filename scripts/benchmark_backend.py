"""Measure thirty real search/run HTTP queries after application startup."""

from __future__ import annotations

import argparse
import json
import math
import platform
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote

from app import create_app

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    ("/api/studies", {"q": query}) for query in (
        "flame", "droplet", "smoke", "combustion", "extinction", "space", "Saffire",
        "FLEX", "oxygen", "pressure", "material", "flow", "suppression", "ignition",
        "nonexistent-psi-query",
    )
]
QUERIES.extend(("/api/runs", filters) for filters in [
    {}, {"fuel_class": "droplet"}, {"fuel_class": "solid"}, {"fuel_class": "gas"},
    {"material": "Methanol"}, {"flow_direction": "concurrent"},
    {"flow_direction": "opposed"}, {"flow_direction": "quiescent"},
    {"o2_min": "15", "o2_max": "21"}, {"o2_min": "21", "o2_max": "30"},
    {"pressure_min": "90", "pressure_max": "110"}, {"flow_min": "0", "flow_max": "5"},
    {"outcome": "burning_rate"}, {"outcome": "observation"},
    {"material": "Methanol", "o2_min": "20", "pressure_max": "110"},
])


def smoke(client: Any) -> list[dict[str, Any]]:
    """Check all eight routes against identifiers from the active snapshot."""
    studies = client.get("/api/studies").get_json()["data"]
    runs = client.get("/api/runs").get_json()["data"]
    if not studies or not runs or not studies[0].get("evidence"):
        raise ValueError("Eight-route smoke requires at least one study, run and evidence record.")
    accession = quote(studies[0]["accession"], safe="")
    evidence_id = quote(studies[0]["evidence"][0]["id"], safe="")
    run_id = quote(runs[0]["id"], safe="")
    paths = ["/api/studies", f"/api/studies/{accession}", f"/api/studies/{accession}/files",
             f"/api/evidence/{evidence_id}", "/api/runs", f"/api/runs/{run_id}",
             "/api/coverage", "/api/health"]
    results = []
    for endpoint in paths:
        response = client.get(endpoint)
        body = response.get_json(silent=True)
        results.append({"endpoint": endpoint, "status": response.status_code,
                        "success_envelope": isinstance(body, dict) and set(body) == {"data", "meta"}})
    return results


def benchmark(data_dir: Path, res_dir: Path, catalog_path: Path, repeat: int = 1) -> dict[str, Any]:
    """Time request handling and JSON serialization, excluding startup and warmup."""
    if repeat < 1:
        raise ValueError("repeat must be at least one")
    started = perf_counter()
    app = create_app({"DATA_DIR": data_dir, "RES_DIR": res_dir, "CATALOG_PATH": catalog_path})
    startup_ms = (perf_counter() - started) * 1000
    samples = []
    with app.test_client() as client:
        health = client.get("/api/health")
        health_body = health.get_json(silent=True) or {}
        active_health = health_body.get("data", {})
        if health.status_code != 200 or active_health.get("readiness") != "ready":
            raise ValueError("Benchmark requires both prepared catalog and graph to be loaded.")
        for endpoint in ("/api/studies", "/api/runs"):
            if client.get(endpoint).status_code != 200:
                raise ValueError("Warmup query failed.")
        smoke_results = smoke(client)
        for iteration in range(repeat):
            for endpoint, parameters in QUERIES:
                started = perf_counter()
                response = client.get(endpoint, query_string=parameters)
                response.get_data()
                elapsed_ms = (perf_counter() - started) * 1000
                body = response.get_json(silent=True) or {}
                samples.append({"iteration": iteration + 1, "endpoint": endpoint,
                                "parameters": parameters, "elapsed_ms": elapsed_ms,
                                "status": response.status_code,
                                "total": body.get("meta", {}).get("total")})
    ordered = sorted(sample["elapsed_ms"] for sample in samples)
    p95_ms = ordered[math.ceil(len(ordered) * 0.95) - 1]
    return {
        "method": "Flask test client; real prepared services; startup, warmup and smoke requests excluded",
        "percentile": "nearest rank: sorted[ceil(0.95 * count) - 1]",
        "measured_at": datetime.now(UTC).isoformat(),
        "inputs": {"data_dir": str(data_dir), "res_dir": str(res_dir), "catalog_path": str(catalog_path)},
        "python": platform.python_version(), "platform": platform.platform(),
        "startup_ms": startup_ms, "health": active_health,
        "query_count": len(samples), "p95_ms": p95_ms, "max_ms": max(ordered),
        "threshold_ms": 1000,
        "passed": (p95_ms < 1000 and all(sample["status"] == 200 for sample in samples)
                   and all(result["status"] == 200 and result["success_envelope"] for result in smoke_results)),
        "smoke": smoke_results,
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--res-dir", type=Path, default=ROOT / "res")
    parser.add_argument("--catalog-path", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least one")
    result = benchmark(args.data_dir, args.res_dir, args.catalog_path or args.res_dir / "catalog.sqlite", args.repeat)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
