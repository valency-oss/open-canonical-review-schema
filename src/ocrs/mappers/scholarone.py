# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""ScholarOne format mapper for canonical reviews."""

from __future__ import annotations

import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..identifiers import generate_canonical_work_id
from ..scales import (
    SCHOLARONE_RECOMMENDATION,
)
from ..schema import schema_id
from ..util import (
    first_paragraph,
    first_present,
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

# ScholarOne recommendation codes (typical configuration)
S1_RECOMMENDATION_MAP = {
    1: "accept",
    2: "minor_revision",
    3: "major_revision",
    4: "reject",
    5: "revise",  # Reject with option to resubmit
}


def _extract_time(payload: dict[str, Any]) -> str:
    """Extract timestamp from ScholarOne payload."""
    for k in (
        "dateReviewReceived",
        "date_review_received",
        "reviewDate",
        "created_at",
    ):
        v = payload.get(k)
        if v is not None:
            return parse_date_flexible(v)
    return now_iso()


def _get_reviewer_id(payload: dict[str, Any]) -> str | None:
    """Extract reviewer identifier."""
    # ScholarOne often uses reviewer number rather than ID
    reviewer_num = first_present(payload, ("reviewerNumber", "reviewer_number"))
    if reviewer_num is not None:
        return f"reviewer_{reviewer_num}"
    for k in ("reviewerId", "reviewer_id", "reviewerOrcid"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return None


def _get_work_id(payload: dict[str, Any]) -> str:
    """Extract document/work identifier."""
    for k in ("documentId", "document_id", "submissionId", "submission_id", "ms_id"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return "unknown"


def _build_target_identifiers(payload: dict[str, Any]) -> dict[str, Any]:
    """Build structured identifiers from ScholarOne payload."""
    from ..identifiers import DOI_PATTERN

    identifiers: dict[str, Any] = {}

    # DOI if present
    doi = payload.get("doi")
    if isinstance(doi, str) and doi and DOI_PATTERN.match(doi):
        identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}

    # Document ID as internal_id
    work_id = _get_work_id(payload)
    if work_id != "unknown":
        identifiers["internal_id"] = {
            "field_name": "documentId",
            "value": work_id,
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
    """Generate a review identifier from ScholarOne fields."""
    doc_id = payload.get("documentId") or payload.get("document_id") or ""
    sub_id = payload.get("submissionId") or payload.get("submission_id") or ""
    rev_num = first_present(payload, ("reviewerNumber", "reviewer_number"))
    rev_num = "" if rev_num is None else rev_num

    if doc_id and rev_num != "":
        return f"{doc_id}_r{rev_num}"
    if sub_id and rev_num != "":
        return f"{sub_id}_r{rev_num}"
    if doc_id:
        return str(doc_id)
    return str(uuid.uuid4())


def _recommendation_code(value: Any) -> int | None:
    """The recommendation code, when it is one of ScholarOne's 1-5."""
    if isinstance(value, int) and not isinstance(value, bool) and value in S1_RECOMMENDATION_MAP:
        return value
    return None


def _parse_recommendation(payload: dict[str, Any]) -> str | None:
    """Parse recommendation from ScholarOne payload."""
    # Try numeric recommendation first
    rec_num = payload.get("overallRecommendation")
    if _recommendation_code(rec_num) is not None:
        return S1_RECOMMENDATION_MAP[rec_num]

    # A code outside 1-5 says nothing (and the codes are lower-is-better, so no
    # higher-is-better scale applies); the label may still say it
    rec_label = payload.get("overallRecommendationLabel")
    if isinstance(rec_label, str):
        return map_recommendation_from_text(rec_label)

    return None


def _best_opinion_text(payload: dict[str, Any]) -> str | None:
    """Find the best text for the opinion summary, if the review has any."""
    for k in ("commentsToAuthor", "comments_to_author", "summary"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return first_paragraph(v.strip(), max_len=500)
    return None


def _map_criteria_to_metrics(
    criteria: list[dict[str, Any]],
    catalog: dict[str, Any],
    amap: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert ScholarOne criteriaResponses to canonical metrics.

    Ensures that:
    - metric.value is always numeric
    - Text labels (from 'label' field or parsed from response) go into metric.justification
    - Proper normalization is applied based on the source scale
    """
    metrics = []
    idx = {m["key"].casefold(): m for m in catalog.get("metrics", [])}

    for crit in criteria:
        if not isinstance(crit, dict):
            continue

        name = crit.get("criterionName") or crit.get("name") or ""
        response = first_present(crit, ("response", "score"))
        max_response = crit.get("maxResponse") or crit.get("max_response") or 5

        if response is None:
            continue

        # Parse response which may be labeled (e.g., "4. Good")
        parsed = parse_labeled_score(
            response,
            system="scholarone",
            metric_type=name.lower(),
            expected_min=1,
            expected_max=int(max_response),
        )

        # If no numeric value, skip this criterion
        if parsed["numeric"] is None:
            continue

        # Map criterion name to metric key
        lcf = name.casefold().strip()
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
            "label": name,
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
        if crit.get("label"):
            justification_parts.append(crit["label"])
        if justification_parts:
            metric["justification"] = " - ".join(justification_parts)

        metrics.append(metric)

    return metrics


def from_scholarone(payload: dict[str, Any], *, keep_raw: bool = False) -> dict[str, Any]:
    """Convert a ScholarOne review to canonical format.

    Args:
        payload: ScholarOne review data (from Web Services API or export).
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

    # Build referee object, only adding referee_id if present
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
        "review_id": f"s1_{review_id}",
        "version": "1.0.0",
        "created_at": created,
        "provenance": {
            "source_system": "scholarone",
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
        ("commentsToEditor", "confidential_to_editors"),
        ("comments_to_editor", "confidential_to_editors"),
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

        # Also add overall metric if we have numeric recommendation
        rec_num = payload.get("overallRecommendation")
        rec_label = payload.get("overallRecommendationLabel")
        if _recommendation_code(rec_num) is not None:
            # Note: ScholarOne uses lower=better for recommendations (1=Accept, 5=Reject)
            # But we normalize so 1.0 = best, using the SCHOLARONE_RECOMMENDATION scale
            parsed = parse_labeled_score(
                rec_num,
                system="scholarone",
                metric_type="recommendation",
                expected_min=1,
                expected_max=5,
            )
            if parsed["numeric"] is not None:
                metric_entry: dict[str, Any] = {
                    "key": "overall",
                    "label": "Overall Recommendation",
                    "aspect": "overall",
                    "scale": parsed["scale"],
                    "value": parsed["numeric"],  # Always numeric
                }
                # For recommendation codes, invert normalization (lower code = better)
                # Use SCHOLARONE_RECOMMENDATION.normalize which handles higher_is_better=False
                norm = SCHOLARONE_RECOMMENDATION.normalize(parsed["numeric"])
                if norm is not None:
                    metric_entry["normalized"] = {
                        "value_0_1": norm,
                        "method": "linear_to_unit_interval",
                    }
                # Add label as justification
                if rec_label:
                    metric_entry["justification"] = rec_label
                out["metrics"].append(metric_entry)

    # Criteria responses -> metrics
    criteria = payload.get("criteriaResponses", [])
    if isinstance(criteria, list) and criteria:
        out["metrics"].extend(_map_criteria_to_metrics(criteria, catalog, amap))

    # Clean up null normalized values
    for m in out["metrics"]:
        if m.get("normalized") is None:
            m.pop("normalized", None)

    # Competing interests
    coi = payload.get("competingInterests")
    if isinstance(coi, str) and coi.strip().lower() not in ("none", "none declared"):
        out["referee"]["competing_interests_declared"] = True
        out["referee"]["competing_interests_statement"] = coi
    elif coi:
        out["referee"]["competing_interests_declared"] = False

    return out


def to_scholarone(canonical: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical review to ScholarOne format.

    A review read from ScholarOne is given back what its reader took: the reviewer, the date
    received, the recommendation with its label, competing interests and each criterion with
    its label, so that reading the result gives the same review.

    Args:
        canonical: A canonical review dictionary.

    Returns:
        A ScholarOne-like review dictionary.
    """
    # Extract review ID
    rid = canonical.get("review_id", "")
    if rid.startswith("s1_"):
        rid = rid[3:]

    # Try to parse reviewer number from review_id
    reviewer_num = None
    if "_r" in rid:
        parts = rid.rsplit("_r", 1)
        if parts[1].isdigit():
            reviewer_num = int(parts[1])
            rid = parts[0]

    out: dict[str, Any] = {
        "documentId": source_work_id(canonical.get("target", {})),
    }

    referee = canonical.get("referee", {}) or {}
    human = referee.get("human_referee", {}) or {}
    if reviewer_num is not None:
        out["reviewerNumber"] = reviewer_num
    elif referee.get("referee_id"):
        out["reviewerId"] = referee["referee_id"]
    for field, value in [
        ("reviewerName", human.get("name")),
        ("reviewerOrcid", human.get("orcid")),
        ("manuscriptTitle", canonical.get("target", {}).get("title")),
        ("journalName", canonical.get("target", {}).get("venue")),
        ("dateReviewReceived", iso_date_or_time(canonical.get("created_at"))),
    ]:
        if value:
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
        out["commentsToEditor"] = nar["confidential_to_editors"]

    # Map recommendation
    dec = source_decision(canonical.get("decision", {}) or {})
    if isinstance(dec.get("recommendation"), str):
        rec = dec["recommendation"]
        # Reverse map to numeric
        reverse_map = {v: k for k, v in S1_RECOMMENDATION_MAP.items()}
        if rec in reverse_map:
            out["overallRecommendation"] = reverse_map[rec]
        # The reader takes the recommendation from the code, and from the label only without
        # one. The label the source gave is kept unless it says another recommendation; without
        # a code it must say this one, or one that does is written
        overall = next(
            (
                m
                for m in canonical.get("metrics", []) or []
                if isinstance(m, dict) and m.get("key") == "overall"
            ),
            {},
        )
        label = overall.get("justification")
        says = map_recommendation_from_text(label) if label else None
        if label and (says == rec or ("overallRecommendation" in out and says is None)):
            out["overallRecommendationLabel"] = label
        elif "overallRecommendation" not in out:
            out["overallRecommendationLabel"] = rec.replace("_", " ").title()

    # Map metrics -> criteriaResponses
    criteria = []
    for m in canonical.get("metrics", []) or []:
        if not isinstance(m, dict):
            continue
        # Skip overall metric (handled as recommendation)
        if m.get("key") == "overall":
            continue

        crit: dict[str, Any] = {
            "criterionName": m.get("label") or m.get("key", ""),
            "response": m.get("value"),
        }
        scale = m.get("scale", {})
        if isinstance(scale, dict) and "max" in scale:
            crit["maxResponse"] = scale["max"]
        else:
            crit["maxResponse"] = 5
        if m.get("justification"):
            crit["label"] = m["justification"]
        criteria.append(crit)

    if criteria:
        out["criteriaResponses"] = criteria

    # Competing interests, as the reader takes them: a statement, or none declared
    if referee.get("competing_interests_statement"):
        out["competingInterests"] = referee["competing_interests_statement"]
    elif referee.get("competing_interests_declared") is False:
        out["competingInterests"] = "None declared"

    return out
