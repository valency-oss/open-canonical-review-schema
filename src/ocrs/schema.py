# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""JSON schema loading and validation for canonical reviews."""

from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from .hierarchy import resolve_definition

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "canonical-review.schema.json"

_validator: Draft202012Validator | None = None
_schema: dict[str, Any] | None = None


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    global _schema, _validator
    p = Path(path) if path else SCHEMA_PATH
    _schema = json.loads(p.read_text())
    _validator = Draft202012Validator(_schema)
    return _schema


def validate_canonical(
    obj: dict[str, Any],
    *,
    schema_path: str | Path | None = None,
    text_sources: dict[str, str] | None = None,
) -> None:
    """Validate a canonical review object; raises ValidationError on failure. A
    `schema_path` applies to this call only; later calls use the packaged schema."""
    if schema_path is not None:
        validator = Draft202012Validator(json.loads(Path(schema_path).read_text()))
    else:
        if _validator is None:
            load_schema()
        assert _validator is not None
        validator = _validator
    validator.validate(obj)
    if is_hierarchical(validator.schema.get("$id", "")) or is_hierarchical(obj.get("$schema", "")):
        check_references(obj, text_sources=text_sources)
    else:
        check_legacy_references(obj, evidence_schema=validator.schema)


FINDING_KINDS = ("strengths", "weaknesses", "questions", "comments", "changes")
EVIDENCE_LINK = "#/$defs/evidenceLink"
_ocrs_schema: dict[str, Any] | None = None


def ocrs_schema() -> dict[str, Any]:
    """The packaged OCRS schema, which says where evidence links are, whatever schema
    a review was validated against."""
    global _ocrs_schema
    if _ocrs_schema is None:
        _ocrs_schema = json.loads(SCHEMA_PATH.read_text())
    return _ocrs_schema


def schema_version(uri: str) -> tuple[int, int, int] | None:
    """The version in a published schema URL, such as (0, 9, 0) for `.../v0.9.0/...`."""
    match = re.search(r"/v(\d+)\.(\d+)\.(\d+)/", uri or "")
    return tuple(int(n) for n in match.groups()) if match else None  # type: ignore[return-value]


def is_hierarchical(uri: str) -> bool:
    """Whether a schema URL names 0.9 or later, whose records use the review hierarchy."""
    version = schema_version(uri)
    return version is not None and version >= (0, 9, 0)


def schema_id() -> str:
    """The packaged schema's `$id`, which a review names in its `$schema`."""
    return ocrs_schema()["$id"]


def has_content(review: dict[str, Any]) -> bool:
    """Whether a review says something about the work, by the schema's `#reviewContent`
    rule: an opinion, a finding, a decision, a metric, a work summary, a check, narrative
    text or a written report. Text counts only when
    it has a character other than whitespace."""
    schema = ocrs_schema()
    [rule] = [r for r in schema["allOf"] if r.get("$anchor") == "reviewContent"]
    # The rule refers to definitions in $defs, so it is checked alongside them
    return Draft202012Validator({**rule, "$defs": schema["$defs"]}).is_valid(review)


def require_content(review: dict[str, Any], source: str) -> None:
    """Raise ValueError when a mapped review has no content, so an empty source is
    reported as such rather than as a schema error."""
    if not has_content(review):
        raise ValueError(
            f"The {source} review has no review content: no opinion, finding, decision, "
            "metric, work summary, check, narrative text "
            "or written report"
        )


