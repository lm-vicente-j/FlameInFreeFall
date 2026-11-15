"""Structural validation against the JSON Schemas in ``pipeline/schemas``.

The schemas are the language-neutral data contracts shared with the backend and
dashboard. Semantic rules that a schema cannot express, such as evidence
resolution, live in the stage that owns the data.
"""
import math
import re
from datetime import datetime
from functools import cache, lru_cache
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from pipeline.paths import SCHEMAS
from pipeline.storage import read_json

FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value):
        return False
    parsed = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    return parsed.utcoffset() is not None


@FORMATS.checks("uri", raises=ValueError)
def _uri(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
        return False
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return False
    parsed = urlsplit(value)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parsed.scheme):
        return False
    if parsed.scheme.lower() in ("http", "https"):
        return bool(parsed.hostname) and (parsed.port is None or 0 < parsed.port <= 65535)
    return bool(parsed.path or parsed.netloc)


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = read_json(path)
        Draft202012Validator.check_schema(schema)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = read_json(SCHEMAS / f"{name}.schema.json")
    return Draft202012Validator(schema, registry=_registry(), format_checker=FORMATS)


def schema_errors(instance: Any, name: str) -> list[str]:
    """Return readable errors, each prefixed with its JSON path; empty when valid."""
    errors = sorted(_validator(name).iter_errors(instance), key=lambda error: str(error.absolute_path))
    messages = [f"{error.json_path}: {error.message}" for error in errors]

    def semantic(value: Any, path: str) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            messages.append(f"{path}: numeric values must be finite")
        elif isinstance(value, dict):
            low, high = value.get("min"), value.get("max")
            if isinstance(low, int | float) and isinstance(high, int | float) and low > high:
                messages.append(f"{path}: min must not exceed max")
            for key, child in value.items():
                semantic(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                semantic(child, f"{path}[{index}]")

    semantic(instance, "$")
    return messages
