"""The interactive loop: show an item, take a decision, persist it at once.

Each decision rewrites its file atomically after the whole document validates, so a
crash or quit never loses earlier decisions or leaves a half-written file. A note
typed with [n]ote lives in memory until a decision saves it; skipping discards it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.review.display import format_card
from pipeline.review.kinds import Item, Kind
from pipeline.schema import schema_errors
from pipeline.storage import read_json, write_json_atomic

Validator = Callable[[dict[str, Any], dict[str, Any]], list[str]]


class ReviewError(ValueError):
    """A file cannot be reviewed or a decision cannot be saved; the message names the file."""


class _Quit(Exception):
    """Raised inside the loop for [q], Ctrl+C and end of input."""


@dataclass(frozen=True)
class Environment:
    reviewer: str
    ask: Callable[[str], str]
    say: Callable[[str], None]
    clock: Callable[[], datetime]
    validator: Validator | None
    packets_dir: Path
    impact: Callable[[], Mapping[str, int]]


@dataclass
class Tally:
    approved: int = 0
    rejected: int = 0
    edited: int = 0
    skipped: int = 0
    quit: bool = False

    @property
    def decided(self) -> int:
        return self.approved + self.rejected + self.edited

    def line(self) -> str:
        return f"approved {self.approved}, rejected {self.rejected}, edited {self.edited}, skipped {self.skipped}"


def utc_stamp(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_document(path: Path, kind: Kind) -> dict[str, Any]:
    try:
        document = read_json(path)
    except (OSError, ValueError) as error:
        raise ReviewError(f"{path}: cannot read as JSON: {error}") from error
    errors = schema_errors(document, kind.schema)
    if errors:
        raise ReviewError(f"{path}: not a valid {kind.schema} file, nothing reviewed: {'; '.join(errors)}")
    return document  # type: ignore[no-any-return]


def default_validator(card: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    from pipeline.cards import validate  # lazy: alias and extraction review must not depend on cards

    return validate(card, packet)


def _card_problems(card: dict[str, Any], env: Environment) -> list[str]:
    packet_path = env.packets_dir / f"{card['accession']}.json"
    if not packet_path.exists():
        return [f"evidence packet {packet_path} not found; cannot verify the card"]
    return (env.validator or default_validator)(card, read_json(packet_path))


def _fingerprint(card: dict[str, Any]) -> str:
    from pipeline.cards import content_fingerprint  # lazy, like default_validator

    return content_fingerprint(card)


def _ask(env: Environment, text: str) -> str:
    try:
        return env.ask(text).strip()
    except (EOFError, KeyboardInterrupt):
        raise _Quit from None


def _save(path: Path, kind: Kind, document: dict[str, Any]) -> None:
    errors = schema_errors(document, kind.schema)
    if errors:
        raise ReviewError(f"{path}: refusing to write an invalid file: {'; '.join(errors)}")
    write_json_atomic(path, document)


def _decide(item: Item, status: str, note: str, env: Environment, fingerprint: str | None = None) -> None:
    item["review"] = {
        "status": status,
        "reviewer": env.reviewer,
        "reviewed_at": utc_stamp(env.clock()),
        "notes": note,
    }
    if fingerprint is not None:
        item["review"]["content_sha256"] = fingerprint


def _review_item(path: Path, kind: Kind, document: dict[str, Any], item: Item, env: Environment, tally: Tally) -> None:
    env.say("")
    if kind.name == "cards":
        env.say(format_card(item, read_json(env.packets_dir / f"{item['accession']}.json")))
    else:
        env.say(kind.render(document, item, env.impact() if kind.name == "aliases" else {}))
    note = item["review"]["notes"]
    prompt = f"[a]pprove [r]eject {'[e]dit ' if kind.editable else ''}[n]ote [s]kip [q]uit > "
    while True:
        if note:
            env.say(f"  note: {note}")
        choice = _ask(env, prompt).lower()[:1]
        if choice == "q":
            raise _Quit
        if choice == "s":
            tally.skipped += 1
            return
        if choice == "n":
            note = _ask(env, "note> ")
        elif choice == "r":
            if not note:
                env.say("  A rejection needs a note saying why; use [n]ote first.")
                continue
            _decide(item, "rejected", note, env)
            tally.rejected += 1
            _save(path, kind, document)
            return
        elif choice == "a":
            problems = _card_problems(item, env) if kind.name == "cards" else []
            if problems:
                env.say("  Cannot approve: the card fails validation (reject or skip):")
                for problem in problems:
                    env.say(f"    - {problem}")
                continue
            _decide(item, "approved", note, env, _fingerprint(item) if kind.name == "cards" else None)
            tally.approved += 1
            _save(path, kind, document)
            return
        elif choice == "e" and kind.editable:
            canonical = _ask(env, "new canonical> ")
            if not canonical:
                env.say("  Empty value ignored.")
                continue
            item["canonical"] = canonical
            item["proposed_by"] = "manual"
            _decide(item, "approved", note, env)
            tally.edited += 1
            _save(path, kind, document)
            return
        elif choice == "e":
            env.say("  Not editable here; reject it with a note instead.")
        else:
            env.say("  Unknown choice.")


def review_file(path: Path, kind: Kind, env: Environment, include_decided: bool) -> Tally:
    """Review one file; raises ReviewError, before showing anything, if the file is invalid."""
    document = load_document(path, kind)
    tally = Tally()
    todo = [i for i in kind.items(document) if include_decided or i["review"]["status"] == "pending"]
    env.say(f"== {path} ({len(todo)} item(s) to review)")
    try:
        for index, item in enumerate(todo, 1):
            env.say(f"-- item {index}/{len(todo)}")
            _review_item(path, kind, document, item, env, tally)
    except _Quit:
        tally.quit = True
    return tally
