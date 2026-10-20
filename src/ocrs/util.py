# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Utility functions for parsing, normalization, and recommendation mapping."""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from .scales import (
    ScaleDefinition,
    get_scale_for_system,
    infer_scale_from_value,
    normalized_to_recommendation,
)

# Pattern to match numeric prefix with optional separator (: . -)
# For "4. Accept", "3: Weak Accept", "6 - Borderline"
# Note: The (?:\.\s+) ensures we don't match decimal numbers like "3.5"
# The label may run over several lines
_num_prefix = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*(?:(?:\.\s+)|[:\-]\s*)?\s*(.*)$", re.DOTALL)
_bullet_pattern = re.compile(r"^\s*(?:[-*•]|\d+[.)\]])\s*", re.MULTILINE)


def now_iso() -> str:
    return _dt.datetime.now(tz=_dt.UTC).isoformat().replace("+00:00", "Z")


def epoch_ms_to_iso(ms: int) -> str:
    return _dt.datetime.fromtimestamp(ms / 1000.0, tz=_dt.UTC).isoformat().replace("+00:00", "Z")


def first_paragraph(text: str, max_len: int = 500) -> str:
    if not text:
        return ""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not parts:
        return text.strip()[:max_len]
    return parts[0][:max_len]


# Fields that identify the review, the work or the reviewer, or say when it happened. Their
# values often start with digits (a DOI, an ORCID, a date, a timestamp) but are never scores.
# Compared without case, `_`, `-` or spaces.
_NOT_SCORE_FIELDS = {
    "id", "ids", "pid", "forum", "number", "ordinal", "rtype", "round",
    "doi", "orcid", "arxiv", "pmid", "pmcid", "isbn", "issn", "url", "link", "version",
    "email", "revieweremail", "contact", "reviewernumber",
    "cdate", "tcdate", "mdate", "tmdate", "ddate", "odate", "pdate",
    "date", "created", "modified", "updated", "submitted", "timesubmitted", "timemodified",
    "time", "timestamp", "datetime",
}  # fmt: skip
# camelCase or snake_case IDs and times: `paperId`, `paper_id`, `createdAt`, `review_date`,
# `created_timestamp`, `reviewTime`
_NOT_SCORE_SUFFIX = re.compile(
    r"(?:^|_|[a-z])(?:Ids?|IDs?|_ids?|At|_at|Date|_date|Time(?:stamp)?|_time(?:stamp)?)$"
)


_NOT_SCORE_LAST_WORDS = {"id", "ids", "at", "date", "time", "timestamp", "doi", "orcid", "url"}


def is_score_field(key: str) -> bool:
    """Whether a source field may hold a score: not an identifier, a link or a time."""
    plain = re.sub(r"[\s_-]", "", key).casefold()
    if plain in _NOT_SCORE_FIELDS or plain.endswith(("orcid", "arxivid", "doi")):
        return False
    # A last word set off by a space, `_` or `-`, in any case: `Paper ID`, `paper-id`,
    # `CREATED_AT`; run-together words only by camelCase (`paperId`), so `valid` is a score
    words = [word for word in re.split(r"[\s_-]+", key.casefold()) if word]
    if len(words) > 1 and words[-1] in _NOT_SCORE_LAST_WORDS:
        return False
    return not _NOT_SCORE_SUFFIX.search(key)


_WORD_EDGE = r"(?<![a-z0-9]){}(?![a-z0-9])"
MIN_PARTIAL_ALIAS = 4


