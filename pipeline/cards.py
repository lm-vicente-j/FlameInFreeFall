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
import re
import sys
import unicodedata
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.schema import schema_errors
from pipeline.storage import read_json, write_json_atomic

CORE_INVESTIGATIONS = ("PSI-25", "PSI-98", "PSI-101", "PSI-69")
MIN_EXCERPT_CHARACTERS = 20
_INTENT_FIELDS = ("objective", "hypothesis", "researchImpacts")

# A number is digits not glued to an identifier: not preceded by a letter, by
# "letter-hyphen" (FLEX-2, PSI-25), by another digit, or by a decimal point.
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])(?<![A-Za-z]-)(\d+(?:[.,]\d+)*|\.\d+)")


class CardError(ValueError):
    """A draft or card is invalid; ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


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


def numbers_in(text: str) -> set[str]:
    """Numeric tokens of ``text``; ``.5`` and ``0.5`` are the same token."""
    return {("0" + token if token.startswith(".") else token) for token in _NUMBER.findall(normalize_text(text))}


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
        supported = set().union(*(numbers_in(item["excerpt"]) for item in known)) if known else set()
        for number in sorted(numbers_in(text) - supported):
            problems.append(f"{label}: number {number} does not occur in any excerpt it cites")
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
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).replace(microsecond=0).isoformat()


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
        card = finalize(draft, packet, datetime.now(timezone.utc))
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
