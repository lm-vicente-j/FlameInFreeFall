"""Offline regressions for the integration findings in issue #42."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from pipeline import pdf_extract, psi, samples
from pipeline.catalog import RemoteFile
from pipeline.runs.build import check_document
from pipeline.runs.flags import _flex_composition
from pipeline.runs.links import _bass_ii
from pipeline.runs.normalizers.bass_extractions import QueueCell, _check_item, _outcome
from pipeline.runs.normalizers.flex import _outcomes
from pipeline.runs.tables import Row
from pipeline.schema import _timestamp, _uri, schema_errors
from pipeline.storage import read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]


def source_record(name="flex"):
    return read_json(ROOT / "data/runs" / (name + ".json"))["records"][0]


class SourceRecord:
    """A record view for detectors that read only identity, kind and original cells."""
    def __init__(self, original, record_id="PSI-25:bass-ii:1"):
        self.original = original
        self.id = record_id
        self.kind = "run"


class NetworkRegressions(unittest.TestCase):
    def test_signed_response_has_a_size_cap(self):
        with self.assertRaises(psi.UntrustedUrlError):
            psi.resolve_signed_url("PSI-69", "x.pdf", 1,
                                   lambda *_: nullcontext(io.BytesIO(b"x" * 20000)), 1)

    def test_signed_url_with_spaces_is_rejected(self):
        with self.assertRaises(psi.UntrustedUrlError):
            psi.resolve_signed_url("PSI-69", "x.pdf", 1,
                                   lambda *_: nullcontext(io.BytesIO(b"https://psi-repo-prod.s3.amazonaws.com/a b")), 1)

    def test_404_is_not_retried(self):
        attempts = []
        def missing(*_):
            attempts.append(1)
            raise HTTPError("https://psi.nasa.gov/", 404, "Missing", {}, None)
        with self.assertRaises(HTTPError) as caught:
            psi.resolve_signed_url("PSI-69", "x.pdf", 1, missing, 1, lambda _: None)
        caught.exception.close()
        self.assertEqual(len(attempts), 1)

    def test_redirect_cannot_leave_the_allowlist(self):
        with self.assertRaises(psi.UntrustedUrlError):
            psi._TrustedRedirects().redirect_request(None, None, 302, "Found", {}, "https://example.com/file")

    def test_budget_counts_api_bytes_and_persists_between_runs(self):
        file = RemoteFile("PSI-69", "file", "psi-data/PSI-69/Reports/x.pdf", 1, 3, "Reports", None, False, True)
        item = samples.PlannedItem(file, "evidence", "A source-backed PDF for development")
        signed = b"https://psi-repo-prod.s3.amazonaws.com/x.pdf"
        requests = []
        def opener(url, _timeout):
            requests.append(url)
            return nullcontext(io.BytesIO(signed if url.startswith(psi.API) else b"pdf"))
        with tempfile.TemporaryDirectory() as folder, patch.object(samples, "plan", return_value=[item]):
            root = Path(folder)
            saved = root / "res/PSI-69"
            saved.mkdir(parents=True)
            write_json_atomic(saved / "metadata.json", {"version": 5})
            write_json_atomic(saved / "files.json", [])
            write_json_atomic(saved / "provenance.json", [{"retrieved_at": "2026-11-15T00:00:00Z"}])
            args = ({"budget_bytes": 1000}, root / "res", root / "samples", root)
            clock = lambda: datetime(2026, 11, 15, tzinfo=UTC)
            manifest = samples.run(*args, None, opener, clock, sleep=lambda _: None)
            self.assertEqual(manifest["transferred_bytes"], len(signed) + 3)
            self.assertEqual(manifest["files"][0]["status"], "downloaded")
            self.assertIn("source_url", manifest["files"][0])
            cached = samples.run(*args, manifest, opener, clock)
            self.assertEqual(cached["transferred_bytes"], 0)
            self.assertEqual(cached["cumulative_transferred_bytes"], manifest["transferred_bytes"])
            self.assertEqual(len(requests), 2)
            (root / "samples/PSI-69/x.pdf").unlink()
            manifest["cumulative_transferred_bytes"] = 999
            exhausted = samples.run(*args, manifest, opener, clock)
            self.assertEqual(exhausted["files"][0]["status"], "failed")
            self.assertEqual(len(requests), 2)

    def test_deadline_is_checked_before_another_read(self):
        response = samples._CountingResponse(io.BytesIO(b"x"), [0], 10, 1)
        with patch.object(samples.time, "monotonic", return_value=2), self.assertRaises(TimeoutError):
            response.read(1)


class ValidationRegressions(unittest.TestCase):
    def test_invalid_dates_and_uris_are_rejected_without_optional_packages(self):
        self.assertFalse(_timestamp("not-a-date"))
        self.assertFalse(_uri("relative/path"))
        self.assertTrue(_timestamp("2026-11-15T00:00:00Z"))
        self.assertTrue(_uri("https://psi.nasa.gov/example"))
        manifest = {"generated_at": "not-a-date", "budget_bytes": 1, "transferred_bytes": 0, "files": []}
        self.assertTrue(schema_errors(manifest, "sample-manifest"))

    def test_budget_cannot_exceed_the_project_cap(self):
        selection = read_json(ROOT / "data/sample_selection.json")
        selection["budget_bytes"] = 250000001
        self.assertTrue(schema_errors(selection, "sample-selection"))

    def test_lone_surrogates_round_trip_without_losing_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.json"
            write_json_atomic(path, {"text": "before\ud800after"})
            self.assertEqual(read_json(path)["text"], "before\ud800after")

    def test_pdf_cli_reports_failure_with_a_nonzero_exit(self):
        summary = pdf_extract.DocumentSummary("PSI-69", "file", 1, "failed", None, 0, "broken", Path("x.json"))
        with patch.object(pdf_extract, "read_json", return_value={}), \
                patch.object(pdf_extract, "extract_all", return_value=[summary]), patch("builtins.print"):
            self.assertEqual(pdf_extract.main([]), 1)

    def test_reversed_and_nonfinite_quantity_bounds_fail_import_validation(self):
        table = read_json(ROOT / "data/runs/flex.json")
        broken = copy.deepcopy(table)
        broken["records"][0]["conditions"]["o2_percent"].update(min=30, max=20)
        self.assertTrue(schema_errors(broken, "run-table"))
        with self.assertRaises(ValueError):
            check_document(broken)
        broken["records"][0]["conditions"]["o2_percent"]["min"] = float("nan")
        self.assertTrue(schema_errors(broken, "run-table"))


class RunRegressions(unittest.TestCase):
    def test_rounded_fractions_and_recorded_argon_are_counted(self):
        cells = {"O initial ambient composition; mole fraction": "0.20",
                 "N initial ambient composition; mole fraction": "0.79",
                 "CO initial ambient composition; mole fraction": "0",
                 "He initial ambient composition; mole fraction": "0"}
        self.assertEqual(list(_flex_composition(SourceRecord(cells))), [])
        cells["N initial ambient composition; mole fraction"] = "0.60"
        cells["Ar initial ambient composition; mole fraction"] = "0.20"
        self.assertEqual(list(_flex_composition(SourceRecord(cells))), [])
        cells["Ar initial ambient composition; mole fraction"] = "0.80"
        self.assertTrue(list(_flex_composition(SourceRecord(cells))))

    def test_flex_rate_with_unknown_unit_is_not_a_measurement(self):
        raw = source_record()["original"]
        outcomes = _outcomes(Row(1, raw))
        rate = next(outcome for outcome in outcomes if outcome.type == "burning_rate")
        self.assertIsNone(rate.result.minimum)

    def test_negative_events_remain_observations(self):
        item = {"model": None, "proposed_by": "llm", "review": {"status": "pending"}}
        proposed = {"type": "blowoff", "gravity": "microgravity", "quote": "Did not blow out",
                    "result": {"kind": "category", "value": "Did not blow out"}}
        self.assertEqual(_outcome(item, "Air display", proposed).type, "observation")

    def test_extraction_is_bound_to_its_exact_column(self):
        cell = QueueCell("PSI-25:bass-ii:1", "Air display", "10 max")
        item = {"record_id": cell.record_id, "column": "Fan display", "source_text": cell.source_text,
                "proposal": {"outcomes": [], "readings": []}}
        with self.assertRaises(ValueError):
            _check_item(Path("proposal.json"), item, [cell])

    def test_file_for_a_different_test_is_not_an_ambiguous_candidate(self):
        record = SourceRecord({"Sample #": "131", "Test #": "T1"})
        wrong = RemoteFile("PSI-25", "wrong", "psi-data/PSI-25/Raw/SAMPLE_131_TEST_T2.csv", 1,
                           1, "Raw Data", None, False, True)
        right = RemoteFile("PSI-25", "right", "psi-data/PSI-25/Raw/SAMPLE_131_TEST_T1.csv", 1,
                           1, "Raw Data", None, False, True)
        self.assertEqual([link.file_id for _, link in _bass_ii([record], [wrong, right])], ["right"])

    def test_bass_cells_and_calibration_unknown_are_preserved(self):
        records = read_json(ROOT / "data/runs/bass.json")["records"]
        joined = next(record for record in records if record["kind"] == "run")
        self.assertTrue(any("!Air display" in key for key in joined["original"]))
        self.assertTrue(any(key.endswith("!@sha256") for key in joined["original"]))
        self.assertIsNone(joined["conditions"]["flow_cm_s"]["min"])


if __name__ == "__main__":
    unittest.main()
