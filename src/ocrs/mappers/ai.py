# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Writing an AI reviewer mapper: the step recorder, the review envelope and `finish`.

An AI review mapper copies the reviewer's own output into OCRS. It never rewrites or
invents text. Whatever has no OCRS field goes, unchanged, to
`extensions.<name>`, which mirrors the reviewer's output. The run details
(work, reviewer commit, model, times, cost) come from whoever ran the
reviewer, as `map_with_record`'s keyword arguments, and are already in the
envelope the mapper receives.

A mapper is an `AIReviewMapper`: it takes the reviewer's output, the envelope and the
paper's blocks (or None), fills the envelope through a `Recorder`, and returns
`finish(...)`.

Each reviewer also has a `to_<name>` that writes an OCRS review back in the reviewer's
own format. It writes back what the mapper reads, from the same OCRS fields, and puts
what the mapper kept in `extensions.<name>` back where it came from, so mapping the
result again gives the same review. A review from anywhere else is written as well as
the format allows; the module of each reviewer says what is lost.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydantic import JsonValue

from ..anchors import Block, BlockKind, find_quote
from ..gaps import count_unmapped, generic_path, leftover, unfilled_paths
from ..identifiers import generate_canonical_work_id
from ..mapping import (
    Coercion,
    Gaps,
    MappingRecord,
    MappingResult,
    MappingStatus,
    Rule,
    SkippedItem,
    Step,
    UnanchoredQuote,
)
from ..schema import load_schema, require_content, schema_id, validate_canonical
from ..util import migrate_work_id_to_identifiers, narrative_text, referee_of

__all__ = [
    "AIReviewMapper",
    "FENCE",
    "Fences",
    "Block",
    "BlockKind",
    "MappingResult",
    "Recorder",
    "add_section",
    "check_text",
    "close_fence",
    "extension",
    "findings_of",
    "finish",
    "indented",
    "join_blocks",
    "open_fence",
    "overall_texts",
    "reviewer_model",
]

AIReviewMapper = Callable[[Any, dict[str, Any], list[Block] | None], MappingResult]
"""(reviewer's output, envelope, paper blocks or None) → the filled review and its record.

The output is the reviewer's JSON as a dict, or its text when the reviewer writes Markdown."""

REVIEW_VERSION = "1.0.0"
UNSPECIFIED = "unspecified"
# The mapping spec every mapper here follows: schemas/mapping-spec.v1.2.0.json.
MAPPING_SPEC_ID = "canonical-review.mapping.v1"
MAPPING_SPEC_VERSION = "1.2.0"
# OCRS fields that cannot apply to a review written by one AI reviewer.
NOT_FOR_AI_REVIEWS = {
    "referees[].human_referee",
    "referees[].hybrid_workflow",
    "referees[].ai_referee.reference",
    "provenance.raw_payload",
    "calibration",
    "signatures",
    "written_report",
}


# A fenced code block opens and closes with three or more backticks or tildes
# (a backtick fence's info string has no backticks, so ```example``` is inline code, not a fence)
FENCE = re.compile(r"^ {0,3}(`{3,}(?=[^`]*$)|~{3,})")
# A closing fence has nothing after its marker but whitespace (```python opens, never closes)
CLOSING_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")