def match_alias(label: str, amap: dict[str, str]) -> str | None:
    """The metric key a field label names, or None.

    The label is an alias, or contains one as whole words (`Soundness score` contains
    `soundness`; the longest alias wins), or is whole words of aliases that all name the
    same metric (`presentation`, from `presentation clarity`). A label shorter than four
    characters is never part of an alias, and one that is part of aliases of different
    metrics (`quality`) names none.
    """
    lcf = label.casefold().strip()
    if not lcf:
        return None
    if lcf in amap:
        return amap[lcf]
    for alias in sorted(amap, key=len, reverse=True):
        if re.search(_WORD_EDGE.format(re.escape(alias)), lcf):
            return amap[alias]
    if len(lcf) < MIN_PARTIAL_ALIAS:
        return None
    pattern = _WORD_EDGE.format(re.escape(lcf))
    keys = {key for alias, key in amap.items() if re.search(pattern, alias)}
    return keys.pop() if len(keys) == 1 else None


def first_present_item(mapping: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, Any]:
    """The first of `keys` whose value is not None, blank text or a boolean (never a score,
    a recommendation or an ID), and its value."""
    for key in keys:
        value = mapping.get(key)
        if value is None or isinstance(value, bool):
            continue
        if not (isinstance(value, str) and not value.strip()):
            return key, value
    return None, None


def first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """The value of the first of `keys` whose value is not None, blank text or a boolean."""
    return first_present_item(mapping, keys)[1]


def parse_numeric_prefix(value: Any) -> tuple[int | float | None, str | None]:
    """Parse strings like '6: Weak Accept' -> (6, 'Weak Accept'). A boolean is not a number."""
    if isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        return value, None
    if not isinstance(value, str):
        return None, None
    m = _num_prefix.match(value)
    if not m:
        return None, value.strip() or None
    num_s, rest = m.group(1), m.group(2)
    num: int | float
    if "." in num_s:
        num = float(num_s)
    else:
        num = int(num_s)
    rest = rest.strip() or None
    return num, rest


def guess_scale_from_value(num: int | float) -> dict[str, Any]:
    # Best-effort: common rubrics are 1..5 or 1..10
    if isinstance(num, float):
        # If in 0..1, treat as ratio
        if 0.0 <= num <= 1.0:
            return {"type": "ratio", "min": 0, "max": 1, "step": 0.01}
        # Otherwise treat as interval with unknown bounds
        return {"type": "interval"}
    if 0 <= num <= 1:
        return {"type": "ratio", "min": 0, "max": 1, "step": 0.05}
    if 1 <= num <= 5:
        return {"type": "ordinal", "min": 1, "max": 5}
    if 1 <= num <= 10:
        return {"type": "ordinal", "min": 1, "max": 10}
    return {"type": "interval"}


def normalize_linear(num: int | float, scale: dict[str, Any]) -> float | None:
    t = scale.get("type")
    if t == "ratio" and scale.get("min") == 0 and scale.get("max") == 1:
        return float(num)
    if t == "ordinal" and "min" in scale and "max" in scale:
        lo, hi = float(scale["min"]), float(scale["max"])
        if hi == lo:
            return None
        return (float(num) - lo) / (hi - lo)
    return None


def map_recommendation_from_numeric(num: int | float, scale: dict[str, Any]) -> str | None:
    # Conservative buckets; adjustable per venue template later
    t = scale.get("type")
    if t != "ordinal" or "min" not in scale or "max" not in scale:
        return None
    lo, hi = int(scale["min"]), int(scale["max"])
    if lo == 1 and hi == 10 and isinstance(num, (int, float)):
        n = float(num)
        if n >= 9:
            return "strong_accept"
        if n >= 7:
            return "accept"
        if n >= 6:
            return "weak_accept"
        if n >= 5:
            return "borderline"
        if n >= 3:
            return "weak_reject"
        if n >= 2:
            return "reject"
        return "strong_reject"
    if lo == 1 and hi == 5 and isinstance(num, (int, float)):
        n = float(num)
        if n >= 5:
            return "accept"
        if n >= 4:
            return "weak_accept"
        if n >= 3:
            return "borderline"
        if n >= 2:
            return "weak_reject"
        return "reject"
    return None


