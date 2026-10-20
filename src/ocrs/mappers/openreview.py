# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""OpenReview format mapper for canonical reviews."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..identifiers import generate_canonical_work_id
from ..scales import normalized_to_recommendation
from ..schema import schema_id
from ..util import (
    epoch_ms_to_iso,
    field_name,
    first_paragraph,
    first_present_item,
    from_source,
    guess_scale_from_value,
    is_number,
    is_score_field,
    iso_to_epoch,
    map_recommendation_from_numeric,
    map_recommendation_from_text,
    match_alias,
    normalize_linear,
    now_iso,
    parse_numeric_prefix,
    score_with_label,
    source_decision,
    source_work_id,
    split_decision,
)

KNOWN_TEXT_KEYS = {
    "summary",
    "metareview",
    "comment",
    "paper_summary",
    "review_summary",
    "review",
    "comments",
    "main_review",
    "detailed_review",
    "confidential_comments",
    "confidential_to_chairs",
    "questions",
    "strengths",
    "weaknesses",
}


RECOMMENDATION_KEYS = (
    "recommendation",
    "rating",
    "decision",
    "overallEvaluation",
    "overall_rating",
    "overall",
)
CONFIDENCE_KEYS = ("confidence", "reviewer_confidence")


def _extract_time(note: dict[str, Any]) -> str:
    # OpenReview uses cdate/tcdate in ms since epoch
    for k in ("tcdate", "cdate", "tmdate", "mdate"):
        v = note.get(k)
        if isinstance(v, int):
            return epoch_ms_to_iso(v)
    return now_iso()


# The kind of note an invitation makes: `…/-/Official_Review`, `…/-/Meta_Review`, `…/-/Decision`
_INVITATION_KIND = re.compile(r"/-/(?:[^/]+/)?(Official_Review|Meta_Review|Decision)$")
_REVIEW_TYPES = {"Meta_Review": "meta_review", "Decision": "recommendation"}


def _get_content(note: dict[str, Any]) -> dict[str, Any]:
    """The review form's fields. API v2 wraps each as `{"value": …}` (with its readers beside
    it, when they differ from the note's); API v1 gives the value itself."""
    c = note.get("content")
    if not isinstance(c, dict):
        return {}
    return {k: v["value"] if isinstance(v, dict) and "value" in v else v for k, v in c.items()}


def _note_kind(note: dict[str, Any]) -> str | None:
    """`Official_Review`, `Meta_Review` or `Decision`, by the invitation (`invitations` in
    API v2, `invitation` in v1), or None."""
    invitations = note.get("invitations")
    names = [*invitations] if isinstance(invitations, list) else []
    names.append(note.get("invitation"))
    for name in names:
        found = _INVITATION_KIND.search(name) if isinstance(name, str) else None
        if found:
            return found.group(1)
    return None


def _get_signer(note: dict[str, Any]) -> str | None:
    sig = note.get("signatures")
    if isinstance(sig, list) and sig:
        if isinstance(sig[0], str):
            return sig[0]
    return None