def _evidence_links(value: Any, node: Any, schema: dict[str, Any]):
    """Every evidence link in `value`, found by following the OCRS schema: only where the
    schema puts an evidenceLink, never inside free-form or source data."""
    if not isinstance(node, dict):
        return
    ref = node.get("$ref")
    if ref == EVIDENCE_LINK:
        if isinstance(value, dict):
            yield value
        return
    if ref:
        target = schema["$defs"].get(ref.removeprefix("#/$defs/"))
        if ref.startswith("#/$defs/") and target is not None:
            yield from _evidence_links(value, target, schema)
        return
    for alternative in node.get("anyOf", []) + node.get("oneOf", []) + node.get("allOf", []):
        yield from _evidence_links(value, alternative, schema)
    if isinstance(value, dict):
        for key, child_node in node.get("properties", {}).items():
            if key in value:
                yield from _evidence_links(value[key], child_node, schema)
    elif isinstance(value, list) and isinstance(node.get("items"), dict):
        for child in value:
            yield from _evidence_links(child, node["items"], schema)


def check_legacy_references(obj: dict[str, Any], *, evidence_schema: dict | None = None) -> None:
    """The rules JSON Schema cannot state: point and check ids are unique, the ids that a
    point's `summarizes` and `addresses` and a check's `finding_ids` name are points in
    `findings`, the claims a point's `claim_ids` name are in `claim_assessments`, and
    `page_end` is not before `page`. Raises ValidationError on the first broken rule."""
    findings = obj.get("findings", {})
    contributions = obj.get("opinion", {}).get("contributions", [])
    points = [(f"findings.{kind}", findings.get(kind, [])) for kind in FINDING_KINDS]
    points.append(("opinion.contributions", contributions))
    checks = obj.get("checks", [])
    seen: set[str] = set()
    for path, items in [*points, ("checks", checks)]:
        for index, point in enumerate(items):
            point_id = point.get("id")
            if point_id is None:
                continue
            if point_id in seen:
                raise ValidationError(f"{path}[{index}].id {point_id!r} is not unique")
            seen.add(point_id)
    finding_ids = {
        point["id"] for kind in FINDING_KINDS for point in findings.get(kind, []) if "id" in point
    }
    claim_ids = {claim["claim_id"] for claim in obj.get("claim_assessments", [])}
    for path, items in points:
        for index, point in enumerate(items):
            for field in ("summarizes", "addresses"):
                for target in point.get(field, []):
                    if target not in finding_ids:
                        raise ValidationError(
                            f"{path}[{index}].{field} names {target!r}, which is not a finding id"
                        )
            for target in point.get("claim_ids", []):
                if target not in claim_ids:
                    raise ValidationError(
                        f"{path}[{index}].claim_ids names {target!r}, which is not a claim_id"
                    )
    for index, check in enumerate(checks):
        for target in check.get("finding_ids", []):
            if target not in finding_ids:
                raise ValidationError(
                    f"checks[{index}].finding_ids names {target!r}, which is not a finding id"
                )
    schema = evidence_schema or (_validator.schema if _validator else ocrs_schema())
    for link in _evidence_links(obj, schema, schema):
        location = link.get("location", {})
        page, page_end = location.get("page"), location.get("page_end")
        if page is not None and page_end is not None and page_end < page:
            raise ValidationError(f"page_end {page_end} is before page {page}")


