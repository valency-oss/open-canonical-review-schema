# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Editorial Manager format mapper for canonical reviews."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..hierarchy import LEGACY_SCHEMA
from ..identifiers import generate_canonical_work_id
from ..util import (
    department_affiliation,
    fields_for,
    first_paragraph,
    from_source,
    id_as_number,
    iso_date_or_time,
    map_recommendation_from_text,
    match_alias,
    narrative_field,
    narrative_parts,
    now_iso,
    parse_date_flexible,
    parse_labeled_score,
    recommendation_label,
    referee_of,
    score_sheet_answers,
    score_sheet_questions,
    section,
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


# Editorial Manager's web service (getReviewerInfoFull) gives one record per reviewer of a
# submission's revision, in the shape of ScholarOne's: the reviewer as `reviewerPersonId`,
# `reviewerFullName`, `reviewerORCIDId` and `scopusId`, their `departments`, the
# recommendation's text as `reviewerRecommendation`, the revision, the time the score sheet was
# completed, and the score sheet's questions and answers. These are the fields of the names the
# reader takes elsewhere. The record has no comments to the editor, and its rating-form
# questions, the editor's rating of the reviewer, are not part of the review.
API_FIELDS = {
    "reviewerPersonId": "reviewerId",
    "reviewerFullName": "reviewerName",
    "reviewerORCIDId": "reviewerOrcid",
    "reviewerRecommendation": "recommendation",
    "scoreSheetCompletedDate": "dateReceived",
    "revision": "revisionNumber",
}


def _with_known_names(payload: dict[str, Any]) -> dict[str, Any]:
    """The review with the web service's field names as the names the reader takes, the
    reviewer's first department as `reviewerAffiliation`, and, since the record has no review
    ID, one made of the revision's document ID and the reviewer's."""
    out = dict(payload)
    for api_name, name in API_FIELDS.items():
        if api_name in payload and name not in out:
            out[name] = payload[api_name]
    affiliation = department_affiliation(payload.get("departments"))
    if affiliation and "reviewerAffiliation" not in out:
        out["reviewerAffiliation"] = affiliation
    document, person = payload.get("documentId"), payload.get("reviewerPersonId")
    no_id = all(out.get(k) is None for k in ("reviewId", "review_id", "id"))
    if no_id and document is not None and person is not None:
        out["reviewId"] = f"{document}_p{person}"
    return out


# The fields of the review's own text the reader takes, in order, each as a part with
# its role and audience; the first the form fills for each role and audience
NARRATIVE_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("summary", "summary", None),
    ("commentsToAuthor", "review", "authors"),
    ("comments_to_author", "review", "authors"),
    ("confidentialCommentsToEditor", "review", "editors"),
    ("confidential_comments_to_editor", "review", "editors"),
)


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

    # The web service gives the reviewer's Scopus author ID as a number
    scopus = payload.get("scopusId")
    if isinstance(scopus, (int, str)) and not isinstance(scopus, bool):
        if re.fullmatch(r"[1-9]\d{9,11}", str(scopus).strip()):
            human_referee["scopus_id"] = str(scopus).strip()

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

    raw, payload = payload, _with_known_names(payload)
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
        "$schema": LEGACY_SCHEMA,
        "review_id": f"em_{review_id}",
        "version": "1.0.0",
        "created_at": created,
        "provenance": {
            "source_system": "editorialmanager",
            "source_review_id": review_id,
            "imported_at": now_iso(),
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.2.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [referee],
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
        out["provenance"]["raw_payload"] = raw

    # The score sheet's answers: those with a number are ratings, those in words parts of the
    # review's text
    scored, written = score_sheet_answers(payload.get("scoreSheetCustomQuestions"))

    # Map title and venue
    title = payload.get("manuscriptTitle")
    if isinstance(title, str) and title.strip():
        out["target"]["title"] = title.strip()
    venue = payload.get("journalName") or payload.get("journal_name")
    if venue:
        out["target"]["venue"] = venue

    # The review's own text, each field as a part, then the score sheet's answers in words
    narrative: list[dict[str, Any]] = []
    taken: set[tuple[str, str | None]] = set()
    for field, role, audience in NARRATIVE_FIELDS:
        v = payload.get(field)
        if isinstance(v, str) and v.strip() and (role, audience) not in taken:
            taken.add((role, audience))
            narrative.append(section(v.strip(), title=field, role=role, audience=audience))
    narrative += [section(text, title=question) for question, text in written]
    if narrative:
        out["narrative"] = narrative

    # Decision
    # The recommendation, and its text as the source wrote it
    decision = {"recommendation": _parse_recommendation(payload)}
    text = payload.get("recommendation")
    if isinstance(text, str) and text.strip():
        decision["source_label"] = text.strip()
    if decision := split_decision(decision):
        out["decision"] = decision

    # Revision number -> round
    rev = payload.get("revisionNumber")
    if rev is not None:
        # EM uses 0-based revision numbers, we use 1-based rounds
        out["review_context"] = {"round": int(rev) + 1}

    # Ratings -> metrics
    ratings = payload.get("ratings", [])
    ratings = [*ratings] if isinstance(ratings, list) else []
    ratings += [
        {"question": q, "score": value} | ({"label": label} if label else {})
        for q, value, label in scored
    ]
    if ratings:
        out["metrics"] = _map_ratings_to_metrics(ratings, catalog, amap)

    return out


def to_editorialmanager(canonical: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical review to Editorial Manager format.

    A review read from Editorial Manager is given back what its reader took: the reviewer,
    the date received, the recommendation with its code, each rating with its label, and the
    score sheet's answers in words as its questions, so that reading the result gives the
    same review.

    Args:
        canonical: A canonical review dictionary.

    Returns:
        An Editorial Manager-like review dictionary.
    """
    same_source = from_source(canonical, "editorialmanager")
    # Extract review ID
    rid = canonical.get("review_id", "")
    if rid.startswith("em_"):
        rid = rid[3:]

    out: dict[str, Any] = {
        "reviewId": rid,
        "manuscriptId": source_work_id(canonical.get("target", {})),
    }

    referee = referee_of(canonical)
    human = referee.get("human_referee", {}) or {}
    for field, value in [
        ("manuscriptTitle", canonical.get("target", {}).get("title")),
        ("journalName", canonical.get("target", {}).get("venue")),
        ("reviewerId", id_as_number(referee.get("referee_id"))),
        ("reviewerName", human.get("name")),
        ("reviewerAffiliation", human.get("affiliation")),
        ("reviewerOrcid", human.get("orcid")),
        ("scopusId", id_as_number(human.get("scopus_id"))),
        ("dateReceived", iso_date_or_time(canonical.get("created_at"))),
    ]:
        if value is not None and value != "":
            out[field] = value

    # Map narrative
    op = canonical.get("opinion", {}) or {}

    # Each part of the review's own text under its own field, when read from this system
    def own_field(role: str, *, editors: bool = False) -> tuple[str, str] | None:
        fields = fields_for(NARRATIVE_FIELDS, role, editors=editors)
        audience = "editors" if editors else None
        return narrative_field(canonical, role, fields, audience=audience, same_source=same_source)

    if summary := own_field("summary"):
        out[summary[0]] = summary[1]
    if review := own_field("review"):
        out[review[0]] = review[1]
    elif op.get("text"):
        out["commentsToAuthor"] = op["text"]
    elif op.get("summary"):
        out["commentsToAuthor"] = op["summary"]

    if confidential := own_field("review", editors=True):
        out[confidential[0]] = confidential[1]
    # Parts of the text, as the score sheet's questions answered in words
    questions = score_sheet_questions(narrative_parts(canonical))
    if questions:
        out["scoreSheetCustomQuestions"] = questions

    # Map recommendation
    # A recommendation OCRS cannot name goes back in the source's words, without a code
    dec = source_decision(canonical.get("decision", {}) or {})
    if label := recommendation_label(canonical):
        out["recommendation"] = label
        codes = {v: k for k, v in EM_RECOMMENDATION_MAP.items()}
        if dec.get("recommendation") in codes:
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
