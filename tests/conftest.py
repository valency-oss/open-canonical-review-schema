# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Pytest configuration for OCRS tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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
