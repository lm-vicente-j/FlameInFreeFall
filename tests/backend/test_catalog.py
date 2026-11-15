"""Exercise real saved PSI inputs without network access or scientific approval."""

import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.catalog import Catalog, CatalogError, build_catalog
from scripts.download_metadata import flatten_files

ROOT = Path(__file__).resolve().parents[2]
ACCESSIONS = ("PSI-47", "PSI-100", "PSI-142")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data, self.res = self.root / "data", self.root / "res"
        self.db = self.res / "catalog.sqlite"
        for kind in ("cards", "evidence"):
            (self.data / kind).mkdir(parents=True)
            for accession in ACCESSIONS:
                shutil.copyfile(ROOT / "data" / kind / f"{accession}.json", self.data / kind / f"{accession}.json")
        for accession in ACCESSIONS:
            (self.res / accession).mkdir(parents=True)
            for name in ("metadata.json", "files.json", "provenance.json"):
                shutil.copyfile(
                    ROOT / "data" / "fixtures" / "backend" / "catalog" / accession / name, self.res / accession / name
                )

    def build(self, **kwargs):
        return build_catalog(self.db, self.data, self.res, **kwargs)

    def alter_source(self, accession, name, mutate):
        path = self.res / accession / name
        value = read(path)
        mutate(value)
        write(path, value)
        provenance_path = self.res / accession / "provenance.json"
        provenance = read(provenance_path)
        for entry in provenance:
            if entry["file"] == name:
                entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                entry["response_bytes"] = len(path.read_bytes())
        write(provenance_path, provenance)

    def test_missing_database_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            Catalog(self.db)
        self.assertFalse(self.db.exists())

    def test_full_saved_catalog_and_unchanged_records(self):
        counts = self.build()
        expected = sum(len(flatten_files(read(self.res / accession / "files.json"))) for accession in ACCESSIONS)
        self.assertEqual(counts["remote_files"], expected)
        catalog = Catalog(self.db)
        self.assertEqual(catalog.health()["investigation_count"], len(ACCESSIONS))
        for accession in ACCESSIONS:
            card = read(self.data / "cards" / f"{accession}.json")
            self.assertEqual(catalog.study(accession), card)
            for item in card["evidence"]:
                self.assertEqual(catalog.evidence(item["id"]), item)
        self.assertIsNone(catalog.study("PSI-99999"))
        self.assertIsNone(catalog.evidence("unknown"))
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT count(*) FROM scientific_search").fetchone()[0], 3)
            self.assertIsInstance(
                json.loads(connection.execute("SELECT source_json FROM remote_files LIMIT 1").fetchone()[0]), dict
            )

    def test_idempotence_and_same_version_update(self):
        first = self.build()
        self.assertEqual(self.build(), first)
        card_path = self.data / "cards" / "PSI-47.json"
        card = read(card_path)
        card["review"]["notes"] = "Pending review; wording changed for this import test."
        write(card_path, card)
        self.assertEqual(self.build(), first)
        self.assertEqual(Catalog(self.db).study("PSI-47"), card)

    def test_subset_import_retains_other_studies_and_files(self):
        original = self.build()
        for accession in ("PSI-100", "PSI-142"):
            (self.data / "cards" / f"{accession}.json").unlink()
        self.assertEqual(self.build(), original)
        self.assertIsNotNone(Catalog(self.db).study("PSI-100"))

    def test_invalid_replacement_preserves_last_good_database(self):
        self.build()
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        path = self.data / "cards" / "PSI-47.json"
        card = read(path)
        card["summary"]["evidence_ids"] = ["missing"]
        write(path, card)
        with self.assertRaises(CatalogError):
            self.build()
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), digest)
        self.assertEqual(Catalog(self.db).health()["investigation_count"], 3)

    def test_source_hash_failure_and_pending_release_gate(self):
        self.build()
        card_path = self.data / "cards" / "PSI-47.json"
        card = read(card_path)
        # Exercise the pending gate explicitly, independent of source review updates.
        card["review"] = {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": ""}
        write(card_path, card)
        with self.assertRaises(CatalogError):
            self.build(allow_pending=False)
        with (self.res / "PSI-47" / "metadata.json").open("ab") as output:
            output.write(b" ")
        with self.assertRaises(CatalogError):
            self.build()
        self.assertIsNotNone(Catalog(self.db).study("PSI-47"))

    def test_packet_passage_cannot_change_saved_metadata(self):
        self.build()
        packet_path = self.data / "evidence" / "PSI-47.json"
        packet = read(packet_path)
        packet["passages"][0]["text"] += " Unverified appended source text."
        write(packet_path, packet)
        with self.assertRaisesRegex(CatalogError, "differs from saved source"):
            self.build()

    def test_literal_queries_and_stable_pagination(self):
        self.build()
        catalog = Catalog(self.db)
        cards, meta = catalog.studies(q="  DAFT  ")
        self.assertEqual([card["accession"] for card in cards], ["PSI-47"])
        self.assertEqual(meta["query"], "DAFT")
        self.assertEqual(meta["matches"][0]["rank"], 1)
        self.assertGreater(meta["matches"][0]["score"], 0)
        for query in ("DAFT OR impossibleword", 'DAFT"; DROP TABLE cards; --', "title:DAFT", "*", '"', "NEAR(DAFT)"):
            self.assertEqual(catalog.studies(q=query)[0], [], query)
        all_cards, metadata = catalog.studies()
        self.assertEqual(metadata["matches"], [])
        self.assertEqual([card["accession"] for card in all_cards], list(ACCESSIONS))
        pieces = [catalog.studies(limit=1, offset=index)[0][0] for index in range(3)]
        self.assertEqual(pieces, all_cards)
        self.assertEqual(catalog.studies(offset=999)[0], [])
        self.assertEqual(catalog.studies(q="DAFT", safety_category="suppression")[0], [])

    def test_file_filters_are_literal_independent_and_stable(self):
        self.build()
        catalog = Catalog(self.db)
        files, meta = catalog.files("PSI-47", limit=100)
        expected = sorted(
            files, key=lambda item: (item["filename"].casefold(), item["filename"], item["file_id"], item["version"])
        )
        self.assertEqual(files, expected)
        self.assertEqual(meta["total"], 33)
        selected = files[0]
        matching, meta = catalog.files(
            "PSI-47", filename=selected["filename"].upper(), extension=selected["extension"].upper()
        )
        self.assertIn(selected, matching)
        if selected["category"]:
            self.assertIn(selected, catalog.files("PSI-47", category=selected["category"].swapcase())[0])
        self.assertEqual(catalog.files("PSI-47", filename="%_")[0], [])
        pieces = [catalog.files("PSI-47", limit=1, offset=index)[0][0] for index in range(len(files))]
        self.assertEqual(pieces, files)
        with self.assertRaises(KeyError):
            catalog.files("PSI-99999")

    def test_approved_phrase_aliases_combine_with_literal_terms(self):
        self.build()
        catalog = Catalog(self.db)
        first = catalog.studies(q="detection measurement")[0]
        second = catalog.studies(q="smoke sensing measurement")[0]
        self.assertEqual(first, second)
        self.assertEqual(catalog.studies(q="suppression")[0], catalog.studies(q="extinguishment")[0])

    def test_replacement_failure_and_live_reader_generation(self):
        self.build()
        reader = Catalog(self.db)
        old = self.db.read_bytes()
        with patch("backend.catalog.os.replace", side_effect=PermissionError("busy")), self.assertRaises(CatalogError):
            self.build()
        self.assertEqual(self.db.read_bytes(), old)
        self.alter_source("PSI-47", "metadata.json", lambda value: value.update(version=value["version"] + 1))
        card_path = self.data / "cards" / "PSI-47.json"
        card = read(card_path)
        card["source_version"] += 1
        # A changed source version invalidates this temporary card's approval.
        card["review"] = {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": ""}
        write(card_path, card)
        packet_path = self.data / "evidence" / "PSI-47.json"
        packet = read(packet_path)
        packet["metadata_version"] += 1
        write(packet_path, packet)
        self.build()
        self.assertEqual(reader.study("PSI-47")["source_version"], card["source_version"])
        self.alter_source("PSI-47", "metadata.json", lambda value: value.update(version=value["version"] - 1))
        card["source_version"] -= 1
        write(card_path, card)
        packet["metadata_version"] -= 1
        write(packet_path, packet)
        with self.assertRaises(CatalogError):
            self.build()

    def test_evidence_collision_is_rejected_after_semantic_validation(self):
        self.build()
        card_path = self.data / "cards" / "PSI-47.json"
        card = read(card_path)
        card["evidence"][0]["locator"] = copy.deepcopy(card["evidence"][0]["locator"])
        # Isolate the persistence collision gate from the upstream validator.
        card["evidence"][0]["source_url"] += "?changed"
        write(card_path, card)
        with (
            patch("backend.catalog.validate", return_value=[]),
            self.assertRaisesRegex(CatalogError, "Evidence ID collision"),
        ):
            self.build()

    def test_invalid_pagination_and_query_values(self):
        self.build()
        catalog = Catalog(self.db)
        for kwargs in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": True}, {"q": "x" * 201}):
            with self.assertRaises(ValueError):
                catalog.studies(**kwargs)
        with self.assertRaises(ValueError):
            catalog.files("PSI-47", extension="csv")


if __name__ == "__main__":
    unittest.main()
