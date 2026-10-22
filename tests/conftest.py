# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Pytest configuration for OCRS tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# Source-codec regression tests inspect the old field layout to retain their detailed
# expectations about source values. Every public import is validated as 0.9 BEFORE this
# projection. test_hierarchy.py exercises the actual 0.9 records and links directly.
def codec_map_from(*args, **kwargs):
    from ocrs import map_from, validate_canonical
    from ocrs.hierarchy import legacy_view

    review = map_from(*args, **kwargs)
    validate_canonical(review)
    return legacy_view(review)


def codec_map_to(target, review):
    from ocrs import map_to, schema_id
    from ocrs.hierarchy import upgrade_content
    from ocrs.schema import is_hierarchical

    if not is_hierarchical(review.get("$schema", "")):
        review = upgrade_content(review, unbounded_fallback=True)
        review["$schema"] = schema_id()
    return map_to(target, review)


def codec_map_with_record(*args, **kwargs):
    from ocrs import map_with_record, validate_canonical
    from ocrs.hierarchy import legacy_view

    result = map_with_record(*args, **kwargs)
    validate_canonical(result.review)
    return result.model_copy(update={"review": legacy_view(result.review)})


def codec_validate(review):
    from ocrs import schema_id, validate_canonical
    from ocrs.hierarchy import upgrade_content
    from ocrs.schema import is_hierarchical

    if not is_hierarchical(review.get("$schema", "")):
        review = upgrade_content(review, unbounded_fallback=True)
        review["$schema"] = schema_id()
    validate_canonical(review)


def narrative_fields(review: dict) -> dict:
    """A review's own text as OCRS 0.7 named its parts, so that tests can say which text a
    reader took for which: summary, detailed_review, author_questions, confidential_to_editors,
    and the other parts as sections."""
    named = {
        ("summary", None): "summary",
        ("review", None): "detailed_review",
        ("questions", None): "author_questions",
        ("review", "editors"): "confidential_to_editors",
    }
    fields: dict = {}
    for part in review.get("narrative") or []:
        audience = "editors" if part.get("audience") == "editors" else None
        field = named.get((part.get("role"), audience))
        if field:
            fields.setdefault(field, part["content"])
        else:
            section = {k: part[k] for k in ("title", "content", "tags") if k in part}
            fields.setdefault("sections", []).append(section)
    return fields
