# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""A mapping record as Markdown, for people checking how a review was mapped."""

from __future__ import annotations

import re
from collections.abc import Iterator
from itertools import groupby
from typing import Any

from .mapping import MappingResult, Rule, Step

MAX_CELL = 120
_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_ITEM = re.compile(r"^(.*?\[\d+\])")
_DEEPEST_ITEM = re.compile(r"^(.*\[\d+\])")

GAP_MEANINGS = {
    "unmapped": "Reviewer fields with no OCRS field. Their values are kept in `extensions`.",
    "unfilled": "OCRS fields this review leaves empty.",
    "coerced": "Reviewer values OCRS does not allow, and what the mapper did instead.",
    "unanchored": "Quotes from the paper that could not be found in it.",
}


def value_at(document: Any, path: str) -> Any:
    for key, index in _TOKEN.findall(path):
        if key:
            document = document.get(key) if isinstance(document, dict) else None
        else:
            position = int(index)
            fits = isinstance(document, list) and position < len(document)
            document = document[position] if fits else None
    return document


def cell(value: Any) -> str:
    text = " ".join(str(value).split())
    if len(text) > MAX_CELL:
        text = text[: MAX_CELL - 1] + "…"
    return text.replace("|", "\\|")


def item_of(path: str) -> str:
    """`issues[3].severity` → `issues[3]`; paths outside a list item → ``."""
    match = _ITEM.match(path)
    return match.group(1) if match else ""


def deepest_item_of(path: str) -> str:
    """`issues[0].tiers[1].items[2].text` → `issues[0].tiers[1].items[2]`."""
    match = _DEEPEST_ITEM.match(path)
    return match.group(1) if match else ""


def relative(path: str, item: str) -> str:
    return path[len(item) :].lstrip(".") or path


def how(step: Step, review: dict[str, Any]) -> tuple[str, str]:
    """How a step was done, and the value it produced."""
    if step.rule == Rule.COPIED:
        return "copied", cell(value_at(review, step.target))
    if step.rule == Rule.LOOKUP:
        return "looked up", cell(f"{step.original} → {step.result}")
    if step.rule == Rule.PARSED:
        return "parsed", cell(step.result)
    if step.rule == Rule.ANCHORED_EXACT:
        found = "found exactly"
    else:
        found = f"found approximately ({step.score:.0%} of the quote)"
    anchor = step.result if isinstance(step.result, dict) else {}
    block = f", block `{anchor['block_id']}`" if anchor.get("block_id") else ""
    return f"{found} in the paper", f"{anchor.get('part')}{block}"


def step_rows(steps: list[Step], review: dict[str, Any], item: str) -> Iterator[str]:
    """One row per step. Reviewer paths inside `item` are shortened relative to it;
    others (a part or tier heading above it) stay whole."""
    yield "| Reviewer field | OCRS field | How | Value |"
    yield "|---|---|---|---|"
    for step in steps:
        rule, value = how(step, review)
        inside = item and step.source.startswith((f"{item}.", f"{item}["))
        source = relative(step.source, item) if inside else step.source
        target = relative(step.target, item_of(step.target))
        yield f"| `{source}` | `{target}` | {rule} | {value} |"


def render_header(result: MappingResult) -> Iterator[str]:
    review, record = result.review, result.record
    system = review["referees"][0]["ai_referee"]["system"]
    framework = system["critic_framework"]
    target = review["target"]
    version = f", version {target['version']}" if target.get("version") else ""
    mapped_at = record.mapped_at.strftime("%Y-%m-%d %H:%M UTC")
    yield f"# {framework['name']} review mapped to OCRS"
    yield ""
    yield "| | |"
    yield "|---|---|"
    yield f"| Review | `{review['review_id']}` |"
    yield f"| Paper | `{target['work_id']}`{version} |"
    models = ", ".join(model["model_id"] for model in system["models"])
    yield f"| Reviewer | {framework['name']} at `{framework['version']}`, model {models} |"
    yield (
        f"| Mapping | {record.status.value}: mapper {record.source_format} "
        f"{record.mapper_version}, OCRS {record.ocrs_version}, {mapped_at} |"
    )
    if record.error:
        yield f"| Error | {cell(record.error)} |"


