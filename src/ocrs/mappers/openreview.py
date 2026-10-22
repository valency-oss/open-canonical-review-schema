# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""OpenReview format mapper for canonical reviews."""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from ..catalog import alias_map, load_catalog
from ..hierarchy import LEGACY_SCHEMA
from ..identifiers import generate_canonical_work_id
from ..scales import normalized_to_recommendation
from ..util import (
    epoch_ms_to_iso,
    field_name,
    fields_for,
    first_paragraph,
    first_present_item,
    for_authors,
    from_source,
    guess_scale_from_value,
    is_number,
    is_score_field,
    iso_to_epoch,
    map_recommendation_from_numeric,
    map_recommendation_from_text,
    match_alias,
    narrative_field,
    narrative_parts,
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
from . import openreview_page as page

# Other names venues give the fields the reader takes: TMLR's `summary_of_contributions`,
# `strengths_and_weaknesses` and `requested_changes`, the NeurIPS Datasets and Benchmarks
# track's `summary_and_contributions`, and COLM's `reasons_to_accept`, `reasons_to_reject` and
# `questions_to_authors`
SUMMARY_KEYS = ("summary", "paper_summary", "review_summary")
SUMMARY_ALIASES = ("summary_of_contributions", "summary_and_contributions")
# The fields of the review's own text the reader takes, in order, each as a part with its
# role and audience; the first the form fills for each role and audience
NARRATIVE_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("summary", "summary", None),
    *((alias, "summary", None) for alias in SUMMARY_ALIASES),
    ("review", "review", None),
    ("comments", "review", None),
    ("main_review", "review", None),
    ("detailed_review", "review", None),
    ("strengths_and_weaknesses", "review", None),
    ("metareview", "review", None),
    ("comment", "review", None),
    ("confidential_comments", "review", "editors"),
    ("confidential_to_chairs", "review", "editors"),
    ("author_questions", "questions", None),
)
FINDING_KEYS = {
    "strengths": ("strengths", "reasons_to_accept"),
    "weaknesses": ("weaknesses", "reasons_to_reject"),
    "questions": ("questions", "questions_to_authors"),
    "changes": ("requested_changes",),
}
# Further named parts of the review a form asks for, kept as narrative sections under their
# field names: a meta-review's account of the discussion (ICLR 2025 and 2026), limitations,
# ethics and broader impact, TMLR's criteria, and the Datasets and Benchmarks track's questions
SECTION_FIELDS = (
    "additional_comments_on_reviewer_discussion",
    "reviewer_concerns",
    "reviewer_scores",
    "claims_and_evidence",
    "audience",
    "correctness",
    "clarity",
    "relation_to_prior_work",
    "documentation",
    "opportunities_for_improvement",
    "limitations",
    "broader_impact_concerns",
    "ethics",
    "additional_feedback",
)
# A form's flag for an ethics review (ICLR's and NeurIPS's list of choices, COLM's Yes or No)
# and the reviewer's account of the concerns, which are `ethics_and_risk`
ETHICS_FLAG_FIELDS = ("flag_for_ethics_review", "ethics_flag")
ETHICS_NOTES_FIELD = "details_of_ethics_concerns"
# ICLR's choices for its flag, and the kind of concern each names
ETHICS_CHOICES = {
    None: "No ethics review needed.",
    "bias_fairness": "Yes, Discrimination / bias / fairness concerns",
    "privacy": "Yes, Privacy, security and safety",
    "security": "Yes, Privacy, security and safety",
    "dual_use": "Yes, Potentially harmful insights, methodologies and applications",
    "human_subjects": "Yes, Responsible research practice (e.g., human subjects, data release)",
    "other": "Yes, Other reasons (please specify below)",
}
# The kinds of concern ICLR's flag names, by the words of its choices
CONCERN_CATEGORIES = (
    (r"bias|fairness|discrimination", "bias_fairness"),
    (r"privacy", "privacy"),
    (r"security|safety", "security"),
    (r"human subjects|responsible research", "human_subjects"),
    (r"harmful", "dual_use"),
)
# Criteria some forms score and others answer in words ("Yes"): a section only when the
# answer is not a score
SCORE_OR_SECTION = {
    "claims_and_evidence",
    "audience",
    "correctness",
    "clarity",
    "relation_to_prior_work",
    "documentation",
    "ethics",
}

