"""Finalize and validate research cards against evidence packets.

The research-card skill (an LLM run outside the app) cannot compute hashes, so it
writes a *draft* (``research-card-draft`` schema) that cites local refs ``E1``,
``E2``... ``finalize`` turns the draft into a research card by taking every
fact that can be computed or copied from the evidence packet (ids, locators,
source URL, title, version, coverage), so the model cannot get them wrong.

``validate`` is the audit gate. Beyond the JSON schema it enforces that:
- every excerpt occurs EXACTLY (character for character) in the cited passage,
- every number in a statement occurs in an excerpt that statement cites,
- observations are not supported only by intent text (objective, hypothesis,
  expected impacts), because PLAN.md forbids presenting those as measured results.

``finalize`` locates a draft excerpt in the passage tolerantly (NFKC and collapsed
whitespace, because the skill cannot reproduce pypdf line breaks and ligatures) but
stores the exact original substring of the passage. The evidence id suffix is the
backend contract's recipe (docs/contracts/STORAGE.md, PR #39): collapse whitespace
with ``" ".join(excerpt.split())``, UTF-8, SHA-256, first 12 hex characters; no NFKC.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.schema import schema_errors
from pipeline.storage import read_json, write_json_atomic

CORE_INVESTIGATIONS = ("PSI-25", "PSI-98", "PSI-101", "PSI-69")
MIN_EXCERPT_CHARACTERS = 20
_INTENT_FIELDS = ("objective", "hypothesis", "researchImpacts")

class CardError(ValueError):
    """A draft or card is invalid; ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def normalize_text(text: str) -> str:
    """NFKC plus collapsed whitespace. For *comparing* text only; never stored or hashed."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def content_fingerprint(card: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the card content a reviewer approves.

    Canonical JSON: sorted keys, compact separators, UTF-8, no non-finite
    numbers. The review block (which stores this fingerprint) and
    ``generation.generated_at`` (which changes on every regeneration) are left out;
    everything else, including evidence and every statement, is covered.
    """
    content = {key: value for key, value in card.items() if key != "review"}
    content["generation"] = {key: value for key, value in card["generation"].items() if key != "generated_at"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_id(passage_id: str, excerpt: str) -> str:
    """``passage_id#`` plus the first 12 hex of SHA-256 of the whitespace-collapsed excerpt.

    This is exactly the backend recipe (STORAGE.md, "Validation before import",
    step 3): no Unicode normalization, only ``" ".join(excerpt.split())``.
    """
    digest = hashlib.sha256(" ".join(excerpt.split()).encode("utf-8")).hexdigest()
    return f"{passage_id}#{digest[:12]}"


def _fold(text: str) -> tuple[str, list[tuple[int, int]]]:
    """NFKC-fold ``text`` one character at a time, collapsing whitespace runs to one space.

    Returns the folded text and, for each folded character, the inclusive span of
    original indexes it came from. Folding per character keeps the mapping exact
    even where NFKC changes the length (ligatures, ``TM``, superscripts).
    """
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        for piece in unicodedata.normalize("NFKC", char):
            if piece.isspace():
                if chars and chars[-1] == " ":
                    spans[-1] = (spans[-1][0], index)
                else:
                    chars.append(" ")
                    spans.append((index, index))
            else:
                chars.append(piece)
                spans.append((index, index))
    return "".join(chars), spans


def locate_excerpt(passage_text: str, excerpt: str) -> str | None:
    """Return the exact substring of ``passage_text`` that ``excerpt`` stands for, or None.

    An excerpt that already occurs verbatim is returned unchanged. Otherwise it is
    located after NFKC and whitespace folding (pypdf line breaks, ligatures) and the
    original characters of the first match are returned.
    """
    stripped = excerpt.strip()
    if stripped and stripped in passage_text:
        return stripped
    needle = _fold(stripped)[0].strip()
    if not needle:
        return None
    folded, spans = _fold(passage_text)
    start = folded.find(needle)
    if start < 0:
        return None
    return passage_text[spans[start][0] : spans[start + len(needle) - 1][1] + 1]


# ------------------------------------------------------------------- numbers
#
# The number rule compares *quantities*, not bare digit strings. A quantity is a
# signed value, in one canonical spelling for exponents, with the unit written
# right after it when there is one:
#   -5 != 5;  1e-6 == 1E-6 == 10^-6 == 1x10-6;  3.5 mm needs 3.5 with unit mm.
# Digits glued to letters (CO2, O2, H03M101) and identifier numbers in
# UPPERCASE-n codes (FLEX-145, PSI-25, NASA-STD-6001) are not quantities.
# Table rows write units in the header ("Burn time; s: 10.1"), so a cell inherits
# the unit of its header.

_SUPERSCRIPT_RUN = re.compile("[\u2070\u00b9\u00b2\u00b3\u2074-\u207b]+")
_QUANTITY = re.compile(
    r"""
    (?:(?<![A-Za-z0-9.)%\]])(?P<sign>[-+]))?
    (?<![A-Za-z0-9.])(?<![A-Z]{2}-)
    (?:
        (?P<ten>10)\^\s?\{?(?P<e4>[-+]?\d+)\}?
      |
        (?P<mant>\d+(?:[.,]\d+)*|\.\d+)
        (?:[eE](?P<e1>[-+]?\d+)
          |\s?[x\u00d7*\u00b7\u22c5]\s?10(?:\^\s?\{?(?P<e2>[-+]?\d+)\}?|(?P<e3>[-+]\d+)))?
    )
    """,
    re.VERBOSE,
)
_UNIT_AFTER = re.compile(
    r"[ -]?(?P<unit>%|\u00b0\s?C|mm\s?Hg|[A-Za-z\u03bc]+(?:\^?[-+]?\d)?(?:/[A-Za-z\u03bc]+(?:\^?[-+]?\d)?)?)"
)
_HEADER_UNIT = re.compile(r"[;(]\s*(?P<unit>[^;()]+?)\s*\)?\s*$")
_UNITS = {
    "%": "%", "percent": "%",
    "kPa": "kPa", "MPa": "MPa", "Pa": "Pa", "atm": "atm", "psia": "psia", "psi": "psi",
    "mmHg": "mmHg", "torr": "mmHg", "Torr": "mmHg", "bar": "bar", "mbar": "mbar",
    "s": "s", "sec": "s", "second": "s", "seconds": "s", "ms": "ms",
    "min": "min", "minute": "min", "minutes": "min",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "nm": "nm", "um": "um", "\u03bcm": "um", "micron": "um", "microns": "um",
    "mm": "mm", "cm": "cm", "m": "m", "km": "km",
    "K": "K", "\u00b0C": "degC", "degC": "degC",
    "g": "g", "mg": "mg", "kg": "kg", "ppm": "ppm", "sccm": "sccm", "slpm": "slpm",
    "W": "W", "kW": "kW", "J": "J", "V": "V", "Hz": "Hz", "L": "L", "mL": "mL",
    "micrometer": "um", "micrometers": "um", "micrometre": "um", "micrometres": "um",
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "centimetres": "cm",
}  # fmt: skip
_ABBREVIATIONS = frozenset(
    {"al", "fig", "figs", "approx", "eq", "eqs", "vs", "no", "ref", "refs", "cf", "ca", "e.g", "i.e"}
)
_LABEL_BEFORE = re.compile(r"\b(?:tables?|figures?|figs?|eqs?|equations?|sections?|pages?|pp?)\.?\s*$", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z\u03bc%\u00b0]{2,}")
_SENTENCE_END = re.compile(r"[.!?]\s+(?=[A-Z(\"'])")


@dataclass(frozen=True)
class Quantity:
    value: str  # signed canonical number, for example "-5", "0.5", "1e-6"
    unit: str | None  # canonical unit written right after the number, if any
    label: bool = field(default=False, compare=False)  # "Table 1", "Fig. 3": a reference, not a quantity

    def __str__(self) -> str:
        if self.unit is None:
            return self.value
        return f"{self.value}{self.unit}" if self.unit == "%" else f"{self.value} {self.unit}"


def _prepare(text: str) -> str:
    """Spell superscripts as ``^n``, unify minus signs, NFKC, collapse whitespace."""
    text = _SUPERSCRIPT_RUN.sub(lambda match: "^" + unicodedata.normalize("NFKC", match.group()), text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2212", "-").replace("\u2010", "-").replace("\u2011", "-")
    return " ".join(text.split())


def _canonical_unit(token: str) -> str | None:
    token = token.replace("^", "").replace(" ", "")
    if token in _UNITS:
        return _UNITS[token]
    if "/" in token:
        numerator, _, denominator = token.partition("/")
        return f"{_UNITS.get(numerator, numerator)}/{_UNITS.get(denominator, denominator)}"
    return None


def _quantities(prepared: str) -> list[Quantity]:
    found = []
    for match in _QUANTITY.finditer(prepared):
        if match["ten"]:
            value = f"1e{int(match['e4'])}"
        else:
            mantissa = "0" + match["mant"] if match["mant"].startswith(".") else match["mant"]
            exponent = match["e1"] or match["e2"] or match["e3"]
            value = mantissa if exponent is None else f"{mantissa}e{int(exponent)}"
        unit_match = _UNIT_AFTER.match(prepared, match.end())
        unit = _canonical_unit(unit_match["unit"]) if unit_match else None
        label = _LABEL_BEFORE.search(prepared, 0, match.start()) is not None
        found.append(Quantity((match["sign"] or "") + value, unit, label))
    return found


def quantities_in(text: str) -> list[Quantity]:
    """Quantities of ``text`` in order of appearance, duplicates included."""
    return _quantities(_prepare(text))


def numbers_in(text: str) -> set[str]:
    """Signed numeric tokens of ``text``; ``.5`` and ``0.5`` are the same token."""
    return {quantity.value for quantity in quantities_in(text)}


@dataclass(frozen=True)
class _Support:
    """What one excerpt can back.

    ``values``: every number in it. ``pairs``: numbers with the unit they carry
    (written after them, or in a table header). ``bare``: numbers with no unit at
    all, such as table cells whose unit sits in a caption. ``mentions``: units named
    anywhere in the text (multi-letter spellings only, so "'s" is not a second).
    """

    values: frozenset[str]
    pairs: frozenset[tuple[str, str]]
    bare: frozenset[str]
    mentions: frozenset[str]

    def has(self, quantity: Quantity, mentions: frozenset[str]) -> bool:
        """``mentions`` are the units named by all excerpts the statement cites."""
        if quantity.unit is None:
            return quantity.value in self.values
        if (quantity.value, quantity.unit) in self.pairs:
            return True
        return quantity.value in self.bare and quantity.unit in mentions


def _support(excerpt: str) -> _Support:
    prepared = _prepare(excerpt)
    values: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    bare: set[str] = set()

    def add(quantity: Quantity, header_unit: str | None = None) -> None:
        values.add(quantity.value)
        unit = quantity.unit or header_unit
        if unit is None:
            bare.add(quantity.value)
        else:
            pairs.add((quantity.value, unit))

    inherited: set[tuple[str, str]] = set()
    for part in prepared.split(" | "):  # table rows: "<header; unit>: <cell>"
        head, colon, cell = part.partition(":")
        header = _HEADER_UNIT.search(head) if colon else None
        if header is None:
            continue
        unit = _canonical_unit(header["unit"]) or ("degC" if header["unit"].strip() == "C" else None)
        if unit is not None:
            for quantity in _quantities(cell.strip()):
                if quantity.unit is None:
                    inherited.add((quantity.value, unit))
    for quantity in _quantities(prepared):
        add(quantity)
    for value, unit in inherited:
        bare.discard(value)
        pairs.add((value, unit))
    mentions = {unit for word in _WORD.findall(prepared) if (unit := _canonical_unit(word))}
    return _Support(frozenset(values), frozenset(pairs), frozenset(bare), frozenset(mentions))


def _sentences(prepared: str) -> list[str]:
    sentences, start = [], 0
    for match in _SENTENCE_END.finditer(prepared):
        words = prepared[start : match.start()].split()
        if words and words[-1].lower().strip("(") in _ABBREVIATIONS:
            continue
        sentences.append(prepared[start : match.start() + 1])
        start = match.end()
    sentences.append(prepared[start:])
    return sentences


def _quantity_problems(label: str, text: str, known: list[dict[str, Any]]) -> list[str]:
    """Number rule for one statement; every message names the statement and the number."""
    supports = [_support(item["excerpt"]) for item in known]
    mentions = frozenset().union(*(support.mentions for support in supports))
    problems = []
    unsupported: set[Quantity] = set()
    for quantity in sorted(set(quantities_in(text)), key=str):
        if any(support.has(quantity, mentions) for support in supports):
            continue
        unsupported.add(quantity)
        if quantity.unit is not None and any(quantity.value in support.values for support in supports):
            found = sorted({unit for s in supports for value, unit in s.pairs if value == quantity.value})
            problems.append(
                f"{label}: number {quantity} does not occur with unit {quantity.unit} in any excerpt it cites "
                f"({quantity.value} appears there {'with ' + ', '.join(found) if found else 'without a unit'})"
            )
            continue
        hint = ""
        bare = quantity.value.lstrip("+-")
        if bare != quantity.value and any(bare in s.values for s in supports):
            hint = f" (an excerpt has {bare} without that sign)"
        elif any(f"-{quantity.value}" in s.values or f"+{quantity.value}" in s.values for s in supports):
            hint = " (an excerpt has that number with a different sign)"
        problems.append(f"{label}: number {quantity} does not occur in any excerpt it cites{hint}")
    for sentence in _sentences(_prepare(text)):
        together = sorted({q for q in _quantities(sentence) if not q.label}, key=str)
        if len({quantity.value for quantity in together}) < 2 or unsupported.intersection(together):
            continue
        if not any(all(support.has(quantity, mentions) for quantity in together) for support in supports):
            listed = ", ".join(str(quantity) for quantity in together)
            problems.append(
                f"{label}: numbers {listed} are stated in one sentence but no single cited excerpt contains "
                f"all of them (sentence: {sentence[:80]!r}); split the sentence or cite one excerpt that has them"
            )
    return problems


# ---------------------------------------------------------------- statements


def _cited(label: str, value: dict[str, Any] | None) -> Iterator[tuple[str, str, list[str]]]:
    if value is not None:
        yield label, value["text"], value["evidence_ids"]


def statements(card: dict[str, Any]) -> Iterator[tuple[str, str, list[str]]]:
    """Every statement that must be supported: (label, text, evidence ids)."""
    yield from _cited("summary", card["summary"])
    for index, claim in enumerate(card["claims"]):
        yield f"claims[{index}] ({claim['id']})", claim["text"], claim["evidence_ids"]
    for index, finding in enumerate(card["findings"]):
        yield from _cited(f"findings[{index}].conditions", finding["conditions"])
    for name, attribute in card["comparison"].items():
        yield from _cited(f"comparison.{name}", attribute)
    for index, limitation in enumerate(card["limitations"]):
        yield f"limitations[{index}]", limitation["text"], limitation["evidence_ids"]
    for index, resource in enumerate(card["modeling_resources"]):
        yield f"modeling_resources[{index}]", resource["description"], resource["evidence_ids"]


def _referenced_ids(card: dict[str, Any]) -> set[str]:
    referenced = {item for _, _, ids in statements(card) for item in ids}
    for entry in card["safety_categories"]:
        referenced.update(entry["evidence_ids"])
    return referenced


# ---------------------------------------------------------------- validation


def _evidence_problems(
    item: dict[str, Any], passages: dict[str, dict[str, Any]], packet: dict[str, Any]
) -> list[str]:
    name = item["id"]
    problems = []
    if item["id"] != evidence_id(item["passage_id"], item["excerpt"]):
        problems.append(f"evidence {name}: id does not match passage_id and excerpt hash")
    passage = passages.get(item["passage_id"])
    if passage is None:
        return [*problems, f"evidence {name}: passage {item['passage_id']} is not in the evidence packet"]
    if item["locator"] != passage["locator"]:
        problems.append(f"evidence {name}: locator differs from the packet passage")
    if item["source_url"] != packet["source_url"]:
        problems.append(f"evidence {name}: source_url differs from the packet")
    if item["investigation"] != packet["investigation"]:
        problems.append(f"evidence {name}: investigation differs from the packet")
    length = len(" ".join(item["excerpt"].split()))
    if length < MIN_EXCERPT_CHARACTERS:
        problems.append(f"evidence {name}: excerpt has {length} characters, minimum is {MIN_EXCERPT_CHARACTERS}")
    if item["excerpt"] not in passage["text"]:
        problems.append(f"evidence {name}: excerpt does not occur exactly in passage {item['passage_id']}")
    return problems


def _is_intent_only(item: dict[str, Any]) -> bool:
    locator = item["locator"]
    return locator["kind"] == "metadata" and locator["field"] in _INTENT_FIELDS


def _statement_problems(card: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    for label, text, ids in statements(card):
        known = [by_id[i] for i in ids if i in by_id]
        for missing in sorted(set(ids) - set(by_id)):
            problems.append(f"{label}: cites unknown evidence id {missing}")
        problems.extend(_quantity_problems(label, text, known))
    return problems


def _claim_problems(card: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    claims: dict[str, dict[str, Any]] = {}
    for claim in card["claims"]:
        if claim["id"] in claims:
            problems.append(f"claim id {claim['id']} is used more than once")
        claims[claim["id"]] = claim
        if claim["type"] != "reported_observation":
            continue
        cited = [by_id[i] for i in claim["evidence_ids"] if i in by_id]
        if all(_is_intent_only(item) for item in cited):
            problems.append(
                f"claim {claim['id']}: reported_observation cites only objective/hypothesis/researchImpacts "
                "metadata, which is intent, not a measured result"
            )
    for index, finding in enumerate(card["findings"]):
        for key, expected in (("observation", "reported_observation"), ("implication", "potential_application")):
            target = claims.get(finding[key])
            if target is None:
                problems.append(f"findings[{index}].{key}: claim {finding[key]} does not exist")
            elif target["type"] != expected:
                problems.append(f"findings[{index}].{key}: claim {finding[key]} is {target['type']}, not {expected}")
    return problems


def _structure_problems(card: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    problems = []
    for key, packet_key in (
        ("accession", "investigation"),
        ("title", "title"),
        ("source_version", "metadata_version"),
        ("coverage", "coverage"),
    ):
        if card[key] != packet[packet_key]:
            problems.append(f"{key} {card[key]!r} differs from the packet ({packet[packet_key]!r})")
    if card["coverage"] == "metadata_only" and not any(item["basis"] == "coverage" for item in card["limitations"]):
        problems.append("metadata_only card needs a limitation with basis 'coverage'")
    if card["accession"] in CORE_INVESTIGATIONS and not card["findings"]:
        problems.append(f"core investigation {card['accession']} needs at least one finding")
    review = card["review"]
    if review["status"] in ("approved", "rejected") and (not review["reviewer"] or not review["reviewed_at"]):
        problems.append(f"review status {review['status']} requires reviewer and reviewed_at")
    if review["status"] == "approved":
        approved = review.get("content_sha256")
        if approved is None:
            problems.append("review status approved has no content_sha256; approve the card with pipeline.review")
        elif approved != content_fingerprint(card):
            problems.append(
                "card content changed after it was approved (content_sha256 does not match); review and approve again"
            )
    return problems


def validate(card: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    """Return every problem found; an empty list means the card is valid."""
    problems = schema_errors(card, "research-card")
    if problems:
        return problems  # later rules assume the schema's shape
    passages = {passage["id"]: passage for passage in packet["passages"]}
    problems.extend(_structure_problems(card, packet))
    by_id: dict[str, dict[str, Any]] = {}
    for item in card["evidence"]:
        if item["id"] in by_id:
            problems.append(f"evidence id {item['id']} is defined more than once")
        by_id[item["id"]] = item
        problems.extend(_evidence_problems(item, passages, packet))
    problems.extend(_statement_problems(card, by_id))
    problems.extend(_claim_problems(card, by_id))
    for orphan in sorted(set(by_id) - _referenced_ids(card)):
        problems.append(f"evidence {orphan} is not referenced by any statement")
    for index, entry in enumerate(card["safety_categories"]):
        for missing in sorted(set(entry["evidence_ids"]) - set(by_id)):
            problems.append(f"safety_categories[{index}]: cites unknown evidence id {missing}")
    return problems


# ------------------------------------------------------------------ finalize


def _timestamp(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(microsecond=0).isoformat()


def _rewrite_refs(value: Any, mapping: dict[str, str], problems: list[str]) -> Any:
    """Copy ``value`` replacing every ``evidence_ids`` list of local refs."""
    if isinstance(value, dict):
        rewritten = {}
        for key, child in value.items():
            if key == "evidence_ids":
                ids: list[str] = []
                for ref in child:
                    if ref not in mapping:
                        problems.append(f"draft cites undefined evidence ref {ref}")
                    elif mapping[ref] not in ids:
                        ids.append(mapping[ref])
                rewritten[key] = ids
            else:
                rewritten[key] = _rewrite_refs(child, mapping, problems)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_refs(child, mapping, problems) for child in value]
    return value


def finalize(draft: dict[str, Any], packet: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Turn a skill draft into a validated, pending-review research card."""
    problems = schema_errors(draft, "research-card-draft")
    if problems:
        raise CardError(problems)
    if draft["accession"] != packet["investigation"]:
        raise CardError([f"draft accession {draft['accession']} differs from packet {packet['investigation']}"])
    passages = {passage["id"]: passage for passage in packet["passages"]}
    evidence: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for item in draft["evidence"]:
        if item["id"] in mapping:
            problems.append(f"draft defines evidence ref {item['id']} more than once")
            continue
        passage = passages.get(item["passage_id"])
        if passage is None:
            problems.append(f"evidence {item['id']}: passage {item['passage_id']} is not in the evidence packet")
            continue
        excerpt = locate_excerpt(passage["text"], item["excerpt"])
        if excerpt is None:
            problems.append(f"evidence {item['id']}: excerpt does not occur in passage {item['passage_id']}")
            continue
        mapping[item["id"]] = evidence_id(item["passage_id"], excerpt)
        if all(existing["id"] != mapping[item["id"]] for existing in evidence):
            evidence.append(
                {
                    "id": mapping[item["id"]],
                    "passage_id": item["passage_id"],
                    "investigation": packet["investigation"],
                    "source_url": packet["source_url"],
                    "locator": copy.deepcopy(passage["locator"]),
                    "excerpt": excerpt,
                }
            )
    body = {key: value for key, value in draft.items() if key not in ("evidence", "generation")}
    card = {
        "accession": packet["investigation"],
        "source_version": packet["metadata_version"],
        "title": packet["title"],
        "acronym": packet["acronym"],
        "coverage": packet["coverage"],
        **_rewrite_refs(body, mapping, problems),
        "evidence": evidence,
        "generation": {
            "method": "skill",
            "skill": "research-card",
            "model": draft["generation"]["model"],
            "generated_at": _timestamp(now),
        },
        "review": {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": ""},
    }
    if not problems:
        problems = validate(card, packet)
    if problems:
        raise CardError(problems)
    return card


# ----------------------------------------------------------------------- CLI


def _load_packet(packets_dir: Path, accession: str) -> dict[str, Any]:
    path = packets_dir / f"{accession}.json"
    if not path.is_file():
        raise CardError([f"evidence packet {path} not found; run python -m pipeline.evidence build"])
    packet: dict[str, Any] = read_json(path)
    return packet


def _cmd_finalize(args: argparse.Namespace) -> int:
    draft = read_json(args.draft)
    try:
        packet = _load_packet(args.packets, str(draft.get("accession")))
        card = finalize(draft, packet, datetime.now(UTC))
    except CardError as error:
        print(f"{args.draft}: {len(error.problems)} problem(s)")
        for problem in error.problems:
            print(f"  - {problem}")
        return 1
    target = args.out / f"{card['accession']}.json"
    write_json_atomic(target, card)
    print(f"wrote {target}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    targets = args.cards or sorted(paths.DATA.joinpath("cards").glob("*.json"))
    failed = 0
    for path in targets:
        card = read_json(path)
        try:
            problems = validate(card, _load_packet(args.packets, str(card.get("accession"))))
        except CardError as error:
            problems = error.problems
        if args.require_approved and card.get("review", {}).get("status") != "approved":
            problems.append("review status is not approved")
        print(f"{path}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        for problem in problems:
            print(f"  - {problem}")
        failed += bool(problems)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.cards", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    finalize_cmd = commands.add_parser("finalize", help="turn a skill draft into a card")
    finalize_cmd.add_argument("draft", type=Path)
    finalize_cmd.add_argument("--packets", type=Path, default=paths.DATA / "evidence")
    finalize_cmd.add_argument("--out", type=Path, default=paths.DATA / "cards")
    finalize_cmd.set_defaults(handler=_cmd_finalize)
    validate_cmd = commands.add_parser("validate", help="validate cards against their evidence packets")
    validate_cmd.add_argument("cards", nargs="*", type=Path)
    validate_cmd.add_argument("--packets", type=Path, default=paths.DATA / "evidence")
    validate_cmd.add_argument("--require-approved", action="store_true")
    validate_cmd.set_defaults(handler=_cmd_validate)
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
