"""Regression checks for source-preserving RDF queries and cautious coverage counts."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from rdflib.namespace import DCTERMS, PROV, RDF

from backend.graph import BASE, QUDT, SCHEMA, SOSA, RunGraph
from pipeline.schema import schema_errors


def category(value: str | None, status: str = "approved") -> dict:
    return {"value": value, "method": "manual" if value is not None else "unknown", "columns": [],
            "review_status": status, "quote": None, "note": None}


def quantity(low: float | None, high: float | None = None, unit: str = "percent") -> dict:
    return {"min": low, "max": low if high is None else high, "unit": unit, "qualifier": None,
            "method": "parsed" if low is not None else "unknown", "columns": [],
            "review_status": "not_required", "quote": None, "note": None}


def record(row: int, kind: str = "run", material: str | None = "cotton") -> dict:
    return {
        "id": f"PSI-1:sample:{row}", "kind": kind, "row": row, "original": {"source": str(row)},
        "conditions": {
            "fuel_class": category("solid"), "material": category(material), "geometry": category("sheet"),
            "flow_direction": category("opposed"), "diluent": category("nitrogen"),
            "o2_percent": quantity(20, 25), "pressure_kpa": quantity(100, unit="kPa"),
            "flow_cm_s": quantity(1, 5, unit="cm/s"),
        },
        "outcomes": [{"type": "burn_time", "gravity": gravity, "result": quantity(value, unit="s")}
                     for gravity, value in (("microgravity", 4), ("normal", 2))],
        "flags": [], "links": [], "review_status": "approved",
    }


def document(records: list[dict]) -> dict:
    return {
        "table": "sample", "investigation": "PSI-1",
        "source": {"filename": "sample.csv", "sha256": "a" * 64, "encoding": "utf-8", "columns": ["source"]},
        "counts": {**{plural: sum(item["kind"] == kind for item in records)
                      for kind, plural in (("run", "runs"), ("range", "ranges"),
                                           ("session", "sessions"), ("note", "notes"))},
                   "duplicate_rows": sum(any(flag["code"] == "duplicate_row" for flag in item["flags"])
                                         for item in records), "empty_rows_skipped": 0},
        "records": records,
    }


class RunGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "data" / "runs").mkdir(parents=True)
        (self.root / "res" / "PSI-1").mkdir(parents=True)
        (self.root / "res" / "PSI-1" / "metadata.json").write_text(
            json.dumps({"experimentHardware": "exact hardware"}), encoding="utf-8"
        )

    def load(self, records: list[dict], hardware: bool = True) -> RunGraph:
        (self.root / "data" / "runs" / "sample.json").write_text(json.dumps(document(records)), encoding="utf-8")
        return RunGraph(self.root / "data", self.root / "res" if hardware else None)

    def test_source_rows_and_paired_gravity_remain_separate(self) -> None:
        original = record(1)
        graph = self.load([original, record(2, "note")])
        row = BASE[f"row/{quote(original['id'], safe='')}"]
        self.assertIn((row, RDF.type, PROV.Entity), graph.graph)
        self.assertNotIn((row, RDF.type, SOSA.Observation), graph.graph)
        observations = list(graph.graph.subjects(SOSA.hasFeatureOfInterest, row))
        self.assertEqual(len(observations), 2)
        self.assertEqual({str(value) for node in observations
                          for value in graph.graph.objects(node, DCTERMS.description)
                          if str(value).startswith("gravity=")},
                         {"gravity=normal", "gravity=microgravity"})
        values, meta = graph.runs({})
        self.assertEqual(values[0], original)
        values[0]["original"]["source"] = "changed"
        self.assertEqual(graph.run(original["id"])[0], original)
        self.assertEqual(meta["total"], 2)
        self.assertEqual(meta["count_basis"], "source_records")
        self.assertEqual(graph.run(original["id"])[1]["table"], "sample")
        flow = BASE[f"row/{quote(original['id'], safe='')}/condition/flow_cm_s"]
        self.assertEqual(str(graph.graph.value(flow, SCHEMA.minValue)), "1")
        self.assertEqual(str(graph.graph.value(flow, SCHEMA.maxValue)), "5")

    def test_numeric_filters_overlap_sweeps_inclusively(self) -> None:
        graph = self.load([record(1)])
        for filters in ({"flow_min": 5}, {"flow_max": 1}, {"o2_min": 25, "o2_max": 25},
                        {"pressure_min": 100, "pressure_max": 100}, {"outcome": "burn_time"}):
            self.assertEqual(graph.runs(filters)[1]["total"], 1, filters)
        self.assertEqual(graph.runs({"flow_min": 5.01})[1]["total"], 0)
        self.assertEqual(graph.runs({"material": 'cotton" } UNION { ?s ?p ?o } # '})[1]["total"], 0)
        for filters in ({"o2_min": float("nan")}, {"o2_max": float("inf")}, {"flow_min": "1"},
                        {"flow_min": 5, "flow_max": 1}, {"gravity": "normal"}):
            with self.assertRaises(ValueError):
                graph.runs(filters)

    def test_unknowns_have_provenance_without_fabricated_measurements(self) -> None:
        item = record(1, material=None)
        item["conditions"]["flow_cm_s"] = quantity(None, unit="cm/s")
        item["conditions"]["flow_cm_s"]["min"] = 1
        item["outcomes"].append({"type": "burning_rate", "gravity": "microgravity",
                                 "result": quantity(None, unit="unknown")})
        graph = self.load([item], hardware=False)
        row = BASE[f"row/{quote(item['id'], safe='')}"]
        node = BASE[f"row/{quote(item['id'], safe='')}/condition/flow_cm_s"]
        self.assertIn((node, PROV.wasDerivedFrom, row), graph.graph)
        self.assertFalse(list(graph.graph.objects(node, QUDT.numericValue)))
        self.assertFalse(list(graph.graph.objects(node, SCHEMA.minValue)))
        self.assertFalse(list(graph.graph.objects(node, SCHEMA.maxValue)))
        self.assertEqual(graph.runs({"flow_min": 0})[1]["total"], 0)
        coverage, _ = graph.coverage({})
        self.assertEqual(coverage["coverage_status"], "unknown_conditions")
        self.assertEqual(coverage["groups"][0]["comparison_status"], "indeterminate")
        self.assertEqual(graph.coverage({"flow_min": 1, "o2_min": 90})[0]["coverage_status"], "unknown_conditions")

    def test_coverage_counts_kinds_duplicates_and_invalid_rows(self) -> None:
        duplicate = record(2)
        duplicate["flags"] = [{"code": "duplicate_row", "columns": [], "detail": "Same cells as row 1"}]
        invalid = record(3)
        invalid["flags"] = [{"code": "invalid_reading", "columns": [], "detail": "Invalid source reading"}]
        graph = self.load([record(1), duplicate, invalid, record(4, "range"), record(5, "session"), record(6, "note")])
        coverage, _ = graph.coverage({})
        counts = coverage["counts"]
        self.assertEqual(counts["source_records"], 6)
        self.assertEqual(counts["run_records"], 3)
        self.assertEqual(counts["distinct_run_records"], 2)
        self.assertEqual(counts["duplicate_rows"], 1)
        self.assertEqual(counts["excluded_quality_records"], 1)
        self.assertEqual(counts["verified_run_count"], 1)
        self.assertEqual(coverage["groups"][0]["run_record_count"], 1)
        self.assertEqual(graph.health()["run_record_count"], 6)
        self.assertEqual(graph.health()["verified_run_count"], 1)

    def test_pending_review_never_proves_absence(self) -> None:
        item = record(1)
        item["review_status"] = "pending"
        item["conditions"]["material"]["review_status"] = "pending"
        graph = self.load([item])
        coverage, meta = graph.coverage({"o2_min": 90})
        self.assertEqual(coverage["counts"]["source_records"], 0)
        self.assertEqual(coverage["coverage_status"], "pending_review")
        self.assertTrue(meta["provisional"])
        self.assertEqual(graph.coverage({"material": "unreviewed-other-alias"})[0]["coverage_status"], "pending_review")
        self.assertEqual(graph.health()["verified_run_count"], 0)

    def test_comparisons_require_equal_known_categories_and_hardware(self) -> None:
        graph = self.load([record(1), record(2, material="PMMA"), record(3, material=None)])
        coverage, _ = graph.coverage({})
        self.assertEqual(len(coverage["groups"]), 3)
        comparisons = coverage["comparisons"]
        self.assertIn("incompatible", {pair["status"] for pair in comparisons})
        self.assertIn("indeterminate", {pair["status"] for pair in comparisons})
        self.assertEqual(coverage["groups"][0]["conditions"]["hardware"], "exact hardware")

    def test_distinct_hardware_is_never_assumed_equivalent(self) -> None:
        other = document([record(1)])
        other["investigation"] = "PSI-2"
        other["records"][0]["id"] = "PSI-2:sample:1"
        other["source"]["sha256"] = "b" * 64
        (self.root / "data" / "runs" / "other.json").write_text(json.dumps(other), encoding="utf-8")
        (self.root / "res" / "PSI-2").mkdir()
        (self.root / "res" / "PSI-2" / "metadata.json").write_text(
            json.dumps({"experimentHardware": "Exact hardware"}), encoding="utf-8"
        )
        graph = self.load([record(1)])
        coverage, _ = graph.coverage({})
        self.assertEqual(len(coverage["groups"]), 2)
        self.assertEqual(coverage["comparisons"][0]["status"], "incompatible")
        self.assertEqual(coverage["comparisons"][0]["differing_fields"], ["hardware"])

    def test_loader_preserves_schema_rejections_and_numeric_semantics(self) -> None:
        invalid_values = [
            {"extra": "not allowed"}, {"method": "mapped", "review_status": "not_required"},
            {"method": "parsed", "review_status": "pending"}, {"method": "llm", "quote": None},
        ]
        for changes in invalid_values:
            item = record(1)
            item["conditions"]["material"].update(changes)
            with self.subTest(changes=changes):
                self.assertTrue(schema_errors(document([item]), "run-table"))
                with self.assertRaises(ValueError):
                    self.load([item])
        for changes in ({"min": 25, "max": 20}, {"initial": float("nan")}, {"max": float("inf")}):
            item = record(1)
            item["conditions"]["o2_percent"].update(changes)
            with self.subTest(changes=changes):
                self.assertTrue(schema_errors(document([item]), "run-table"))
                with self.assertRaises(ValueError):
                    self.load([item])

    def test_missing_snapshot_and_bad_documents_are_distinct(self) -> None:
        graph = RunGraph(self.root / "missing")
        self.assertEqual(graph.health()["state"], "unavailable")
        self.assertIsNone(graph.health()["verified_run_count"])
        with self.assertRaises(RuntimeError):
            graph.runs({})
        data = document([record(1)])
        data["counts"]["runs"] = 2
        (self.root / "data" / "runs" / "sample.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            RunGraph(self.root / "data")
        data = document([record(1), copy.deepcopy(record(1))])
        (self.root / "data" / "runs" / "sample.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            RunGraph(self.root / "data")

    def test_reviewed_empty_region_is_explicit_and_no_bins_are_invented(self) -> None:
        graph = self.load([record(1)])
        coverage, meta = graph.coverage({"o2_min": 50, "o2_max": 60, "pressure_min": 90})
        self.assertEqual(coverage["coverage_status"], "not_in_PSI")
        self.assertEqual(coverage["region"]["o2_percent"], {"min": 50, "max": 60})
        self.assertEqual(coverage["groups"], [])
        self.assertEqual(meta["scope"], "saved_PSI_snapshot")
        self.assertFalse(meta["provisional"])


if __name__ == "__main__":
    unittest.main()
