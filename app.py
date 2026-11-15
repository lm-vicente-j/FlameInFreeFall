"""Serve prepared PSI records without changing their scientific review status."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent
ACCESSION = re.compile(r"PSI-[0-9]+")
EVIDENCE = re.compile(r"PSI-[0-9]+:[^#]+#[0-9a-f]{12}")
RUN_ID = re.compile(r"PSI-[0-9]+:[a-z0-9]+(?:-[a-z0-9]+)*:[0-9]+")
RUN_ENUMS = {
    "fuel_class": {"solid", "droplet", "gas"},
    "flow_direction": {"concurrent", "opposed", "quiescent"},
    "outcome": {
        "burn_time", "burning_rate", "extinction_diameter", "test_end",
        "burn_length", "spread_length", "spread_rate", "ignition", "extinction",
        "blowoff", "weight_loss_rate", "flames_ignited", "observation",
    },
}
RUN_BOUNDS = {f"{field}_{bound}" for field in ("o2", "pressure", "flow")
              for bound in ("min", "max")}
RUN_PARAMETERS = set(RUN_ENUMS) | RUN_BOUNDS | {"material", "geometry"}


class RequestFailure(Exception):
    """A contract error with a stable public response."""

    def __init__(self, status: int, code: str, state: str, message: str,
                 resource: str | None = None, parameters: list[str] | None = None,
                 health: dict[str, Any] | None = None):
        self.status = status
        self.body = {"error": {"code": code, "message": message, "details": {
            "state": state, "resource": resource, "parameters": parameters or [],
            "health": health,
        }}}


def _invalid(parameters: list[str]) -> None:
    raise RequestFailure(400, "invalid_parameters", "invalid_parameters",
                         "Invalid path or query parameters.", parameters=sorted(set(parameters)))


def _parameters(allowed: set[str], paginated: bool = False) -> dict[str, Any]:
    allowed = allowed | ({"limit", "offset"} if paginated else set())
    invalid = [key for key in request.args
               if key not in allowed or len(request.args.getlist(key)) != 1]
    if invalid:
        _invalid(invalid)
    values: dict[str, Any] = request.args.to_dict()
    if paginated:
        for key, default, minimum, maximum in (("limit", 20, 1, 100),
                                               ("offset", 0, 0, None)):
            raw = values.get(key, str(default))
            if re.fullmatch(r"[0-9]+", raw) is None:
                _invalid([key])
            try:
                number = int(raw)
            except ValueError:
                _invalid([key])
            if number < minimum or (maximum is not None and number > maximum):
                _invalid([key])
            values[key] = number
    return values


def _identifier(value: str, pattern: re.Pattern[str], name: str) -> None:
    # Flask has already decoded the path. A second decode would change the ID.
    if pattern.fullmatch(value) is None:
        _invalid([name])


def _run_parameters(paginated: bool) -> dict[str, Any]:
    values = _parameters(RUN_PARAMETERS, paginated)
    invalid = []
    for key, value in values.items():
        if ((key in RUN_ENUMS and value not in RUN_ENUMS[key])
                or (key in {"material", "geometry"} and not value.strip())):
            invalid.append(key)
        elif key in RUN_BOUNDS:
            try:
                number = float(value)
            except (ValueError, OverflowError):
                invalid.append(key)
                continue
            if not math.isfinite(number) or number < 0 or (key.startswith("o2_") and number > 100):
                invalid.append(key)
            else:
                values[key] = number
    for field in ("o2", "pressure", "flow"):
        low, high = f"{field}_min", f"{field}_max"
        if (low in values and high in values and low not in invalid and high not in invalid
                and values[low] > values[high]):
            invalid.extend([low, high])
    if invalid:
        _invalid(invalid)
    return values


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Load existing catalog and graph once; keep unavailable services explicit."""
    app = Flask(__name__, static_folder=str(ROOT / "static"))
    app.config.from_mapping(DATA_DIR=ROOT / "data", RES_DIR=ROOT / "res")
    if config:
        app.config.update(config)
    app.config.setdefault("CATALOG_PATH", Path(app.config["RES_DIR"]) / "catalog.sqlite")
    services: dict[str, Any] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for name in ("catalog", "graph"):
        try:
            service: Any
            if name == "catalog":
                from backend.catalog import Catalog

                service = Catalog(Path(app.config["CATALOG_PATH"]))
            elif app.config.get("RUN_GRAPH") is not None:
                service = app.config["RUN_GRAPH"]
            else:
                from backend.graph import RunGraph

                service = RunGraph(Path(app.config["DATA_DIR"]), Path(app.config["RES_DIR"]))
            summary = service.health()
            if summary.get("state") == "unavailable":
                raise ValueError("Prepared dataset unavailable")
            summaries[name] = summary
            services[name] = service
        except Exception:
            # Prepared-data failures must not prevent the other service starting.
            services[name] = None
    app.extensions["psi_services"] = services

    def required(name: str) -> Any:
        if name == "catalog" and services[name] is not None:
            try:
                summaries[name] = services[name].health()
            except (ValueError, OSError):
                raise RequestFailure(503, "data_unavailable", "catalog_unavailable",
                                     "The prepared catalog is unavailable.") from None
        if services[name] is None:
            raise RequestFailure(503, "data_unavailable", f"{name}_unavailable",
                                 f"The prepared {name} is unavailable.")
        return services[name]

    def missing(resource: str) -> None:
        raise RequestFailure(404, "not_found", "unknown_resource",
                             "The requested resource was not found.", resource=resource)

    @app.errorhandler(RequestFailure)
    def contract_error(error: RequestFailure) -> Any:
        return jsonify(error.body), error.status

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception) -> Any:
        if isinstance(error, HTTPException):
            status = error.code or 500
            failure = RequestFailure(status, "not_found" if status == 404 else "invalid_parameters",
                                     "unknown_resource" if status == 404 else "invalid_parameters",
                                     error.name, resource=request.path)
        else:
            failure = RequestFailure(500, "internal_error", "internal_error",
                                     "The request could not be completed.")
        return jsonify(failure.body), failure.status

    @app.get("/")
    def index() -> Any:
        if (ROOT / "static" / "index.html").is_file():
            return send_from_directory(str(ROOT / "static"), "index.html")
        raise RequestFailure(503, "data_unavailable", "frontend_unavailable",
                             "The frontend entry point is unavailable.", resource="/")

    @app.get("/api/studies")
    def studies() -> Any:
        values = _parameters({"q", "safety_category"}, True)
        query = values.get("q", "").strip()
        if len(values.get("q", "")) > 200:
            _invalid(["q"])
        category = values.get("safety_category")
        if category is not None and category not in {"prevention", "detection", "suppression"}:
            _invalid(["safety_category"])
        data, meta = required("catalog").studies(query, category, values["limit"], values["offset"])
        return jsonify(data=data, meta=meta)

    @app.get("/api/studies/<path:accession>/files")
    def files(accession: str) -> Any:
        _identifier(accession, ACCESSION, "accession")
        values = _parameters({"filename", "category", "extension"}, True)
        filename, category, extension = (values.get("filename", ""), values.get("category"),
                                         values.get("extension"))
        invalid = []
        if len(filename) > 200:
            invalid.append("filename")
        if category is not None and not category:
            invalid.append("category")
        if extension is not None and re.fullmatch(r"\.[A-Za-z0-9]+", extension) is None:
            invalid.append("extension")
        if invalid:
            _invalid(invalid)
        catalog = required("catalog")
        if catalog.study(accession) is None:
            missing(accession)
        data, meta = catalog.files(accession, filename, category,
                                   extension.lower() if extension is not None else None,
                                   values["limit"], values["offset"])
        return jsonify(data=data, meta=meta)

    @app.get("/api/studies/<path:accession>")
    def study(accession: str) -> Any:
        _identifier(accession, ACCESSION, "accession")
        _parameters(set())
        catalog = required("catalog")
        data = catalog.study(accession)
        if data is None:
            missing(accession)
        available = all(catalog.evidence(item["id"]) is not None for item in data.get("evidence", []))
        meta = {"evidence_state": "available" if available else "unavailable",
                "source": catalog.source(accession)}
        return jsonify(data=data, meta=meta)

    @app.get("/api/evidence/<path:evidence_id>")
    def evidence(evidence_id: str) -> Any:
        _identifier(evidence_id, EVIDENCE, "id")
        _parameters(set())
        data = required("catalog").evidence(evidence_id)
        if data is None:
            card = required("catalog").study(evidence_id.split(":", 1)[0])
            if card is not None and any(item["id"] == evidence_id for item in card.get("evidence", [])):
                raise RequestFailure(503, "data_unavailable", "evidence_unavailable",
                                     "The known evidence body is unavailable.", resource=evidence_id)
            missing(evidence_id)
        return jsonify(data=data, meta={"state": "available"})

    @app.get("/api/runs")
    def runs() -> Any:
        values = _run_parameters(True)
        limit, offset = values.pop("limit"), values.pop("offset")
        data, meta = required("graph").runs(values, limit, offset)
        return jsonify(data=data, meta=meta)

    @app.get("/api/runs/<path:run_id>")
    def run(run_id: str) -> Any:
        _identifier(run_id, RUN_ID, "id")
        _parameters(set())
        result = required("graph").run(run_id)
        if result is None:
            missing(run_id)
        record, source = result
        from backend.graph import is_provisional

        return jsonify(data=record, meta={"provisional": is_provisional(record),
                                          "source": source})

    @app.get("/api/coverage")
    def coverage() -> Any:
        values = _run_parameters(False)
        data, meta = required("graph").coverage(values)
        return jsonify(data=data, meta=meta)

    @app.get("/api/health")
    def health() -> Any:
        _parameters(set())
        active = {name: dict(summary) for name, summary in summaries.items()}
        if services["catalog"] is not None:
            try:
                active["catalog"] = services["catalog"].health()
            except (ValueError, OSError):
                active.pop("catalog", None)
        catalog, graph = active.get("catalog", {}), active.get("graph", {})
        loaded = len(active)
        dates = [summary["snapshot_date"] for summary in active.values()
                 if summary.get("snapshot_date") is not None]
        data = {
            "readiness": ("unavailable", "degraded", "ready")[loaded],
            "snapshot_date": min(dates) if dates else None,
            "catalog": "loaded" if "catalog" in active else "unavailable",
            "graph": "loaded" if "graph" in active else "unavailable",
            "investigation_count": catalog.get("investigation_count"),
            "run_record_count": graph.get("run_record_count"),
            "verified_run_count": graph.get("verified_run_count"),
        }
        if not loaded:
            raise RequestFailure(503, "data_unavailable", "prepared_data_unavailable",
                                 "No prepared dataset is available.", health=data)
        return jsonify(data=data, meta={"coverage_counts_provisional": graph.get("verified_run_count") is None})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000)
