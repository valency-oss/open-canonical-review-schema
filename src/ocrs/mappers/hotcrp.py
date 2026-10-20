# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""HotCRP format mapper for canonical reviews."""

from __future__ import annotations

import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..identifiers import generate_canonical_work_id
from ..schema import schema_id
from ..util import (
    field_name,
    first_paragraph,
    first_present,
    from_source,
    id_as_number,
    is_number,
    is_score_field,
    iso_to_epoch,
    map_recommendation_from_text,
    match_alias,
    now_iso,
    parse_date_flexible,
    parse_labeled_score,
    score_to_recommendation,
    score_with_label,
    source_decision,
    source_work_id,
    split_bullet_list,
    split_decision,
)

# Common HotCRP text field names that should not be treated as metrics
KNOWN_TEXT_KEYS = {
    "paper_summary",
    "summary",
    "comments",
    "strengths",
    "weaknesses",
    "questions",
    "questions_for_authors",
    "confidential_comments",
    "comments_to_pc",
    "detailed_comments",
}

# HotCRP expertise level mapping (common scales)
EXPERTISE_LEVEL_MAP = {
    1: "not_familiar",
    2: "somewhat_familiar",
    3: "knowledgeable",
    4: "expert",
    5: "expert",
}


def _extract_time(payload: dict[str, Any]) -> str:
    """Extract timestamp from HotCRP payload."""
    for k in ("submitted_at", "timeSubmitted", "created_at", "cdate"):
        v = payload.get(k)
        if v is not None:
            return parse_date_flexible(v)
    return now_iso()


def _get_reviewer_id(payload: dict[str, Any]) -> str | None:
    """Extract reviewer identifier from HotCRP payload."""
    reviewer = payload.get("reviewer")
    if isinstance(reviewer, dict):
        for k in ("user", "email", "id"):
            v = reviewer.get(k)
            if isinstance(v, str) and v:
                return v
    # Fallback to top-level fields
    for k in ("reviewerEmail", "reviewer_id", "contactId"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
        # HotCRP's contactId is a number
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)
    return None


def _get_work_id(payload: dict[str, Any]) -> str:
    """Extract paper/work identifier."""
    for k in ("pid", "paperId", "paper_id", "submission_id"):
        v = payload.get(k)
        if v is not None:
            return str(v)
    return "unknown"


def _build_target_identifiers(payload: dict[str, Any]) -> dict[str, Any]:
    """Build structured identifiers from HotCRP payload."""
    from ..identifiers import DOI_PATTERN

    identifiers: dict[str, Any] = {}

    # Check for DOI in payload
    doi = payload.get("doi")
    if isinstance(doi, str) and doi and DOI_PATTERN.match(doi):
        identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}

    # HotCRP paper ID as internal_id
    work_id = _get_work_id(payload)
    if work_id != "unknown":
        identifiers["internal_id"] = {
            "field_name": "hotcrp_pid",
            "value": work_id,
        }

    return identifiers


def _build_human_referee(payload: dict[str, Any]) -> dict[str, Any]:
    """Build human_referee object with identity fields."""
    from ..identifiers import normalize_orcid

    human_referee: dict[str, Any] = {}

    # Check for ORCID
    reviewer = payload.get("reviewer", {})
    orcid = None
    if isinstance(reviewer, dict):
        orcid = reviewer.get("orcid")
    if not orcid:
        orcid = payload.get("reviewerOrcid") or payload.get("orcid")

    if orcid and isinstance(orcid, str):
        normalized = normalize_orcid(orcid)
        if normalized:
            human_referee["orcid"] = normalized

    # Name and affiliation
    if isinstance(reviewer, dict):
        if reviewer.get("name"):
            human_referee["name"] = reviewer["name"]
        if reviewer.get("affiliation"):
            human_referee["affiliation"] = reviewer["affiliation"]

    return human_referee


