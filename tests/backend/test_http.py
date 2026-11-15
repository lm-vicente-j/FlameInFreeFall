"""Exercise HTTP validation, dataset readiness and unchanged response records."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

import app as application


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence_id = "PSI-69:meta:objective#0693c364c63b"
        self.evidence = {"id": self.evidence_id, "excerpt": "Exact source text."}
        self.card = {"accession": "PSI-69", "evidence": [self.evidence],
                     "review_status": "pending"}
        self.record = {"id": "PSI-69:flex:1", "review_status": "pending", "conditions": {},
                       "outcomes": [{"gravity": "microgravity", "result": {"review_status": "pending"}},
                                    {"gravity": "normal", "result": {"review_status": "pending"}}]}
        self.source = {"investigation": {"accession": "PSI-69"},
                       "table": {"slug": "flex"}, "source": {"filename": "FLEX.csv"}}
        self.catalog = Mock()
        self.catalog.health.return_value = {"investigation_count": 2, "snapshot_date": "2026-11-14"}
        self.catalog.studies.return_value = ([self.card], {"total": 1, "limit": 20, "offset": 0})
        self.catalog.study.side_effect = lambda accession: self.card if accession == "PSI-69" else None
        self.catalog.evidence.side_effect = lambda identifier: self.evidence if identifier == self.evidence_id else None
        self.catalog.files.return_value = ([], {"total": 0, "limit": 20, "offset": 0})
        self.source_summary = {"accession": "PSI-69", "doi": "10.60555/mbq8-0451"}
        self.catalog.source.side_effect = lambda accession: self.source_summary if accession == "PSI-69" else None
        self.graph = Mock()
        self.graph.health.return_value = {"run_record_count": 6, "verified_run_count": 0,
                                          "snapshot_date": "2026-11-15"}
        self.graph.runs.return_value = ([self.record], {"total": 1, "provisional": True,
                                                       "sources": [self.source]})
        self.graph.run.side_effect = lambda identifier: (
            (self.record, self.source) if identifier == self.record["id"] else None)
        self.graph.coverage.return_value = ({"state": "available", "verified_run_count": 0},
                                           {"scope": "saved_PSI_snapshot"})

    def make_app(self, catalog_available: bool = True, graph_available: bool = True):
        catalog_class = Mock(return_value=self.catalog)
        if not catalog_available:
            catalog_class.side_effect = FileNotFoundError("private path")
        graph_class = Mock(return_value=self.graph)
        if not graph_available:
            graph_class.side_effect = ValueError("private graph failure")
        with patch.dict("sys.modules", {
            "backend.catalog": SimpleNamespace(Catalog=catalog_class),
            "backend.graph": SimpleNamespace(RunGraph=graph_class),
        }):
            result = application.create_app({"TESTING": True})
        self.catalog_class, self.graph_class = catalog_class, graph_class
        return result

    def assert_error(self, response, status: int, code: str, state: str | None = None):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(set(response.json), {"error"})
        self.assertEqual(set(response.json["error"]), {"code", "message", "details"})
        self.assertEqual(response.json["error"]["code"], code)
        self.assertEqual(set(response.json["error"]["details"]),
                         {"state", "resource", "parameters", "health"})
        if state:
            self.assertEqual(response.json["error"]["details"]["state"], state)

    def test_study_search_passes_literal_trimmed_text_and_preserves_cards(self):
        client = self.make_app().test_client()
        response = client.get("/api/studies", query_string={"q": "  droplet OR:*  ",
                              "safety_category": "prevention", "limit": "3", "offset": "2"})
        self.assertEqual(response.status_code, 200)
        self.catalog.studies.assert_called_once_with("droplet OR:*", "prevention", 3, 2)
        self.assertEqual(response.json["data"], [self.card])
        self.assertEqual(set(response.json), {"data", "meta"})

    def test_validation_precedes_dataset_availability(self):
        client = self.make_app(False, False).test_client()
        invalid_urls = [
            "/api/studies?limit=0", "/api/studies?limit=101", "/api/studies?offset=-1",
            "/api/studies?limit=1.0", "/api/studies?limit=1&limit=2",
            "/api/studies?unknown=x", "/api/studies?safety_category=unknown",
            "/api/studies?q=" + "a" * 201, "/api/studies/invalid",
            "/api/studies/PSI-69?limit=1", "/api/studies/PSI-69/files?extension=csv",
            "/api/studies/PSI-69/files?category=", "/api/studies/PSI-69/files?filename=" + "a" * 201,
            "/api/studies/bad/files", "/api/evidence/not-an-id", "/api/runs/not-an-id",
            "/api/runs?fuel_class=plasma", "/api/runs?flow_direction=upward",
            "/api/runs?outcome=unknown", "/api/runs?material=", "/api/runs?geometry=%20",
            "/api/runs?o2_min=nan", "/api/runs?flow_min=inf", "/api/runs?o2_max=101",
            "/api/runs?pressure_min=-1", "/api/runs?flow_min=abc",
            "/api/runs?o2_min=21&o2_max=20", "/api/runs?pressure_min=2&pressure_max=1",
            "/api/runs?flow_min=2&flow_max=1", "/api/runs?gravity=microgravity",
            "/api/coverage?limit=1", "/api/coverage?o2_min=nan", "/api/health?unknown=1",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assert_error(client.get(url), 400, "invalid_parameters")

    def test_supported_requests_distinguish_unavailable_and_empty(self):
        client = self.make_app(False, False).test_client()
        for url in ("/api/studies", "/api/studies/PSI-999", "/api/studies/PSI-999/files",
                    "/api/runs", "/api/runs/PSI-69:flex:1", "/api/coverage"):
            with self.subTest(url=url):
                self.assert_error(client.get(url), 503, "data_unavailable")
        self.catalog.studies.return_value = ([], {"total": 0})
        self.graph.runs.return_value = ([], {"total": 0})
        client = self.make_app().test_client()
        for url in ("/api/studies?offset=100", "/api/studies/PSI-69/files?filename=absent", "/api/runs?offset=100"):
            self.assertEqual(client.get(url).json["data"], [])
        self.assert_error(client.get("/api/studies/PSI-999/files"), 404, "not_found")

    def test_evidence_decodes_once_and_preserves_exact_record(self):
        client = self.make_app().test_client()
        encoded = quote(self.evidence_id, safe="")
        response = client.get("/api/evidence/" + encoded)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"data": self.evidence, "meta": {"state": "available"}})
        self.assert_error(client.get("/api/evidence/" + quote(encoded, safe="")), 400, "invalid_parameters")
        self.assert_error(client.get("/api/evidence/" + quote("PSI-69:unknown#000000000000", safe="")),
                          404, "not_found")

    def test_known_missing_evidence_is_unavailable_and_card_is_unchanged(self):
        self.catalog.evidence.side_effect = None
        self.catalog.evidence.return_value = None
        client = self.make_app().test_client()
        response = client.get("/api/studies/PSI-69")
        self.assertEqual(response.json, {"data": self.card, "meta": {"evidence_state": "unavailable",
                                                                       "source": self.source_summary}})
        self.assert_error(client.get("/api/evidence/" + quote(self.evidence_id, safe="")),
                          503, "data_unavailable", "evidence_unavailable")

    def test_study_detail_adds_source_beside_unchanged_card(self):
        client = self.make_app().test_client()
        response = client.get("/api/studies/PSI-69")
        self.assertEqual(response.json["data"], self.card)
        self.assertEqual(response.json["meta"], {"evidence_state": "available", "source": self.source_summary})
        self.source_summary = None
        self.assertIsNone(client.get("/api/studies/PSI-69").json["meta"]["source"])

    def test_files_use_parent_lookup_and_normalized_extension(self):
        client = self.make_app().test_client()
        response = client.get("/api/studies/PSI-69/files?extension=.CSV&category=Table&filename=Flex")
        self.assertEqual(response.status_code, 200)
        self.catalog.files.assert_called_once_with("PSI-69", "Flex", "Table", ".csv", 20, 0)

    def test_run_filters_are_typed_and_coverage_keeps_service_metadata(self):
        client = self.make_app().test_client()
        response = client.get("/api/runs?fuel_class=droplet&o2_min=20&o2_max=21&flow_min=0&limit=1")
        self.assertEqual(response.json["data"], [self.record])
        self.graph.runs.assert_called_once_with({"fuel_class": "droplet", "o2_min": 20.0,
                                                "o2_max": 21.0, "flow_min": 0.0}, 1, 0)
        response = client.get("/api/coverage?pressure_max=100")
        self.graph.coverage.assert_called_once_with({"pressure_max": 100.0})
        self.assertEqual(response.json["meta"], {"scope": "saved_PSI_snapshot"})

    def test_run_detail_keeps_source_outside_unchanged_record(self):
        client = self.make_app().test_client()
        response = client.get("/api/runs/PSI-69:flex:1")
        self.assertEqual(response.json, {"data": self.record, "meta": {"source": self.source,
                                                                      "provisional": True}})
        self.assert_error(client.get("/api/runs/PSI-69:flex:99"), 404, "not_found")

    def test_run_approval_requires_complete_review(self):
        client = self.make_app().test_client()
        self.record["review_status"] = "approved"
        self.assertTrue(client.get("/api/runs/PSI-69:flex:1").json["meta"]["provisional"])
        for outcome in self.record["outcomes"]:
            outcome["result"]["review_status"] = "approved"
        self.assertFalse(client.get("/api/runs/PSI-69:flex:1").json["meta"]["provisional"])

    def test_graph_explicit_unavailable_state_is_not_loaded(self):
        self.graph.health.return_value = {"state": "unavailable", "run_record_count": None,
                                          "verified_run_count": None, "snapshot_date": None}
        client = self.make_app().test_client()
        self.assertEqual(client.get("/api/health").json["data"]["graph"], "unavailable")
        self.assert_error(client.get("/api/runs"), 503, "data_unavailable")

    def test_health_reports_real_counts_and_all_readiness_states(self):
        for catalog_available, graph_available, state in ((True, True, "ready"),
                (True, False, "degraded"), (False, True, "degraded"), (False, False, "unavailable")):
            with self.subTest(state=state, catalog=catalog_available):
                client = self.make_app(catalog_available, graph_available).test_client()
                response = client.get("/api/health")
                data = response.json["data"] if state != "unavailable" else response.json["error"]["details"]["health"]
                self.assertEqual(response.status_code, 503 if state == "unavailable" else 200)
                self.assertEqual(data["readiness"], state)
                self.assertEqual(data["investigation_count"], 2 if catalog_available else None)
                self.assertEqual(data["run_record_count"], 6 if graph_available else None)
                self.assertEqual(data["verified_run_count"], 0 if graph_available else None)

    def test_catalog_health_follows_atomic_replacement_and_graph_loads_once(self):
        client = self.make_app().test_client()
        self.catalog.health.return_value = {"investigation_count": 3, "snapshot_date": "2026-11-13"}
        self.assertEqual(client.get("/api/health").json["data"]["investigation_count"], 3)
        self.assertEqual(client.get("/api/health").json["data"]["snapshot_date"], "2026-11-13")
        self.graph_class.assert_called_once()
        self.graph.health.assert_called_once()
        self.catalog.health.side_effect = FileNotFoundError("private deleted database")
        self.assertEqual(client.get("/api/health").json["data"]["readiness"], "degraded")
        self.assert_error(client.get("/api/studies"), 503, "data_unavailable")

    def test_unexpected_errors_hide_private_details(self):
        self.catalog.studies.side_effect = RuntimeError("secret path and traceback")
        response = self.make_app().test_client().get("/api/studies")
        self.assert_error(response, 500, "internal_error")
        self.assertNotIn("secret", response.get_data(as_text=True))

    def test_frontend_and_static_assets_are_served_only_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "static").mkdir()
            (root / "static" / "sample.js").write_text("const original = true;", encoding="utf-8")
            with patch.object(application, "ROOT", root):
                client = self.make_app().test_client()
                self.assert_error(client.get("/"), 503, "data_unavailable", "frontend_unavailable")
                response = client.get("/static/sample.js")
                self.assertEqual(response.get_data(as_text=True), "const original = true;")
                response.close()
                (root / "static" / "index.html").write_text("<title>Existing frontend</title>", encoding="utf-8")
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Existing frontend", response.get_data(as_text=True))
                response.close()


if __name__ == "__main__":
    unittest.main()
