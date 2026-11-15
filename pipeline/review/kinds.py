"""What differs between the three reviewable file kinds."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.paths import DATA
from pipeline.review.display import format_alias, format_card, format_extraction

Item = dict[str, Any]


@dataclass(frozen=True)
class Kind:
    name: str
    schema: str
    default_dir: Path
    exclude_suffix: str | None
    items: Callable[[dict[str, Any]], list[Item]]
    render: Callable[[dict[str, Any], Item, Mapping[str, int]], str]
    editable: bool
    rebuild_runs: bool
    """True when run records derive from this kind, so ``pipeline.runs build`` must be rerun."""


KINDS = {
    "aliases": Kind(
        name="aliases",
        schema="alias-dictionary",
        default_dir=DATA / "aliases",
        exclude_suffix=None,
        items=lambda doc: doc["entries"],
        render=lambda doc, item, impact: format_alias(doc["name"], item, impact),
        editable=True,
        rebuild_runs=True,
    ),
    "extractions": Kind(
        name="extractions",
        schema="llm-extraction",
        default_dir=DATA / "extractions",
        exclude_suffix=".queue.json",
        items=lambda doc: doc["items"],
        render=lambda doc, item, impact: format_extraction(item),
        editable=False,
        rebuild_runs=True,
    ),
    "cards": Kind(
        name="cards",
        schema="research-card",
        default_dir=DATA / "cards",
        exclude_suffix=None,
        items=lambda doc: [doc],  # a card is one item; its review block is the document's
        render=lambda doc, item, impact: format_card(item),
        editable=False,
        rebuild_runs=False,
    ),
}


def default_files(kind: Kind) -> list[Path]:
    return sorted(
        path
        for path in kind.default_dir.glob("*.json")
        if not (kind.exclude_suffix and path.name.endswith(kind.exclude_suffix))
    )