def _best_opinion_text(payload: dict[str, Any]) -> str | None:
    """Find the best text for the opinion summary, if the review has any."""
    for k in ("paper_summary", "summary", "comments", "detailed_comments"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return first_paragraph(v.strip(), max_len=500)
    return None


def _collect_findings(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract strengths, weaknesses, questions from HotCRP fields. A form with both
    `questions` and `questions_for_authors` gives both, in that order."""
    findings: dict[str, Any] = {}
    for k in ("strengths", "weaknesses", "questions", "questions_for_authors"):
        v = payload.get(k)
        canon_key = "questions" if k == "questions_for_authors" else k
        items: list[dict[str, Any]] = []
        if isinstance(v, list):
            items = [{"text": str(x)} for x in v if x is not None and str(x).strip()]
        elif isinstance(v, str) and v.strip():
            items = [{"text": b} for b in split_bullet_list(v)]
        if items:
            findings.setdefault(canon_key, []).extend(items)
    return findings


def _parse_round(payload: dict[str, Any]) -> int | None:
    """Parse review round from HotCRP payload."""
    r = payload.get("round")
    if isinstance(r, int):
        return r
    if isinstance(r, str):
        # Parse strings like "R1", "R2", "main", "Round 2"
        s = r.strip().lower()
        if s in ("main", "r1", "round 1", "1"):
            return 1
        if s.startswith("r") and s[1:].isdigit():
            return int(s[1:])
        if s.startswith("round ") and s[6:].strip().isdigit():
            return int(s[6:].strip())
        if s.isdigit():
            return int(s)
    return None


def _metric_key_for_label(
    label: str,
    amap: dict[str, str],
    idx: dict[str, Any],
) -> tuple[str, str | None]:
    """Map a field label to a metric key and aspect."""
    if not label:
        return "other", "other"
    lcf = label.casefold()
    if lcf in idx:
        m = idx[lcf]
        return m["key"], m.get("aspect")
    key = match_alias(lcf, amap)
    if key:
        return key, None
    return "other", "other"


def from_hotcrp(payload: dict[str, Any], *, keep_raw: bool = False) -> dict[str, Any]:
    """Convert a HotCRP review to canonical format.

    Args:
        payload: HotCRP review data (from JSON export or API).
        keep_raw: If True, preserve the original payload in provenance.raw_payload.

    Returns:
        A canonical review dictionary.
    """
    catalog = load_catalog()
    amap = alias_map(catalog)
    idx = {m["key"].casefold(): m for m in catalog.get("metrics", [])}

    created = _extract_time(payload)
    identifiers = _build_target_identifiers(payload)
    reviewer_id = _get_reviewer_id(payload)

    # Generate review_id
    rid = payload.get("id")
    review_id = str(rid) if rid is not None else str(uuid.uuid4())

    # Build referee object, only adding referee_id if present
    human_referee = _build_human_referee(payload)
    referee: dict[str, Any] = {
        "referee_type": "human",
        "identity_mode": "confidential",
        "human_referee": human_referee if human_referee else {},
    }
    if reviewer_id:
        referee["referee_id"] = reviewer_id

    # Build provenance, only adding source_review_id if present
    provenance: dict[str, Any] = {
        "source_system": "hotcrp",
        "imported_at": now_iso(),
        "mapping": {
            "mapping_spec_id": "canonical-review.mapping.v1",
            "mapping_spec_version": "1.1.0",
            "mapper_version": "0.1.0",
        },
    }
    if rid is not None:
        provenance["source_review_id"] = str(rid)

    out: dict[str, Any] = {
        "$schema": schema_id(),
        "review_id": f"hotcrp_{review_id}",
        "version": "1.0.0",
        "created_at": created,
        "provenance": provenance,
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

    # Narrative mapping
    narrative: dict[str, Any] = {}
    for src, dst in [
        ("paper_summary", "summary"),
        ("summary", "summary"),
        ("comments", "detailed_review"),
        ("detailed_comments", "detailed_review"),
        ("confidential_comments", "confidential_to_editors"),
        ("comments_to_pc", "confidential_to_editors"),
        ("questions_for_authors", "author_questions"),
    ]:
        v = payload.get(src)
        if isinstance(v, str) and v.strip():
            if dst not in narrative:
                narrative[dst] = v.strip()
    if narrative:
        out["narrative"] = narrative

    # Findings
    findings = _collect_findings(payload)
    if findings:
        out["findings"] = findings

    # Parse overall merit / recommendation
    # The first of these the form fills; a null one does not hide the next
    rec_raw = first_present(
        payload, ("overall_merit", "overall", "recommendation", "rating", "score")
    )

    decision: dict[str, Any] = {}
    if rec_raw is not None:
        # Use enhanced parsing with proper scale handling
        parsed = parse_labeled_score(
            rec_raw,
            system="hotcrp",
            metric_type="overall_merit",
            expected_min=1,
            expected_max=5,  # Default HotCRP scale
        )

        if parsed["numeric"] is not None:
            # Determine recommendation from text label first, then numeric
            if parsed["label"]:
                decision["recommendation"] = (
                    map_recommendation_from_text(parsed["label"])
                    or score_to_recommendation(parsed["numeric"], scale_min=1, scale_max=5)
                    or "borderline"
                )
            else:
                decision["recommendation"] = (
                    score_to_recommendation(parsed["numeric"], scale_min=1, scale_max=5)
                    or "borderline"
                )

            # Build metric with numeric value and text justification
            metric: dict[str, Any] = {
                "key": "overall",
                "label": "Overall Merit",
                "aspect": "overall",
                "scale": parsed["scale"],
                "value": parsed["numeric"],  # Always numeric
            }
            if parsed["normalized"] is not None:
                metric["normalized"] = {
                    "value_0_1": parsed["normalized"],
                    "method": "linear_to_unit_interval",
                }
            # Store text label as justification
            if parsed["label"]:
                metric["justification"] = parsed["label"]

            out["metrics"].append(metric)
        elif isinstance(rec_raw, str):
            decision["recommendation"] = map_recommendation_from_text(rec_raw) or "borderline"

    # Parse reviewer expertise
    exp_raw = first_present(payload, ("reviewer_expertise", "expertise"))
    if exp_raw is not None:
        parsed = parse_labeled_score(
            exp_raw,
            system="hotcrp",
            metric_type="expertise",
            expected_min=1,
            expected_max=5,
        )
        if parsed["numeric"] is not None:
            metric = {
                "key": "confidence",
                "label": "Reviewer Expertise",
                "aspect": "confidence",
                "scale": parsed["scale"],
                "value": parsed["numeric"],  # Always numeric
            }
            if parsed["normalized"] is not None:
                metric["normalized"] = {
                    "value_0_1": parsed["normalized"],
                    "method": "linear_to_unit_interval",
                }
            # Store text label as justification
            if parsed["label"]:
                metric["justification"] = parsed["label"]
            out["metrics"].append(metric)

            # Also add expertise to review_context
            level = EXPERTISE_LEVEL_MAP.get(int(parsed["numeric"]), "knowledgeable")
            out["review_context"] = {"expertise": {"self_reported_level": level}}

    # Parse confidence if separate from expertise
    conf_raw = payload.get("confidence")
    if conf_raw is not None:
        parsed = parse_labeled_score(
            conf_raw,
            system="hotcrp",
            metric_type="confidence",
            expected_min=1,
            expected_max=5,
        )
        if parsed["numeric"] is not None:
            # Check if we already have a confidence metric
            has_conf = any(m.get("key") == "confidence" for m in out["metrics"])
            if not has_conf:
                metric = {
                    "key": "confidence",
                    "label": "Reviewer Confidence",
                    "aspect": "confidence",
                    "scale": parsed["scale"],
                    "value": parsed["numeric"],  # Always numeric
                }
                if parsed["normalized"] is not None:
                    metric["normalized"] = {
                        "value_0_1": parsed["normalized"],
                        "method": "linear_to_unit_interval",
                    }
                if parsed["label"]:
                    metric["justification"] = parsed["label"]
                out["metrics"].append(metric)
            if parsed["normalized"] is not None:
                decision["confidence"] = float(max(0.0, min(1.0, parsed["normalized"])))

    if decision:
        out["decision"] = split_decision(decision)

    # Additional numeric fields as metrics
    skip_keys = (
        KNOWN_TEXT_KEYS
        | {"id", "pid", "paperId", "ordinal", "rtype", "submitted", "submitted_at"}
        | {"reviewer", "round", "overall_merit", "overall", "recommendation", "rating"}
        | {"reviewer_expertise", "expertise", "confidence", "score"}
    )
    for k, v in payload.items():
        if k in skip_keys or not is_score_field(k):
            continue
        # Use enhanced parsing with proper label extraction
        parsed = parse_labeled_score(
            v,
            system="hotcrp",
            metric_type=k,
            expected_min=1,
            expected_max=5,  # Default HotCRP scale
        )
        if parsed["numeric"] is None:
            continue
        key, _ = _metric_key_for_label(k.replace("_", " ").strip(), amap, idx)
        aspect = None
        for m in catalog.get("metrics", []):
            if m["key"] == key:
                aspect = m.get("aspect")
                break
        if aspect is None:
            aspect = "other"
        metric_entry: dict[str, Any] = {
            "key": key,
            "label": k.replace("_", " ").strip(),
            "aspect": aspect,
            "scale": parsed["scale"],
            "value": parsed["numeric"],  # Always numeric
        }
        if parsed["normalized"] is not None:
            metric_entry["normalized"] = {
                "value_0_1": float(max(0.0, min(1.0, parsed["normalized"]))),
                "method": "linear_to_unit_interval",
            }
        # Store text label as justification
        if parsed["label"]:
            metric_entry["justification"] = parsed["label"]
        out["metrics"].append(metric_entry)

    # Clean up null normalized values
    for m in out["metrics"]:
        if m.get("normalized") is None:
            m.pop("normalized", None)

    # Add round to review_context if present
    rnd = _parse_round(payload)
    if rnd is not None:
        if "review_context" not in out:
            out["review_context"] = {}
        out["review_context"]["round"] = rnd

    return out


# The fields from_hotcrp takes the recommendation, the expertise and the confidence from
_DECISION_FIELDS = {
    "overall_merit",
    "overall",
    "recommendation",
    "rating",
    "score",
    "reviewer_expertise",
    "expertise",
    "confidence",
}


def _recommendation_read_back(value: int | float, label: str | None) -> str:
    """The recommendation from_hotcrp takes from overall_merit with this label."""
    return (
        (map_recommendation_from_text(label) if label else None)
        or score_to_recommendation(value, scale_min=1, scale_max=5)
        or "borderline"
    )


def to_hotcrp(canonical: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical review to a HotCRP review.

    A review read from HotCRP is given back as HotCRP holds it: its scores under their own
    field names with their labels ("4. Accept"), its reviewer, its submission time and its
    questions for the authors, so that reading the result gives the same review. A review
    from elsewhere gives its scores under their catalog keys.

    Args:
        canonical: A canonical review dictionary.

    Returns:
        A HotCRP-like review dictionary.
    """
    # Extract review ID
    rid = canonical.get("review_id", "")
    if rid.startswith("hotcrp_"):
        rid = rid[7:]

    same_source = from_source(canonical, "hotcrp")
    out: dict[str, Any] = {
        "id": id_as_number(rid),
        "pid": id_as_number(source_work_id(canonical.get("target", {}))),
    }
    submitted_at = iso_to_epoch(canonical.get("created_at"))
    if submitted_at is not None:
        out["submitted_at"] = submitted_at

    # The reviewer, as the reader takes it
    referee = canonical.get("referee", {}) or {}
    human = referee.get("human_referee", {}) or {}
    reviewer = {"user": referee.get("referee_id")} | {
        k: human.get(k) for k in ("name", "affiliation", "orcid")
    }
    reviewer = {k: v for k, v in reviewer.items() if v}
    if reviewer:
        out["reviewer"] = reviewer

    # Map opinion/narrative to comments
    op = canonical.get("opinion", {}) or {}
    nar = canonical.get("narrative", {}) or {}

    if nar.get("summary"):
        out["paper_summary"] = nar["summary"]
    if nar.get("detailed_review"):
        out["comments"] = nar["detailed_review"]
    elif op.get("text"):
        out["comments"] = op["text"]
    elif op.get("summary"):
        out["comments"] = op["summary"]

    if nar.get("confidential_to_editors"):
        out["confidential_comments"] = nar["confidential_to_editors"]
    if nar.get("author_questions"):
        out["questions_for_authors"] = nar["author_questions"]

    # Map findings
    findings = canonical.get("findings", {}) or {}
    for k in ("strengths", "weaknesses", "questions"):
        texts = [
            f.get("text") for f in findings.get(k) or [] if isinstance(f, dict) and f.get("text")
        ]
        if k == "questions" and "questions_for_authors" in out:
            # The reader adds the questions for the authors to the questions, after those from
            # `questions`: only those before them are written there
            asked = split_bullet_list(out["questions_for_authors"])
            if asked and texts[-len(asked) :] == asked:
                texts = texts[: -len(asked)]
        if texts:
            out[k] = "\n".join(f"- {text}" for text in texts)

    # Scores, each with its label. The overall score carries the recommendation in its label
    dec = source_decision(canonical.get("decision", {}) or {})
    rec = dec.get("recommendation") if isinstance(dec.get("recommendation"), str) else None
    rec_label = rec.replace("_", " ").title() if rec else None
    for m in canonical.get("metrics", []) or []:
        if not isinstance(m, dict) or m.get("value") is None:
            continue
        key, label = m.get("key"), m.get("label")
        if key == "overall":
            # The reader takes a recommendation from this field and reads only a number
            # there: any other value would hide the review's recommendation, or make one up
            if not is_number(m["value"]):
                continue
            # The reader takes the recommendation from the score's label, then its value: a
            # label that would read back as another recommendation gives way to the decision's
            label = m.get("justification")
            if rec and _recommendation_read_back(m["value"], label) != rec:
                label = rec_label
            out.setdefault("overall_merit", score_with_label({**m, "justification": label}, ". "))
        elif key == "confidence":
            # HotCRP asks for expertise; a review read from it may also give a confidence
            confidence = same_source and label == "Reviewer Confidence"
            out.setdefault(
                "confidence" if confidence else "reviewer_expertise", score_with_label(m, ". ")
            )
        elif key:
            named = (same_source or key == "other") and isinstance(label, str) and label.strip()
            field = field_name(label) if named else key
            # The fields the reader takes the recommendation and the expertise from are theirs
            if field not in _DECISION_FIELDS:
                out.setdefault(field, score_with_label(m, ". "))
    if rec_label and "overall_merit" not in out:
        out["overall_merit"] = rec_label

    # Add round if present
    ctx = canonical.get("review_context", {}) or {}
    if ctx.get("round"):
        out["round"] = f"R{ctx['round']}"

    return out
