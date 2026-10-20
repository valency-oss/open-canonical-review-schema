# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""JSON schema loading and validation for canonical reviews."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "canonical-review.schema.json"

_validator: Draft202012Validator | None = None
_schema: dict[str, Any] | None = None


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    global _schema, _validator
    p = Path(path) if path else SCHEMA_PATH
    _schema = json.loads(p.read_text())
    _validator = Draft202012Validator(_schema)
    return _schema


def validate_canonical(obj: dict[str, Any], *, schema_path: str | Path | None = None) -> None:
    """Validate a canonical review object; raises ValidationError on failure."""
    global _validator
    if _validator is None or schema_path is not None:
        load_schema(schema_path)
    assert _validator is not None
    _validator.validate(obj)
    check_references(obj)


FINDING_KINDS = ("strengths", "weaknesses", "questions", "comments")
# Every place OCRS holds action items: (path, the review → the list there)
ACTION_ITEM_LISTS = (
    ("findings.changes", lambda r: r.get("findings", {}).get("changes", [])),
    (
        "ethics_and_risk.required_mitigations",
        lambda r: r.get("ethics_and_risk", {}).get("required_mitigations", []),
    ),
)
EVIDENCE_LINK = "#/$defs/evidenceLink"
_ocrs_schema: dict[str, Any] | None = None


def ocrs_schema() -> dict[str, Any]:
    """The packaged OCRS schema, which says where evidence links are, whatever schema
    a review was validated against."""
    global _ocrs_schema
    if _ocrs_schema is None:
        _ocrs_schema = json.loads(SCHEMA_PATH.read_text())
    return _ocrs_schema


def schema_id() -> str:
    """The packaged schema's `$id`, which a review names in its `$schema`."""
    return ocrs_schema()["$id"]


def has_content(review: dict[str, Any]) -> bool:
    """Whether a review says something about the work, by the schema's `#reviewContent`
    rule: an opinion, a finding, a decision, a metric, a claim or artifact assessment, a
    check, an ethical concern, narrative text or a written report. Text counts only when
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
            "metric, claim or artifact assessment, check, ethical concern, narrative text "
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


def check_references(obj: dict[str, Any]) -> None:
    """The rules JSON Schema cannot state: point and check ids are unique, the ids that
    `summarizes`, `applies_to.finding_id` and `checks[].finding_ids` name are findings,
    each `opinion.contributions[].claim_id` is a claim in `claim_assessments`, and
    `page_end` is not before `page`. Raises ValidationError on the first broken rule."""
    findings = obj.get("findings", {})
    finding_ids: set[str] = set()
    seen: set[str] = set()
    points = [(f"findings.{kind}", findings.get(kind, [])) for kind in FINDING_KINDS]
    actions = [(path, get(obj)) for path, get in ACTION_ITEM_LISTS]
    checks = obj.get("checks", [])
    for path, items in [*points, *actions, ("checks", checks)]:
        for index, point in enumerate(items):
            point_id = point.get("id")
            if point_id is None:
                continue
            if point_id in seen:
                raise ValidationError(f"{path}[{index}].id {point_id!r} is not unique")
            seen.add(point_id)
    for _, items in points:
        finding_ids.update(point["id"] for point in items if "id" in point)
    for path, items in points:
        for index, point in enumerate(items):
            for target in point.get("summarizes", []):
                if target not in finding_ids:
                    raise ValidationError(
                        f"{path}[{index}].summarizes names {target!r}, which is not a finding id"
                    )
    for path, items in actions:
        for index, item in enumerate(items):
            target = item.get("applies_to", {}).get("finding_id")
            if target is not None and target not in finding_ids:
                raise ValidationError(
                    f"{path}[{index}].applies_to.finding_id {target!r} is not a finding id"
                )
    for index, check in enumerate(checks):
        for target in check.get("finding_ids", []):
            if target not in finding_ids:
                raise ValidationError(
                    f"checks[{index}].finding_ids names {target!r}, which is not a finding id"
                )
    claim_ids = {claim["claim_id"] for claim in obj.get("claim_assessments", [])}
    for index, contribution in enumerate(obj.get("opinion", {}).get("contributions", [])):
        target = contribution.get("claim_id")
        if target is not None and target not in claim_ids:
            raise ValidationError(
                f"opinion.contributions[{index}].claim_id {target!r} is not a claim_id"
            )
    schema = ocrs_schema()
    for link in _evidence_links(obj, schema, schema):
        location = link.get("location", {})
        page, page_end = location.get("page"), location.get("page_end")
        if page is not None and page_end is not None and page_end < page:
            raise ValidationError(f"page_end {page_end} is before page {page}")
