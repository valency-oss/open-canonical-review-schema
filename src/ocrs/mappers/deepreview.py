# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Google DeepReview report (Markdown) → OCRS.

DeepReview's "Copy Report" gives the review as Markdown:

    ## Summary                          → opinion.summary
    ## Strengths, ## Weaknesses         → findings.strengths, findings.weaknesses
    ## Potential Issues And Suggestions
    ### [Introduction, …] (Pages: 1-9)   one part of the paper
    #### Potential Mistakes and Improvements   numbered points
    #### Minor Corrections and Typos           bulleted points

The mapper first parses the report into the export's own structure, and the paths
in the mapping record name places in it:

    summary, strengths[i].{title, text}, weaknesses[i].{title, text},
    issues[i].heading, issues[i].tiers[j].heading,
    issues[i].tiers[j].items[k].{title, location, text}, other.<heading>,
    other.preamble (text above the first section, other than the report's wrapper)

Each point becomes a finding with the part and tier headings as its `group`. A
point's bold heading is its title, and a parenthetical list of places at its end
(`(Section 2.1, Pages 10–11; Figure 1a)`), or a heading that is only places
(`Page 14, Figure 1(a) caption`), gives one evidence link per `;`- or `&`-separated
place, with its page, page range and section when there is just one of each. The
paper's text the point quotes in italics (`*"…"*`) becomes evidence quotes, and
rewrites it proposes (`Consider revising to *"…"*`, `*"…"* would be more precise`,
`"A" should be "B"`, `Change "A" to "B"`) become suggested edits; rewrites it warns
against ("Do not replace …") stay in its text. An edit has an `original` only when
the report quotes the text it replaces, as in `"A" should be "B"`; otherwise the
report gives only the new text. A work it says the paper should
cite (`(Reference Paper: Title, Authors, Year)`) becomes an `external` evidence
link with the work's title, authors and year. All of these are recorded as
`parsed` steps.

The report's Weaknesses restate points made in full under Potential Issues, so
each is marked `summarizes: []`: an overview, though the report does not say
which points it covers. The report states no severity. DeepReview's own page
shows Potential Mistakes points as Major and Minor Corrections as Minor, so the
tier is looked up as `major` or `minor`; a tier the mapper does not know is
recorded as a coercion and left without severity.

`to_deepreview` writes an OCRS review back as such a report (see its docstring).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable
from typing import Any

from ..anchors import Block
from ..mapping import MappingResult
from .ai import (
    BLOCK_START,
    FENCE,
    THEMATIC_BREAK,
    Fences,
    Recorder,
    add_section,
    check_text,
    close_fence,
    extension,
    findings_of,
    finish,
    indented,
    join_blocks,
    overall_texts,
)

MAPPER_VERSION = "1.1.0"
TIER_SEVERITY = {
    "Potential Mistakes and Improvements": "major",
    "Minor Corrections and Typos": "minor",
}
ISSUES_HEADING = "Potential Issues And Suggestions"
SECTIONS = {"Summary": "summary", "Strengths": "strengths", "Weaknesses": "weaknesses"}

ITEM_START = re.compile(r"^(?:\d+\.|[-*])\s+(.*)$")
BOLD_HEAD = re.compile(r"^\*\*(.+?)\*\*\s*:?\s*(.*)$", re.DOTALL)
PLACE_WORD = (
    r"(?:pp?\.|pages?|sections?|sec\.|tables?|fig(?:ure)?s?\.?|eq(?:uation)?s?\.?|"
    r"appendi(?:x|ces)|abstract|ref(?:erence)?s?\.?|bibliography|acknowledg\w*|"
    r"column|lines?|footnote)"
)
# A heading that is only places, such as `Page 1, Column 2 (…)`, `Abstract (Page 1)` or
# `Table I(a) and Table I(b), …`: its first part is place words and identifiers alone,
# so `Table 1 Conflicts with the Prose (…)` is a title, not a place
# Each identifier is read one way only: its runs are possessive, so the `and` in `1and2`
# is never tried both as part of one and as the word between two, and a lone `I`, `V`, `X`
# or `L` is a numeral, never also a lettered identifier. Without that, a long list that
# fails at its end would be retried every way it could be split.
PLACE_ID = (
    r"(?:\d[\w.()–-]*+|[IVXL]++(?:-[\w.]++)?(?:\([a-z]\))?"
    r"|(?![IVXL](?![\d.]))[A-Z][\d.]*+(?:\([a-z]\))?)"
)
PLACES_ONLY = re.compile(
    rf"^(?i:{PLACE_WORD})(?:\s+{PLACE_ID}(?:\s*(?:,|and|&)\s*(?:(?i:{PLACE_WORD})\s+)?{PLACE_ID})*)?$"
)
FIRST_PART = re.compile(r",\s|\s\(")
# The report's own wrapper above its first section
PREAMBLE_BOILERPLATE = {"# HIGH LEVEL SUMMARY", "---"}
HAS_PLACE = re.compile(rf"(?<![A-Za-z]){PLACE_WORD}(?![a-z])", re.IGNORECASE)
PAGES = re.compile(r"(?<![A-Za-z])(?:pages?|pp?\.)\s*(\d+)(?:\s*[–-]\s*(\d+))?", re.IGNORECASE)
MORE_PAGES = re.compile(r"^\s*(?:,|and|&)\s*\d")
# Another section number after one, as in `Section 2.1 and 2.3`
MORE_SECTIONS = re.compile(r"^\s*(?:,|and|&|–)\s*(?:\d|[IVX]+\b|[A-Z](?:[\d.-]|\b))")
# `Section 2.3`, `Section IV-B1`, `Section 2.3(a)` or the range `Section 2.3–2.5`
SECTION_ID = r"[0-9A-Z](?:[\w.-]*\w)?(?:\([a-z0-9]+\))?"
SECTION = re.compile(rf"(?<![A-Za-z])Section\s+({SECTION_ID}(?:\s*–\s*{SECTION_ID})?)")
LINK_TYPES = [
    (re.compile(r"(?<![A-Za-z])(?:fig(?:ure)?s?)(?![a-z])", re.IGNORECASE), "figure"),
    (re.compile(r"(?<![A-Za-z])tables?(?![a-z])", re.IGNORECASE), "table"),
    (re.compile(r"(?<![A-Za-z])eq(?:uation)?s?(?![a-z])", re.IGNORECASE), "equation"),
    (re.compile(r"(?<![A-Za-z])appendi(?:x|ces)(?![a-z])", re.IGNORECASE), "appendix"),
    (
        re.compile(r"(?<![A-Za-z])(?:ref(?:erence)?s?\.?|bibliography)(?![a-z])", re.IGNORECASE),
        "bibliography",
    ),
]
# A quoted span: *"…"*, `"…"` or "…"; a plain or code quote may be empty ("" for a deletion)
QUOTE = r'(\*"[^"\n]+?"\*|`"[^"`\n]*?"`|"[^"\n]*?")'


def wrapped(pattern: str) -> re.Pattern[str]:
    """`pattern` with each space matching any whitespace, so a soft-wrapped line matches."""
    return re.compile(pattern.replace(" ", r"\s+"))


EDITS = [
    # Consider revising to *"R"* (or *"R2"*): new text only; the report does not say
    # exactly which text it replaces
    wrapped(
        r"[Cc]onsider (?:revising|rewriting|rephrasing|rewording|writing)"
        rf"(?: (?:it|this))?(?: to| as)? {QUOTE}(?: or {QUOTE})?"
    ),
    # "A" (and "A2") should be "B", "A" → "B", Change "A" to "B", Replace "A" with "B":
    # the last quote replaces each of the others
    wrapped(rf"{QUOTE}(?: and {QUOTE})? should (?:be|read) {QUOTE}"),
    wrapped(rf"{QUOTE} (?:\$\\rightarrow\$|→) {QUOTE}"),
    wrapped(rf"(?:[Cc]hange|[Rr]eplace) {QUOTE} (?:to|with) {QUOTE}"),
]
# A further pair right after a Change/Replace edit: `, and "C" to "D"`
# A rewrite the reviewer warns against: a negation that governs the rewrite verb, as in
# `Do not (simply) replace "A" with "B"`, `You cannot change …` or `Don’t replace …`.
# Words between the negation and the verb may only be a couple of adverbs, a
# parenthetical or a phrase set off by commas: `To avoid confusion, replace …` and
# `… is not consistent, so change …` are not negated.
NEGATION = re.compile(r"\b(?:not|never|cannot|avoid(?:ing)?)\b|n['’]t\b", re.IGNORECASE)
MAX_WORDS_BETWEEN = 2
# Where a clause can end: ; : ! ? a paragraph break or new list item (not a wrapped
# line), or a full stop before a space that does not close an abbreviation (`Sect. 2`,
# `e.g. `), allowing closing quotes or brackets between them; the stop in `2.3` is never
# followed by a space
CLAUSE_END = re.compile(r"[;:!?]|\n(?=\s*(?:\n|[-*]\s|\d+\.\s))|\.(?=[\"'”’)\]*`]*\s)")
LAST_WORD = re.compile(r"[\w.]*$")
ABBREVIATIONS = {"e.g", "i.e", "al", "ref", "refs", "sect", "sec", "eq", "eqs", "fig", "figs"}
ABBREVIATIONS |= {"tab", "vs", "cf", "no", "p", "pp", "approx"}
QUOTED = re.compile(QUOTE)


def masked(text: str) -> str:
    """`text` with quoted spans and parentheticals blanked out, keeping every offset, so
    their words and punctuation neither negate nor end a clause."""
    chars = list(text)
    for match in QUOTED.finditer(text):
        chars[match.start() : match.end()] = " " * (match.end() - match.start())
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        if depth:
            chars[index] = " "
        if char == ")" and depth:
            depth -= 1
    return "".join(chars)


def negation_reader(text: str) -> Callable[[int], bool]:
    """A test of whether a negation in the clause before an offset governs the rewrite
    there. The text is masked and its clauses and negations found once, however many
    rewrites it words."""
    plain = masked(text)
    clause_starts = [0]
    for end in CLAUSE_END.finditer(plain):
        word = LAST_WORD.search(plain[max(0, end.start() - 8) : end.start()]).group(0).lower()
        if end.group(0) != "." or word not in ABBREVIATIONS:
            clause_starts.append(end.end())
    negations = [match.span() for match in NEGATION.finditer(plain)]
    negation_ends = [end for _, end in negations]
    # Whether the words from a negation to each offset after it leave the negation near
    # enough to govern a rewrite there: commas pair up left to right into `, … ,` phrases
    # with none left over, and at most MAX_WORDS_BETWEEN words lie outside those phrases.
    # An offset answers to the last negation before it, so each stretch of text is read
    # once, and only until it has too many words for any later offset.
    near = bytearray(len(plain) + 1)
    for index, end in enumerate(negation_ends):
        following = negation_ends[index + 1] if index + 1 < len(negation_ends) else len(near)
        inside = in_word = False  # inside a `, … ,` phrase; inside a word outside one
        words = 0
        for offset in range(end, following):
            if offset > end:
                char = plain[offset - 1]
                if char == ",":
                    inside, in_word = not inside, False
                elif inside:
                    pass
                elif char.isspace():
                    in_word = False
                elif not in_word:
                    words, in_word = words + 1, True
            if words > MAX_WORDS_BETWEEN:
                break
            near[offset] = not inside

    def negated(start: int) -> bool:
        clause_start = clause_starts[bisect_right(clause_starts, start) - 1]
        last = bisect_right(negation_ends, start) - 1  # the last negation before `start`
        return last >= 0 and negations[last][0] >= clause_start and bool(near[start])

    return negated


CHAINED_EDIT = wrapped(rf",? and {QUOTE} (?:to|with) {QUOTE}")
# One `Reference Paper: Title, Authors, Year` entry; never across the `;` between entries,
# out of its parentheses or into the next entry; an entry without a year is left as text
REFERENCE_PAPER = re.compile(
    r"Reference Paper: ((?:(?!Reference Paper:)[^;()])+?), ([^,;()]+?), (\d{4})(?=\s*[;)])"
)
PAPER_QUOTE = re.compile(r'\*"([^"\n]+?)"\*')
# Wording the reviewer proposes rather than quotes: an italic quote followed (after at
# most one parenthetical) by "would be more precise", "reads better", "instead" and the like
PROPOSED_WORDING = re.compile(
    r'\*"([^"\n]+?)"\*(?:\s*\([^()]*\))?\s*'
    r"(?:(?:would|might|could) (?:be|read) (?:more \w+|clearer|better|preferable)"
    r"|reads (?:better|more \w+)|is (?:clearer|preferable)|instead\b)"
)
MIN_QUOTE_WORDS = 4
# A new place after `&` in a location, as in `Section IV-A, Page 2 & Section IV-B2, Page 4`
NEXT_PLACE = re.compile(r"\s+(?:Section|Page|Appendix|Table|Figure)\b")
LEADING_JOIN = re.compile(r"^(?:&|and)\s+")


def unquote(token: str) -> str:
    return token.strip("*`")[1:-1]


# Parsing the report


def fenced_lines(text: str) -> set[int]:
    """Where each line inside a fenced code block outside lists starts in `text` (a fence
    in a list item cannot hide a heading)."""
    fences, starts, offset = Fences(lists=True), set(), 0
    for line in text.splitlines(keepends=True):
        if fences.inside(line):
            starts.add(offset)
        offset += len(line)
    return starts


def split_sections(text: str, level: int) -> list[tuple[str | None, str]]:
    """(heading, body) for each heading of exactly `level` #s; text before the first has None.
    A heading inside a fenced code block is part of the code."""
    marker = re.compile(rf"^{'#' * level} (?!#)(.*)$", re.MULTILINE)
    fenced = fenced_lines(text)
    parts, heading, start = [], None, 0
    for match in marker.finditer(text):
        if match.start() in fenced:
            continue
        parts.append((heading, text[start : match.start()]))
        heading, start = match.group(1).strip(), match.end()
    parts.append((heading, text[start:]))
    return parts


def lazy_continuation(line: str, item: Fences) -> bool:
    """Whether `line`, unindented, lazily continues the paragraph its item ends with: it
    comes straight after the item's paragraph text (not after a blank line or code) and
    starts no block. `item` has read the item's lines as written, marker and all."""
    if not line.strip() or BLOCK_START.match(line) or FENCE.match(line):
        return False
    if THEMATIC_BREAK.match(line):
        return False
    return item.paragraph and item.open is None


def split_items(body: str) -> tuple[list[str], str]:
    """The list items in `body`, each without its marker and dedented, and any other text."""
    items: list[list[str]] = []
    other: list[str] = []
    in_item = False
    item_indent = 0  # where the open item's content starts
    # The open item's lines, read as written (its own marker included) as they come, so
    # whether a line lazily continues it is known without reading it again
    item_fences = Fences(lists=True)
    for line in body.splitlines():
        if line.strip() == "---":
            # Dropped as before, but one indented less than the item's content ends it
            # (unless it is a line of the item's code), and one inside it ends its
            # paragraph, so no lazy line follows
            held = in_item and item_fences.holds(line)
            if len(line) - len(line.lstrip(" ")) < item_indent and not held:
                in_item = False
            elif in_item:
                item_fences.inside(line)
            continue
        # A thematic break (`- - -`, `* * *`) is no item, as the fence tracker reads it
        brk = THEMATIC_BREAK.match(line)
        start = None if brk else ITEM_START.match(line)
        # A break indented less than the item's content ends the item, unless it is a line
        # of the item's code
        outdented = (
            brk
            and len(line) - len(line.lstrip(" ")) < item_indent
            and not (in_item and item_fences.holds(line))
        )
        if start:
            items.append([start.group(1)])
            in_item, item_indent = True, start.start(1)
            item_fences = Fences(lists=True)
            item_fences.inside(line)
        elif in_item and not outdented and (not line.strip() or line.startswith((" ", "\t"))):
            items[-1].append(line)
            item_fences.inside(line)
        elif in_item and lazy_continuation(line, item_fences):
            # A soft-wrapped line straight after the item's text stays in the item, as the
            # fence tracker reads it
            items[-1].append(line)
            item_fences.inside(line)
        elif line.strip():
            # Other text ends the item: lines after it are not the item's
            other.append(line)
            in_item = False
    texts = []
    for lines in items:
        rest = lines[1:]
        indents = [len(line) - len(line.lstrip()) for line in rest if line.strip()]
        cut = min(indents, default=0)
        texts.append("\n".join([lines[0], *(line[cut:] for line in rest)]).strip())
    return texts, "\n".join(other).strip()


def trailing_parenthetical(head: str) -> tuple[str, str] | None:
    """(head before it, its contents) when `head` ends in a balanced parenthetical."""
    if not head.endswith(")"):
        return None
    depth = 0
    for index in range(len(head) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(head[index], 0)
        if depth == 0:
            return head[:index].rstrip(), head[index + 1 : -1].strip()
    return None


def parse_item(item: str) -> dict[str, str]:
    """A point's title, location and text, as the report writes them."""
    bold = BOLD_HEAD.match(item)
    if not bold:
        return {"text": item}
    head, text = bold.group(1).strip().rstrip(":").strip(), bold.group(2).strip()
    parsed: dict[str, str] = {}
    if PLACES_ONLY.match(FIRST_PART.split(head, maxsplit=1)[0]):
        parsed["location"] = head
    else:
        split = trailing_parenthetical(head)
        if split and HAS_PLACE.search(split[1]):
            parsed["title"], parsed["location"] = split
        else:
            parsed["title"] = head
    parsed["text"] = text
    return parsed


def parse_point(item: str) -> dict[str, str]:
    """A Strengths or Weaknesses bullet: `**Title:** text`, or just text."""
    bold = BOLD_HEAD.match(item)
    if bold and bold.group(2).strip():
        return {"title": bold.group(1).strip().rstrip(":").strip(), "text": bold.group(2).strip()}
    return {"text": item}


def parse_tier(heading: str | None, body: str) -> dict[str, Any] | None:
    """One tier of points, such as Minor Corrections and Typos; text above the first
    tier is kept as a tier with no heading."""
    items, rest = split_items(body)
    if heading is None:
        return {"heading": "", "items": [], "text": body.strip()} if items or rest else None
    tier: dict[str, Any] = {"heading": heading, "items": [parse_item(item) for item in items]}
    if rest:
        tier["text"] = rest
    return tier


def parse_issues(body: str, other: dict[str, str]) -> list[dict[str, Any]]:
    """The parts of Potential Issues And Suggestions, each with its tiers of points."""
    issues = []
    for part, part_body in split_sections(body, 3):
        if part is None:
            if part_body.strip(" \n-"):
                keep(other, ISSUES_HEADING, part_body.strip())
            continue
        tiers = [parse_tier(*section) for section in split_sections(part_body, 4)]
        issues.append({"heading": part, "tiers": [tier for tier in tiers if tier]})
    return issues


def keep(other: dict[str, str], heading: str, text: str) -> None:
    """Keep text the mapper has no field for, adding to any already kept under `heading`."""
    if text:
        other[heading] = f"{other[heading]}\n\n{text}" if heading in other else text


def parse_report(markdown: str) -> dict[str, Any]:
    """The report in its own structure (see the module docstring). A section that appears
    more than once adds to the first."""
    report: dict[str, Any] = {}
    other: dict[str, str] = {}
    for heading, body in split_sections(markdown, 2):
        if heading is None:
            lines = [line.strip() for line in body.splitlines()]
            preamble = [line for line in lines if line and line not in PREAMBLE_BOILERPLATE]
            keep(other, "preamble", "\n".join(preamble))
        elif heading == "Summary":
            summary = body.strip()
            report["summary"] = (
                f"{report['summary']}\n\n{summary}" if "summary" in report else summary
            )
        elif heading in ("Strengths", "Weaknesses"):
            items, rest = split_items(body)
            report.setdefault(SECTIONS[heading], []).extend(parse_point(item) for item in items)
            keep(other, heading, rest)
        elif heading == ISSUES_HEADING:
            report.setdefault("issues", []).extend(parse_issues(body, other))
        else:
            keep(other, heading, body.strip())
    if other:
        report["other"] = other
    return report


# Mapping


def split_places(location: str) -> list[str]:
    """The places in a location, split at `;`, and at `&` when a new place follows it;
    never inside parentheses."""
    places, depth, start = [], 0, 0
    for index, char in enumerate(location):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and (char == ";" or (char == "&" and NEXT_PLACE.match(location, index + 1))):
            places.append(location[start:index])
            start = index + 1
    places.append(location[start:])
    return places


def location_link(place: str, source: str, target: str, recorder: Recorder) -> dict[str, Any]:
    """One evidence link for one place, such as `Section 1.3, Pages 4–5`."""
    link: dict[str, Any] = {"type": "paper_section", "ref": place}
    if not SECTION.search(place):
        for pattern, kind in LINK_TYPES:
            if pattern.search(place):
                link["type"] = recorder.parse(source, f"{target}.type", place, kind)
                break
    location: dict[str, Any] = {}
    pages = list(PAGES.finditer(place))
    if len(pages) == 1 and not MORE_PAGES.match(place[pages[0].end() :]):
        first, last = int(pages[0].group(1)), pages[0].group(2)
        location["page"] = recorder.parse(source, f"{target}.location.page", place, first)
        if last and int(last) > first:
            location["page_end"] = recorder.parse(
                source, f"{target}.location.page_end", place, int(last)
            )
    sections = [
        match.group(1)
        for match in SECTION.finditer(place)
        for _ in range(2 if MORE_SECTIONS.match(place[match.end() :]) else 1)
    ]
    if len(sections) == 1:
        location["section"] = recorder.parse(
            source, f"{target}.location.section", place, sections[0]
        )
    elif re.match(r"^Abstract\b", place):
        location["section"] = recorder.parse(
            source, f"{target}.location.section", place, "Abstract"
        )
    if location:
        link["location"] = location
    return link


def edit_phrases(text: str):
    """(original or None, replacement, phrase, negated, replacement span) for each rewrite
    the text words; a chained pair shares its Change/Replace verb's negation."""
    negated = negation_reader(text)
    for pattern_index, pattern in enumerate(EDITS):
        for match in pattern.finditer(text):
            is_negated = negated(match.start())
            matches = [match]
            while pattern is EDITS[-1] and (chained := CHAINED_EDIT.match(text, matches[-1].end())):
                matches.append(chained)
            for phrase in matches:
                groups = [index for index, token in enumerate(phrase.groups(), 1) if token]
                if pattern_index == 0:
                    pairs = [(None, index) for index in groups]
                else:
                    pairs = [(unquote(phrase.group(index)), groups[-1]) for index in groups[:-1]]
                for original, index in pairs:
                    replacement = unquote(phrase.group(index))
                    yield original, replacement, phrase.group(0), is_negated, phrase.span(index)
    for match in PROPOSED_WORDING.finditer(text):
        is_negated = negated(match.start())
        yield None, match.group(1), match.group(0), is_negated, match.span(1)


def suggested_edits(text: str, source: str, target: str, recorder: Recorder) -> list[dict]:
    """The rewrites the point proposes; rewrites it warns against are left in its text."""
    edits: list[dict[str, str]] = []
    for original, replacement, phrase, is_negated, _ in edit_phrases(text):
        if is_negated:
            continue
        edit = {"replacement": replacement}
        if original:
            edit = {"original": original, **edit}
        if edit not in edits:
            edit_target = f"{target}.suggested_edits[{len(edits)}]"
            edits.append(recorder.parse(source, edit_target, phrase, edit))
    return edits


def paper_quotes(text: str) -> list[str]:
    """Passages the point quotes from the paper: italic quotes, except where the quote is
    replacement wording, whether the point proposes it or warns against it."""
    spans = [span for *_, span in edit_phrases(text)]
    quotes = []
    for match in PAPER_QUOTE.finditer(text):
        quote = match.group(1)
        is_replacement = any(start < match.end() and match.start() < end for start, end in spans)
        if is_replacement or quote in quotes or len(quote.split()) < MIN_QUOTE_WORDS:
            continue
        quotes.append(quote)
    return quotes


def map_issue(
    item: dict[str, str],
    source: str,
    target: str,
    group: list[str],
    point_id: str,
    recorder: Recorder,
    blocks: list[Block] | None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {"id": point_id}
    if item.get("title"):
        finding["title"] = recorder.copy(f"{source}.title", f"{target}.title", item["title"])
    finding["text"] = recorder.copy(f"{source}.text", f"{target}.text", item["text"])
    finding["group"] = group
    links = []
    if item.get("location"):
        for place in split_places(item["location"]):
            place = LEADING_JOIN.sub("", place.strip().rstrip(",").rstrip())
            if place:
                link_target = f"{target}.evidence_links[{len(links)}]"
                recorder.parse(f"{source}.location", f"{link_target}.ref", item["location"], place)
                links.append(location_link(place, f"{source}.location", link_target, recorder))
    edits = suggested_edits(item["text"], f"{source}.text", target, recorder)
    for quote in paper_quotes(item["text"]):
        link_target = f"{target}.evidence_links[{len(links)}]"
        recorder.parse(f"{source}.text", f"{link_target}.quote", quote, quote)
        recorder.anchor(f"{source}.text", link_target, quote, blocks)
        links.append({"type": "paper_section", "ref": "", "quote": quote})
    links += cited_works(item["text"], f"{source}.text", target, recorder, len(links))
    if links:
        finding["evidence_links"] = links
    if edits:
        finding["suggested_edits"] = edits
    return finding


def cited_works(text: str, source: str, target: str, recorder: Recorder, start: int) -> list:
    """External evidence links for the works the point says the paper should cite."""
    links = []
    for match in REFERENCE_PAPER.finditer(text):
        title, authors, year = match.groups()
        work = {"title": title.strip(), "authors": [authors.strip()], "year": int(year)}
        link_target = f"{target}.evidence_links[{start + len(links)}]"
        recorder.parse(source, f"{link_target}.work", match.group(0), work)
        links.append({"type": "external", "ref": match.group(0), "work": work})
    return links


def map_point(point: dict[str, str], source: str, target: str, recorder: Recorder) -> dict:
    finding: dict[str, Any] = {}
    if point.get("title"):
        finding["title"] = recorder.copy(f"{source}.title", f"{target}.title", point["title"])
    finding["text"] = recorder.copy(f"{source}.text", f"{target}.text", point["text"])
    links = cited_works(point["text"], f"{source}.text", target, recorder, 0)
    if links:
        finding["evidence_links"] = links
    return finding


def map_tier(
    part: dict[str, Any],
    part_index: int,
    tier_index: int,
    weaknesses: list[dict[str, Any]],
    recorder: Recorder,
    blocks: list[Block] | None,
) -> None:
    """Add one tier's points to `weaknesses`."""
    part_source = f"issues[{part_index}]"
    tier_source = f"{part_source}.tiers[{tier_index}]"
    tier = part["tiers"][tier_index]
    for item_index, item in enumerate(tier["items"]):
        source = f"{tier_source}.items[{item_index}]"
        if not item.get("text"):
            recorder.skip(source, "no text")
            continue
        target = f"findings.weaknesses[{len(weaknesses)}]"
        group = [recorder.copy(f"{part_source}.heading", f"{target}.group[0]", part["heading"])]
        group.append(recorder.copy(f"{tier_source}.heading", f"{target}.group[1]", tier["heading"]))
        point_id = f"issue-{part_index + 1}.{tier_index + 1}.{item_index + 1}"
        finding = map_issue(item, source, target, group, point_id, recorder, blocks)
        severity = recorder.lookup(
            f"{tier_source}.heading", f"{target}.severity", tier["heading"], TIER_SEVERITY
        )
        if severity:
            finding["severity"] = severity
        weaknesses.append(finding)


def map_deepreview(
    output: str, review: dict[str, Any], blocks: list[Block] | None
) -> MappingResult:
    """Fills `review`, the envelope map_with_record built, from DeepReview's Markdown report."""
    if not isinstance(output, str):
        raise TypeError("DeepReview output is the report's Markdown text")
    report = parse_report(output)
    recorder = Recorder(checks_quotes=blocks is not None)
    if report.get("summary"):
        summary = recorder.copy("summary", "opinion.summary", report["summary"])
        review["opinion"]["summary"] = summary
    strengths = [
        {"id": f"strength-{index + 1}"}
        | map_point(point, f"strengths[{index}]", f"findings.strengths[{index}]", recorder)
        for index, point in enumerate(report.get("strengths", []))
    ]
    weaknesses = [
        {"id": f"weakness-{index + 1}"}
        | map_point(point, f"weaknesses[{index}]", f"findings.weaknesses[{index}]", recorder)
        | {"summarizes": []}
        for index, point in enumerate(report.get("weaknesses", []))
    ]
    for part_index, part in enumerate(report.get("issues", [])):
        for tier_index, tier in enumerate(part["tiers"]):
            if tier["heading"]:
                map_tier(part, part_index, tier_index, weaknesses, recorder, blocks)
    findings = {"strengths": strengths, "weaknesses": weaknesses}
    findings = {kind: points for kind, points in findings.items() if points}
    if findings:
        review["findings"] = findings
    result = finish(review, recorder, report, ignored=set())
    keep_skipped_points(result.review, report.get("issues", []))
    return result


def keep_skipped_points(review: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    """Keep each point skipped for having no text with its empty text, even a bare one that
    left nothing else, so `to_deepreview` writes it back in its place and the points after
    it keep their IDs."""
    for p, part in enumerate(issues):
        for t, tier in enumerate(part["tiers"]):
            for i, item in enumerate(tier["items"]):
                if tier["heading"] and not item.get("text"):
                    kept = review.setdefault("extensions", {}).setdefault("deepreview", {})
                    kept_part = slot(kept, "issues", p, len(issues))
                    kept_tier = slot(kept_part, "tiers", t, len(part["tiers"]))
                    slot(kept_tier, "items", i, len(tier["items"]))["text"] = ""


def slot(parent: dict[str, Any], key: str, index: int, length: int) -> dict[str, Any]:
    """The dict at `parent[key][index]`, making the list (as long as the report's) and the
    dict when the mapper kept nothing there."""
    items = parent.setdefault(key, [None] * length)
    if not isinstance(items[index], dict):
        items[index] = {}
    return items[index]


# OCRS → DeepReview

BOILERPLATE = "# HIGH LEVEL SUMMARY\n---"
ISSUE_ID = re.compile(r"^issue-(\d+)\.(\d+)\.(\d+)$")
GENERAL_PART = "[General]"
SEVERITY_TIER = {
    "critical": "Potential Mistakes and Improvements",
    "major": "Potential Mistakes and Improvements",
    "minor": "Minor Corrections and Typos",
    "info": "Minor Corrections and Typos",
}
NUMBERED_TIERS = {"Potential Mistakes and Improvements"}
# OCRS findings DeepReview has no section for, each written under a heading of its own
EXTRA_FINDINGS = {"questions": "Questions", "changes": "Requested Changes", "comments": "Comments"}
LIST_MARKER = re.compile(r"^(?:\d+\.|[-*])\s")
SECTION_HEADING = re.compile(r"^## (?!#)", re.MULTILINE)


def demoted(text: str) -> str:
    """`text` with its own `##` headings made `###`, outside fenced code (read as the
    parser reads it), so free text from another review (Markdown too, often) does not
    start sections of the report."""
    fences = Fences(lists=True)
    return "\n".join(
        line if fences.inside(line) else SECTION_HEADING.sub("### ", line)
        for line in text.split("\n")
    )


def write_item(marker: str, head: str | None, text: str) -> str:
    """A list item: `**head:** text`, or just text. The text starts on the next line when
    starting it on the marker's line would change how the report reads back: when it
    begins with a list or a code fence, when the marker's line would be a thematic break,
    or when all its later lines are indented (the parser takes the indentation they share
    as the list's)."""
    pad = " " * (len(marker) + 1)
    later = [line for line in text.split("\n")[1:] if line.strip()]
    first = text.split("\n")[0].rstrip("\r")
    own_line = (
        LIST_MARKER.match(text)
        or FENCE.match(first)
        # `* ***` or `* **` would be a thematic break, not an item
        or THEMATIC_BREAK.match(f"{marker} {first}")
        or (later and all(line[0] in " \t" for line in later))
    )
    # A heading the reviewer wrapped keeps its later lines indented under the marker
    head = indented(head, pad) if head else head
    if not head:
        # An item may start empty; the marker's trailing space keeps it an item
        return (
            f"{marker} \n{pad}{indented(text, pad)}"
            if own_line
            else f"{marker} {indented(text, pad)}"
        )
    if own_line:
        return f"{marker} **{head}:**\n{pad}{indented(text, pad)}"
    return f"{marker} **{head}:** {indented(text, pad)}".rstrip()


def places(point: dict[str, Any]) -> str:
    """The point's location as the report writes it: its places, `;`-separated."""
    refs = [
        link["ref"]
        for link in point.get("evidence_links") or []
        if link.get("ref") and not link.get("quote") and link.get("type") != "external"
    ]
    return "; ".join(refs)


def read_places(location: str) -> list[str]:
    """The places the mapper reads out of a location, as `map_issue` splits them."""
    places = (LEADING_JOIN.sub("", p.strip().rstrip(",").rstrip()) for p in split_places(location))
    return [place for place in places if place]


def issue_head(point: dict[str, Any]) -> str | None:
    """The point's bold heading: its title, then its places in parentheses. Places alone
    are written bare when they read back as the same places (`Page 14, Figure 1(a)
    caption`), else in parentheses (`(Page 2; Figure 1)`), which read back as places with
    no title."""
    title, location = point.get("title"), places(point)
    if title and location:
        return f"{title} ({location})"
    if location:
        return places_head(location)
    return title or None


def places_head(location: str) -> str:
    """A heading of places alone: bare when it reads back as the same places, else in
    parentheses, which read back as places with no title."""
    bare = parse_item(f"**{location}:** x")
    if "title" not in bare and read_places(bare.get("location", "")) == read_places(location):
        return location
    return f"({location})"


def is_issue(point: dict[str, Any]) -> bool:
    """Whether a weakness is a point under Potential Issues rather than in Weaknesses."""
    group = point.get("group") or []
    return len(group) >= 2 or (bool(point.get("severity")) and "summarizes" not in point)


def place_issues(points: list[dict[str, Any]], kept: list[Any]) -> dict[int, dict[str, Any]]:
    """Parts by index, each with its tiers by index, each with its items by index.

    A point the mapper made has an ID `issue-<part>.<tier>.<item>` that says where it was,
    and what the mapper kept goes back where it was too. Only then does any other point
    go to the part and tier its group names (or its severity's tier under General), after
    what is there, so it never takes a place the report's own points had.
    """
    parts: dict[int, dict[str, Any]] = {}

    def by_heading(found: dict[int, dict[str, Any]], heading: str, new: dict) -> int:
        index = next((i for i, x in found.items() if x.get("heading") == heading), None)
        if index is None:
            index = max(found, default=-1) + 1
            found[index] = new
        return index

    def headings(point: dict[str, Any]) -> tuple[str, str]:
        group = point.get("group") or []
        part = group[0] if group else GENERAL_PART
        return part, group[1] if len(group) > 1 else SEVERITY_TIER[point["severity"]]

    placed = [(point, ISSUE_ID.match(point.get("id", ""))) for point in points]
    for point, place in placed:
        if place:
            part_heading, tier_heading = headings(point)
            p, t, i = (int(n) - 1 for n in place.groups())
            part = parts.setdefault(p, {"heading": part_heading, "tiers": {}})
            tier = part["tiers"].setdefault(t, {"heading": tier_heading, "items": {}})
            tier["items"][i] = {"head": issue_head(point), "text": point["text"]}
    overlay_kept_issues(parts, kept)
    for point, place in placed:
        if not place:
            part_heading, tier_heading = headings(point)
            p = by_heading(parts, part_heading, {"heading": part_heading, "tiers": {}})
            tiers = parts[p]["tiers"]
            t = by_heading(tiers, tier_heading, {"heading": tier_heading, "items": {}})
            items = tiers[t]["items"]
            items[max(items, default=-1) + 1] = {"head": issue_head(point), "text": point["text"]}
    return parts


def overlay_kept_issues(parts: dict[int, dict[str, Any]], kept: list[Any]) -> None:
    """Put back what the mapper kept of each part: headings of parts and tiers with no
    mapped point, text outside the points, and points it skipped for having no text."""
    for p, kept_part in enumerate(kept):
        if not isinstance(kept_part, dict):
            continue
        part = parts.setdefault(p, {"heading": "", "tiers": {}})
        part["heading"] = kept_part.get("heading", part["heading"])
        for t, kept_tier in enumerate(kept_part.get("tiers") or []):
            if not isinstance(kept_tier, dict):
                continue
            tier = part["tiers"].setdefault(t, {"heading": "", "items": {}})
            tier["heading"] = kept_tier.get("heading", tier["heading"])
            if kept_tier.get("text"):
                tier["text"] = kept_tier["text"]
            for i, kept_item in enumerate(kept_tier.get("items") or []):
                if isinstance(kept_item, dict) and i not in tier["items"]:
                    title, location = kept_item.get("title"), kept_item.get("location")
                    # Places alone go in parentheses when written bare they would read
                    # back as a title (`**(Page 2; Figure 1):**`)
                    head = title or (places_head(location) if location else None)
                    if title and location:
                        head = f"{title} ({location})"
                    tier["items"][i] = {"head": head, "text": kept_item.get("text", "")}


def write_issues(parts: dict[int, dict[str, Any]], preamble: str | None) -> str:
    lines = [f"## {ISSUES_HEADING}"]
    if preamble:
        lines.append(preamble)
    for p in sorted(parts):
        part = parts[p]
        lines.append(f"### {part['heading']}")
        for t in sorted(part["tiers"]):
            tier = part["tiers"][t]
            if tier["heading"]:
                lines.append(f"#### {tier['heading']}\n")
            if tier.get("text"):
                lines.append(f"{tier['text']}\n")
            numbered = tier["heading"] in NUMBERED_TIERS
            items = [
                write_item(f"{n}." if numbered else "*", item["head"], item["text"])
                for n, item in enumerate((tier["items"][i] for i in sorted(tier["items"])), 1)
            ]
            if items:
                lines.append("\n\n".join(items) + "\n")
    # Only newlines: an empty point's marker keeps its trailing space, or it is no point
    return "\n".join(lines).rstrip("\n")


def write_points(points: list[dict[str, Any]]) -> str:
    return "\n".join(write_item("*", point.get("title"), point["text"]) for point in points)


def to_deepreview(canonical: dict[str, Any]) -> str:
    """An OCRS review as DeepReview's Markdown report.

    The review's summary (or, without one, its full text) is the Summary; strengths and
    weaknesses are the Strengths and Weaknesses, a point's title its bold heading. A
    weakness whose group names a part and a tier, or that has a severity and is not an
    overview, is a point under Potential Issues And Suggestions, its places written back
    after its title: critical and major points as Potential Mistakes and Improvements,
    minor and info as Minor Corrections and Typos, under a General part when its group
    names none. Contributions, questions, requested changes, comments, the full text when
    there is also a summary, and checks, which DeepReview does not report, are written
    under headings of their own, so a reader still sees them (the mapper keeps them in
    `extensions.deepreview`). Scores, the decision, severities beyond the tier's and text
    for the editors only are left out.
    """
    kept = extension(canonical, "deepreview")
    other: dict[str, str] = dict(kept.get("other") or {})
    opinion = canonical.get("opinion") or {}
    # The wrapper and the text above the first section stay first; a fence the text leaves
    # open is closed when sections follow, or it would swallow them
    head = [BOILERPLATE]
    if other.get("preamble"):
        head.append(other.pop("preamble"))
    sections: list[str] = []
    summary, text = overall_texts(canonical)
    if summary or text:
        sections.append(f"## Summary\n{demoted(summary or text)}")
    for kind, heading in (("strengths", "Strengths"), ("weaknesses", "Weaknesses")):
        points = [p for p in findings_of(canonical, kind) if kind == "strengths" or not is_issue(p)]
        rest = other.pop(heading, None)
        if points or rest:
            # The text kept beside the points comes only from a DeepReview report, whose
            # item splitter reads no fences, so it keeps its place; a fence it leaves open
            # is contained by the section going last
            body = "\n\n".join(part for part in (rest, write_points(points)) if part)
            sections.append(f"## {heading}\n{body}")
    issues = [p for p in findings_of(canonical, "weaknesses") if is_issue(p)]
    parts = place_issues(issues, kept.get("issues") or [])
    issues_preamble = other.pop(ISSUES_HEADING, None)
    if parts or issues_preamble:
        sections.append(write_issues(parts, issues_preamble))
    if summary and text:
        add_section(other, "Review", text)
    contributions = [c for c in opinion.get("contributions") or [] if c.get("text")]
    if contributions:
        add_section(other, "Contributions", write_points(contributions))
    for kind, heading in EXTRA_FINDINGS.items():
        if findings_of(canonical, kind):
            add_section(other, heading, write_points(findings_of(canonical, kind)))
    for check in canonical.get("checks") or []:
        if text := check_text(check):
            add_section(other, check.get("label") or check["kind"], text)
    sections += [f"## {heading}\n{demoted(text)}" for heading, text in other.items()]
    # A section that leaves a code fence open goes last, where it swallows no other
    if sections:
        head[-1] = close_fence(head[-1])  # the text above the first section, or the wrapper
        head.append(join_blocks(sections))
    return "\n\n".join(head) + "\n"