_ACCEPT = re.compile(r"\baccept(?:s|ed|ance)?\b")
_REJECT = re.compile(r"\breject(?:s|ed|ion)?\b")
_RELATIVE_TO_ACCEPT = re.compile(
    r"\b(?:below|beneath|under|above|over|short\s+of|shy\s+of"
    r"|not\s+(?:yet\s+)?(?:ready|suitable|fit)\s+for)"
    r"\s+(?:the\s+)?accept\w*(?:\s+(?:threshold|bar|level|standard)s?)?"
)
_NEGATED_QUALIFIED_ACCEPT = re.compile(
    r"\b(?:not|never)\s+(?:an?\s+|the\s+)?(?:strong|weak|clear|full)\s+accept\w*"
)
_DOUBLE_NEGATIVE = re.compile(r"\b(?:not|never)\s+(?:an?\s+)?unacceptable\b")
_NEGATED_ACCEPT = re.compile(
    r"\b(?:not|never|cannot)\s+(?:be\s+)?accept(?:ed|able)?\b|\bunacceptable\b"
)


def map_recommendation_from_text(s: str) -> str | None:
    if not s:
        return None
    x = s.casefold().replace("_", " ")
    # A negated strong, weak or clear accept says only what it is not, so it is set aside
    # (alone, it leaves no label and a score decides). A plainly negated acceptance ("not
    # acceptable") is a rejection
    # The rest of the label may still state one: "Weak accept (not a strong accept)"
    x = _NEGATED_QUALIFIED_ACCEPT.sub(" ", x)
    # Wording that places the work against the acceptance threshold ("below the acceptance
    # threshold", ICLR's "marginally above the acceptance threshold") is no verdict of its
    # own: it is set aside, so a verdict beside it still counts and, alone, it leaves the
    # score to decide
    x = _RELATIVE_TO_ACCEPT.sub(" ", x)
    # A double negative ("not unacceptable") is no clear verdict either way
    if _DOUBLE_NEGATIVE.search(x):
        return None
    if _NEGATED_ACCEPT.search(x):
        return "reject"
    # Common phrases - order matters for overlapping matches
    if "strong accept" in x:
        return "strong_accept"
    if "weak accept" in x:
        return "weak_accept"
    if "border" in x:
        return "borderline"
    if "weak reject" in x:
        return "weak_reject"
    if "strong reject" in x:
        return "strong_reject"
    # Check "resubmit/resubmission" before "reject" as "reject and encourage resubmission" -> revise
    if "resubmit" in x or "resubmission" in x:
        return "revise"
    # Whole words: "acceptable" is not "accept"
    if x.strip() in {"accept", "yes"} or _ACCEPT.search(x):
        return "accept"
    if x.strip() in {"reject", "no"} or _REJECT.search(x):
        return "reject"
    if "major revision" in x:
        return "major_revision"
    if "minor revision" in x:
        return "minor_revision"
    if "revise" in x:
        return "revise"
    return None


def split_bullet_list(text: str) -> list[str]:
    """Split text on bullet markers (-, *, •, numbered) or double newlines.

    Returns a list of stripped, non-empty items.
    """
    if not text or not text.strip():
        return []
    # First, check if text has bullet markers
    if _bullet_pattern.search(text):
        # Split on newlines and strip bullet markers
        items = []
        for line in text.splitlines():
            cleaned = _bullet_pattern.sub("", line).strip()
            if cleaned:
                items.append(cleaned)
        return items
    # Otherwise split on double newlines or single newlines
    parts = re.split(r"\n\s*\n|\n", text)
    return [p.strip() for p in parts if p.strip()]


