# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""OpenAIReview paper.json → OCRS.

OpenAIReview writes one entry per review method under `methods`, keyed
`<method>__<model>`. The mapper reads the merged `progressive` comments, or the
only method there is. A paper.json can hold merged comments from several models,
one review each: the mapper reads those of the run's `model_id`, and without one,
the first. The `progressive_original` entry holds the same comments
before merging and is not kept, nor is `paragraphs`, the paper's own text.

Each comment becomes a weakness: `title`, `explanation` as the text,
`comment_type` as a tag and `quote` as an evidence link. OpenAIReview gives no
severity and no location other than its own paragraph number, which is kept
in `extensions.openaireview`.

`to_openaireview` writes an OCRS review back as a paper.json (see its docstring).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from ..anchors import Block
from ..gaps import generic_path
from ..mapping import MappingResult
from .ai import (
    UNSPECIFIED,
    Recorder,
    extension,
    findings_of,
    finish,
    overall_texts,
    reviewer_model,
)

MAPPER_VERSION = "1.1.0"
MERGED_METHOD_PREFIX = "progressive__"
UNMERGED_METHOD_PREFIX = "progressive_original__"
IGNORED = {"paragraphs", f"methods.{UNMERGED_METHOD_PREFIX}*"}


class Comment(BaseModel):
    title: str = ""
    quote: str = ""
    explanation: str = ""
    comment_type: str = ""


class Method(BaseModel):
    overall_feedback: str = ""
    comments: list[Comment] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class PaperResult(BaseModel):
    methods: dict[str, Method] = {}


def method_wildcard(method_keys: list[str]) -> Callable[[str], str]:
    """Turns `methods.progressive__<model>.x` into `methods.progressive__*.x`.

    So gaps from runs on different models sum together. Model names contain
    dots, so the keys must be known rather than parsed out of a path.
    """

    def generic(path: str) -> str:
        path = generic_path(path)
        for key in method_keys:
            prefix = f"methods.{key}"
            if path == prefix or path.startswith((f"{prefix}.", f"{prefix}[")):
                return f"methods.{key.split('__')[0]}__*{path[len(prefix) :]}"
        return path

    return generic


def model_method(methods: dict[str, Any], model: str | None) -> str | None:
    """The merged method OpenAIReview ran with `model`: `progressive__<model>`, or the one
    whose own `model` says it. A paper.json holds one merged method per model it ran."""
    if not model:
        return None
    for key, method in methods.items():
        if key.startswith(MERGED_METHOD_PREFIX) and (
            key == f"{MERGED_METHOD_PREFIX}{model}"
            or (isinstance(method, dict) and method.get("model") == model)
        ):
            return key
    return None


def pick_method(methods: dict[str, Any], model: str | None = None) -> str:
    """The method to map: the merged one run with the review's model, else the first merged
    one, else the only one there is."""
    merged = [key for key in methods if key.startswith(MERGED_METHOD_PREFIX)]
    chosen = model_method(methods, model)
    if chosen:
        return chosen
    if model and len(merged) > 1:
        raise ValueError(f"No OpenAIReview method ran with model {model}: {sorted(merged)}")
    if merged:
        return merged[0]
    others = [key for key in methods if not key.startswith(UNMERGED_METHOD_PREFIX)]
    if len(others) != 1:
        raise ValueError(f"Cannot tell which OpenAIReview method to map: {sorted(methods)}")
    return others[0]


def map_comment(
    comment: Comment, source: str, target: str, recorder: Recorder, blocks: list[Block] | None
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "text": recorder.copy(f"{source}.explanation", f"{target}.text", comment.explanation)
    }
    if comment.title:
        finding["title"] = recorder.copy(f"{source}.title", f"{target}.title", comment.title)
    if comment.comment_type:
        finding["tags"] = [
            recorder.copy(f"{source}.comment_type", f"{target}.tags[0]", comment.comment_type)
        ]
    if comment.quote:
        link_target = f"{target}.evidence_links[0]"
        link = recorder.evidence_link(f"{source}.quote", link_target, comment.quote, "", blocks)
        finding["evidence_links"] = [link]
    return finding


def map_openaireview(
    output: dict[str, Any], review: dict[str, Any], blocks: list[Block] | None
) -> MappingResult:
    """Fills `review`, the envelope map_with_record built, from the reviewer's output."""
    paper = PaperResult.model_validate(output)
    # The review's model, when the caller gave one, says which model's comments to map
    key = pick_method(output.get("methods") or {}, reviewer_model(review))
    method, prefix = paper.methods[key], f"methods.{key}"
    recorder = Recorder(checks_quotes=blocks is not None)
    if method.overall_feedback:
        review["opinion"]["summary"] = recorder.copy(
            f"{prefix}.overall_feedback", "opinion.summary", method.overall_feedback
        )
    if method.prompt_tokens is not None and method.completion_tokens is not None:
        target = "referee.ai_referee.outputs.token_usage"
        review["referee"]["ai_referee"]["outputs"] = {
            "token_usage": {
                "input_tokens": recorder.copy(
                    f"{prefix}.prompt_tokens", f"{target}.input_tokens", method.prompt_tokens
                ),
                "output_tokens": recorder.copy(
                    f"{prefix}.completion_tokens",
                    f"{target}.output_tokens",
                    method.completion_tokens,
                ),
            }
        }
    weaknesses = []
    skipped = []
    for index, comment in enumerate(method.comments):
        source = f"{prefix}.comments[{index}]"
        if not comment.explanation:
            recorder.skip(source, "no explanation")
            skipped.append(index)
            continue
        target = f"findings.weaknesses[{len(weaknesses)}]"
        # The ID says where the comment was, so it goes back there
        weaknesses.append(
            {"id": f"comment-{index + 1}"} | map_comment(comment, source, target, recorder, blocks)
        )
    if weaknesses:
        review["findings"] = {"weaknesses": weaknesses}
    result = finish(
        review,
        recorder,
        output,
        ignored=IGNORED,
        generic=method_wildcard(list(paper.methods)),
    )
    keep_what_was_mapped(result.review, list(paper.methods), key, len(method.comments), skipped)
    return result