def render_gaps(result: MappingResult) -> Iterator[str]:
    gaps, framework = result.record.gaps, result.record.source_format
    anchored = sum(
        step.rule in (Rule.ANCHORED_EXACT, Rule.ANCHORED_FUZZY) for step in result.record.steps
    )
    yield "## Gaps"
    yield ""
    yield "| Gap | Count | Meaning |"
    yield "|---|---|---|"
    yield f"| Unmapped | {len(gaps.unmapped)} fields | {GAP_MEANINGS['unmapped']} |"
    yield f"| Unfilled | {len(gaps.unfilled)} fields | {GAP_MEANINGS['unfilled']} |"
    yield f"| Coerced | {len(gaps.coerced)} values | {GAP_MEANINGS['coerced']} |"
    if gaps.unanchored is None:
        unanchored = "not checked (no paper given)"
    else:
        unanchored = f"{len(gaps.unanchored)} of {len(gaps.unanchored) + anchored} quotes"
    yield f"| Unanchored | {unanchored} | {GAP_MEANINGS['unanchored']} |"
    if gaps.unmapped:
        yield ""
        yield f"### Unmapped: kept in `extensions.{framework}`"
        yield ""
        yield "| Reviewer field | Times |"
        yield "|---|---|"
        yield from (f"| `{field.path}` | {field.count} |" for field in gaps.unmapped)
    if gaps.coerced:
        yield ""
        yield "### Coerced"
        yield ""
        yield "| Reviewer field | Value | OCRS field | Result | Why |"
        yield "|---|---|---|---|---|"
        for c in gaps.coerced:
            yield (
                f"| `{c.source}` | {cell(c.original)} | `{c.target}` | {cell(c.result)} "
                f"| {cell(c.reason)} |"
            )
    if gaps.unanchored:
        yield ""
        yield "### Unanchored"
        yield ""
        yield "| Reviewer field | Quote | Best match |"
        yield "|---|---|---|"
        for quote in gaps.unanchored:
            yield f"| `{quote.source}` | {cell(quote.quote)} | {quote.best_score:.0%} |"
    if gaps.unfilled:
        yield ""
        yield "### Unfilled"
        yield ""
        whole = [path for path in gaps.unfilled if "." not in path]
        if whole:
            yield "- **Whole sections**: " + ", ".join(f"`{path}`" for path in whole)
        parts = [path for path in gaps.unfilled if "." in path]
        for section, paths in groupby(parts, key=lambda path: path.split(".")[0]):
            names = ", ".join(f"`{path.split('.', 1)[1]}`" for path in paths)
            yield f"- **{section}**: {names}"


def render_steps(result: MappingResult) -> Iterator[str]:
    review, record = result.review, result.record
    yield "## How each field was mapped"
    # One group per OCRS item (a finding), headed by the most specific reviewer item it
    # came from: several findings can come from one reviewer list item's children.
    for target_item, steps in groupby(record.steps, key=lambda step: item_of(step.target)):
        steps = list(steps)
        item = max((deepest_item_of(step.source) for step in steps), key=len)
        yield ""
        if not target_item:
            yield "### Review"
        else:
            title = value_at(review, f"{target_item}.title")
            suffix = f": {cell(title)}" if title else ""
            yield f"### `{item}` → `{target_item}`{suffix}"
        yield ""
        yield from step_rows(steps, review, item)
    if record.skipped:
        yield ""
        yield "## Skipped"
        yield ""
        yield from (f"- `{item.source}`: {item.reason}" for item in record.skipped)


def render_mapping_markdown(result: MappingResult) -> str:
    sections = [render_header(result), render_gaps(result), render_steps(result)]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"
