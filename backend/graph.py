"""Load prepared source rows into RDF without approving their scientific interpretation."""

from __future__ import annotations

import copy
import json
import math
import threading
from collections import Counter, defaultdict
from decimal import Decimal
from functools import cache
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jsonschema import Draft202012Validator
from rdflib import Graph, Literal, Namespace, URIRef, Variable
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS, SKOS, XSD
from rdflib.plugins.sparql import prepareQuery
from referencing import Registry, Resource

from pipeline.paths import SCHEMAS
from pipeline.schema import FORMATS, schema_errors

BASE = Namespace("https://flameinfreefall.local/resource/")
VOCAB = Namespace("https://flameinfreefall.local/vocab/")
SSN = Namespace("http://www.w3.org/ns/ssn/")
SOSA = Namespace("http://www.w3.org/ns/sosa/")
QUDT = Namespace("http://qudt.org/schema/qudt/")
UNIT = Namespace("http://qudt.org/vocab/unit/")
SCHEMA = Namespace("https://schema.org/")
UNITS = {
    "percent": UNIT.PERCENT, "kPa": UNIT.KiloPA, "cm/s": UNIT["CentiM-PER-SEC"],
    "s": UNIT.SEC, "mm": UNIT.MilliM, "cm": UNIT.CentiM, "mm/s": UNIT["MilliM-PER-SEC"],
}
CATEGORIES = ("fuel_class", "material", "geometry", "flow_direction")
NUMERIC = {"o2": "o2_percent", "pressure": "pressure_kpa", "flow": "flow_cm_s"}
GROUP_FIELDS = (*CATEGORIES, "hardware")
QUALITY_EXCLUSIONS = {"invalid_reading", "inconsistent_values", "suspected_typo", "references_other_rows"}
PREFIXES = """
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ssn: <http://www.w3.org/ns/ssn/>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX sosa: <http://www.w3.org/ns/sosa/>
PREFIX schema: <https://schema.org/>
"""
# All query text is fixed. User values enter only through initBindings.
CATEGORY_QUERY = PREFIXES + """
SELECT DISTINCT ?row WHERE {
  ?row ssn:hasProperty ?property .
  ?property dct:identifier ?field ; rdf:value ?wanted .
}
"""
NUMERIC_QUERY = PREFIXES + """
SELECT DISTINCT ?row WHERE {
  ?row ssn:hasProperty ?property .
  ?property dct:identifier ?field ; schema:minValue ?lo ; schema:maxValue ?hi .
  FILTER ((!BOUND(?minimum) || ?hi >= ?minimum) && (!BOUND(?maximum) || ?lo <= ?maximum))
}
"""
OUTCOME_QUERY = PREFIXES + """
SELECT DISTINCT ?row WHERE {
  ?observation sosa:hasFeatureOfInterest ?row ; sosa:observedProperty ?wanted .
}
"""
# rdflib parses SPARQL with a shared pyparsing grammar that is not thread-safe: two requests parsing
# at once can corrupt it for the life of the process. Parse each fixed query once, at import, and
# evaluate under a lock because Flask serves requests on several threads.
_PREPARED = {text: prepareQuery(text) for text in (CATEGORY_QUERY, NUMERIC_QUERY, OUTCOME_QUERY)}
_QUERY_LOCK = threading.Lock()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


