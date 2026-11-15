"""Validate actual Flask/service responses against the active offline contract.

Tracked metadata snapshots and current prepared records are copied unchanged
into an isolated fixture. They represent selected studies, not all of PSI.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from app import create_app
from backend.catalog import Catalog, build_catalog
from backend.graph import RunGraph
from pipeline.schema import FORMATS

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"
SPEC = ROOT / "docs" / "contracts" / "openapi-current.json"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


class ActiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.data, cls.res = cls.root / "data", cls.root / "res"
        cls.db = cls.res / "catalog.sqlite"
        cls.spec = read(SPEC)
        resources = [(SPEC.resolve().as_uri(), Resource(cls.spec, DRAFT202012))]
        for path in sorted((ROOT / "pipeline" / "schemas").glob("*.schema.json")):
            schema = read(path)
            resource = Resource.from_contents(schema)
            resources.extend(((schema["$id"], resource), (path.resolve().as_uri(), resource)))
        cls.registry = Registry().with_resources(resources)
        cls.cards = {}
        for accession in ("PSI-47", "PSI-100", "PSI-142"):
            for kind in ("cards", "evidence"):
                value = read(ROOT / "data" / kind / f"{accession}.json")
                write(cls.data / kind / f"{accession}.json", value)
                if kind == "cards":
                    cls.cards[accession] = value
            shutil.copytree(FIXTURES / "backend" / "catalog" / accession, cls.res / accession)
        cls.original_rows = []
        for path in sorted((FIXTURES / "runs").glob("*.json")):
            value = read(path)
            write(cls.data / "runs" / path.name, value)
            cls.original_rows.extend(value["records"])
        build_catalog(cls.db, cls.data, cls.res)
        catalog = Catalog(cls.db)
        cls.remote = [item for accession in cls.cards for item in catalog.files(accession, limit=100)[0]]
        cls.graph = RunGraph(cls.data, cls.res)
        cls.application = create_app(
            {"TESTING": True, "DATA_DIR": cls.data, "RES_DIR": cls.res, "CATALOG_PATH": cls.db, "RUN_GRAPH": cls.graph}
        )

    def setUp(self) -> None:
        self.client = self.application.test_client()

    def validator(self, path: str, status: int = 200) -> Draft202012Validator:
        schema = self.spec["paths"][path]["get"]["responses"][str(status)]["content"]["application/json"]["schema"]
        # An absolute outer reference establishes the OpenAPI document's base URI.
        pointer = "/paths/" + path.replace("~", "~0").replace("/", "~1")
        pointer += f"/get/responses/{status}/content/application~1json/schema"
        validator = Draft202012Validator(
            {"$ref": SPEC.resolve().as_uri() + "#" + pointer}, registry=self.registry, format_checker=FORMATS
        )
        Draft202012Validator.check_schema(schema)
        return validator

    def assert_contract(self, response: Any, path: str, status: int = 200) -> Any:
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(response.mimetype, "application/json")
        body = response.get_json()
        errors = sorted(self.validator(path, status).iter_errors(body), key=lambda error: str(error.path))
        self.assertEqual(errors, [], "\n".join(f"{error.json_path}: {error.message}" for error in errors))
        return body

    def test_all_eight_routes_validate_real_service_responses(self) -> None:
        card = self.cards["PSI-47"]
        evidence_id = card["evidence"][0]["id"]
        runs, _ = self.graph.runs({})
        cases = [
            ("/api/studies", "/api/studies"),
            ("/api/studies?q=droplet", "/api/studies"),
            ("/api/studies/PSI-47", "/api/studies/{accession}"),
            ("/api/studies/PSI-47/files?extension=.CSV", "/api/studies/{accession}/files"),
            ("/api/evidence/" + quote(evidence_id, safe=""), "/api/evidence/{id}"),
            ("/api/runs", "/api/runs"),
            ("/api/runs/" + quote(runs[0]["id"], safe=""), "/api/runs/{id}"),
            ("/api/coverage?o2_min=20&o2_max=30", "/api/coverage"),
            ("/api/health", "/api/health"),
        ]
        for url, path in cases:
            with self.subTest(url=url):
                self.assert_contract(self.client.get(url), path)

    def test_cards_evidence_files_and_source_rows_are_unchanged(self) -> None:
        for accession, card in self.cards.items():
            body = self.assert_contract(self.client.get(f"/api/studies/{accession}"), "/api/studies/{accession}")
            self.assertEqual(body["data"], card)
            evidence = card["evidence"][0]
            body = self.assert_contract(
                self.client.get("/api/evidence/" + quote(evidence["id"], safe="")), "/api/evidence/{id}"
            )
            self.assertEqual(body["data"], evidence)
            files = self.assert_contract(
                self.client.get(f"/api/studies/{accession}/files?limit=100"), "/api/studies/{accession}/files"
            )
            self.assertEqual(files["data"], [item for item in self.remote if item["accession"] == accession])
        response = self.assert_contract(self.client.get("/api/runs?limit=100"), "/api/runs")
        self.assertEqual(response["data"], self.original_rows)

    def test_filters_empty_pages_and_zero_verified_count_validate(self) -> None:
        for url, path in (
            ("/api/studies?offset=999", "/api/studies"),
            ("/api/studies/PSI-47/files?filename=absent", "/api/studies/{accession}/files"),
            ("/api/runs?o2_min=20&o2_max=21&flow_min=0&limit=2", "/api/runs"),
            ("/api/runs?material=not-a-saved-material", "/api/runs"),
            ("/api/coverage?o2_min=99&pressure_max=1", "/api/coverage"),
        ):
            with self.subTest(url=url):
                self.assert_contract(self.client.get(url), path)
        health = self.assert_contract(self.client.get("/api/health"), "/api/health")
        self.assertEqual(health["data"]["verified_run_count"], 0)
        self.assertEqual(health["data"]["graph"], "loaded")
        self.assertFalse(health["meta"]["coverage_counts_provisional"])

    def test_validation_missing_resources_and_unavailable_data_errors_validate(self) -> None:
        for url, path, status in (
            ("/api/studies?limit=0", "/api/studies", 400),
            ("/api/studies?q=a&q=b", "/api/studies", 400),
            ("/api/studies/PSI-999", "/api/studies/{accession}", 404),
            ("/api/studies/PSI-999/files", "/api/studies/{accession}/files", 404),
            ("/api/evidence/" + quote("PSI-69:unknown#000000000000", safe=""), "/api/evidence/{id}", 404),
            ("/api/runs/PSI-69:flex:999999", "/api/runs/{id}", 404),
            ("/api/runs?o2_min=30&o2_max=20", "/api/runs", 400),
            ("/api/runs?gravity=normal", "/api/runs", 400),
            ("/api/coverage?pressure_min=nan", "/api/coverage", 400),
        ):
            with self.subTest(url=url):
                self.assert_contract(self.client.get(url), path, status)
        unavailable = create_app(
            {
                "TESTING": True,
                "DATA_DIR": self.root / "missing-data",
                "RES_DIR": self.root / "missing-res",
                "CATALOG_PATH": self.root / "missing.sqlite",
            }
        ).test_client()
        for path in ("/api/studies", "/api/runs", "/api/coverage", "/api/health"):
            with self.subTest(unavailable=path):
                self.assert_contract(unavailable.get(path), path, 503)

    def test_degraded_health_does_not_invent_graph_counts(self) -> None:
        client = create_app(
            {"TESTING": True, "DATA_DIR": self.root / "missing-data", "RES_DIR": self.res, "CATALOG_PATH": self.db}
        ).test_client()
        body = self.assert_contract(client.get("/api/health"), "/api/health")
        self.assertEqual(body["data"]["readiness"], "degraded")
        self.assertIsNone(body["data"]["verified_run_count"])

    def test_service_failure_uses_the_public_error_contract(self) -> None:
        catalog = self.application.extensions["psi_services"]["catalog"]
        with patch.object(catalog, "studies", side_effect=RuntimeError("private diagnostic")):
            body = self.assert_contract(self.client.get("/api/studies"), "/api/studies", 500)
        self.assertEqual(body["error"]["code"], "internal_error")
        self.assertNotIn("private diagnostic", json.dumps(body))

    def test_active_schemas_reject_changed_records_and_impossible_counts(self) -> None:
        original = self.client.get("/api/studies/PSI-47").get_json()
        changed = copy.deepcopy(original)
        changed["data"]["invented_field"] = True
        self.assertFalse(self.validator("/api/studies/{accession}").is_valid(changed))
        health = self.client.get("/api/health").get_json()
        health["data"]["verified_run_count"] = None
        self.assertFalse(self.validator("/api/health").is_valid(health))
        coverage = self.client.get("/api/coverage").get_json()
        coverage["data"]["counts"]["verified_run_count"] = -1
        self.assertFalse(self.validator("/api/coverage").is_valid(coverage))

    def test_active_routes_and_external_references_are_current(self) -> None:
        expected = {
            "/api/studies",
            "/api/studies/{accession}",
            "/api/studies/{accession}/files",
            "/api/evidence/{id}",
            "/api/runs",
            "/api/runs/{id}",
            "/api/coverage",
            "/api/health",
        }
        self.assertEqual(set(self.spec["paths"]), expected)
        for schema in self.spec["components"]["schemas"].values():
            Draft202012Validator.check_schema(schema)
        serialized = json.dumps(self.spec)
        self.assertNotIn('"$ref": "schemas/', serialized)
        self.assertEqual(self.spec["x-search-review"]["status"], "approved")
        for name in ("Card", "Evidence", "Run"):
            self.assertTrue(self.spec["components"]["schemas"][name]["$ref"].startswith("../../pipeline/schemas/"))
        self.assertIsInstance(self.application.extensions["psi_services"]["catalog"], Catalog)
        self.assertIs(self.application.extensions["psi_services"]["graph"], self.graph)


if __name__ == "__main__":
    unittest.main()