KNOWN_TEXT_KEYS = {
    ETHICS_NOTES_FIELD,
    *SUMMARY_ALIASES,
    *(key for keys in FINDING_KEYS.values() for key in keys),
    *(key for key in SECTION_FIELDS if key not in SCORE_OR_SECTION),
    "strengths_and_weaknesses",
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


def _extract_updated(note: dict[str, Any]) -> str | None:
    """When the note was last changed (`tmdate`, else `mdate`), if it says."""
    for k in ("tmdate", "mdate"):
        v = note.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            return epoch_ms_to_iso(v)
    return None


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
    for k in (*SUMMARY_KEYS, *SUMMARY_ALIASES):
        if isinstance(content.get(k), str) and content[k].strip():
            return content[k].strip()
    for k in (
        "review",
        "comments",
        "main_review",
        "detailed_review",
        "strengths_and_weaknesses",
        "metareview",
        "comment",
    ):
        if isinstance(content.get(k), str) and content[k].strip():
            return first_paragraph(content[k].strip(), max_len=500)
    return ""


def _finding_field(content: dict[str, Any], kind: str) -> tuple[str, Any] | None:
    """The field a kind of finding is in, and its value: the first of its names the form fills."""
    return next(
        ((name, content[name]) for name in FINDING_KEYS[kind] if content.get(name) is not None),
        None,
    )


def _points(text: str, kind: str) -> list[dict[str, Any]]:
    """The points of a finding field written as text, as the forum-page reader reads them.

    A list's items are its points (a lead-in such as "Major concerns:" is not one); text with no
    list has a point per line. Headings ("Major concerns:", "**Minor**", "## Clarity") are the
    `group` of the points under them, and a Minor or Typos heading makes its weaknesses minor
    and its requested changes minor. Text under a References heading is no point.
    Questions are not split at headings: a bold line there is a question.
    """
    if kind == "questions":
        sections = [(None, None, text.splitlines())]
    else:
        sections = page._sections(text)
    points: list[dict[str, Any]] = []
    for heading, _level, lines in sections:
        if heading and page._ENDS_FINDINGS.fullmatch(heading):
            continue
        # A list marker alone on its line holds no point
        lines = [line for line in lines if line.strip() not in ("-", "*", "+", "•")]
        if any(page._ITEM.match(line) for line in lines):
            texts = page._items(lines)
        else:
            texts = [line.strip() for line in lines if line.strip()]
        minor = bool(heading and re.search(r"\b(?:minor|typos?)\b", heading, re.IGNORECASE))
        for text_ in texts:
            point: dict[str, Any] = {"text": text_}
            lead = page._BOLD_LEAD.match(text_)
            if lead:
                point["title"] = page._squash(lead.group(1)).rstrip(":.")
            if heading:
                point["group"] = [heading]
            if minor and kind in ("weaknesses", "changes"):
                point["severity"] = "minor"
            points.append(point)
    return points


def _collect_findings(content: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in FINDING_KEYS:
        _name, v = _finding_field(content, k) or (None, None)
        if isinstance(v, list):
            items = [{"text": str(x)} for x in v if str(x).strip()]
            if items:
                out[k] = items
        elif isinstance(v, str) and v.strip():
            points = _points(v.strip(), k)
            if points:
                out[k] = points
    return out


def _ethics_flag(field: str, value: Any, bounds: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Whether a form's ethics flag says the reviewer has ethical concerns, and of which kinds.

    The flag is ICLR's list of choices (`["No ethics review needed."]`, `["Yes, Privacy,
    security and safety"]`), a choice written with its number (`"2: No, there are no or only
    very minor ethics concerns"`), or a number whose label on the form says Yes or No (COLM's
    1, "No"). Raises ValueError when the answer says neither.
    """
    words = []
    for answer in value if isinstance(value, list) else [value]:
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            words.append(_form_label(field, answer, bounds))
        elif isinstance(answer, str):
            number, rest = parse_numeric_prefix(answer)
            if number is None:
                words.append(answer)
            else:  # "2: No, …", or a number alone ("1"), which the form's label says
                words.append(rest or _form_label(field, number, bounds))
    words = [w.strip() for w in words if isinstance(w, str) and w.strip()]
    yes = [w for w in words if re.match(r"yes\b", w, re.IGNORECASE)]
    if yes:
        categories = []
        for answer in yes:
            found = [c for words_, c in CONCERN_CATEGORIES if re.search(words_, answer, re.I)]
            categories += [c for c in found or ["other"] if c not in categories]
        return True, categories
    if words and all(re.match(r"no\b", w, re.IGNORECASE) for w in words):
        return False, []
    raise ValueError(f"{field} says neither yes nor no: {value!r}")


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
    "labels": {"6": "Strong Accept"}, "values": [1, 3, 5, 6]}`), else a guess from the value."""
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
    values = given.get("values")
    if isinstance(values, list) and values:
        scale["values"] = values
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
        "$schema": LEGACY_SCHEMA,
        "review_id": review_id,
        "version": "1.0.0",
        "created_at": created,
        **(
            {"updated_at": updated}
            if (updated := _extract_updated(note)) not in (None, created)
            else {}
        ),
        "provenance": {
            "source_system": "openreview",
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
        out["referees"][0]["referee_id"] = signer
    # The license the review itself is published under, and the note it replies to when that
    # is not the submission: another review
    if isinstance(note.get("license"), str) and note["license"].strip():
        out["provenance"]["license"] = {"name": note["license"].strip()}
    replyto = note.get("replyto")
    if isinstance(replyto, str) and replyto and replyto != note.get("forum"):
        out["related_reviews"] = [{"type": "responds_to", "review_id": replyto}]
    if keep_raw:
        out["provenance"]["raw_payload"] = note

    # The review's own text: the first field the form fills for each part, each under its name
    narrative: list[dict[str, Any]] = []
    taken: set[tuple[str, str | None]] = set()
    for field, role, audience in NARRATIVE_FIELDS:
        v = content.get(field)
        if isinstance(v, str) and v.strip() and (role, audience) not in taken:
            taken.add((role, audience))
            narrative.append(section(v.strip(), title=field, role=role, audience=audience))
    # A finding field written as text is kept as written, beside the points read from it
    finding_texts = {
        found[0]
        for k in FINDING_KEYS
        if (found := _finding_field(content, k)) and isinstance(found[1], str) and found[1].strip()
    }
    narrative += [
        section(v.strip(), title=k)
        for k, v in content.items()
        if (k in SECTION_FIELDS or k in finding_texts)
        and isinstance(v, str)
        and v.strip()
        and not (k in SCORE_OR_SECTION and parse_numeric_prefix(v)[0] is not None)
    ]
    if narrative:
        out["narrative"] = narrative

    findings = _collect_findings(content)
    if findings:
        out["findings"] = findings
        # strengthen opinion if missing
        if (not out["opinion"].get("summary")) and findings:
            any_text = next(iter(findings.values()))[0]["text"]
            out["opinion"]["summary"] = first_paragraph(any_text, 200)

    # Ethics: the form's flag says whether the reviewer has concerns, and of which kinds; the
    # flag is kept as the form gave it, so the writer gives it back in the form's encoding
    ethics: dict[str, Any] = {}
    flags: dict[str, Any] = {}
    for field in ETHICS_FLAG_FIELDS:
        if field not in content:
            continue
        try:
            concerns, categories = _ethics_flag(field, content[field], scale_bounds)
        except ValueError:
            continue
        flags[field] = content[field]
        ethics["ethical_concerns"] = ethics.get("ethical_concerns", False) or concerns
        known = ethics.get("concern_categories", [])
        ethics["concern_categories"] = known + [c for c in categories if c not in known]
    notes = content.get(ETHICS_NOTES_FIELD)
    if isinstance(notes, str) and notes.strip():
        ethics["notes"] = notes.strip()
    if not ethics.get("concern_categories"):
        ethics.pop("concern_categories", None)
    if ethics:
        out["ethics_and_risk"] = ethics
    if flags:
        # What the flags say, so the writer gives them back only while the review says it too
        # A copy: an edit to the review's categories must not change what the flags said
        says = copy.deepcopy(
            {k: ethics[k] for k in ("ethical_concerns", "concern_categories") if k in ethics}
        )
        kept = {"fields": flags, "say": says}
        out.setdefault("extensions", {}).setdefault("openreview", {})["ethics_flags"] = kept

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
            # The recommendation in the form's own words ("Accept (Poster)")
            if rec_raw.strip():
                decision["source_label"] = rec_raw.strip()
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
                decision["credence"] = float(max(0.0, min(1.0, n01)))
    if decision:
        out["decision"] = split_decision(decision)

    # Additional structured metric fields from content
    for k, v in content.items():
        # The fields read above; another score field (a numeric `rating` beside a text
        # `recommendation`) is a metric, unless it repeats one already there
        if k in KNOWN_TEXT_KEYS or k in (rec_key, conf_key) or k in flags:
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
        # The reviewer's label, or the form's for the value, as for the overall score: a note
        # that gives "3 good" and one that gives 3 on a form where 3 is "good" say the same
        label = rest or _form_label(k, num, scale_bounds)
        if label:
            metric["justification"] = label
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

    # Each part of the review's own text under its own field, when read from OpenReview
    def own_field(role: str, *, editors: bool = False, first: str | None = None):
        fields = fields_for(NARRATIVE_FIELDS, role, editors=editors)
        fields = (first, *fields) if first else fields
        audience = "editors" if editors else None
        return narrative_field(canonical, role, fields, audience=audience, same_source=same_source)

    text_field = _TEXT_FIELD.get(kind, "review")
    if isinstance(op.get("text"), str):
        content[text_field] = op["text"]
    elif review := own_field("review", first=text_field):
        content[review[0]] = review[1]
    if confidential := own_field("review", editors=True):
        content[confidential[0]] = confidential[1]
    if questions := own_field("questions"):
        content[questions[0]] = questions[1]

    # Findings. A kind read from a field's text goes back as that text, while its points are
    # still the ones the reader takes from it; otherwise each kind is a list under the first
    # field the reader takes it from
    findings = canonical.get("findings", {}) or {}
    # The parts kept under their field names: those that are no summary, review or questions,
    # and that the authors may read
    others = [
        s
        for s in narrative_parts(canonical)
        if s.get("role") in (None, "other") and for_authors(s) and s["content"].strip()
    ]
    sections = [s for s in others if isinstance(s.get("title"), str)]
    texts: set[str] = set()
    for k, names in FINDING_KEYS.items():
        points = [f for f in findings.get(k) or [] if isinstance(f, dict)]
        written = next((s for s in sections if s["title"] in names), None)
        if written and isinstance(written.get("content"), str):
            if _points(written["content"], k) == points:
                texts.add(written["title"])
                continue
        if points:
            content[names[0]] = [f.get("text") for f in points if f.get("text")]
    # The parts of the review kept under their field names, in order
    for part in sections:
        if part["title"] in SECTION_FIELDS or part["title"] in texts:
            content.setdefault(part["title"], part.get("content"))
    # A review from elsewhere with no text of its own: its other parts, under their headings
    if not same_source and text_field not in content and others:
        content[text_field] = "\n\n".join(
            f"{s['title']}:\n\n{s['content']}" if s.get("title") else s["content"] for s in others
        )

    # Ethics: the form's flag as it gave it, while the review still says what it said, else
    # the review's concerns as ICLR's choices; and the reviewer's account of the concerns
    ethics = canonical.get("ethics_and_risk") or {}
    kept = ((canonical.get("extensions") or {}).get("openreview") or {}).get("ethics_flags")
    kept = kept if isinstance(kept, dict) else {}
    says = {k: ethics[k] for k in ("ethical_concerns", "concern_categories") if k in ethics}
    if "ethical_concerns" in ethics:
        if kept.get("say") == says and isinstance(kept.get("fields"), dict):
            content.update({k: v for k, v in kept["fields"].items() if k in ETHICS_FLAG_FIELDS})
        else:
            content["flag_for_ethics_review"] = _ethics_choices(ethics)
    if isinstance(ethics.get("notes"), str):
        content[ETHICS_NOTES_FIELD] = ethics["notes"]

    # The summary, unless the reader would take the same one from the text or the findings
    own_summary = own_field("summary")
    summary = own_summary[1] if own_summary else op.get("summary")
    if isinstance(summary, str) and (
        own_summary is not None or summary != _summary_the_reader_infers(content)
    ):
        content = {(own_summary[0] if own_summary else "summary"): summary, **content}

    # Scores, each under its own field. A review read from OpenReview keeps its fields and
    # labels; one from elsewhere is written under the catalog's keys
    dec = source_decision(canonical.get("decision", {}) or {})
    rec = dec.get("recommendation") if isinstance(dec.get("recommendation"), str) else None
    rec_label = recommendation_label(canonical)
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
                rec_field = _RECOMMENDATION_FIELD.get(kind, "recommendation")
                if _recommendation_read_back(val, rec_label, scale) == rec:
                    label = rec_label
                elif RECOMMENDATION_KEYS.index(rec_field) < RECOMMENDATION_KEYS.index(field):
                    # Words the score's number would read past ("Not sure" beside an 8) go in
                    # a field the reader takes the recommendation from first
                    overall_says_recommendation = False
                else:
                    label = recommendation_label(canonical, own=False)
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

    # Without a score to carry it, the recommendation has its own field, as do the words of
    # one OCRS cannot name
    if rec_label and not overall_says_recommendation:
        content[_RECOMMENDATION_FIELD.get(kind, "recommendation")] = rec_label

    note: dict[str, Any] = {
        "id": canonical.get("review_id"),
        "forum": source_work_id(canonical.get("target", {})),
        "content": content,
    }
    referee_id = referee_of(canonical).get("referee_id")
    if referee_id:
        note["signatures"] = [referee_id]
    if same_source:
        license_ = (canonical.get("provenance") or {}).get("license") or {}
        if isinstance(license_.get("name"), str):
            note["license"] = license_["name"]
        replies = [
            r["review_id"]
            for r in canonical.get("related_reviews") or []
            if isinstance(r, dict) and r.get("type") == "responds_to" and r.get("review_id")
        ]
        if replies:
            note["replyto"] = replies[0]
    cdate = iso_to_epoch(canonical.get("created_at"), ms=True)
    if cdate is not None:
        note["cdate"] = cdate
    mdate = iso_to_epoch(canonical.get("updated_at"), ms=True)
    if mdate is not None:
        note["mdate"] = mdate
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


def _ethics_choices(ethics: dict[str, Any]) -> list[str]:
    """A review's ethical concerns as ICLR's choices for its ethics flag."""
    if not ethics.get("ethical_concerns"):
        return [ETHICS_CHOICES[None]]
    categories = ethics.get("concern_categories") or ["other"]
    choices = [ETHICS_CHOICES.get(c, ETHICS_CHOICES["other"]) for c in categories]
    return list(dict.fromkeys(choices))


def _summary_the_reader_infers(content: dict[str, Any]) -> str:
    """The summary from_openreview takes from a note's text, or from its findings."""
    inferred = _best_text_opinion(content)
    if not inferred:
        findings = _collect_findings(content)
        if findings:
            inferred = first_paragraph(next(iter(findings.values()))[0]["text"], 200)
    return inferred