# A line that starts a block of its own, so never lazily continues a paragraph: a list
# item, a heading, a quote or a thematic break
BLOCK_START = re.compile(
    r"^ {0,3}(?:[-*+]\s|\d{1,9}[.)](?:\s|$)|#{1,6}(?:\s|$)|>|(?:[-*_]\s*){3,}$)"
)
# The `>` markers that open a line of a block quote, nested quotes included, and one of them
QUOTE_MARKERS = re.compile(r"^(?: {0,3}> ?)+")
QUOTE_MARKER = re.compile(r"^ {0,3}> ?")
# A Setext heading's underline: up to three spaces, then a run of `=` or of `-`, alone
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
# An ATX heading: up to three spaces, then one to six `#` and a space or the line's end
ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
# Three or more `-`, `*` or `_`, spaced or not, alone on a line: a thematic break
THEMATIC_BREAK = re.compile(r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
# A list item's marker: `- `, `* `, `+ `, `1. ` or `1) `, after any indentation
LIST_ITEM = re.compile(r"^( *)(?:[-*+]|\d{1,9}[.)])(?: +|$)")


class Fences:
    """Tracks whether a line is inside a fenced code block, line by line.

    With `lists`, a fence belongs to the list item it opens in, as Markdown reads it: it is
    found and closed relative to the item's indentation, and a line indented less than the
    item ends the item and its code. So a fence after a list marker (`- ```py`) is code, its
    closing marker never opens another fence, and a heading at the line's start, which ends
    any item, is never inside an item's code.
    """

    def __init__(self, lists: bool = False) -> None:
        self.open: str | None = None  # the open fence's marker
        self.indent = 0  # how far the open fence's opening line is indented
        self.lists = lists
        self.items: list[int] = []  # content indentation of each open list item, outermost first
        self.depth = 0  # how many items deep the open fence is (0: outside lists)
        self.paragraph = False  # whether the last line continued an item's paragraph
        self.quote_fence: str | None = None  # a fence open inside a block quote, by marker
        self.quote_fence_depth = 0  # how many quotes deep that fence opened
        self.quote_paragraph = False  # whether the last line was a quote's paragraph text

    def closes(self, line: str) -> bool:
        """Whether `line` closes the open fence."""
        closing = CLOSING_FENCE.match(line)
        assert self.open is not None
        return bool(
            closing
            and closing.group(1)[0] == self.open[0]
            and len(closing.group(1)) >= len(self.open)
        )

    def holds(self, line: str) -> bool:
        """Whether `line` still belongs to the open fence (as code or its closing marker),
        before it is read: a line that ends the fence's list item does not."""
        line = line.rstrip("\r\n").expandtabs(4)
        if self.open is None:
            return False
        if not self.lists or not line.strip():
            return True
        base = self.items[self.depth - 1] if self.depth else 0
        return len(line) - len(line.lstrip(" ")) >= base

    def inside(self, line: str) -> bool:
        """Whether `line` is part of a fence (its opening and closing lines included)."""
        # A line may come with its ending, CRLF included; tabs indent to four-column stops
        line = line.rstrip("\r\n").expandtabs(4)
        if not self.lists:
            if self.open is None:
                fence = FENCE.match(line)
                self.open = fence.group(1) if fence else None
                self.indent = len(line) - len(line.lstrip(" "))
                return fence is not None
            if self.closes(line):
                self.open = None
            return True
        blank = not line.strip()
        indent = len(line) - len(line.lstrip(" "))
        base = self.items[self.depth - 1] if self.open is not None and self.depth else 0
        if self.open is not None and (blank or indent >= base):
            # Still in the fence's item (or outside lists): code until the closing marker
            if self.closes(line[base:]):
                self.open = None
            return True
        if blank:
            self.paragraph = self.quote_paragraph = False
            return False
        # A Setext underline (`===`, `--`) straight after an item's paragraph text, in the
        # item, makes that text a heading and ends the paragraph; it comes before any list
        # marker or thematic break reading of the line
        if self.paragraph and self.items and indent >= self.items[-1]:
            segment = line[self.items[-1] :]
            # (inside a quote, the underline is read without the quote's markers)
            if SETEXT_UNDERLINE.match(segment) or (
                QUOTE_MARKERS.match(segment)
                and SETEXT_UNDERLINE.match(QUOTE_MARKERS.sub("", segment))
            ):
                self.paragraph = self.quote_paragraph = False
                return False
        # A thematic break (`- - -`, `* * *`) looks like a marker but is no list item; inside
        # an item it is read relative to the item's content, however deep the item is
        # (the deepest item whose content the line reaches, ancestors included)
        inner = max((c for c in self.items if c <= indent), default=0)
        brk = THEMATIC_BREAK.match(line) or THEMATIC_BREAK.match(line[inner:])
        # A soft-wrapped line straight after an item's paragraph text stays in the item
        # (a lazy continuation), unless it starts a block of its own (a break included)
        lazy = self.paragraph and not brk and not BLOCK_START.match(line) and not FENCE.match(line)
        # Otherwise a line indented less than an item's content ends that item and its code
        while self.items and indent < self.items[-1] and not lazy:
            self.items.pop()
        if self.open is not None and len(self.items) < self.depth:
            self.open = None
        item = None if brk else LIST_ITEM.match(line)
        # A marker starts a list at up to three spaces, or nests anywhere in an item
        if item and (len(item.group(1)) <= 3 or self.items):
            marker = item.group(0)
            self.items.append(len(marker) if marker.endswith(" ") else len(marker) + 1)
            rest = line[len(marker) :]
        else:
            base = self.items[-1] if self.items else 0
            if indent < base:
                self.paragraph = lazy
                self.quote_paragraph = self.quote_paragraph and lazy
                return False
            rest = line[base:]
        fence = FENCE.match(rest)
        if fence:
            self.open, self.depth = fence.group(1), len(self.items)
            self.indent = len(line) - len(line.lstrip(" "))
            self.paragraph = self.quote_paragraph = False
            return True
        # Only paragraph text continues lazily: not indented code (four spaces past the item's
        # content, unless it continues a paragraph), a heading or a thematic break
        relative = len(rest) - len(rest.lstrip(" "))
        code = relative >= 4 and not self.paragraph
        # A quote's own content counts: `> # Heading` or `> ---` ends a paragraph, while a
        # quoted paragraph (`> text`) continues lazily like any other
        quoted = QUOTE_MARKERS.sub("", rest)
        in_quote = quoted != rest
        depth = QUOTE_MARKERS.match(rest).group(0).count(">") if in_quote else 0
        # Indented code inside a quote: four spaces past the quote's own marker, unless it
        # continues a paragraph of the same quote (a quote just opened has none)
        if in_quote and len(quoted) - len(quoted.lstrip(" ")) >= 4 and not self.quote_paragraph:
            code = True
        # A fence inside a quote runs to its closing marker (as long as its opener, at
        # least) or the quote's end; its lines are code, not paragraph text
        # (a quote the fence opened in that ends, a nested one inside its parent, ends it)
        if depth < self.quote_fence_depth:
            self.quote_fence = None
        if not in_quote:
            self.quote_fence = None
        elif self.quote_fence is not None:
            # Read at the fence's own depth: deeper markers are part of its code
            inner = rest
            for _ in range(self.quote_fence_depth):
                inner = QUOTE_MARKER.sub("", inner, count=1)
            closing = CLOSING_FENCE.match(inner)
            if (
                closing
                and closing.group(1)[0] == self.quote_fence[0]
                and len(closing.group(1)) >= len(self.quote_fence)
            ):
                self.quote_fence = None
            code = True
        elif fence_in_quote := FENCE.match(quoted):
            self.quote_fence, self.quote_fence_depth = fence_in_quote.group(1), depth
        self.paragraph = (
            bool(self.items)
            and bool(quoted.strip())
            and not code
            and not ATX_HEADING.match(quoted)
            and not THEMATIC_BREAK.match(quoted)
            and not FENCE.match(quoted)
        )
        self.quote_paragraph = in_quote and self.paragraph
        return False


def ocrs_version() -> str:
    try:
        return version("ocrs")
    except PackageNotFoundError:
        return "unknown"


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


class Recorder:
    """Collects the steps of one mapping and the paths it read."""

    def __init__(self, checks_quotes: bool) -> None:
        self.steps: list[Step] = []
        self.read: set[str] = set()
        self.coerced: list[Coercion] = []
        self.unanchored: list[UnanchoredQuote] | None = [] if checks_quotes else None
        self.skipped: list[SkippedItem] = []

    def copy(self, source: str, target: str, value: JsonValue) -> JsonValue:
        self.read.add(source)
        self.steps.append(Step(source=source, target=target, rule=Rule.COPIED))
        return value

    def lookup(self, source: str, target: str, value: str, table: dict[str, str]) -> str | None:
        self.read.add(source)
        result = table.get(value)
        if result is None:
            reason = f"not one of {sorted(table)}; left out"
            self.coerced.append(
                Coercion(source=source, target=target, original=value, result=None, reason=reason)
            )
            return None
        self.steps.append(
            Step(source=source, target=target, rule=Rule.LOOKUP, original=value, result=result)
        )
        return result

    def skip(self, source: str, reason: str) -> None:
        self.skipped.append(SkippedItem(source=source, reason=reason))

    def evidence_link(
        self, source: str, target: str, quote: str, ref: str, blocks: list[Block] | None
    ) -> dict[str, Any]:
        """An evidence link for `quote`, and where in the paper the quote was found.

        The place goes in the step's result (part of the paper and block ID), not in
        the link: OCRS has no field for a block ID that would mean anything outside
        the document it came from.
        """
        self.copy(source, f"{target}.quote", quote)
        self.anchor(source, target, quote, blocks)
        return {"type": "paper_section", "ref": ref, "quote": quote}

    def parse(self, source: str, target: str, original: str, result: JsonValue) -> JsonValue:
        """`result` was read out of `original`, part of a value at `source`, by a pattern."""
        self.read.add(source)
        self.steps.append(
            Step(source=source, target=target, rule=Rule.PARSED, original=original, result=result)
        )
        return result

    def anchor(self, source: str, target: str, quote: str, blocks: list[Block] | None) -> None:
        """Record where in the paper `quote` was found, or that it was not."""
        if blocks is None or self.unanchored is None:
            return
        match, best_score = find_quote(quote, blocks)
        if match is None:
            self.unanchored.append(
                UnanchoredQuote(source=source, quote=quote, best_score=best_score)
            )
        else:
            self.steps.append(
                Step(
                    source=source,
                    target=target,
                    rule=Rule.ANCHORED_EXACT if match.exact else Rule.ANCHORED_FUZZY,
                    result={"part": match.block.kind.value, "block_id": match.block.id},
                    score=round(match.score, 3),
                )
            )


def build_review(
    *,
    framework: str,
    mapper_version: str,
    review_id: str,
    source_system: str,
    work_id: str,
    work_type: str,
    started_at: datetime,
    ended_at: datetime,
    reviewer_commit: str | None = None,
    reviewer_version: str | None = None,
    model_id: str | None = None,
    work_version: str | None = None,
    requested_by: str | None = None,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """The parts of an OCRS review that come from the run, not the reviewer's output.

    `work_id` is any identifier of the paper: a canonical work ID, a DOI, a URL, or the
    platform's own ID, which becomes an internal_id named after `source_system`. A hosted
    reviewer may publish no commit, version or model; those are then `unspecified`,
    which OCRS requires to be stated.
    """
    identifiers = migrate_work_id_to_identifiers(work_id, source_system)
    framework_info: dict[str, Any] = {
        "name": framework,
        "version": reviewer_version or (reviewer_commit[:12] if reviewer_commit else UNSPECIFIED),
    }
    if reviewer_commit:
        framework_info["commit"] = reviewer_commit
    execution: dict[str, Any] = {
        "started_at": iso(started_at),
        "ended_at": iso(ended_at),
        "wall_time_seconds": (ended_at - started_at).total_seconds(),
    }
    if cost_usd is not None:
        execution["cost"] = {"currency": "USD", "estimated_total": cost_usd}
    review: dict[str, Any] = {
        "$schema": schema_id(),
        "review_id": review_id,
        "version": REVIEW_VERSION,
        "created_at": iso(ended_at),
        "provenance": {
            "source_system": source_system,
            "source_review_id": review_id,
            "imported_at": iso(datetime.now(UTC)),
            "mapping": {
                "mapping_spec_id": MAPPING_SPEC_ID,
                "mapping_spec_version": MAPPING_SPEC_VERSION,
                "mapper_version": mapper_version,
            },
        },
        "referees": [
            {
                "referee_type": "ai",
                "identity_mode": "open",
                "ai_referee": {
                    "system": {
                        "critic_framework": framework_info,
                        "models": [{"role": "reviewer", "model_id": model_id or UNSPECIFIED}],
                    },
                    "execution": execution,
                },
            }
        ],
        "target": {
            "work_id": generate_canonical_work_id(identifiers),
            "work_type": work_type,
            "identifiers": identifiers,
        },
        "opinion": {},
    }
    if work_version:
        review["target"]["version"] = work_version
    if requested_by:
        review["review_context"] = {"requested_by": requested_by}
    return review


# Writing a review back in a reviewer's own format


def extension(canonical: dict[str, Any], framework: str) -> dict[str, Any]:
    """What the reviewer's mapper kept in `extensions.<framework>`, or {} when it kept
    nothing (or the review came from somewhere else)."""
    kept = (canonical.get("extensions") or {}).get(framework)
    return kept if isinstance(kept, dict) else {}


def reviewer_model(canonical: dict[str, Any]) -> str | None:
    """The model the review's AI referee ran as reviewer, if it says one."""
    system = (referee_of(canonical).get("ai_referee") or {}).get("system") or {}
    for model in system.get("models") or []:
        if model.get("role") == "reviewer" and model.get("model_id") not in (None, UNSPECIFIED):
            return model["model_id"]
    return None


def overall_texts(canonical: dict[str, Any]) -> tuple[str | None, str | None]:
    """The review's summary and its full text, from `opinion` or else `narrative`. Text
    for the editors only (a part with audience `editors`) is never among them."""
    opinion = canonical.get("opinion") or {}
    summary = opinion.get("summary") or narrative_text(canonical, "summary")
    text = opinion.get("text") or narrative_text(canonical, "review")
    return summary or None, (text if text != summary else None) or None


def findings_of(canonical: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The review's findings of one kind. One with empty text is kept: a reviewer's empty
    point is still a point, and the IDs of those after it depend on it."""
    found = (canonical.get("findings") or {}).get(kind) or []
    return [p for p in found if isinstance(p, dict) and isinstance(p.get("text"), str)]


def open_fence(text: str) -> str | None:
    """The marker of a code fence `text` leaves open outside any list, or None. (A fence in
    a list item ends with the item, at the next line that starts at the margin.)"""
    fences = Fences(lists=True)
    for line in text.splitlines():
        fences.inside(line)
    return fences.open if fences.open is not None and fences.depth == 0 else None


def close_fence(text: str) -> str:
    """`text` with any fence it leaves open closed, so it cannot swallow what follows. The
    closing marker is indented as the opening one was (at most three spaces, as a closing
    marker may be), so it also closes the fence where that line sits in a list item."""
    fences = Fences(lists=True)
    for line in text.splitlines():
        fences.inside(line)
    if fences.open is None or fences.depth:
        return text
    return f"{text}\n{' ' * min(fences.indent, 3)}{fences.open}"


def join_blocks(
    blocks: list[str | None],
    separator: str = "\n\n",
    *,
    is_open: Callable[[str], object] | None = None,
    close: Callable[[str], str] | None = None,
) -> str:
    """Blocks of a report whose order the reader does not depend on, joined. One that leaves
    a code fence open goes last, where it swallows nothing, when it starts at the margin;
    any other that does is closed where it is, unless it is already last.
    A reviewer's own report can leave a fence open only in its last block, so it comes
    back in its own order. `is_open` and `close` find and close a block's open fence, for
    a block read differently from plain Markdown."""
    is_open, close = is_open or open_fence, close or close_fence
    present = [block for block in blocks if block]
    unclosed = [i for i, block in enumerate(present) if is_open(block)]
    if not unclosed:
        return separator.join(present)
    last = unclosed[-1]
    # Only a block that starts at the margin may move: one that starts indented would, after
    # a list, become part of the list's last item. It stays in place, closed, instead
    if not movable(present[last]):
        # A block that cannot move whole may still split at a paragraph boundary: a closed
        # head that stays, and an open tail that can follow a list (prose kept from before
        # and after a list together). A block already last needs neither
        head, tail = (
            (present[last], None) if last == len(present) - 1 else split_open_tail(present[last])
        )
        if tail is None:
            # The final block swallows nothing, so it is left as it is
            return separator.join([*(close(block) for block in present[:-1]), present[-1]])
        present[last] = head
        ordered = [close(block) for block in present if block]
        return separator.join([*ordered, tail])
    ordered = [close(block) for i, block in enumerate(present) if i != last]
    return separator.join([*ordered, present[last]])


def movable(block: str) -> bool:
    """Whether a block may move after a list: it starts at the margin, or with a thematic
    break indented less than any list item's content (two spaces at least), which ends the
    list. Tabs count as indentation, to the next multiple of four columns."""
    first = next((line for line in block.splitlines() if line.strip()), "").expandtabs(4)
    leading = len(first) - len(first.lstrip(" "))
    return leading == 0 or (leading == 1 and bool(THEMATIC_BREAK.match(first)))


def split_open_tail(block: str) -> tuple[str, str | None]:
    """`block` split at the last paragraph boundary after which it can move: a head that
    leaves no fence open, and a movable tail. (block, None) when there is none. The block
    is read once, noting at each boundary whether the lines before it leave a fence open."""
    lines = block.split("\n")
    fences = Fences(lists=True)
    split, text_before = None, False
    for k, line in enumerate(lines):
        closed_before = fences.open is None or fences.depth > 0
        boundary = k > 0 and not lines[k - 1].strip() and line.strip()
        if boundary and closed_before and text_before and movable(line):
            split = k
        fences.inside(line)
        text_before = text_before or bool(line.strip())
    if split is None:
        return block, None
    return "\n".join(lines[:split]).rstrip("\n"), "\n".join(lines[split:])


def add_section(sections: dict[str, str], heading: str, text: str) -> None:
    """Add `text` under `heading`, after any text already there, so two things with the
    same heading (two checks of one kind, say) are both kept."""
    if heading in sections:
        text = f"{close_fence(sections[heading])}\n\n{text}"
    sections[heading] = text


def indented(text: str, prefix: str) -> str:
    """`text` with every line after the first indented by `prefix`, blank lines left blank,
    so it stays inside the list item it starts."""
    first, *rest = text.split("\n")
    return "\n".join([first, *(f"{prefix}{line}" if line.strip() else "" for line in rest)])


def check_text(check: dict[str, Any]) -> str:
    """A check in prose, for a format with no place of its own for it: its summary, then
    what else it says (outcome, who ran it, measurements, items, the findings it names)."""
    parts = [check["summary"]] if check.get("summary") else []
    if check.get("outcome"):
        parts.append(f"Outcome: {check['outcome'].replace('_', ' ')}")
    performer = (check.get("performed_by") or {}).get("name")
    if performer and performer not in check.get("summary", ""):
        parts.append(f"Performed by: {performer}")
    lines = []
    for m in check.get("measurements") or []:
        unit = f" {m['unit']}" if m.get("unit") else ""
        lines.append(f"- {m.get('label') or m['key']}: {m['value']}{unit}")
    for item in check.get("items") or []:
        target = item.get("target") or {}
        work = target.get("work") or {}
        name = target.get("ref") or work.get("citation") or work.get("title") or target["type"]
        flagged = " (flagged)" if item.get("flagged") else ""
        notes = f" — {item['notes']}" if item.get("notes") else ""
        lines.append(f"- {name}: {item['status']}{flagged}{notes}")
    if lines:
        parts.append("\n".join(lines))
    if check.get("finding_ids"):
        parts.append(f"Findings: {', '.join(check['finding_ids'])}")
    return "\n\n".join(parts)


def finish(
    review: dict[str, Any],
    recorder: Recorder,
    output: dict[str, Any],
    *,
    ignored: set[str],
    generic: Callable[[str], str] = generic_path,
) -> MappingResult:
    """Put what was not mapped in `extensions`, validate, and record the gaps.

    `ignored` lists output paths that are deliberately not kept (`*` matches
    any key). `generic` turns an output path into the form gaps are summed by.
    """
    framework = review["referees"][0]["ai_referee"]["system"]["critic_framework"]["name"]
    mapper_version = review["provenance"]["mapping"]["mapper_version"]
    left = leftover(output, recorder.read, ignored, generic)
    if left:
        review["extensions"] = {framework: left}
    require_content(review, framework)
    validate_canonical(review)
    gaps = Gaps(
        unmapped=count_unmapped(left, generic),
        unfilled=unfilled_paths(review, load_schema(), NOT_FOR_AI_REVIEWS),
        coerced=recorder.coerced,
        unanchored=recorder.unanchored,
    )
    record = MappingRecord(
        status=MappingStatus.PARTIAL if recorder.skipped else MappingStatus.OK,
        source_format=framework,
        mapper_version=mapper_version,
        ocrs_version=ocrs_version(),
        mapped_at=datetime.now(UTC),
        steps=recorder.steps,
        skipped=recorder.skipped,
        gaps=gaps,
    )
    return MappingResult(review=review, record=record)
