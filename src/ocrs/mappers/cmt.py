# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""CMT format mapper for canonical reviews."""

from __future__ import annotations

import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..hierarchy import LEGACY_SCHEMA
from ..identifiers import generate_canonical_work_id
from ..util import (
    field_name,
    first_paragraph,
    first_present,
    from_source,
    guess_scale_from_value,
    id_as_number,
    is_number,
    is_score_field,
    map_recommendation_from_numeric,
    map_recommendation_from_text,
    match_alias,
    narrative_field,
    narrative_text,
    normalize_linear,
    now_iso,
    parse_numeric_prefix,
    recommendation_label,
    referee_of,
    score_with_label,
    section,
    source_decision,
    source_work_id,
    split_decision,
)

NARR_KEYS = {"summary", "commentsToAuthors", "reviewText", "commentsToChairs"}


def _get_work_id(payload: dict[str, Any]) -> str:
    """Extract paper/work identifier."""
    for k in ("paperId", "submissionId", "paper_id", "submission_id"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return "unknown"


def _build_target_identifiers(payload: dict[str, Any]) -> dict[str, Any]:
    """Build structured identifiers from CMT payload."""
    from ..identifiers import DOI_PATTERN

    identifiers: dict[str, Any] = {}

    # DOI if present
    doi = payload.get("doi")
    if isinstance(doi, str) and doi and DOI_PATTERN.match(doi):
        identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}

    # Paper ID as internal_id
    work_id = _get_work_id(payload)
    if work_id != "unknown":
        identifiers["internal_id"] = {
            "field_name": "paperId",
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


def from_cmt(payload: dict[str, Any], *, keep_raw: bool = False) -> dict[str, Any]:
    catalog = load_catalog()
    amap = alias_map(catalog)

    source_review_id = first_present(payload, ("reviewId", "id"))
    review_id = str(source_review_id if source_review_id is not None else uuid.uuid4())
    created_at = first_present(payload, ("createdAt", "reviewDate"))
    created_at = created_at if isinstance(created_at, str) else now_iso()

    identifiers = _build_target_identifiers(payload)
    venue = payload.get("conferenceName")
    track = payload.get("trackName")

    # Build human referee identity
    human_referee = _build_human_referee(payload)
    referee: dict[str, Any] = {
        "referee_type": "human",
        "identity_mode": "confidential",
        "human_referee": human_referee if human_referee else {},
    }
    if payload.get("reviewerId") is not None:
        referee["referee_id"] = str(payload["reviewerId"])

    out: dict[str, Any] = {
        "$schema": LEGACY_SCHEMA,
        "review_id": review_id,
        "version": "1.0.0",
        "created_at": created_at,
        "provenance": {
            "source_system": "cmt",
            "source_review_id": "" if source_review_id is None else str(source_review_id),
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
            "work_type": "other",
        },
        "metric_catalog_ref": catalog.get("catalog_id"),
        "metrics": [],
        "opinion": {},
    }
    # Add title, venue and track only if present
    title = payload.get("paperTitle")
    if isinstance(title, str) and title.strip():
        out["target"]["title"] = title.strip()
    if venue:
        out["target"]["venue"] = venue
    if track:
        out["target"]["track"] = track

    if keep_raw:
        out["provenance"]["raw_payload"] = payload

    # The review's own text: its summary, and its comments to the authors and to the chairs
    narrative = []
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        narrative.append(section(summary.strip(), title="summary", role="summary"))
        out["opinion"]["summary"] = summary.strip()
    # The first of the fields with text, not the first filled with blanks
    review_field = next(
        (
            f
            for f in ("commentsToAuthors", "reviewText")
            if isinstance(payload.get(f), str) and payload[f].strip()
        ),
        "reviewText",
    )
    review_text = payload.get(review_field)
    if isinstance(review_text, str) and review_text.strip():
        narrative.append(
            section(review_text.strip(), title=review_field, role="review", audience="authors")
        )
        if "summary" not in out["opinion"]:
            out["opinion"]["summary"] = first_paragraph(review_text.strip())
    chairs = payload.get("commentsToChairs")
    if isinstance(chairs, str) and chairs.strip():
        narrative.append(
            section(chairs.strip(), title="commentsToChairs", role="review", audience="editors")
        )
    if narrative:
        out["narrative"] = narrative

    # Decision
    dec = {}
    rec_raw = first_present(payload, ("overallEvaluation", "recommendation"))
    if rec_raw is not None:
        num, rest = parse_numeric_prefix(rec_raw)
        if num is not None:
            scale = guess_scale_from_value(num)
            dec["recommendation"] = (
                map_recommendation_from_text(rest or "")
                or map_recommendation_from_numeric(num, scale)
                or "borderline"
            )
            n01 = normalize_linear(num, scale)
            out["metrics"].append(
                {
                    "key": "overall",
                    "label": "Overall Assessment",
                    "aspect": "overall",
                    "scale": scale,
                    "value": num,
                    "normalized": (
                        {"value_0_1": n01, "method": "linear_to_unit_interval"}
                        if n01 is not None
                        else None
                    ),
                }
            )
            if rest:
                out["metrics"][-1]["justification"] = rest
        elif isinstance(rec_raw, str):
            dec["recommendation"] = map_recommendation_from_text(rec_raw) or "borderline"
            # The recommendation in the form's own words
            if rec_raw.strip():
                dec["source_label"] = rec_raw.strip()
    conf_raw = payload.get("confidence")
    if conf_raw is not None:
        num, conf_label = parse_numeric_prefix(conf_raw)
        if num is not None:
            scale = guess_scale_from_value(num)
            n01 = normalize_linear(num, scale)
            out["metrics"].append(
                {
                    "key": "confidence",
                    "label": "Reviewer Confidence",
                    "aspect": "confidence",
                    "scale": scale,
                    "value": num,
                    "normalized": (
                        {"value_0_1": n01, "method": "linear_to_unit_interval"}
                        if n01 is not None
                        else None
                    ),
                }
            )
            if conf_label:
                out["metrics"][-1]["justification"] = conf_label
            if n01 is not None:
                dec["credence"] = float(max(0.0, min(1.0, n01)))
    if dec:
        out["decision"] = split_decision(dec)

    # Metrics from remaining numeric fields
    for k, v in payload.items():
        if (
            k in NARR_KEYS
            or k
            in {
                "reviewId",
                "id",
                "createdAt",
                "reviewDate",
                "paperId",
                "submissionId",
                "conferenceName",
                "trackName",
                "reviewerId",
                "overallEvaluation",
                "recommendation",
                "confidence",
            }
            or not is_score_field(k)
        ):
            continue
        num, rest = parse_numeric_prefix(v)
        if num is None:
            continue
        label = k.replace("_", " ").strip()
        lcf = label.casefold()
        key = match_alias(lcf, amap) or "other"
        aspect = next(
            (m.get("aspect") for m in catalog.get("metrics", []) if m["key"] == key),
            "other",
        )
        scale = guess_scale_from_value(num)
        n01 = normalize_linear(num, scale)
        mm = {"key": key, "label": label, "aspect": aspect, "scale": scale, "value": num}
        if n01 is not None:
            mm["normalized"] = {
                "value_0_1": float(max(0.0, min(1.0, n01))),
                "method": "linear_to_unit_interval",
            }
        if rest:
            mm["justification"] = rest
        out["metrics"].append(mm)

    if referee.get("referee_id") is None:
        referee.pop("referee_id", None)

    # cleanup
    for m in out["metrics"]:
        if m.get("normalized") is None:
            m.pop("normalized", None)
    return out


_DECISION_FIELDS = {"overallEvaluation", "recommendation", "confidence"}


def _recommendation_read_back(value: int | float, label: str | None) -> str:
    """The recommendation from_cmt takes from an overall score with this label."""
    return (
        map_recommendation_from_text(label or "")
        or map_recommendation_from_numeric(value, guess_scale_from_value(value))
        or "borderline"
    )


def to_cmt(canonical: dict[str, Any]) -> dict[str, Any]:
    """A CMT export row with what OCRS holds. A review read from CMT is given back its scores
    under their own field names, with their labels, so that reading the row gives the same
    review; a review from elsewhere gives its scores under their catalog keys."""
    target = canonical.get("target", {}) or {}
    referee = referee_of(canonical)
    same_source = from_source(canonical, "cmt")
    out: dict[str, Any] = {
        "reviewId": canonical.get("review_id"),
        "paperId": id_as_number(source_work_id(target)),
    }
    for field, value in [
        ("paperTitle", target.get("title")),
        ("conferenceName", target.get("venue")),
        ("trackName", target.get("track")),
        ("reviewerId", referee.get("referee_id")),
        ("reviewDate", canonical.get("created_at")),
    ]:
        if value is not None:
            out[field] = value

    # narrative/opinion
    op = canonical.get("opinion", {}) or {}
    # The comments to the authors under their own field, when read from CMT
    found = narrative_field(
        canonical, "review", ("commentsToAuthors", "reviewText"), same_source=same_source
    )
    review_field, review_text = found or ("commentsToAuthors", op.get("text"))
    # The summary, unless it is the first paragraph of the review, which the reader takes
    own_summary = narrative_text(canonical, "summary")
    summary = op.get("summary") or own_summary
    if isinstance(summary, str) and (
        own_summary is not None
        or not isinstance(review_text, str)
        or summary != first_paragraph(review_text)
    ):
        out["summary"] = summary
    if isinstance(review_text, str):
        out[review_field] = review_text
    chairs = narrative_text(canonical, audience="editors")
    if chairs is not None:
        out["commentsToChairs"] = chairs

    # decision + metrics
    dec = source_decision(canonical.get("decision", {}) or {})
    rec = dec.get("recommendation") if isinstance(dec.get("recommendation"), str) else None
    metrics = [m for m in canonical.get("metrics", []) or [] if isinstance(m, dict)]
    for m in metrics:
        if m.get("value") is None:
            continue
        key = m.get("key")
        if key == "overall":
            # The reader takes a recommendation from this field and reads only a number
            # there: any other value would hide the review's recommendation, or make one up
            if not is_number(m["value"]):
                continue
            # The reader takes the recommendation from the score's label, then its value: a
            # label that would read back as another recommendation gives way to the decision's
            label = m.get("justification")
            if rec and _recommendation_read_back(m["value"], label) != rec:
                label = recommendation_label(canonical)
                # Words the score's number would read past ("Not sure") give way to OCRS's
                if _recommendation_read_back(m["value"], label) != rec:
                    label = recommendation_label(canonical, own=False)
            out.setdefault("overallEvaluation", score_with_label({**m, "justification": label}))
        elif key == "confidence":
            out.setdefault("confidence", score_with_label(m))
        elif key:
            label = m.get("label")
            named = (same_source or key == "other") and isinstance(label, str) and label.strip()
            field = field_name(label) if named else key
            # The fields the reader takes the recommendation and the confidence from are theirs
            if field not in _DECISION_FIELDS:
                out.setdefault(field, score_with_label(m))
    # A recommendation OCRS cannot name goes too, in its words, which the reader keeps
    if "overallEvaluation" not in out and (label := recommendation_label(canonical)):
        out["recommendation"] = label
    return out
