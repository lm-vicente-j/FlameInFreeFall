"""Alias dictionaries: reviewed mappings from repeated source text to canonical values.

Only an approved entry is a settled mapping. A pending entry (proposed by a model
or a person, not yet reviewed) still produces a value so the data stays usable,
but the value keeps review status "pending". A rejected entry or a missing one
yields an unknown value that names the unmapped text.

A missing alias is "pending" rather than "not_required": a person has to supply a
mapping. A rejected alias is "rejected" so the decision stays visible on the record.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.runs.tables import collapse
from pipeline.runs.values import Category, mapped_category, unknown_category
from pipeline.schema import schema_errors
from pipeline.storage import read_json


class AliasError(ValueError):
    """An alias file is invalid; the message names the file."""


@dataclass(frozen=True)
class AliasEntry:
    source: str
    canonical: str
    proposed_by: str
    review_status: str


@dataclass(frozen=True)
class AliasDictionary:
    name: str
    entries: dict[str, AliasEntry]

    def lookup(self, text: str) -> AliasEntry | None:
        return self.entries.get(collapse(text))

    def resolve(self, text: str, columns: tuple[str, ...]) -> Category:
        """Map one source cell to a category value with provenance."""
        key = collapse(text)
        if not key:
            return unknown_category("blank in source", columns)
        entry = self.entries.get(key)
        if entry is None:
            return mapped_category(
                None, columns, "pending", None, f'no alias entry in "{self.name}" for source text "{key}"'
            )
        if entry.review_status == "rejected":
            return mapped_category(
                None,
                columns,
                "rejected",
                None,
                f'alias for source text "{key}" in "{self.name}" was rejected; unmapped',
            )
        if entry.review_status == "approved":
            return mapped_category(entry.canonical, columns, "approved", key, None)
        note = f"alias proposed by {entry.proposed_by}; not yet reviewed"
        return mapped_category(entry.canonical, columns, "pending", key, note)


AliasSet = Mapping[str, AliasDictionary]


def _check(document: Any, path: Path, name: str) -> None:
    errors = schema_errors(document, "alias-dictionary")
    if errors:
        raise AliasError(f"{path}: invalid alias dictionary: {'; '.join(errors)}")
    if document["name"] != name:
        raise AliasError(f"{path}: dictionary name {document['name']!r} must equal the file name {name!r}")


def load_dictionary(directory: Path, name: str) -> AliasDictionary:
    """Load ``<directory>/<name>.json``; a missing file is an empty dictionary."""
    path = directory / f"{name}.json"
    if not path.exists():
        return AliasDictionary(name, {})
    document = read_json(path)
    _check(document, path, name)
    entries: dict[str, AliasEntry] = {}
    for raw in document["entries"]:
        source = raw["source"]
        if source != collapse(source):
            raise AliasError(f"{path}: source {source!r} must be stripped with inner whitespace collapsed")
        if source in entries:
            raise AliasError(f"{path}: duplicate source {source!r}")
        status = raw["review"]["status"]
        if status not in ("approved", "pending", "rejected"):
            raise AliasError(
                f"{path}: entry {source!r} has review status {status!r}; use approved, pending or rejected"
            )
        entries[source] = AliasEntry(source, raw["canonical"], raw["proposed_by"], status)
    return AliasDictionary(name, entries)


def load_aliases(directory: Path, names: Iterable[str]) -> dict[str, AliasDictionary]:
    return {name: load_dictionary(directory, name) for name in names}


def add_proposals(
    directory: Path, name: str, sources: Iterable[str], proposals: Mapping[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """Return the dictionary document with a pending model proposal for each new source.

    Existing entries are never changed, so reviewed work is preserved. Also returns
    the sources for which no proposal is known.
    """
    path = directory / f"{name}.json"
    document: dict[str, Any] = read_json(path) if path.exists() else {"name": name, "entries": []}
    _check(document, path, name)
    present = {entry["source"] for entry in document["entries"]}
    unproposed: list[str] = []
    for source in sorted({collapse(s) for s in sources if collapse(s)} - present):
        canonical = proposals.get(source)
        if canonical is None:
            unproposed.append(source)
            continue
        review = {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": ""}
        document["entries"].append({"source": source, "canonical": canonical, "proposed_by": "llm", "review": review})
    document["entries"].sort(key=lambda entry: entry["source"])
    return document, unproposed
