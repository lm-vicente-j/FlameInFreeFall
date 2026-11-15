"""Structural validation against the JSON Schemas in ``pipeline/schemas``.

The schemas are the language-neutral data contracts shared with the backend and
dashboard. Semantic rules that a schema cannot express, such as evidence
resolution, live in the stage that owns the data.
"""
from functools import cache, lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from pipeline.paths import SCHEMAS
from pipeline.storage import read_json


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
    return Draft202012Validator(schema, registry=_registry(), format_checker=Draft202012Validator.FORMAT_CHECKER)


def schema_errors(instance: Any, name: str) -> list[str]:
    """Return readable errors, each prefixed with its JSON path; empty when valid."""
    errors = sorted(_validator(name).iter_errors(instance), key=lambda error: list(error.absolute_path))
    return [f"{error.json_path}: {error.message}" for error in errors]