def check_references(obj: dict[str, Any], *, text_sources: dict[str, str] | None = None) -> None:
    """Review-local IDs, downward references, score scales and source ranges.

    Supply exact stored text through text_sources to also check span bounds and quotes.
    Validation never downloads or normalizes source text. The permitted link directions
    make the semantic graph acyclic without requiring reciprocal edges.
    """
    types: dict[str, str] = {}
    items = []

    def register(item, kind):
        id = item["id"]
        if id in types:
            raise ValidationError(f"ID {id!r} is not unique across review records")
        types[id] = kind
        items.append((kind, item))

    for category, values in obj.get("findings", {}).items():
        for item in values:
            register(item, "change" if category == "changes" else "finding")
    for name, kind in [("claims", "claim"), ("contributions", "contribution")]:
        for item in obj.get("work_summary", {}).get(name, []):
            register(item, kind)
    for item in obj.get("target", {}).get("artifacts", []):
        register(item, "artifact")
    for item in obj.get("checks", []):
        register(item, "check")
        for result in item.get("results", []):
            register(result, "check_result")
    for item in obj.get("metrics", []):
        register(item, "metric")

    def target(id, expected, field):
        if types.get(id) != expected:
            raise ValidationError(f"{field} references {id!r}; expected an existing {expected}")

    for kind, item in [("opinion", obj.get("opinion", {})), *items]:
        for id in item.get("supported_by", []):
            target(id, "finding", f"{kind}.supported_by")
        for id in item.get("metric_refs", []):
            target(id, "metric", "opinion.metric_refs")
        for id in item.get("addresses", []):
            target(id, "finding", "change.addresses")
        for ref in item.get("about", []):
            target(ref["id"], ref["type"], "finding.about")
        if kind == "check" and item.get("procedure", {}).get("artifact_id"):
            target(item["procedure"]["artifact_id"], "artifact", "check.procedure.artifact_id")
        if kind == "metric":
            try:
                definition = resolve_definition(obj, item)
            except KeyError as exc:
                raise ValidationError(
                    f"Metric {item['id']!r} has an unresolved definition_ref"
                ) from exc
            _check_metric(item, definition["scale"])

    for link in _evidence_links(obj, ocrs_schema(), ocrs_schema()):
        resource = link["resource"]
        if resource["type"] == "artifact":
            target(resource["id"], "artifact", "evidence.resource.id")
        location = link.get("location", {})
        for start, end in [("page", "page_end"), ("line_start", "line_end")]:
            if start in location and end in location and location[end] < location[start]:
                raise ValidationError(f"{end} is before {start}")
        if span := location.get("span"):
            if span["end"] <= span["start"]:
                raise ValidationError("span.end must be greater than span.start")
            if text_sources is not None and span["text_ref"] in text_sources:
                text = text_sources[span["text_ref"]]
                if span["end"] > len(text):
                    raise ValidationError("span.end exceeds the referenced text length")
                if "quote" in link and link["quote"] != text[span["start"] : span["end"]]:
                    raise ValidationError("quote does not equal the selected span")


def _check_metric(metric: dict, scale: dict) -> None:
    """Check the observation against its referenced original scale, not a guessed scale."""

    def number(v):
        return type(v) is int or type(v) is float and math.isfinite(v)

    if "min" in scale and "max" in scale and scale["min"] > scale["max"]:
        raise ValidationError("Scale min exceeds max")
    values = metric["value"] if isinstance(metric["value"], list) else [metric["value"]]
    for value in values:
        numeric_scale = scale["type"] in {"interval", "ratio"} or (
            "values" not in scale and any(key in scale for key in ("min", "max", "step"))
        )
        if numeric_scale and not number(value):
            raise ValidationError("A numeric scale requires numeric metric values")
        if "values" in scale:
            # JSON true and 1 are different allowed values, despite Python equality.
            if not any(
                value == allowed and isinstance(value, bool) == isinstance(allowed, bool)
                for allowed in scale["values"]
            ):
                raise ValidationError(f"Metric value {value!r} is not an allowed scale value")
        if type(value) is float and not math.isfinite(value):
            raise ValidationError("Metric values must be finite")
        if number(value):
            if "min" in scale and value < scale["min"] or "max" in scale and value > scale["max"]:
                raise ValidationError(f"Metric value {value} is outside its scale")
            if "step" in scale and "min" in scale:
                delta = Fraction(str(value)) - Fraction(str(scale["min"]))
                if (delta / Fraction(str(scale["step"]))).denominator != 1:
                    raise ValidationError("Metric value does not follow the original scale step")
    interval = metric.get("uncertainty", {}).get("interval")
    if interval:
        if not number(metric["value"]) or interval["low"] > interval["high"]:
            raise ValidationError("A metric interval requires a numeric value and low ≤ high")
        if any(
            not number(v)
            or "min" in scale
            and v < scale["min"]
            or "max" in scale
            and v > scale["max"]
            for v in interval.values()
        ):
            raise ValidationError("Metric interval is outside the original scale")
