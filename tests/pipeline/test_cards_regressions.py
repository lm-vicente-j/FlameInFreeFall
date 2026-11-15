"""Regressions for card evidence checks and reproducible pending drafts."""
import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pipeline.cards import _is_intent_only, _quantity_problems, content_fingerprint, finalize, validate
from pipeline.review.cli import main as review_main
from pipeline.review.display import format_card
from pipeline.storage import read_json

ROOT = Path(__file__).resolve().parents[2]


def evidence(text, kind="pdf", field="objective"):
    return {"excerpt": text, "locator": {"kind": kind, "field": field}}


class CardRegressions(unittest.TestCase):
    def test_title_does_not_turn_intent_into_results(self):
        self.assertTrue(_is_intent_only(evidence("Observed flame results", "metadata", "title")))
        self.assertTrue(_is_intent_only(evidence("We aim to observe flames", "metadata")))
        self.assertFalse(_is_intent_only(evidence("We measured flames", "metadata", "description")))

    def test_comparators_are_preserved(self):
        self.assertTrue(_quantity_problems("claim", "> 20 % oxygen", [evidence("< 20 % oxygen")]))
        self.assertFalse(_quantity_problems("claim", "at least twenty percent oxygen",
                                            [evidence(">= 20 percent oxygen")]))

    def test_number_words_are_checked(self):
        self.assertTrue(_quantity_problems("claim", "twenty-one tests", [evidence("20 tests")]))
        self.assertFalse(_quantity_problems("claim", "twenty-one tests", [evidence("21 tests")]))

    def test_conditions_cannot_be_combined_across_clauses(self):
        source = evidence("Sample A used 20 % oxygen at 100 kPa; sample B used 30 % oxygen at 80 kPa.")
        self.assertTrue(_quantity_problems("claim", "Sample A used 20 % oxygen at 80 kPa.", [source]))

    def test_all_saved_drafts_reproduce_saved_cards(self):
        # Finalizing a draft always yields a pending card; the saved card may since have been
        # reviewed. Everything but the review block must match, and an approval must still
        # bind to exactly the content the draft produces.
        for path in sorted((ROOT / "data/drafts").glob("*.json")):
            with self.subTest(path=path.name):
                draft = read_json(path)
                packet = read_json(ROOT / "data/evidence" / path.name)
                card = finalize(draft, packet, datetime.fromisoformat(draft["generation"]["generated_at"]))
                saved = read_json(ROOT / "data/cards" / path.name)
                review = saved.pop("review")
                card.pop("review")
                self.assertEqual(card, saved)
                if review["status"] == "approved":
                    self.assertEqual(review["content_sha256"], content_fingerprint({**card, "review": review}))
        self.assertEqual(len(list((ROOT / "data/drafts").glob("*.json"))), 24)

    def test_source_limitations_require_citations(self):
        card = copy.deepcopy(read_json(ROOT / "data/cards/PSI-69.json"))
        card["limitations"].append({"text": "A source limitation", "basis": "source", "evidence_ids": []})
        self.assertTrue(any("limitation" in e for e in validate(card, read_json(ROOT / "data/evidence/PSI-69.json"))))

    def test_file_keys_must_belong_to_inventory(self):
        card = copy.deepcopy(read_json(ROOT / "data/cards/PSI-69.json"))
        card["modeling_resources"].append({"description": "A resource", "file_keys": ["psi-data/PSI-69/missing"],
                                            "evidence_ids": card["summary"]["evidence_ids"]})
        self.assertTrue(any("inventory" in e for e in validate(card, read_json(ROOT / "data/evidence/PSI-69.json"))))

    def test_review_shows_context_and_all_fields(self):
        card = read_json(ROOT / "data/cards/PSI-69.json")
        rendered = format_card(card, read_json(ROOT / "data/evidence/PSI-69.json"))
        for heading in ("comparison:", "safety categories:", "modeling resources:", "[["):
            self.assertIn(heading, rendered)

    def test_malformed_review_input_is_a_clear_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "card.json"
            path.write_text("{invalid", encoding="utf-8")
            messages = []
            result = review_main(["cards", "--reviewer", "tester", "--path", str(path)], say=messages.append)
            self.assertEqual(result, 1)
            self.assertTrue(any(message.startswith("error:") for message in messages))


if __name__ == "__main__":
    unittest.main()
