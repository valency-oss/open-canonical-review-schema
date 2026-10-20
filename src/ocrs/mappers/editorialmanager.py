# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Editorial Manager format mapper for canonical reviews."""

from __future__ import annotations

import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..identifiers import generate_canonical_work_id
from ..schema import schema_id
from ..util import (
    first_paragraph,
    id_as_number,
    iso_date_or_time,
    map_recommendation_from_text,
    match_alias,
    now_iso,
    parse_date_flexible,
    parse_labeled_score,
    source_decision,
    source_work_id,
    split_decision,
)

# Editorial Manager recommendation codes
EM_RECOMMENDATION_MAP = {
    1: "accept",
    2: "minor_revision",
    3: "major_revision",
    4: "reject",
    5: "revise",  # Reject and Encourage Resubmission
}


def _extract_time(payload: dict[str, Any]) -> str:
    """Extract timestamp from Editorial Manager payload."""
    for k in ("dateReceived", "date_received", "reviewDate", "created_at"):
        v = payload.get(k)
        if v is not None:
            return parse_date_flexible(v)
    return now_iso()


def _get_reviewer_id(payload: dict[str, Any]) -> str | None:
    """Extract reviewer identifier."""
    for k in ("reviewerId", "reviewer_id", "reviewerEmail"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return None


def _get_work_id(payload: dict[str, Any]) -> str:
    """Extract manuscript/work identifier."""
    for k in ("manuscriptId", "manuscript_id", "ms_id", "documentId"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return "unknown"


def _build_target_identifiers(payload: dict[str, Any]) -> dict[str, Any]:
    """Build structured identifiers from Editorial Manager payload."""
    from ..identifiers import DOI_PATTERN

    identifiers: dict[str, Any] = {}

    # DOI if present
    doi = payload.get("doi")
    if isinstance(doi, str) and doi and DOI_PATTERN.match(doi):
        identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}

    # Manuscript ID as internal_id
    ms_id = _get_work_id(payload)
    if ms_id != "unknown":
        identifiers["internal_id"] = {
            "field_name": "manuscriptId",
            "value": ms_id,
        }

    return identifiers


def _build_human_referee(payload: dict[str, Any]) -> dict[str, Any]:
    """Build human_referee object with identity fields."""
    from ..identifiers import normalize_orcid

    human_referee: dict[str, Any] = {}

    # Check for ORCID
    orcid = payload.get("reviewerOrcid") or payload.get("orcid")
    if orcid and isinstance(orcid, str):
        normalized = normalize_orcid(orcid)
        if normalized:
            human_referee["orcid"] = normalized

    # Name and affiliation
    name = payload.get("reviewerName") or payload.get("reviewer_name")
    if name and isinstance(name, str):
        human_referee["name"] = name

    affiliation = payload.get("reviewerAffiliation") or payload.get("affiliation")
    if affiliation and isinstance(affiliation, str):
        human_referee["affiliation"] = affiliation

    return human_referee


def _get_review_id(payload: dict[str, Any]) -> str:
    """Extract review identifier."""
    for k in ("reviewId", "review_id", "id"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return str(uuid.uuid4())


def _parse_recommendation(payload: dict[str, Any]) -> str | None:
    """Parse recommendation from Editorial Manager payload."""
    # Try recommendation code first
    code = payload.get("recommendationCode")
    if isinstance(code, int) and code in EM_RECOMMENDATION_MAP:
        return EM_RECOMMENDATION_MAP[code]

    # Try text recommendation
    rec = payload.get("recommendation")
    if isinstance(rec, str):
        return map_recommendation_from_text(rec)

    return None


def _best_opinion_text(payload: dict[str, Any]) -> str | None:
    """Find the best text for the opinion summary, if the review has any."""
    for k in ("commentsToAuthor", "comments_to_author", "summary", "comments"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return first_paragraph(v.strip(), max_len=500)
    return None


def _map_ratings_to_metrics(
    ratings: list[dict[str, Any]],
    catalog: dict[str, Any],
    amap: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert Editorial Manager ratings array to canonical metrics.

    Ensures that:
    - metric.value is always numeric
    - Text labels (from 'label' field or parsed from score) go into metric.justification
    - Proper normalization is applied based on the source scale
    """
    metrics = []
    idx = {m["key"].casefold(): m for m in catalog.get("metrics", [])}

    for rating in ratings:
        if not isinstance(rating, dict):
            continue

        question = rating.get("question") or rating.get("criterionName") or ""
        score = rating.get("score")
        max_score = rating.get("maxScore") or rating.get("max_score") or 5

        if score is None:
            continue

        # Parse score which may be labeled (e.g., "4. Good")
        parsed = parse_labeled_score(
            score,
            system="editorialmanager",
            metric_type=question.lower(),
            expected_min=1,
            expected_max=int(max_score),
        )

        # If no numeric value, skip this rating
        if parsed["numeric"] is None:
            continue

        # Map question to metric key
        lcf = question.casefold().strip()
        key = "other"
        aspect = "other"

        if lcf in idx:
            m = idx[lcf]
            key = m["key"]
            aspect = m.get("aspect", "other")
        else:
            key = match_alias(lcf, amap) or "other"

        # Look up aspect from catalog if we found a key
        if key != "other":
            for m in catalog.get("metrics", []):
                if m["key"] == key:
                    aspect = m.get("aspect", "other")
                    break

        metric: dict[str, Any] = {
            "key": key,
            "label": question,
            "aspect": aspect,
            "scale": parsed["scale"],
            "value": parsed["numeric"],  # Always numeric
        }
        if parsed["normalized"] is not None:
            metric["normalized"] = {
                "value_0_1": float(max(0.0, min(1.0, parsed["normalized"]))),
                "method": "linear_to_unit_interval",
            }

        # Combine justification from parsed label and explicit label field
        justification_parts = []
        if parsed["label"]:
            justification_parts.append(parsed["label"])
        if rating.get("label"):
            justification_parts.append(rating["label"])
        if justification_parts:
            metric["justification"] = " - ".join(justification_parts)

        metrics.append(metric)

    return metrics


def from_editorialmanager(payload: dict[str, Any], *, keep_raw: bool = False) -> dict[str, Any]:
    """Convert an Editorial Manager review to canonical format.

    Args:
        payload: Editorial Manager review data (from API or export).
        keep_raw: If True, preserve the original payload in provenance.raw_payload.

    Returns:
        A canonical review dictionary.
    """
    catalog = load_catalog()
    amap = alias_map(catalog)

    created = _extract_time(payload)
    identifiers = _build_target_identifiers(payload)
    reviewer_id = _get_reviewer_id(payload)
    review_id = _get_review_id(payload)

    human_referee = _build_human_referee(payload)
    referee: dict[str, Any] = {
        "referee_type": "human",
        "identity_mode": "confidential",
        "human_referee": human_referee if human_referee else {},
    }
    if reviewer_id:
        referee["referee_id"] = reviewer_id

    out: dict[str, Any] = {
        "$schema": schema_id(),
        "review_id": f"em_{review_id}",
        "version": "1.0.0",
        "created_at": created,
        "provenance": {
            "source_system": "editorialmanager",
            "source_review_id": review_id,
            "imported_at": now_iso(),
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referee": referee,
        "target": {
            "identifiers": identifiers,
            "work_id": generate_canonical_work_id(identifiers),
            "work_type": "article",
        },
        "metric_catalog_ref": catalog.get("catalog_id"),
        "metrics": [],
        "opinion": {"summary": summary} if (summary := _best_opinion_text(payload)) else {},
    }

    if keep_raw:
        out["provenance"]["raw_payload"] = payload

    # Map title and venue
    title = payload.get("manuscriptTitle")
    if isinstance(title, str) and title.strip():
        out["target"]["title"] = title.strip()
    venue = payload.get("journalName") or payload.get("journal_name")
    if venue:
        out["target"]["venue"] = venue

    # Narrative mapping
    narrative: dict[str, Any] = {}

    for src, dst in [
        ("commentsToAuthor", "detailed_review"),
        ("comments_to_author", "detailed_review"),
        ("confidentialCommentsToEditor", "confidential_to_editors"),
        ("confidential_comments_to_editor", "confidential_to_editors"),
        ("summary", "summary"),
    ]:
        v = payload.get(src)
        if isinstance(v, str) and v.strip():
            if dst not in narrative:
                narrative[dst] = v.strip()

    if narrative:
        out["narrative"] = narrative

    # Decision
    rec = _parse_recommendation(payload)
    if rec:
        out["decision"] = split_decision({"recommendation": rec})

    # Revision number -> round
    rev = payload.get("revisionNumber")
    if rev is not None:
        # EM uses 0-based revision numbers, we use 1-based rounds
        out["review_context"] = {"round": int(rev) + 1}

    # Ratings -> metrics
    ratings = payload.get("ratings", [])
    if isinstance(ratings, list) and ratings:
        out["metrics"] = _map_ratings_to_metrics(ratings, catalog, amap)

    return out


def to_editorialmanager(canonical: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical review to Editorial Manager format.

    A review read from Editorial Manager is given back what its reader took: the reviewer,
    the date received, the recommendation with its code and each rating with its label, so
    that reading the result gives the same review.

    Args:
        canonical: A canonical review dictionary.

    Returns:
        An Editorial Manager-like review dictionary.
    """
    # Extract review ID
    rid = canonical.get("review_id", "")
    if rid.startswith("em_"):
        rid = rid[3:]

    out: dict[str, Any] = {
        "reviewId": rid,
        "manuscriptId": source_work_id(canonical.get("target", {})),
    }

    referee = canonical.get("referee", {}) or {}
    human = referee.get("human_referee", {}) or {}
    for field, value in [
        ("manuscriptTitle", canonical.get("target", {}).get("title")),
        ("journalName", canonical.get("target", {}).get("venue")),
        ("reviewerId", id_as_number(referee.get("referee_id"))),
        ("reviewerName", human.get("name")),
        ("reviewerOrcid", human.get("orcid")),
        ("dateReceived", iso_date_or_time(canonical.get("created_at"))),
    ]:
        if value is not None and value != "":
            out[field] = value

    # Map narrative
    nar = canonical.get("narrative", {}) or {}
    op = canonical.get("opinion", {}) or {}

    if nar.get("summary"):
        out["summary"] = nar["summary"]
    if nar.get("detailed_review"):
        out["commentsToAuthor"] = nar["detailed_review"]
    elif op.get("text"):
        out["commentsToAuthor"] = op["text"]
    elif op.get("summary"):
        out["commentsToAuthor"] = op["summary"]

    if nar.get("confidential_to_editors"):
        out["confidentialCommentsToEditor"] = nar["confidential_to_editors"]

    # Map recommendation
    dec = source_decision(canonical.get("decision", {}) or {})
    if isinstance(dec.get("recommendation"), str):
        out["recommendation"] = dec["recommendation"].replace("_", " ").title()
        codes = {v: k for k, v in EM_RECOMMENDATION_MAP.items()}
        if dec["recommendation"] in codes:
            out["recommendationCode"] = codes[dec["recommendation"]]

    # Map round -> revisionNumber
    ctx = canonical.get("review_context", {}) or {}
    if ctx.get("round"):
        out["revisionNumber"] = ctx["round"] - 1

    # Map metrics -> ratings
    ratings = []
    for m in canonical.get("metrics", []) or []:
        if not isinstance(m, dict):
            continue
        rating: dict[str, Any] = {
            "question": m.get("label") or m.get("key", ""),
            "score": m.get("value"),
        }
        scale = m.get("scale", {})
        if isinstance(scale, dict) and "max" in scale:
            rating["maxScore"] = scale["max"]
        else:
            rating["maxScore"] = 5
        if m.get("justification"):
            rating["label"] = m["justification"]
        ratings.append(rating)

    if ratings:
        out["ratings"] = ratings

    return out