def migrate_work_id_to_identifiers(
    work_id: str, source_system: str | None = None
) -> dict[str, Any]:
    """Convert legacy work_id string to identifiers structure.

    Auto-detects identifier type from format:
    - Canonical work ID ("doi:10.xxxx/...", "internal_id:paperId:42") -> that identifier
    - DOI format (10.xxxx/...) -> doi
    - Valency Hub work page (https://hub.valency.io/works/W_...) or citation
      (vlnc:W_...) -> valency_id
    - URL format -> permalink
    - Otherwise -> internal_id with source_system as field_name

    Args:
        work_id: Legacy work_id string
        source_system: Source system name for internal_id field_name

    Returns:
        Dictionary matching workIdentifiers schema
    """
    from .identifiers import (
        DOI_PATTERN,
        RESOLVERS,
        VALENCY_WORK_PATTERN,
        build_resolver_url,
        parse_canonical_work_id,
    )

    work_id = work_id.strip()

    parsed = parse_canonical_work_id(work_id)
    if parsed:
        id_type, field_name, value = parsed
        if id_type == "internal_id":
            return {"internal_id": {"field_name": field_name, "value": value}}
        if id_type in ("permalink", "purl"):
            return {id_type: value}
        identifier = {"value": value}
        hyperlink = build_resolver_url(id_type, value)
        if hyperlink:
            identifier["hyperlink"] = hyperlink
        return {id_type: identifier}

    # Check if it's a DOI
    if DOI_PATTERN.match(work_id):
        return {"doi": {"value": work_id, "hyperlink": f"https://doi.org/{work_id}"}}

    # Check if it's a Valency Hub work page, or a Hub citation ("vlnc:W_..."). A page's
    # query and fragment (?utm_source=share, #abstract) don't name the work.
    hub_works = RESOLVERS["valency_id"]
    if work_id.startswith(hub_works):
        works_path = urlsplit(hub_works).path
        valency_id = urlsplit(work_id).path.removeprefix(works_path).rstrip("/")
        if VALENCY_WORK_PATTERN.match(valency_id):
            return {"valency_id": {"value": valency_id, "hyperlink": work_id}}
    if work_id.startswith("vlnc:"):
        valency_id = work_id.removeprefix("vlnc:")
        if VALENCY_WORK_PATTERN.match(valency_id):
            return {
                "valency_id": {
                    "value": valency_id,
                    "hyperlink": build_resolver_url("valency_id", valency_id),
                }
            }

    # Check if it's a URL
    if work_id.startswith("http://") or work_id.startswith("https://"):
        return {"permalink": work_id}

    # Fallback to internal_id
    field_name = source_system or "legacy_work_id"
    return {"internal_id": {"field_name": field_name, "value": work_id}}


def source_work_id(target: dict[str, Any]) -> str | None:
    """The source system's own ID for the reviewed work, for mapping back to it.

    Uses identifiers.internal_id, then the value in a canonical work_id. A work_id
    that is not canonical (from a record made before work_id had a format) is
    returned as is.
    """
    from .identifiers import parse_canonical_work_id

    internal = (target.get("identifiers") or {}).get("internal_id")
    if isinstance(internal, dict) and internal.get("value"):
        return str(internal["value"])
    work_id = target.get("work_id")
    if not isinstance(work_id, str) or work_id == "unknown":
        return None
    parsed = parse_canonical_work_id(work_id)
    return parsed[2] if parsed else work_id