@cache
def _record_validator() -> Draft202012Validator:
    """Compile the same value constraints without repeated unevaluated-property traversal."""
    schema = json.loads((SCHEMAS / "run-table.schema.json").read_text(encoding="utf-8"))
    provenance = schema["$defs"]["provenance"]
    for name in ("category", "quantity"):
        value = schema["$defs"][name]
        value["allOf"] = copy.deepcopy(provenance["allOf"])
        value["properties"].update(copy.deepcopy(provenance["properties"]))
        value["required"].extend(provenance["required"])
        value["additionalProperties"] = value.pop("unevaluatedProperties")
    common = json.loads((SCHEMAS / "common.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources([(common["$id"], Resource.from_contents(common))])
    schema["$ref"] = "#/$defs/record"
    # The root envelope applies only to the envelope validation below.
    for name in ("properties", "required", "additionalProperties"):
        schema.pop(name, None)
    return Draft202012Validator(schema, registry=registry, format_checker=FORMATS)


def _known(value: dict[str, Any]) -> bool:
    if value["method"] == "unknown":
        return False
    if "value" in value:
        return isinstance(value["value"], str) and bool(value["value"].strip())
    return value.get("unit") in UNITS and all(
        isinstance(value.get(bound), (int, float)) and math.isfinite(value[bound])
        for bound in ("min", "max")
    ) and value["min"] <= value["max"]


def _flags(record: dict[str, Any]) -> set[str]:
    return {flag["code"] for flag in record["flags"]}


def _reviewed(record: dict[str, Any]) -> bool:
    values = [*record["conditions"].values(), *(outcome["result"] for outcome in record["outcomes"])]
    return record["review_status"] == "approved" and all(
        value["review_status"] in {"approved", "not_required"} for value in values
    )


def _verified(record: dict[str, Any]) -> bool:
    return (record["kind"] == "run" and _reviewed(record)
            and not (_flags(record) & (QUALITY_EXCLUSIONS | {"duplicate_row"})))


def is_provisional(record: dict[str, Any]) -> bool:
    """Whether a source record still lacks explicit, complete scientific approval."""
    return not _reviewed(record)


class RunGraph:
    """One validated prepared snapshot, its RDF graph, and source-preserving queries."""

    def __init__(self, data_dir: Path, res_dir: Path | None = None):
        self.graph = Graph()
        self._records: dict[str, dict[str, Any]] = {}
        self._sources: dict[str, dict[str, Any]] = {}
        self._hardware: dict[str, str | None] = {}
        self._uris: dict[str, str] = {}
        self.available = False
        runs_dir = data_dir / "runs"
        if not runs_dir.is_dir():
            return
        paths = sorted(runs_dir.glob("*.json"))
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        for document in documents:
            self._validate(document)
        for document in documents:
            accession = document["investigation"]
            if accession not in self._hardware:
                self._hardware[accession] = self._load_hardware(res_dir, accession)
            self._add_document(document)
        self.available = bool(paths)

    @staticmethod
    def _load_hardware(res_dir: Path | None, accession: str) -> str | None:
        if res_dir is None:
            return None
        path = res_dir / accession / "metadata.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8")).get("experimentHardware")
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _validate(document: dict[str, Any]) -> None:
        errors = schema_errors({**document, "records": []}, "run-table")
        if errors:
            raise ValueError(f"Invalid run table: {'; '.join(errors[:3])}")
        records = document["records"]
        validator = _record_validator()
        for record in records:
            error = next(validator.iter_errors(record), None)
            if error is not None:
                raise ValueError(f"Invalid source record at {error.json_path}: {error.message}")
            values = [*record["conditions"].values(), *(outcome["result"] for outcome in record["outcomes"])]
            for value in values:
                for bound in ("min", "max", "initial", "final"):
                    number = value.get(bound)
                    if isinstance(number, float) and not math.isfinite(number):
                        raise ValueError("Non-finite source measurement")
                low, high = value.get("min"), value.get("max")
                if low is not None and high is not None and low > high:
                    raise ValueError("Reversed source measurement bounds")
        if len({record["id"] for record in records}) != len(records):
            raise ValueError("Duplicate record IDs in run table")
        counts = Counter(record["kind"] for record in records)
        for kind, key in (("run", "runs"), ("range", "ranges"), ("session", "sessions"), ("note", "notes")):
            if counts[kind] != document["counts"][key]:
                raise ValueError(f"Incorrect {key} count")
        if sum("duplicate_row" in _flags(record) for record in records) != document["counts"]["duplicate_rows"]:
            raise ValueError("Incorrect duplicate_rows count")
        for record in records:
            expected = f"{document['investigation']}:{document['table']}:{record['row']}"
            if record["id"] != expected:
                raise ValueError(f"Record ID does not match its source row: {record['id']}")

    def _provenance(self, node: URIRef, row: URIRef, value: dict[str, Any]) -> None:
        self.graph.add((node, RDF.type, PROV.Entity))
        self.graph.add((node, PROV.wasDerivedFrom, row))
        activity = BASE[f"activity/{value['method']}"]
        self.graph.add((activity, RDF.type, PROV.Activity))
        self.graph.add((node, PROV.wasGeneratedBy, activity))
        self.graph.add((node, PROV.value, Literal(_json(value))))

    def _quantity(self, node: URIRef, value: dict[str, Any]) -> None:
        self.graph.add((node, RDF.type, QUDT.QuantityValue))
        self.graph.add((node, QUDT.unit, UNITS[value["unit"]]))
        # Exact bound indexes avoid aggregating the two bound resources on every request.
        self.graph.add((node, SCHEMA.minValue, Literal(Decimal(str(value["min"])), datatype=XSD.decimal)))
        self.graph.add((node, SCHEMA.maxValue, Literal(Decimal(str(value["max"])), datatype=XSD.decimal)))
        if value["min"] == value["max"]:
            self.graph.add((node, QUDT.numericValue, Literal(Decimal(str(value["min"])), datatype=XSD.decimal)))
        # Bounds also index points, so one fixed query handles inclusive sweep overlap.
        for bound in ("min", "max"):
            part = URIRef(f"{node}/{bound}")
            self.graph.add((node, DCTERMS.hasPart, part))
            self.graph.add((part, RDF.type, QUDT.QuantityValue))
            self.graph.add((part, DCTERMS.identifier, Literal(bound)))
            self.graph.add((part, QUDT.unit, UNITS[value["unit"]]))
            self.graph.add((part, QUDT.numericValue, Literal(Decimal(str(value[bound])), datatype=XSD.decimal)))
        if value["qualifier"]:
            self.graph.add((node, DCTERMS.description, Literal(f"qualifier={value['qualifier']}")))

    def _add_document(self, document: dict[str, Any]) -> None:
        source = {key: document[key] for key in ("investigation", "table", "source")}
        source_uri = BASE[f"source/sha256/{document['source']['sha256']}"]
        investigation = BASE[f"investigation/{document['investigation']}"]
        self.graph.add((source_uri, RDF.type, PROV.Entity))
        self.graph.add((source_uri, DCTERMS.title, Literal(document["source"]["filename"])))
        self.graph.add((source_uri, DCTERMS.identifier, Literal(document["source"]["sha256"])))
        self.graph.add((source_uri, PROV.value, Literal(_json(source))))
        for record in document["records"]:
            identifier = record["id"]
            if identifier in self._records:
                raise ValueError(f"Duplicate record ID across tables: {identifier}")
            row = BASE[f"row/{quote(identifier, safe='')}"]
            self._records[identifier] = record
            self._sources[identifier] = source
            self._uris[str(row)] = identifier
            self.graph.add((row, RDF.type, PROV.Entity))
            self.graph.add((row, DCTERMS.identifier, Literal(identifier)))
            self.graph.add((row, PROV.wasDerivedFrom, source_uri))
            self.graph.add((row, DCTERMS.isPartOf, investigation))
            self.graph.add((row, PROV.value, Literal(_json(record))))
            for field, value in record["conditions"].items():
                node = URIRef(f"{row}/condition/{field}")
                self._provenance(node, row, value)
                if not _known(value):
                    continue
                self.graph.add((row, SSN.hasProperty, node))
                self.graph.add((node, RDF.type, SSN.Property))
                self.graph.add((node, DCTERMS.identifier, Literal(field)))
                if "value" in value:
                    self.graph.add((node, RDF.value, Literal(value["value"])))
                    if field == "material" or (field == "fuel_class" and value["review_status"] == "approved"):
                        kind = "material" if field == "material" else "fuel"
                        concept = VOCAB[f"{kind}/{quote(value['value'], safe='')}"]
                        self.graph.add((row, DCTERMS.subject, concept))
                        self.graph.add((concept, RDF.type, SKOS.Concept))
                        self.graph.add((concept, RDFS.label, Literal(value["value"])))
                else:
                    self._quantity(node, value)
            for index, outcome in enumerate(record["outcomes"]):
                observation = URIRef(f"{row}/outcome/{index}")
                result = URIRef(f"{observation}/result")
                value = outcome["result"]
                self._provenance(result, row, value)
                if not _known(value):
                    continue
                property_uri = VOCAB[f"outcome/{outcome['type']}"]
                self.graph.add((observation, RDF.type, SOSA.Observation))
                self.graph.add((observation, SOSA.hasFeatureOfInterest, row))
                self.graph.add((observation, SOSA.observedProperty, property_uri))
                self.graph.add((property_uri, RDF.type, SOSA.ObservableProperty))
                self.graph.add((observation, SOSA.hasResult, result))
                self.graph.add((observation, DCTERMS.description, Literal(f"gravity={outcome['gravity']}")))
                self.graph.add((observation, DCTERMS.description, Literal(
                    "Source-reported outcome; scientific review is recorded in the result provenance."
                )))
                if "value" in value:
                    self.graph.add((result, RDF.type, SOSA.Result))
                    self.graph.add((result, RDF.value, Literal(value["value"])))
                else:
                    self._quantity(result, value)

    def health(self) -> dict[str, Any]:
        records = list(self._records.values())
        return {
            "state": "available" if self.available else "unavailable",
            "run_record_count": len(records) if self.available else None,
            "verified_run_count": sum(map(_verified, records)) if self.available else None,
            "snapshot_date": None,
        }

    @staticmethod
    def _validate_filters(filters: dict[str, Any]) -> None:
        allowed = {*CATEGORIES, "outcome", *(f"{name}_{bound}" for name in NUMERIC for bound in ("min", "max"))}
        if set(filters) - allowed:
            raise ValueError("Unsupported filter")
        for key, value in filters.items():
            if key in CATEGORIES or key == "outcome":
                if not isinstance(value, str) or not value:
                    raise ValueError(f"Invalid {key}")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Invalid numeric filter {key}")
        for prefix in NUMERIC:
            minimum, maximum = filters.get(f"{prefix}_min"), filters.get(f"{prefix}_max")
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"Reversed {prefix} bounds")

    def _select(self, filters: dict[str, Any]) -> list[str]:
        self._validate_filters(filters)
        if not self.available:
            raise RuntimeError("Prepared run graph is unavailable")
        selected = set(self._records)
        queries: list[tuple[str, dict[str, Any]]] = []
        for field in CATEGORIES:
            if field in filters:
                queries.append((CATEGORY_QUERY, {"field": Literal(field), "wanted": Literal(filters[field])}))
        for prefix, field in NUMERIC.items():
            bindings = {"field": Literal(field)}
            for bound, variable in (("min", "minimum"), ("max", "maximum")):
                if f"{prefix}_{bound}" in filters:
                    bindings[variable] = Literal(Decimal(str(filters[f"{prefix}_{bound}"])), datatype=XSD.decimal)
            if len(bindings) > 1:
                queries.append((NUMERIC_QUERY, bindings))
        if "outcome" in filters:
            queries.append((OUTCOME_QUERY, {"wanted": VOCAB[f"outcome/{quote(filters['outcome'], safe='')}"]}))
        for query, bindings in queries:
            with _QUERY_LOCK:
                rows = self.graph.query(_PREPARED[query], initBindings=bindings).bindings
            matches = {self._uris[str(result[Variable("row")])] for result in rows}
            selected.intersection_update(matches)
            if not selected:
                return []
        return sorted(selected, key=lambda identifier: (
            int(identifier.split(":")[0].split("-")[1]), identifier.split(":")[1], int(identifier.split(":")[2])
        ))

    def _source_list(self, identifiers: list[str]) -> list[dict[str, Any]]:
        sources = {_json(self._sources[identifier]): self._sources[identifier] for identifier in identifiers}
        return copy.deepcopy(list(sources.values()))

    def runs(
        self, filters: dict[str, Any], limit: int = 20, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if (isinstance(limit, bool) or isinstance(offset, bool)
                or not isinstance(limit, int) or not isinstance(offset, int)):
            raise ValueError("Pagination must use integers")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination bounds")
        identifiers = self._select(filters)
        page = identifiers[offset:offset + limit]
        return copy.deepcopy([self._records[identifier] for identifier in page]), {
            "total": len(identifiers), "limit": limit, "offset": offset, "count_basis": "source_records",
            "sources": self._source_list(page),
            "provisional": any(not _reviewed(self._records[identifier]) for identifier in identifiers),
        }

    def run(self, identifier: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if not self.available:
            raise RuntimeError("Prepared run graph is unavailable")
        if identifier not in self._records:
            return None
        return copy.deepcopy((self._records[identifier], self._sources[identifier]))

    def _group(self, identifier: str) -> tuple[str | None, ...]:
        record = self._records[identifier]
        return (*(record["conditions"][field]["value"] if _known(record["conditions"][field]) else None
                  for field in CATEGORIES),
                self._hardware[self._sources[identifier]["investigation"]])

    def coverage(self, filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        identifiers = self._select(filters)
        records = [self._records[identifier] for identifier in identifiers]
        distinct = [identifier for identifier in identifiers if self._records[identifier]["kind"] == "run"
                    and "duplicate_row" not in _flags(self._records[identifier])]
        eligible = [identifier for identifier in distinct
                    if not (_flags(self._records[identifier]) & QUALITY_EXCLUSIONS)]
        grouped: dict[tuple[str | None, ...], list[str]] = defaultdict(list)
        for identifier in eligible:
            grouped[self._group(identifier)].append(identifier)
        groups: list[dict[str, Any]] = []
        for conditions, members in sorted(grouped.items(), key=lambda item: _json(item[0])):
            known = all(value is not None for value in conditions)
            complete = known and all(
                _known(self._records[identifier]["conditions"][field])
                for identifier in members for field in ("o2_percent", "pressure_kpa", "flow_cm_s")
            )
            reviewed = all(_reviewed(self._records[identifier]) for identifier in members)
            groups.append({
                "conditions": dict(zip(GROUP_FIELDS, conditions, strict=True)),
                "comparison_status": "compatible" if known else "indeterminate",
                "review_status": "reviewed" if reviewed else "pending",
                "run_record_count": len(members),
                "verified_run_count": sum(_verified(self._records[identifier]) for identifier in members),
                "coverage_status": (
                    "pending_review" if not reviewed else "covered" if complete else "unknown_conditions"
                ),
            })
        comparisons = []
        for left, right in combinations(range(len(groups)), 2):
            a, b = groups[left]["conditions"], groups[right]["conditions"]
            differing = [field for field in GROUP_FIELDS if a[field] is not None and b[field] is not None
                         and a[field] != b[field]]
            comparisons.append({"group_indices": [left, right],
                                "status": "incompatible" if differing else "indeterminate",
                                "differing_fields": differing})
        # Empty matches cannot establish absence while the surrounding saved corpus is unreviewed or incomplete.
        context_filters = {key: value for key, value in filters.items() if key not in {
            "o2_min", "o2_max", "pressure_min", "pressure_max"
        }}
        context = self._select(context_filters)
        context_runs = [identifier for identifier in context if self._records[identifier]["kind"] == "run"
                        and "duplicate_row" not in _flags(self._records[identifier])]
        if not context_runs or not eligible:
            # An empty match can exclude unresolved aliases, outcomes, or unknown numeric conditions.
            # Those saved rows must still block a verified absence claim.
            context_runs = [identifier for identifier, record in self._records.items()
                            if record["kind"] == "run" and "duplicate_row" not in _flags(record)]
        pending = any(not _reviewed(self._records[identifier]) for identifier in context_runs)
        unknown = any(
            any(value is None for value in self._group(identifier))
            or any(not _known(self._records[identifier]["conditions"][field])
                   for field in ("o2_percent", "pressure_kpa", "flow_cm_s"))
            or bool(_flags(self._records[identifier]) & QUALITY_EXCLUSIONS)
            for identifier in context_runs
        )
        status = ("pending_review" if pending else "unknown_conditions" if unknown
                  else "covered" if eligible else "not_in_PSI")
        kinds = Counter(record["kind"] for record in records)
        counts = {
            "source_records": len(records), "run_records": kinds["run"], "distinct_run_records": len(distinct),
            "range_records": kinds["range"], "session_records": kinds["session"], "note_records": kinds["note"],
            "duplicate_rows": sum("duplicate_row" in _flags(record) for record in records),
            "verified_run_count": sum(map(_verified, records)),
            "pending_review_records": sum(not _reviewed(self._records[identifier]) for identifier in distinct),
            "unknown_condition_records": sum(
                any(value is None for value in self._group(identifier))
                or any(not _known(self._records[identifier]["conditions"][field])
                       for field in ("o2_percent", "pressure_kpa", "flow_cm_s")) for identifier in distinct
            ),
            "excluded_quality_records": len(distinct) - len(eligible),
        }
        return {"state": "available", "coverage_status": status,
                "region": {field: {"min": filters.get(f"{prefix}_min"), "max": filters.get(f"{prefix}_max")}
                           for prefix, field in (("o2", "o2_percent"), ("pressure", "pressure_kpa"))},
                "counts": counts, "groups": groups, "comparisons": comparisons}, {
                    "count_basis": "distinct_run_records", "scope": "saved_PSI_snapshot",
                    "provisional": pending or unknown, "sources": self._source_list(identifiers),
                }