def keep_what_was_mapped(
    review: dict[str, Any], keys: list[str], key: str, count: int, skipped: list[int]
) -> None:
    """Keep in extensions which method was mapped (empty when all of it was) and each skipped
    comment's empty explanation, so `to_openaireview` puts both back without guessing."""
    kept = review.setdefault("extensions", {}).setdefault("openaireview", {})
    methods = kept.get("methods") or {}
    mapped = dict(methods.get(key) or {})
    if skipped:
        comments = list(mapped.get("comments") or [None] * count)
        for index in skipped:
            comments[index] = {**(comments[index] or {}), "explanation": ""}
        mapped["comments"] = comments
    kept["methods"] = {
        k: mapped if k == key else methods[k] for k in keys if k == key or k in methods
    }


# OCRS → OpenAIReview

# Findings written as comments, in this order; OpenAIReview has no place for strengths
COMMENT_KINDS = ("weaknesses", "questions", "changes", "comments")
COMMENT_ID = re.compile(r"^comment-(\d+)$")


def write_comment(point: dict[str, Any], kept: dict[str, Any] | None) -> dict[str, Any]:
    """One comment from a finding, with what the mapper kept of the comment it came from."""
    comment: dict[str, Any] = dict(kept or {})
    if point.get("title"):
        comment["title"] = point["title"]
    quotes = [link["quote"] for link in point.get("evidence_links") or [] if link.get("quote")]
    if quotes:
        comment["quote"] = quotes[0]
    comment["explanation"] = point["text"]
    if point.get("tags"):
        comment["comment_type"] = point["tags"][0]
    return comment


def write_comments(
    weaknesses: list[dict[str, Any]],
    others: list[dict[str, Any]],
    kept: list[Any],
    from_openaireview: bool,
) -> list[dict[str, Any]]:
    """The comments in the order the reviewer wrote them, then any new ones.

    The mapper keeps the comment list's length in extensions: a comment it skipped kept its
    empty explanation, and one it mapped is the weakness with ID `comment-<n>` (in a review
    from OpenAIReview), which gets back the fields the mapper did not read. What is kept of
    a comment whose weakness is gone goes with it.
    """
    by_position: dict[int, dict[str, Any]] = {}
    new = []
    for point in weaknesses:
        place = COMMENT_ID.match(point.get("id", "")) if from_openaireview else None
        position = int(place.group(1)) - 1 if place else None
        if position is None or position in by_position:
            new.append(point)
        else:
            by_position[position] = point
    comments: list[dict[str, Any]] = []
    for position, entry in enumerate(kept):
        if isinstance(entry, dict) and "explanation" in entry:
            comments.append(dict(entry))
        elif position in by_position:
            comments.append(write_comment(by_position.pop(position), entry))
    # Mapped comments past the end of what was kept left nothing there
    comments += [write_comment(by_position[p], None) for p in sorted(by_position)]
    return comments + [write_comment(point, None) for point in [*new, *others]]


def to_openaireview(canonical: dict[str, Any]) -> dict[str, Any]:
    """An OCRS review as OpenAIReview's paper.json, with one method.

    The review's summary (or, without one, its full text) is the overall feedback, and each
    weakness, question, requested change and comment is a comment: its title, its text as
    the explanation, its first tag as the comment type and its first quote. Token usage is
    the method's prompt and completion tokens. Strengths, contributions, scores, checks and
    the decision have no place in paper.json and are left out, as are the paper's own text
    and text for the editors only.
    """
    kept = copy.deepcopy(extension(canonical, "openaireview"))
    methods = kept.pop("methods", None) or {}
    model = reviewer_model(canonical) or UNSPECIFIED
    # The mapper keeps the method it mapped: the one run with the review's model, else a
    # merged one, as when it picked one
    merged = [k for k in methods if k.startswith(MERGED_METHOD_PREFIX)]
    key = model_method(methods, reviewer_model(canonical)) or next(
        iter(merged or methods), f"{MERGED_METHOD_PREFIX}{model}"
    )
    method: dict[str, Any] = (
        dict(methods[key])
        if key in methods
        else {"label": f"Progressive ({model})", "model": model}
    )
    summary, text = overall_texts(canonical)
    feedback = summary or text
    if feedback:
        method["overall_feedback"] = feedback
    others = [point for kind in COMMENT_KINDS[1:] for point in findings_of(canonical, kind)]
    method["comments"] = write_comments(
        findings_of(canonical, "weaknesses"), others, method.get("comments") or [], key in methods
    )
    outputs = ((canonical.get("referee") or {}).get("ai_referee") or {}).get("outputs") or {}
    usage = outputs.get("token_usage") or {}
    if usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
        method["prompt_tokens"] = usage["input_tokens"]
        method["completion_tokens"] = usage["output_tokens"]
    # A review from elsewhere gets the slug and title OpenAIReview writes; a review from
    # OpenAIReview gets back its own
    paper: dict[str, Any] = {} if methods else {"slug": "paper"}
    title = (canonical.get("target") or {}).get("title")
    if title and not methods:
        paper["title"] = title
    paper |= kept
    # The other methods the reviewer ran go back as they were
    paper["methods"] = {k: method if k == key else v for k, v in {**methods, key: None}.items()}
    return paper
