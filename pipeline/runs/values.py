"""Value and record types for normalized runs, with builders for each method.

Every value says how it was obtained (``method``) and whether a person still has
to look at it (``review_status``). A record's status is the least-reviewed status
among its values, so one pending alias is visible at record level.
"""

from dataclasses import dataclass
from typing import Any, Literal

Method = Literal["parsed", "mapped", "llm", "manual", "unknown"]
ReviewStatus = Literal["rejected", "pending", "approved", "not_required"]
Qualifier = Literal["approximate"]
Kind = Literal["run", "note"]
Gravity = Literal["microgravity", "normal"]

REVIEW_ORDER: tuple[ReviewStatus, ...] = ("rejected", "pending", "approved", "not_required")
"""Least reviewed first."""


@dataclass(frozen=True)
class Provenance:
    method: Method
    columns: tuple[str, ...]
    review_status: ReviewStatus
    quote: str | None
    note: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "columns": list(self.columns),
            "review_status": self.review_status,
            "quote": self.quote,
            "note": self.note,
        }


@dataclass(frozen=True)
class Category:
    value: str | None
    provenance: Provenance

    def to_json(self) -> dict[str, Any]:
        return {"value": self.value, **self.provenance.to_json()}


@dataclass(frozen=True)
class Quantity:
    minimum: float | None
    maximum: float | None
    unit: str
    qualifier: Qualifier | None
    provenance: Provenance

    def to_json(self) -> dict[str, Any]:
        return {
            "min": self.minimum,
            "max": self.maximum,
            "unit": self.unit,
            "qualifier": self.qualifier,
            **self.provenance.to_json(),
        }


Value = Category | Quantity


@dataclass(frozen=True)
class Outcome:
    type: str
    gravity: Gravity
    result: Value

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, "gravity": self.gravity, "result": self.result.to_json()}


@dataclass(frozen=True)
class Conditions:
    fuel_class: Category
    material: Category
    geometry: Category
    o2_percent: Quantity
    pressure_kpa: Quantity
    flow_cm_s: Quantity
    flow_direction: Category
    diluent: Category

    def values(self) -> tuple[Value, ...]:
        return (
            self.fuel_class,
            self.material,
            self.geometry,
            self.o2_percent,
            self.pressure_kpa,
            self.flow_cm_s,
            self.flow_direction,
            self.diluent,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "fuel_class": self.fuel_class.to_json(),
            "material": self.material.to_json(),
            "geometry": self.geometry.to_json(),
            "o2_percent": self.o2_percent.to_json(),
            "pressure_kpa": self.pressure_kpa.to_json(),
            "flow_cm_s": self.flow_cm_s.to_json(),
            "flow_direction": self.flow_direction.to_json(),
            "diluent": self.diluent.to_json(),
        }


def least_reviewed(statuses: list[ReviewStatus]) -> ReviewStatus:
    return min(statuses, key=REVIEW_ORDER.index)


@dataclass(frozen=True)
class Record:
    id: str
    kind: Kind
    row: int
    original: dict[str, str]
    conditions: Conditions
    outcomes: tuple[Outcome, ...]

    @property
    def review_status(self) -> ReviewStatus:
        values = list(self.conditions.values()) + [outcome.result for outcome in self.outcomes]
        return least_reviewed([value.provenance.review_status for value in values])

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "row": self.row,
            "original": self.original,
            "conditions": self.conditions.to_json(),
            "outcomes": [outcome.to_json() for outcome in self.outcomes],
            "review_status": self.review_status,
        }


def unknown_category(note: str, columns: tuple[str, ...] = ()) -> Category:
    return Category(None, Provenance("unknown", columns, "not_required", None, note))


def unknown_quantity(unit: str, note: str, columns: tuple[str, ...] = ()) -> Quantity:
    return Quantity(None, None, unit, None, Provenance("unknown", columns, "not_required", None, note))


def parsed_category(value: str, columns: tuple[str, ...], note: str | None = None) -> Category:
    return Category(value, Provenance("parsed", columns, "not_required", None, note))


def parsed_quantity(
    minimum: float,
    maximum: float,
    unit: str,
    qualifier: Qualifier | None,
    columns: tuple[str, ...],
    note: str | None = None,
) -> Quantity:
    if minimum > maximum:
        raise ValueError(f"minimum {minimum} exceeds maximum {maximum}")
    return Quantity(minimum, maximum, unit, qualifier, Provenance("parsed", columns, "not_required", None, note))


def mapped_category(
    value: str | None, columns: tuple[str, ...], review_status: ReviewStatus, quote: str | None, note: str | None
) -> Category:
    method: Method = "mapped" if value is not None else "unknown"
    return Category(value, Provenance(method, columns, review_status, quote, note))


def manual_category(value: str, note: str) -> Category:
    """An investigation-level constant; it is reviewed as code, hence not_required."""
    return Category(value, Provenance("manual", (), "not_required", None, note))