def _build_target_identifiers(
    note: dict[str, Any], submission: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build structured identifiers from OpenReview note, and from the submission it reviews."""
    from ..identifiers import ARXIV_PATTERN, DOI_PATTERN

    content = _get_content(note)
    identifiers: dict[str, Any] = {}

    # Check for DOI in content
    doi = content.get("doi")
    if isinstance(doi, str) and doi and DOI_PATTERN.match(doi):
        identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}

    # Check for arXiv ID in content
    for arxiv_key in ("arxiv_id", "arxiv", "arXiv"):
        arxiv = content.get(arxiv_key)
        if isinstance(arxiv, str) and arxiv:
            # Clean up potential URL format
            arxiv_clean = arxiv.replace("https://arxiv.org/abs/", "").replace(
                "http://arxiv.org/abs/", ""
            )
            if ARXIV_PATTERN.match(arxiv_clean):
                identifiers["arxiv_id"] = {
                    "value": arxiv_clean,
                    "hyperlink": f"https://arxiv.org/abs/{arxiv_clean}",
                }
                break

    # The submission is the authority for the work's own DOI and arXiv ID
    sub = submission or {}
    doi = sub.get("doi")
    if isinstance(doi, str):
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I)
        if DOI_PATTERN.match(doi):
            identifiers["doi"] = {"value": doi, "hyperlink": f"https://doi.org/{doi}"}
    arxiv = sub.get("arxiv_id")
    if isinstance(arxiv, str):
        arxiv = re.sub(
            r"^(?:https?://)?arxiv\.org/(?:abs|pdf)/|^arxiv:", "", arxiv.strip(), flags=re.I
        )
        if ARXIV_PATTERN.match(arxiv):
            identifiers["arxiv_id"] = {
                "value": arxiv,
                "hyperlink": f"https://arxiv.org/abs/{arxiv}",
            }

    # OpenReview forum/note ID as internal_id
    forum_id = note.get("forum") or sub.get("id")
    if isinstance(forum_id, str) and forum_id:
        identifiers["internal_id"] = {
            "field_name": "openreview_forum",
            "value": forum_id,
            "hyperlink": f"https://openreview.net/forum?id={forum_id}",
        }
    else:
        # Fallback to note ID
        note_id = note.get("id")
        if isinstance(note_id, str) and note_id:
            identifiers["internal_id"] = {
                "field_name": "openreview_note",
                "value": note_id,
                "hyperlink": f"https://openreview.net/forum?id={note_id}",
            }
        else:
            # Fallback to a paper ID in the review form
            for k in ("paper_id", "submission_id", "work_id"):
                v = content.get(k)
                if isinstance(v, str) and v:
                    identifiers["internal_id"] = {"field_name": k, "value": v}
                    break

    return identifiers


def _build_target(
    note: dict[str, Any], content: dict[str, Any], submission: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build target object with identifiers; the submission also gives its title and venue."""
    identifiers = _build_target_identifiers(note, submission)
    target: dict[str, Any] = {
        "identifiers": identifiers,
        "work_id": generate_canonical_work_id(identifiers),
        "work_type": "preprint",
    }

    sub = submission or {}
    title = sub.get("title")
    if isinstance(title, str) and title.strip():
        target["title"] = title.strip()
    venue = sub.get("venue") or sub.get("venueid")
    if isinstance(venue, str) and venue.strip():
        target["venue"] = venue.strip()

    # Add version if present
    version = content.get("version")
    if isinstance(version, str) and version.strip():
        target["version"] = version.strip()

    return target


def _best_text_opinion(content: dict[str, Any]) -> str:
    for k in ("summary", "paper_summary", "review_summary"):
        if isinstance(content.get(k), str) and content[k].strip():
            return content[k].strip()
    for k in ("review", "comments", "main_review", "detailed_review", "metareview", "comment"):
        if isinstance(content.get(k), str) and content[k].strip():
            return first_paragraph(content[k].strip(), max_len=500)
    return ""


def _collect_findings(content: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("strengths", "weaknesses", "questions"):
        v = content.get(k)
        if isinstance(v, list):
            items = [{"text": str(x)} for x in v if str(x).strip()]
            if items:
                out[k] = items
        elif isinstance(v, str) and v.strip():
            # if newline-separated
            bullets = [b.strip("-* \t") for b in v.splitlines()]
            bullets = [b for b in bullets if b]
            if bullets:
                out[k] = [{"text": b} for b in bullets]
    return out


def _metric_key_for_label(
    label: str,
    amap: dict[str, str],
    idx: dict[str, Any],
) -> tuple[str, str | None]:
    # Return (key, aspect)
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


def _bounded_scale(field: str, num: int | float, bounds: dict[str, Any] | None) -> dict[str, Any]:
    """The scale of a score: the review form's own bounds for the field (`{"min": 1, "max": 6,
    "labels": {"6": "Strong Accept"}}`), else a guess from the value."""
    if not _has_bounds(field, bounds):
        return guess_scale_from_value(num)
    given = (bounds or {})[field]
    scale: dict[str, Any] = {"type": "ordinal", "min": given["min"], "max": given["max"]}
    labels = given.get("labels")
    anchors = []
    for value, label in labels.items() if isinstance(labels, dict) else []:
        number, _ = parse_numeric_prefix(value)
        if number is not None and isinstance(label, str) and label.strip():
            anchors.append({"value": number, "label": label.strip()})
    if anchors:
        scale["anchors"] = sorted(anchors, key=lambda a: a["value"])
    return scale


def _has_bounds(field: str, bounds: dict[str, Any] | None) -> bool:
    """Whether the form gave numeric bounds for `field`."""
    given = (bounds or {}).get(field)
    return isinstance(given, dict) and all(
        isinstance(given.get(k), (int, float)) and not isinstance(given.get(k), bool)
        for k in ("min", "max")
    )


def _form_label(field: str, num: int | float, bounds: dict[str, Any] | None) -> str | None:
    """The form's description of a score's value ("Accept: Technically solid paper"), which
    API v2 leaves out of the note when the value is a number."""
    given = (bounds or {}).get(field)
    labels = given.get("labels") if isinstance(given, dict) else None
    if not isinstance(labels, dict):
        return None
    for value, label in labels.items():
        if parse_numeric_prefix(value)[0] == num and isinstance(label, str):
            return label.strip() or None
    return None


def from_openreview(
    note: dict[str, Any],
    *,
    keep_raw: bool = False,
    scale_bounds: dict[str, Any] | None = None,
    submission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map an OpenReview note (API v1, or v2 with its `{"value": …}` fields) to OCRS.

    `scale_bounds` holds the review form's bounds for its score fields, `{field: {"min": 1,
    "max": 6, "labels": {"6": "Strong Accept"}}}`, so scores are on the form's own scales, not
    guessed ones. `submission` (`id`, `title`, `venue`, `venueid`, `doi`, `arxiv_id`) fills what
    the work is, which a review note does not carry. A Meta_Review or Decision note, known by
    its invitation, has `review_context.review_type` `meta_review` or `recommendation`.
    """
    catalog = load_catalog()
    amap = alias_map(catalog)
    # also index by metric key as lowercase to allow exact_key match
    idx = {m["key"].casefold(): m for m in catalog.get("metrics", [])}

    created = _extract_time(note)
    content = _get_content(note)

    signer = _get_signer(note)

    review_id = note.get("id") if isinstance(note.get("id"), str) else str(uuid.uuid4())

    out: dict[str, Any] = {
        "$schema": schema_id(),
        "review_id": review_id,
        "version": "1.0.0",
        "created_at": created,
        "provenance": {
            "source_system": "openreview",
            "imported_at": now_iso(),
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referee": {
            "referee_type": "human",
            "identity_mode": "confidential",
            "human_referee": {},
        },
        "target": _build_target(note, content, submission),
        "metric_catalog_ref": catalog.get("catalog_id"),
        "metrics": [],
        "opinion": {"summary": summary} if (summary := _best_text_opinion(content)) else {},
    }

    kind = _note_kind(note)
    if kind in _REVIEW_TYPES:
        out["review_context"] = {"review_type": _REVIEW_TYPES[kind]}
    venueid = (submission or {}).get("venueid")
    if isinstance(venueid, str) and venueid.strip():
        out["extensions"] = {"openreview": {"venueid": venueid.strip()}}
    if isinstance(note.get("id"), str):
        out["provenance"]["source_review_id"] = note["id"]
    if signer:
        out["referee"]["referee_id"] = signer
    if keep_raw:
        out["provenance"]["raw_payload"] = note

    # narrative mapping
    narrative = {}
    for src, dst in [
        ("summary", "summary"),
        ("review", "detailed_review"),
        ("comments", "detailed_review"),
        ("main_review", "detailed_review"),
        ("detailed_review", "detailed_review"),
        ("metareview", "detailed_review"),
        ("comment", "detailed_review"),
        ("confidential_comments", "confidential_to_editors"),
        ("confidential_to_chairs", "confidential_to_editors"),
        ("author_questions", "author_questions"),
    ]:
        v = content.get(src)
        if isinstance(v, str) and v.strip():
            # keep the first non-empty for detailed_review fields
            if dst not in narrative:
                narrative[dst] = v.strip()
    if narrative:
        out["narrative"] = narrative

    findings = _collect_findings(content)
    if findings:
        out["findings"] = findings
        # strengthen opinion if missing
        if (not out["opinion"].get("summary")) and findings:
            any_text = next(iter(findings.values()))[0]["text"]
            out["opinion"]["summary"] = first_paragraph(any_text, 200)

    # decision and metrics
    # The first of these the form fills is the recommendation; a null one does not hide the next
    rec_key, rec_raw = first_present_item(content, RECOMMENDATION_KEYS)
    # The first confidence field that gives a number, so `confidence: "High"` beside
    # `reviewer_confidence: 4` still sets the decision's confidence
    numeric = [k for k in CONFIDENCE_KEYS if parse_numeric_prefix(content.get(k))[0] is not None]
    conf_key, conf_raw = (
        (numeric[0], content[numeric[0]])
        if numeric
        else first_present_item(content, CONFIDENCE_KEYS)
    )

    # Parse recommendation
    decision = {}
    if rec_raw is not None:
        num, rest = parse_numeric_prefix(rec_raw)
        if num is not None:
            scale = _bounded_scale(rec_key, num, scale_bounds)
            n01 = normalize_linear(num, scale)
            # The reviewer's own words first, as for CMT and HotCRP (the form's description
            # of the value when the note gives only the number), then the number
            label = rest or _form_label(rec_key, num, scale_bounds)
            decision["recommendation"] = (
                map_recommendation_from_text(label or "")
                or map_recommendation_from_numeric(num, scale)
                or (
                    normalized_to_recommendation(n01)
                    if _has_bounds(rec_key, scale_bounds) and n01 is not None
                    else "borderline"
                )
            )
            # also store overall metric
            out["metrics"].append(
                {
                    "key": "overall",
                    "label": rec_key.replace("_", " ").strip(),
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
            if label:
                out["metrics"][-1]["justification"] = label
        elif isinstance(rec_raw, str):
            decision["recommendation"] = map_recommendation_from_text(rec_raw) or "borderline"
    if conf_raw is not None:
        num, conf_label = parse_numeric_prefix(conf_raw)
        if num is not None:
            scale = _bounded_scale(conf_key, num, scale_bounds)
            conf_label = conf_label or _form_label(conf_key, num, scale_bounds)
            # treat confidence as metric; decision.confidence expects 0..1
            n01 = normalize_linear(num, scale)
            out["metrics"].append(
                {
                    "key": "confidence",
                    "label": conf_key.replace("_", " ").strip(),
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
            # The label after the number ("4: I have substantial expertise") is kept
            if conf_label:
                out["metrics"][-1]["justification"] = conf_label
            if isinstance(n01, (int, float)):
                decision["confidence"] = float(max(0.0, min(1.0, n01)))
    if decision:
        out["decision"] = split_decision(decision)

    # Additional structured metric fields from content
    for k, v in content.items():
        # The fields read above; another score field (a numeric `rating` beside a text
        # `recommendation`) is a metric, unless it repeats one already there
        if k in KNOWN_TEXT_KEYS or k in (rec_key, conf_key):
            continue
        if not is_score_field(k):
            continue
        # numeric-like fields
        num, rest = parse_numeric_prefix(v)
        if num is None:
            continue
        key, _aspect = _metric_key_for_label(k.replace("_", " ").strip(), amap, idx)
        # A recommendation or confidence field is that score, whatever its name says
        if k in RECOMMENDATION_KEYS:
            key = "overall"
        elif k in CONFIDENCE_KEYS:
            key = "confidence"
        # One overall score and one confidence: a second field naming either (`overall_rating`
        # beside a numeric `rating`) is the same score, but kept when the first was text
        if key in ("overall", "confidence") and any(m["key"] == key for m in out["metrics"]):
            continue
        aspect = None
        for m in catalog.get("metrics", []):
            if m["key"] == key:
                aspect = m.get("aspect")
                break
        if aspect is None:
            aspect = "other"
        scale = _bounded_scale(k, num, scale_bounds)
        norm = normalize_linear(num, scale)
        metric = {
            "key": key,
            "label": k.replace("_", " ").strip(),
            "aspect": aspect,
            "scale": scale,
            "value": num,
        }
        if norm is not None:
            metric["normalized"] = {
                "value_0_1": float(max(0.0, min(1.0, norm))),
                "method": "linear_to_unit_interval",
            }
        if rest:
            metric["justification"] = rest
        out["metrics"].append(metric)

    # Remove null normalized stubs
    for m in out["metrics"]:
        if m.get("normalized") is None:
            m.pop("normalized", None)
    return out


# The kind of note a review type is, and the fields that note writes its text and its
# recommendation in
_NOTE_KINDS = {v: k for k, v in _REVIEW_TYPES.items()}
_TEXT_FIELD = {"Meta_Review": "metareview", "Decision": "comment"}
_RECOMMENDATION_FIELD = {"Decision": "decision"}


def to_openreview(canonical: dict[str, Any]) -> dict[str, Any]:
    """A note-like dict with a review form in `content`.

    A review read from OpenReview is given back as its note held it: its scores under their
    own field names with their labels ("7: Accept, but not among top submissions"), its
    time, and, for a meta-review or a decision, its kind and the fields that kind writes, so
    that reading the note gives the same review. A review from elsewhere gives its scores
    under their catalog keys, and its recommendation as text.
    """
    same_source = from_source(canonical, "openreview")
    kind = _NOTE_KINDS.get((canonical.get("review_context") or {}).get("review_type"))
    content: dict[str, Any] = {}

    # Map narrative/opinion
    op = canonical.get("opinion", {}) or {}
    nar = canonical.get("narrative", {}) or {}
    text = op.get("text") if isinstance(op.get("text"), str) else nar.get("detailed_review")
    if isinstance(text, str):
        content[_TEXT_FIELD.get(kind, "review")] = text
    if "confidential_to_editors" in nar and isinstance(nar["confidential_to_editors"], str):
        content["confidential_comments"] = nar["confidential_to_editors"]

    # Findings
    findings = canonical.get("findings", {}) or {}
    for k in ("strengths", "weaknesses", "questions"):
        if isinstance(findings.get(k), list) and findings[k]:
            content[k] = [
                f.get("text") for f in findings[k] if isinstance(f, dict) and f.get("text")
            ]

    # The summary, unless the reader would take the same one from the text or the findings
    summary = nar.get("summary") if isinstance(nar.get("summary"), str) else op.get("summary")
    if isinstance(summary, str) and (
        "summary" in nar or summary != _summary_the_reader_infers(content)
    ):
        content = {"summary": summary, **content}

    # Scores, each under its own field. A review read from OpenReview keeps its fields and
    # labels; one from elsewhere is written under the catalog's keys
    dec = source_decision(canonical.get("decision", {}) or {})
    rec = dec.get("recommendation") if isinstance(dec.get("recommendation"), str) else None
    rec_label = rec.replace("_", " ").title() if rec else None
    overall_written = False
    # Whether the overall score was written to a field the reader takes the recommendation from
    overall_says_recommendation = False
    for m in canonical.get("metrics", []) or []:
        if not isinstance(m, dict):
            continue
        key = m.get("key")
        val = m.get("value")
        if not key or val is None:
            continue
        name = field_name(m["label"]) if same_source and isinstance(m.get("label"), str) else ""
        if key == "overall":
            # The reader takes a recommendation from the overall score's field and reads only a
            # number there: any other value would hide the review's recommendation, or make one
            # up, so it is left out
            if overall_written or not is_number(val):
                continue
            overall_written = True
            # A score read from OpenReview goes back to its own field: on a field the reader
            # takes no recommendation from (`overall_score`), it says none
            field = name or "rating"
            if field not in RECOMMENDATION_KEYS:
                content[field] = score_with_label(m, form_gives_labels=True)
                continue
            overall_says_recommendation = True
            # The score's label says the recommendation, read first; a label that would
            # read back as another gives way to the decision's
            label = m.get("justification") if same_source else None
            scale = m.get("scale") if same_source else None
            if rec and _recommendation_read_back(val, label, scale) != rec:
                label = rec_label
            labelled = {**m, "justification": label}
            content[field] = score_with_label(labelled, form_gives_labels=same_source)
        elif key == "confidence":
            field = name if name in CONFIDENCE_KEYS else "confidence"
            written = score_with_label(m, form_gives_labels=True) if same_source else val
            content.setdefault(field, written)
        else:
            written = score_with_label(m, form_gives_labels=True) if same_source else val
            field = name or key
            # The fields the reader takes the recommendation and the confidence from are theirs
            if field not in RECOMMENDATION_KEYS and field not in CONFIDENCE_KEYS:
                content.setdefault(field, written)

    # Without a score to carry it, the recommendation has its own field
    if rec and not overall_says_recommendation:
        content[_RECOMMENDATION_FIELD.get(kind, "recommendation")] = rec_label

    note: dict[str, Any] = {
        "id": canonical.get("review_id"),
        "forum": source_work_id(canonical.get("target", {})),
        "content": content,
    }
    referee_id = canonical.get("referee", {}).get("referee_id")
    if referee_id:
        note["signatures"] = [referee_id]
    cdate = iso_to_epoch(canonical.get("created_at"), ms=True)
    if cdate is not None:
        note["cdate"] = cdate
    if kind:
        # An invitation names the venue and the kind of note; the reader needs only the kind
        venueid = ((canonical.get("extensions") or {}).get("openreview") or {}).get("venueid")
        note["invitation"] = f"{venueid or ''}/-/{kind}"
    return note


def _recommendation_read_back(
    value: int | float, label: str | None, scale: dict[str, Any] | None
) -> str | None:
    """The recommendation from_openreview takes from an overall score with this label, on the
    score's own scale; None when it would fall back to a guess."""
    return map_recommendation_from_text(label or "") or (
        map_recommendation_from_numeric(value, scale) if scale else None
    )


def _summary_the_reader_infers(content: dict[str, Any]) -> str:
    """The summary from_openreview takes from a note's text, or from its findings."""
    inferred = _best_text_opinion(content)
    if not inferred:
        findings = _collect_findings(content)
        if findings:
            inferred = first_paragraph(next(iter(findings.values()))[0]["text"], 200)
    return inferred
