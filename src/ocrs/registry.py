# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Registry of source/target mappers for canonical review conversion."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from pydantic import AwareDatetime, validate_call

from .anchors import Block
from .hierarchy import legacy_view, upgrade_content
from .mappers import deepreview, openaireview, reviewer3
from .mappers.ai import AIReviewMapper, build_review
from .mappers.cmt import from_cmt, to_cmt
from .mappers.editorialmanager import from_editorialmanager, to_editorialmanager
from .mappers.hotcrp import from_hotcrp, to_hotcrp
from .mappers.jats import from_jats, to_jats
from .mappers.journal import from_journal_narrative, to_journal_narrative
from .mappers.openreview import from_openreview, to_openreview
from .mappers.scholarone import from_scholarone, to_scholarone
from .mapping import MappingResult
from .schema import require_content, schema_id, validate_canonical

_FROM: dict[str, Callable[..., dict[str, Any]]] = {
    "cmt": from_cmt,
    "editorialmanager": from_editorialmanager,
    "hotcrp": from_hotcrp,
    "jats": from_jats,
    "journal_narrative": from_journal_narrative,
    "openreview": from_openreview,
    "scholarone": from_scholarone,
}

# AI reviewer sources: their mappers also return a mapping record (steps and gaps).
_FROM_WITH_RECORD: dict[str, AIReviewMapper] = {
    "deepreview": deepreview.map_deepreview,
    "openaireview": openaireview.map_openaireview,
    "reviewer3": reviewer3.map_reviewer3,
}
_MAPPER_VERSIONS = {
    "deepreview": deepreview.MAPPER_VERSION,
    "openaireview": openaireview.MAPPER_VERSION,
    "reviewer3": reviewer3.MAPPER_VERSION,
}

# AI reviewer targets give the reviewer's own output: JSON as a dict, or Markdown text.
_TO: dict[str, Callable[[dict[str, Any]], dict[str, Any] | str]] = {
    "cmt": to_cmt,
    "deepreview": deepreview.to_deepreview,
    "editorialmanager": to_editorialmanager,
    "hotcrp": to_hotcrp,
    "jats": to_jats,
    "journal_narrative": to_journal_narrative,
    "openaireview": openaireview.to_openaireview,
    "openreview": to_openreview,
    "reviewer3": reviewer3.to_reviewer3,
    "scholarone": to_scholarone,
}


def supported_sources():
    return sorted([*_FROM, *_FROM_WITH_RECORD])


def supported_targets():
    return sorted(_TO.keys())


def map_from(
    source: str,
    payload: dict[str, Any],
    *,
    keep_raw: bool = False,
    scale_bounds: dict[str, Any] | None = None,
    submission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a review to OCRS. For an AI reviewer, `payload` holds map_with_record's arguments,
    `output` included.

    For `openreview`, `payload` is a note (API v1, or v2 with `{"value": …}` fields);
    `scale_bounds` is its review form's bounds for each score field (`{"rating": {"min": 1,
    "max": 6, "labels": {"6": "Strong Accept"}}}`) and `submission` the work reviewed
    (`id`, `title`, `venue`, `venueid`, `doi`, `arxiv_id`). Other sources take neither."""
    if (scale_bounds is not None or submission is not None) and source != "openreview":
        raise ValueError(f"scale_bounds and submission apply to openreview, not {source}")
    if source in _FROM_WITH_RECORD:
        out = map_with_record(source, **payload).review
        if keep_raw:
            raw = payload["output"]
            out["provenance"]["raw_payload"] = raw if isinstance(raw, dict) else {"text": raw}
    elif source == "openreview":
        out = from_openreview(
            payload, keep_raw=keep_raw, scale_bounds=scale_bounds, submission=submission
        )
    elif source in _FROM:
        out = _FROM[source](payload, keep_raw=keep_raw)
    else:
        raise ValueError(f"Unsupported source: {source}. Supported: {supported_sources()}")
    if source not in _FROM_WITH_RECORD:
        out = upgrade_content(out, unbounded_fallback=scale_bounds is None)
        out["$schema"] = schema_id()
        if scale_bounds is not None and out.get("metrics"):
            # The caller's bounds, not the venue's form: `source.snapshot` is reserved for
            # the original rubric, so these are recorded as supplied by the caller.
            out.setdefault("extensions", {}).setdefault("openreview", {})["caller_scale_bounds"] = (
                copy.deepcopy(scale_bounds)
            )
    require_content(out, source)
    validate_canonical(out)
    return out


def mapper_version(source: str) -> str:
    if source not in _MAPPER_VERSIONS:
        raise ValueError(f"No mapping record for {source}. Supported: {sorted(_MAPPER_VERSIONS)}")
    return _MAPPER_VERSIONS[source]


@validate_call
def map_with_record(
    source: str,
    output: dict[str, Any] | str,
    *,
    review_id: str,
    source_system: str,
    work_id: str,
    work_type: str,
    started_at: AwareDatetime,
    ended_at: AwareDatetime,
    reviewer_commit: str | None = None,
    reviewer_version: str | None = None,
    model_id: str | None = None,
    work_version: str | None = None,
    requested_by: str | None = None,
    cost_usd: float | None = None,
    blocks: list[Block] | None = None,
) -> MappingResult:
    """Map an AI reviewer's own output to OCRS, with a record of each step and the gaps.

    `output` is the reviewer's file, unchanged: its JSON as a dict, or its text when the
    reviewer writes Markdown (DeepReview). The keyword arguments are what that file
    doesn't say: which review and paper, what kind of work the paper is, who produced the
    review, the reviewer's commit or version, the model, the run's times and cost. A hosted
    reviewer that publishes no version or model gets `unspecified` for them. `blocks` is the
    paper, to find each quote in; without it, quotes are copied but not checked.
    """
    if source not in _FROM_WITH_RECORD:
        raise ValueError(f"No mapping record for {source}. Supported: {sorted(_FROM_WITH_RECORD)}")
    review = build_review(
        framework=source,
        mapper_version=_MAPPER_VERSIONS[source],
        review_id=review_id,
        source_system=source_system,
        work_id=work_id,
        work_type=work_type,
        work_version=work_version,
        reviewer_commit=reviewer_commit,
        reviewer_version=reviewer_version,
        model_id=model_id,
        started_at=started_at,
        ended_at=ended_at,
        cost_usd=cost_usd,
        requested_by=requested_by,
    )
    return _FROM_WITH_RECORD[source](output, review, blocks)


def map_to(target: str, canonical_review: dict[str, Any]) -> dict[str, Any] | str:
    """Write an OCRS review in a target's format. An AI reviewer target gives its own output:
    OpenAIReview's paper.json as a dict, DeepReview's and Reviewer3's report as Markdown."""
    validate_canonical(canonical_review)
    if target not in _TO:
        raise ValueError(f"Unsupported target: {target}. Supported: {supported_targets()}")
    return _TO[target](legacy_view(canonical_review))
