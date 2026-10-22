# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Journal narrative format mapper for canonical reviews."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..hierarchy import LEGACY_SCHEMA
from ..identifiers import generate_canonical_work_id, parse_canonical_work_id
from ..util import first_paragraph, narrative_text, now_iso, referee_of, section


def _build_target_identifiers(payload: dict[str, Any]) -> dict[str, Any]:
    """Build structured identifiers from journal payload."""
    from ..identifiers import DOI_PATTERN

    identifiers: dict[str, Any] = {}

    # DOI is primary for journal articles
    doi = payload.get("doi")
    if isinstance(doi, str) and doi and DOI_PATTERN.match(doi):
        identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}

    # Manuscript ID as internal_id
    ms_id = payload.get("manuscript_id")
    if isinstance(ms_id, str) and ms_id:
        identifiers["internal_id"] = {
            "field_name": "manuscript_id",
            "value": ms_id,
        }
    elif payload.get("work_id"):
        identifiers["internal_id"] = {
            "field_name": "work_id",
            "value": str(payload["work_id"]),
        }

    return identifiers


# A heading on a line of its own, as journals print a review's parts: "Summary:", "Strengths:"
_HEADING = re.compile(r"^[^\n]{1,60}:$")


def _summary(text: str) -> str:
    """The review's first paragraph, or, when that is a heading ("Summary:"), the paragraph
    under it."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1 and _HEADING.match(paragraphs[0]):
        return first_paragraph(paragraphs[1], max_len=500)
    return first_paragraph(text, max_len=500)


def from_journal_narrative(
    payload: dict[str, Any],
    *,
    keep_raw: bool = False,
) -> dict[str, Any]:
    review_id = str(payload.get("review_id") or payload.get("id") or uuid.uuid4())
    created_at = (
        payload.get("created_at") if isinstance(payload.get("created_at"), str) else now_iso()
    )
    full_text = payload.get("full_text") if isinstance(payload.get("full_text"), str) else ""

    identifiers = _build_target_identifiers(payload)
    venue = payload.get("journal") or payload.get("venue")
    reviewer_id = payload.get("reviewer_id")

    out: dict[str, Any] = {
        "$schema": LEGACY_SCHEMA,
        "review_id": review_id,
        "version": "1.0.0",
        "created_at": created_at,
        "provenance": {
            "source_system": "journal_narrative",
            "source_review_id": str(payload.get("source_review_id") or payload.get("id") or ""),
            "imported_at": now_iso(),
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.2.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [
            {
                "referee_type": "human",
                "identity_mode": "confidential",
                "human_referee": {},
            }
        ],
        "target": {
            "identifiers": identifiers,
            "work_id": generate_canonical_work_id(identifiers),
            "work_type": "article",
        },
        "metrics": [],
        "opinion": {"summary": _summary(full_text)} if full_text.strip() else {},
    }
    if full_text.strip():
        out["narrative"] = [section(full_text.strip(), title="full_text", role="review")]

    # A journal's reviewer number is an ID like any other
    if reviewer_id is not None and reviewer_id != "":
        out["referees"][0]["referee_id"] = str(reviewer_id)
    if isinstance(venue, str) and venue.strip():
        out["target"]["venue"] = venue.strip()

    if keep_raw:
        out["provenance"]["raw_payload"] = payload
    return out


def to_journal_narrative(canonical: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    target = canonical.get("target", {})
    doi = ((target.get("identifiers") or {}).get("doi") or {}).get("value")
    if not doi:
        parsed = parse_canonical_work_id(str(target.get("work_id", "")))
        doi = parsed[2] if parsed and parsed[0] == "doi" else None
    out["doi"] = doi
    out["journal"] = canonical.get("target", {}).get("venue")
    out["review_id"] = canonical.get("review_id")
    out["created_at"] = canonical.get("created_at")
    reviewer_id = referee_of(canonical).get("referee_id")
    if reviewer_id:
        out["reviewer_id"] = reviewer_id
    # Narrative text
    text = None
    review_text = narrative_text(canonical, "review")
    if review_text and review_text.strip():
        text = review_text.strip()
    else:
        op = canonical.get("opinion", {}) or {}
        if isinstance(op.get("text"), str) and op["text"].strip():
            text = op["text"].strip()
        elif isinstance(op.get("summary"), str):
            text = op["summary"]
    out["full_text"] = text or ""
    return out
