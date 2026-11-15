"""Plain-text blocks that show a reviewer one item at a time.

Everything here is pure: it formats data and returns a string.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pipeline.runs.tables import collapse
from pipeline.storage import read_json

_EXCERPT_LIMIT = 400


def count_run_cells(runs_dir: Path) -> Counter[str]:
    """Count, per whitespace-collapsed cell text, the run records whose original cells contain it."""
    counts: Counter[str] = Counter()
    for path in sorted(runs_dir.glob("*.json")):
        for record in read_json(path).get("records", []):
            counts.update({collapse(str(cell)) for cell in record.get("original", {}).values()})
    return counts


def mark_quotes(text: str, quotes: Iterable[str]) -> str:
    """Wrap the first occurrence of every quote in ``[[ ]]``; overlapping quotes merge into one span."""
    spans = sorted((start, start + len(q)) for q in quotes if q and (start := text.find(q)) >= 0)
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        out += [text[cursor:start], "[[", text[start:end], "]]"]
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def format_alias(dictionary: str, item: Mapping[str, Any], impact: Mapping[str, int]) -> str:
    count = impact.get(item["source"], 0)
    return "\n".join(
        [
            f"alias  dictionary: {dictionary}",
            f"  source text : {item['source']!r}",
            f"  canonical   : {item['canonical']!r}",
            f"  proposed_by : {item['proposed_by']}",
            f"  run records with this exact source text: {count}",
        ]
    )


def _result(result: Mapping[str, Any]) -> str:
    if result["kind"] == "category":
        return f"category {result['value']!r}"
    approx = " (approximate)" if result["qualifier"] == "approximate" else ""
    return f"{result['min']}..{result['max']} {result['unit']}{approx}"


def format_extraction(item: Mapping[str, Any]) -> str:
    proposal = item["proposal"]
    quotes = [o["quote"] for o in proposal["outcomes"]] + [r["quote"] for r in proposal["readings"]]
    lines = [
        f"extraction  record: {item['record_id']}",
        f"  source text : {mark_quotes(item['source_text'], quotes)}",
        f"  model       : {item['model']}   proposed_by: {item['proposed_by']}",
    ]
    for outcome in proposal["outcomes"]:
        lines.append(
            f"  outcome : {outcome['type']} / {outcome['gravity']} = {_result(outcome['result'])}"
            f"   quote: {outcome['quote']!r}"
        )
    for reading in proposal["readings"]:
        lines.append(
            f"  reading : {reading['instrument']} {reading['min']}..{reading['max']}   quote: {reading['quote']!r}"
        )
    lines.extend(f"  WARNING: quote not found in source text: {q!r}" for q in quotes if q not in item["source_text"])
    return "\n".join(lines)


def _excerpts(ids: Iterable[str], evidence: Mapping[str, str]) -> list[str]:
    lines = []
    for evidence_id in ids:
        excerpt = collapse(evidence.get(evidence_id, "<unknown evidence id>"))
        if len(excerpt) > _EXCERPT_LIMIT:
            excerpt = excerpt[:_EXCERPT_LIMIT] + "..."
        lines.append(f"      {evidence_id}: {excerpt!r}")
    return lines


def format_card(card: Mapping[str, Any]) -> str:
    evidence = {e["id"]: e["excerpt"] for e in card["evidence"]}
    lines = [
        f"card  {card['accession']}  {card['title']}",
        f"  coverage: {card['coverage']}",
        f"  summary : {card['summary']['text']}",
        *_excerpts(card["summary"]["evidence_ids"], evidence),
        "  claims:",
    ]
    for claim in card["claims"]:
        lines.append(f"    {claim['id']} [{claim['type']}] {claim['text']}")
        lines.extend(_excerpts(claim["evidence_ids"], evidence))
    lines.append("  findings:")
    for finding in card["findings"]:
        lines.append(
            f"    {finding['observation']} -> {finding['implication']} ({finding['category']}); "
            f"conditions: {finding['conditions']['text']}"
        )
    if not card["findings"]:
        lines.append("    (none)")
    lines.append("  limitations:")
    for limitation in card["limitations"]:
        lines.append(f"    ({limitation['basis']}) {limitation['text']}")
    if not card["limitations"]:
        lines.append("    (none)")
    return "\n".join(lines)