def parse_date_flexible(value: str | int | float) -> str:
    """Parse various date formats to ISO 8601 datetime string.

    Handles:
    - ISO 8601 strings (passthrough if already valid)
    - Unix timestamps in seconds (int/float)
    - Unix timestamps in milliseconds (int > 1e11)
    - Date-only strings like "2024-12-20" (assumes midnight UTC)
    """
    if isinstance(value, (int, float)):
        # Heuristic: if > 1e11, it's likely milliseconds
        if value > 1e11:
            return epoch_ms_to_iso(int(value))
        return _dt.datetime.fromtimestamp(value, tz=_dt.UTC).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str):
        return now_iso()
    s = value.strip()
    if not s:
        return now_iso()
    # If it looks like ISO 8601 with time component, return as-is (normalize Z)
    if "T" in s:
        # Ensure it ends with Z or timezone
        if not s.endswith("Z") and "+" not in s and "-" not in s[10:]:
            s = s + "Z"
        return s.replace("+00:00", "Z")
    # Date-only: assume midnight UTC
    try:
        dt = _dt.datetime.strptime(s, "%Y-%m-%d")
        return dt.replace(tzinfo=_dt.UTC).isoformat().replace("+00:00", "Z")
    except ValueError:
        pass
    # Try other common formats
    for fmt in ("%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            dt = _dt.datetime.strptime(s, fmt)
            return dt.replace(tzinfo=_dt.UTC).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    # Fallback: return current time
    return now_iso()


# =============================================================================
# Enhanced Score Parsing and Transformation
# =============================================================================


def parse_labeled_score(
    value: Any,
    *,
    system: str | None = None,
    metric_type: str | None = None,
    expected_min: int | float | None = None,
    expected_max: int | float | None = None,
) -> dict[str, Any]:
    """Parse a labeled score like "3. Weak Accept" into components.

    This function handles various formats:
    - Pure numeric: 4, 3.5
    - Numeric with text: "4. Accept", "3: Weak Accept", "6 - Borderline"
    - Text only: "Accept", "Weak Reject" (returns None for numeric)

    Args:
        value: The score value to parse (int, float, or string)
        system: Optional source system for scale lookup
        metric_type: Optional metric type for scale lookup
        expected_min: Override minimum for scale inference
        expected_max: Override maximum for scale inference

    Returns:
        Dictionary with:
        - numeric: The numeric value (or None if text-only)
        - label: The text label (or None if numeric-only)
        - scale: Inferred or looked-up scale definition as dict
        - normalized: Normalized value in [0, 1] range
        - justification: Text explanation (same as label, for convenience)
    """
    numeric, label = parse_numeric_prefix(value)

    result: dict[str, Any] = {
        "numeric": numeric,
        "label": label,
        "scale": None,
        "normalized": None,
        "justification": label,
    }

    if numeric is None:
        return result

    # Determine the scale to use
    if expected_min is not None and expected_max is not None:
        scale = ScaleDefinition(min_value=expected_min, max_value=expected_max)
    elif system and metric_type:
        scale = get_scale_for_system(system, metric_type)
    else:
        scale = infer_scale_from_value(numeric)

    result["scale"] = scale.to_schema()
    result["normalized"] = scale.normalize(numeric)

    return result


def build_metric_from_score(
    key: str,
    label: str,
    value: Any,
    *,
    aspect: str | None = None,
    system: str | None = None,
    expected_min: int | float = 1,
    expected_max: int | float = 5,
) -> dict[str, Any] | None:
    """Build a canonical metric assessment from a score value.

    Ensures that:
    - metric.value is always numeric
    - Text labels go into metric.justification
    - Proper normalization is applied

    Args:
        key: Metric key (e.g., "overall", "novelty")
        label: Human-readable label for the metric
        value: The score value (may be labeled like "4. Accept")
        aspect: Optional aspect category
        system: Source system for scale lookup
        expected_min: Expected minimum value on source scale
        expected_max: Expected maximum value on source scale

    Returns:
        Canonical metric assessment dict, or None if value cannot be parsed
    """
    parsed = parse_labeled_score(
        value,
        system=system,
        metric_type=key,
        expected_min=expected_min,
        expected_max=expected_max,
    )

    if parsed["numeric"] is None:
        return None

    metric: dict[str, Any] = {
        "key": key,
        "label": label,
        "scale": parsed["scale"] or {"type": "ordinal", "min": expected_min, "max": expected_max},
        "value": parsed["numeric"],  # Always numeric
    }

    if aspect:
        metric["aspect"] = aspect

    if parsed["normalized"] is not None:
        metric["normalized"] = {
            "value_0_1": float(max(0.0, min(1.0, parsed["normalized"]))),
            "method": "linear_to_unit_interval",
        }

    if parsed["label"]:
        metric["justification"] = parsed["label"]

    return metric


def score_to_recommendation(
    value: Any,
    *,
    scale_min: int | float = 1,
    scale_max: int | float = 5,
) -> str | None:
    """Convert a numeric or labeled score to a recommendation string.

    Uses the configured thresholds to map normalized scores to recommendations.

    Args:
        value: Score value (numeric or labeled string)
        scale_min: Minimum value on the source scale
        scale_max: Maximum value on the source scale

    Returns:
        Recommendation string or None if value cannot be parsed
    """
    parsed = parse_labeled_score(value, expected_min=scale_min, expected_max=scale_max)

    # First try text-based mapping
    if parsed["label"]:
        text_rec = map_recommendation_from_text(parsed["label"])
        if text_rec:
            return text_rec

    # Then try numeric-based mapping
    if parsed["normalized"] is not None:
        return normalized_to_recommendation(parsed["normalized"])

    return None


def split_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Separate source revision labels without inferring an acceptance judgment."""
    result = {key: value for key, value in decision.items() if value is not None}
    revision = {
        "minor_revision": "minor",
        "major_revision": "major",
        "revise": "unspecified",
    }.get(result.get("recommendation"))
    if revision:
        result.pop("recommendation")
        result["revision_requirement"] = revision
    return result


def source_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Join decisions for single-field exports, prioritizing requested revision.

    This is lossy when an independent acceptance judgment is also present.
    An explicit no-revision requirement leaves the acceptance judgment unchanged.
    """
    result = dict(decision)
    recommendation = {
        "minor": "minor_revision",
        "major": "major_revision",
        "unspecified": "revise",
    }.get(result.get("revision_requirement"))
    if recommendation:
        result["recommendation"] = recommendation
    return result


# Writing back to a source. A writer gives a source back what its reader took from it, in
# the source's own form, so that reading what it writes gives the same review.


def from_source(canonical: dict[str, Any], system: str) -> bool:
    """Whether a review was read from `system`, so that its metric labels are that
    system's field names."""
    return (canonical.get("provenance") or {}).get("source_system") == system


def score_with_label(
    metric: dict[str, Any], separator: str = ": ", *, form_gives_labels: bool = False
) -> Any:
    """A score as a review form writes it: the value, with the label the reviewer gave it
    ("6: Weak Accept"). Written back to the form whose scale anchors the score
    (`form_gives_labels`), a label that is its anchor for the value is left out: that form
    says it for the value alone. Any other system needs the label written."""
    value, label = metric.get("value"), metric.get("justification")
    # The readers take a label only after a number: any other value is written as it is
    if not is_number(value):
        return value
    anchors = (metric.get("scale") or {}).get("anchors") or []
    form_labels = {a.get("value"): a.get("label") for a in anchors if isinstance(a, dict)}
    if not isinstance(label, str) or not label.strip():
        return value
    if form_gives_labels and form_labels.get(value) == label:
        return value
    return f"{plain_number(value)}{separator}{label}"


def plain_number(value: int | float) -> str:
    """A number as the readers parse it: digits, with no exponent (1e-06 is 0.000001)."""
    text = str(value)
    return format(Decimal(text), "f") if "e" in text.lower() else text


def is_number(value: Any) -> bool:
    """Whether a value is a number, not a boolean."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def field_name(label: str) -> str:
    """A source's field name from the metric label its reader made of it, which spells
    underscores as spaces."""
    return label.strip().replace(" ", "_")


def id_as_number(value: Any) -> Any:
    """An identifier as a system that numbers its records writes it: a number when it is
    one, written without leading zeros."""
    if isinstance(value, str) and value.isdigit() and str(int(value)) == value:
        return int(value)
    return value


def iso_to_epoch(iso: Any, *, ms: bool = False) -> int | None:
    """An ISO 8601 time as Unix time, in seconds or milliseconds; None when it is not one."""
    if not isinstance(iso, str):
        return None
    try:
        dt = _dt.datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return round(dt.timestamp() * (1000 if ms else 1))


def iso_date_or_time(iso: Any) -> Any:
    """A time as a system that records dates writes it: the date alone when the time is
    midnight UTC, which is how its reader takes a date."""
    if isinstance(iso, str) and iso.endswith("T00:00:00Z"):
        return iso[:10]
    return iso


# ScholarOne's and Editorial Manager's web services give a review's score sheet as
# `scoreSheetCustomQuestions`: each question (`questionText`, `questionName`, `answerType`)
# with the reviewer's answer in `scoreSheetCustomAnswer` (`answerText`, `numericValue`)
_NUMBER = re.compile(r"^\s*[+-]?\d+(?:\.\d+)?\s*$")


def score_sheet_answers(
    questions: Any,
) -> tuple[list[tuple[str, int | float, str | None]], list[tuple[str, str]]]:
    """A score sheet's answers: (question, value, the answer's text when it says more than
    the value) for each answer with a number, and (question, text) for each answered in words.

    An answer has a number when the service gives one (`numericValue`), or when it is an
    integer question (Editorial Manager's `Integer`, whose `numericValue` is always null)
    answered with a number. A question without an answer is left out, as the services do.
    """
    scored: list[tuple[str, int | float, str | None]] = []
    written: list[tuple[str, str]] = []
    # The services document XML only: in JSON, one question may come as an object, not a list
    questions = [questions] if isinstance(questions, dict) else questions
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict):
            continue
        name = question.get("questionText") or question.get("questionName")
        answers = question.get("scoreSheetCustomAnswer")
        answers = answers if isinstance(answers, list) else [answers]
        answers = [a for a in answers if isinstance(a, dict)]
        if not isinstance(name, str) or not name.strip() or not answers:
            continue
        name = name.strip()
        texts = [a["answerText"].strip() for a in answers if isinstance(a.get("answerText"), str)]
        texts = [t for t in texts if t]
        value = answers[0].get("numericValue") if len(answers) == 1 else None
        if isinstance(value, str) and _NUMBER.match(value):
            value = float(value) if "." in value else int(value)
        if (
            not isinstance(value, (int, float))
            and len(texts) == 1
            and question.get("answerType") == "Integer"
            and _NUMBER.match(texts[0])
        ):
            value = float(texts[0]) if "." in texts[0] else int(texts[0])
            texts = []
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            label = texts[0] if len(texts) == 1 and texts[0] != str(value) else None
            scored.append((name, value, label))
        elif texts:
            written.append((name, "\n".join(texts)))
    return scored, written


def score_sheet_questions(sections: Any) -> list[dict[str, Any]]:
    """Text answers, as `narrative.sections` holds them, as score-sheet questions."""
    return [
        {"questionText": s["title"], "scoreSheetCustomAnswer": {"answerText": s["content"]}}
        for s in (sections if isinstance(sections, list) else [])
        if isinstance(s, dict)
        and isinstance(s.get("title"), str)
        and isinstance(s.get("content"), str)
    ]


def department_affiliation(departments: Any) -> str | None:
    """The reviewer's first affiliation (by `affiliationOrderNumber`) in the `departments` of
    ScholarOne's and Editorial Manager's web services: its `affiliation`, or else its
    department and institution."""
    listed = [departments] if isinstance(departments, dict) else departments
    listed = [d for d in listed if isinstance(d, dict)] if isinstance(listed, list) else []
    if not listed:
        return None
    first = min(listed, key=lambda d: d.get("affiliationOrderNumber") or 0)
    parts = [first.get("affiliation")] if first.get("affiliation") else []
    parts = parts or [first.get(k) for k in ("department", "institution")]
    affiliation = ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return affiliation or None
