# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Reviewer3 report (Markdown) → OCRS.

Reviewer3 exports its report as Markdown:

    # Review Report
    <the paper's title>                 → target.title
    ### Overview                        → opinion.contributions
    ### AI Text Detection               → checks[]: ai_text_detection
    ### Fatal Flaws                     → checks[]: fatal_flaw_screen
    ### Reference Check                 → checks[]: reference_verification
    ### Reviewer Comments               → findings.comments

The mapper first parses the report into the export's own structure, and the paths
in the mapping record name places in it:

    title, overview[i].{title, text}, ai_text_detection,
    fatal_flaws.{text, items[i].{title, text}},
    reference_check.{summary, entries[i].{number, citation, status}, text},
    comments[i].{number, title, page, page_end, excerpt, text},
    other.<heading>, other.preamble (text above the first section, other than the
    report's wrapper and title)

Overview bullets (`**Title** — text`) are what the reviewer reads the paper as
contributing; they make no judgment, so they are contributions, not strengths.

The three checks keep the report's own sentence as their `summary`. A check gets an
`outcome` only when the report states one: "No fatal methodological flaws were
identified" is `no_issues`, and fatal flaws listed as points are `issues_found`,
each a `critical` weakness the check names in `finding_ids`. The AI-text and
reference checks report numbers without a verdict, so they get none. Percentages
become `measurements` as 0–1 fractions (33% → 0.33), the detector named in the
sentence ("the full Pangram report") becomes `performed_by`, and the reference
counts become integer measurements. Each row of the reference table becomes an
item with the entry's number and citation as printed and its status in the
report's words. An entry is `flagged` when its status says it failed ("Not Found",
"Unverified") and not flagged when it says it passed ("Verified (DOI)"); a status
that says neither ("Pending") gets no `flagged`, rather than a guess. "Not Found"
does not mean the reference is wrong.

Reviewer Comments are numbered points: `N. **Title**`, optionally `— Page N`, an
optional excerpt of the paper as a blockquote, then the explanation. The report
does not say whether a comment is a weakness, a question or a remark, so comments
go in `findings.comments`, with no severity. A comment's page and excerpt give
one evidence link: a quote with its page, or, when the excerpt is only a label
such as `Fig 3`, a link to that figure. Places the explanation names only in its
prose are not parsed.

The report is Markdown with TeX, so the review's `text_format` says so. All
values read by a pattern are recorded as `parsed` steps.

`to_reviewer3` writes an OCRS review back as such a report (see its docstring).
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from typing import Any

from ..anchors import Block
from ..mapping import MappingResult
from .ai import (
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
    open_fence,
    overall_texts,
)

MAPPER_VERSION = "1.1.0"
TEXT_FORMAT = {"markup": "markdown", "math": "tex"}
# OCRS requires a check to say something: one of these
CHECK_CONTENT = {"summary", "outcome", "measurements", "items"}
COMMENTS_GROUP = "Reviewer Comments"
FATAL_SEVERITY = {"Fatal Flaws": "critical"}
SECTIONS = {
    "Overview": "overview",
    "AI Text Detection": "ai_text_detection",
    "Fatal Flaws": "fatal_flaws",
    "Reference Check": "reference_check",
    "Reviewer Comments": "comments",
}
WRAPPER = {"# Review Report", "---"}

SECTION = re.compile(r"^### (?!#)(.*)$", re.MULTILINE)
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
# A list marker may sit up to three spaces in (CommonMark); deeper markers are nested items
# A line that starts a block of its own, so it never lazily continues a point: a blockquote,
# a heading, a thematic break or an ordered list item
NEW_BLOCK = re.compile(r"^ {0,3}(?:>|#{1,6}(?:\s|$)|(?:[-*_]\s*){3,}$|\d{1,9}[.)](?:\s|$))")
TOP_BULLET = re.compile(r"^( {0,3})([-*]\s+)(.*)$")
TITLED = re.compile(r"^\*\*(.+?)\*\*\s*(?:[—–:]|\s-)?\s*(.*)$", re.DOTALL)
# The page suffix takes its own leading spaces, so no run of spaces can be split two ways
COMMENT_START = re.compile(
    r"^( {0,3})(\d+)\.\s+\*\*(.+?)\*\*(?:\s*[—–-]\s*Pages?\s+(\d+)(?:\s*[–-]\s*(\d+))?)?\s*$"
)
# The excerpt is a label, not the paper's text: `Fig 3`, `Figure 2(b)`, `Table 1`, `Eq. (4)`
LABEL_TYPES = [
    (re.compile(r"^fig(?:ure)?s?\.?\s*\(?\d+[a-z]?\)?(?:\([a-z]\))?$", re.IGNORECASE), "figure"),
    (re.compile(r"^tables?\.?\s*\(?[\dIVX]+[a-z]?\)?$", re.IGNORECASE), "table"),
    (re.compile(r"^eq(?:uation)?s?\.?\s*\(?\d+[a-z]?\)?$", re.IGNORECASE), "equation"),
]
# A number starts where its digits do, not partway along a run that failed to match
PERCENT = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*%\s+([A-Za-z][\w-]*)")
DETECTOR = re.compile(r"\bfull ([A-Z][\w.-]*(?: [A-Z][\w.-]*)*) report\b")
NO_FATAL = re.compile(r"^No fatal\b[^.]*\b(?:identified|found|detected)\b", re.IGNORECASE)
CHECKED = re.compile(r"\bChecked\s+(\d+)\s+references?\b", re.IGNORECASE)
# A label's words own the spaces between them, and the spaces after it are the separator's
COUNT = re.compile(r"(?<!\d)(\d+)\s+([a-z]+(?: +[a-z]+)*)\s*(?=[,.;]|$)")
# The .docx renders a reference row as `#12 — Citation: … — Status: Not Found`
ENTRY_LINE = re.compile(r"^#(\d+)\s*[—–-]\s*Citation:\s*(.+?)\s*[—–-]\s*Status:\s*(.+)$")
# A status's verdict. A problem it rules out ("No errors", "No mismatch") reads as passing;
# then failure phrases are checked before passing words, so "Not Found" is never "Found"
PROBLEM = r"(?:errors?|mismatch(?:es)?|issues?|problems?|discrepanc(?:y|ies))"
# The whole ruled-out list: "no errors or mismatches", "without errors, issues and problems"
NEGATED_PROBLEM = re.compile(
    rf"\b(?:no|without|zero)\s+{PROBLEM}(?:\s*(?:,|/|\bor\b|\band\b|\bnor\b)\s*{PROBLEM})*\b",
    re.IGNORECASE,
)
# A problem the status says was dealt with: "Mismatch resolved" (but "not resolved" fails)
RESOLVED_PROBLEM = re.compile(
    rf"\b{PROBLEM}\s+(?:(?:was|were|has been|have been)\s+)?(?:resolved|fixed|corrected|cleared)\b",
    re.IGNORECASE,
)
FAILED_STATUS = re.compile(
    r"\b(?:not\s+(?:found|verified|matched|resolved|available)|no\s+(?:match|record|result)s?|"
    r"unverified|unresolved|unmatched|missing|fail(?:ed|s|ure)?|errors?|mismatch(?:ed|es)?|"
    r"invalid|retracted|broken)\b",
    re.IGNORECASE,
)
PASSED_STATUS = re.compile(
    r"\b(?:verified|found|ok|matched|valid|confirmed|resolved)\b", re.IGNORECASE
)


def status_flag(status: str) -> bool | None:
    """True when the status says the check failed, False when it says it passed, and None
    when it says neither."""
    cleared = RESOLVED_PROBLEM.sub(" ok ", NEGATED_PROBLEM.sub(" ok ", status))
    if FAILED_STATUS.search(cleared):
        return True
    if PASSED_STATUS.search(cleared):
        return False
    return None


UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
TABLE_FIELDS = {"#": "number", "citation": "citation", "status": "status"}
BLOCKQUOTE = re.compile(r"^\s*> ?")
EMPHASIS = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")


def trim_blank_lines(lines: list[str]) -> str:
    """`lines` joined, without blank lines at either end; indentation and trailing spaces
    (a Markdown hard break) are kept."""
    start = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
    end = next((i for i in range(len(lines), 0, -1) if lines[i - 1].strip()), start)
    return "\n".join(lines[start:end])


def prose_paragraphs(text: str) -> list[str]:
    """The paragraphs of `text` outside fenced code, each stripped."""
    paragraphs: list[list[str]] = [[]]
    fences = Fences(lists=True)
    for line in text.splitlines():
        if fences.inside(line) or not line.strip():
            paragraphs.append([])
        else:
            paragraphs[-1].append(line.strip())
    return [" ".join(lines) for lines in paragraphs if lines]


def plain(text: str) -> str:
    """`text` without bold markers, which the report puts on counts and statuses."""
    return EMPHASIS.sub(lambda m: m.group(1) or m.group(2), text).strip()


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")


# Parsing the report


class CommentReader(Fences):
    """Reads Reviewer Comments line by line as parse_comments does: a header at the list's
    own indentation, outside code, starts a comment, and its explanation is read for code
    afresh (the header is no list item); a deeper numbered line is part of the explanation.
    """

    def __init__(self) -> None:
        super().__init__(lists=True)
        self.list_indent: int | None = None
        self.code = False  # whether the last line read was code

    def read(self, line: str) -> re.Match[str] | None:
        """Take in `line`; the header's match when it starts a comment, else None."""
        self.code = self.inside(line)
        start = None if self.code else COMMENT_START.match(line)
        if start and self.list_indent is not None and len(start.group(1)) > self.list_indent:
            start = None
        if start:
            if self.list_indent is None:
                self.list_indent = len(start.group(1))
            self.open, self.items, self.depth, self.paragraph = None, [], 0, False
        return start

    @property
    def open_at_margin(self) -> bool:
        """Whether a fence is open outside any list."""
        return self.open is not None and self.depth == 0


def split_sections(markdown: str) -> list[tuple[str | None, str]]:
    """(heading, body) for each `###` section; text before the first has None. A heading
    inside a fenced code block is part of the code."""
    parts: list[tuple[str | None, str]] = []
    heading: str | None = None
    lines: list[str] = []
    # A fence in a list item cannot hide a heading, which ends the item. Reviewer Comments
    # is read as parse_comments reads it, so both find the same code there
    fences: Fences = Fences(lists=True)
    for line in markdown.splitlines():
        if isinstance(fences, CommentReader):
            fences.read(line)
            code = fences.code
        else:
            code = fences.inside(line)
        match = None if code else SECTION.match(line)
        if match:
            parts.append((heading, "\n".join(lines)))
            heading, lines = match.group(1).strip(), []
            fences = CommentReader() if heading == COMMENTS_GROUP else Fences(lists=True)
        else:
            lines.append(line)
    parts.append((heading, "\n".join(lines)))
    return parts


def keep(other: dict[str, str], heading: str, text: str) -> None:
    """Keep text the mapper has no field for, adding to any already kept under `heading`."""
    if text:
        other[heading] = f"{other[heading]}\n\n{text}" if heading in other else text


def outdented_break(line: str, content_indent: int) -> bool:
    """Whether `line` is a thematic break indented less than an item's content, which ends
    the item (one at the content's indentation is inside it)."""
    return bool(THEMATIC_BREAK.match(line)) and len(line) - len(line.lstrip(" ")) < content_indent


def parse_bullets(body: str) -> tuple[list[dict[str, str]], str]:
    """Bulleted points as {title, text} (`**Title** — text`) or {text}, and the other text.

    A point runs on through blank lines and indented lines, so its paragraphs, nested
    lists and code blocks are kept as written, less the list's own indentation.
    """
    items: list[tuple[int, list[str]]] = []  # (content indentation, lines)
    rest: list[str] = []
    in_item = False
    list_indent: int | None = None
    fences = Fences(lists=True)
    for line in body.splitlines():
        # A line of fenced code is never a point, though it may continue one; a point's own
        # code is read relative to its indentation, as Markdown reads it
        # A line that belongs to an open fence is never a point; a bullet that ends an item
        # and its unclosed code is one, even when it opens a fence of its own (`- ```py`)
        held = fences.holds(line)
        # Whether the line before ended in paragraph text, which alone continues lazily
        paragraph = fences.paragraph
        code = fences.inside(line)
        # A thematic break (`- - -`) is no point, as the fence tracker reads it
        bullet = None if held or THEMATIC_BREAK.match(line) else TOP_BULLET.match(line)
        if bullet and (list_indent is None or len(bullet.group(1)) <= list_indent):
            list_indent = len(bullet.group(1)) if list_indent is None else list_indent
            items.append((len(bullet.group(1)) + len(bullet.group(2)), [bullet.group(3)]))
            in_item = True
        elif (
            in_item
            and (held or not outdented_break(line, items[-1][0]))
            and (not line.strip() or line.startswith((" ", "\t")))
        ):
            items[-1][1].append(line)
        elif in_item and not code and paragraph and not NEW_BLOCK.match(line):
            # A lazy continuation: an unindented line straight after the point's paragraph
            # text (not a heading, break or code, as the fence tracker reads it) still
            # belongs to it (a soft-wrapped bullet)
            items[-1][1].append(line)
        elif line.strip():
            rest.append(line)
            in_item = False  # an unindented line ends the point
        elif not in_item:
            rest.append(line)  # a blank line between paragraphs of other prose
    points = []
    for content_indent, lines in items:
        # Dedent by the point's own content indentation, so deeper indentation (a nested
        # list, an indented code block) is kept
        more = [
            line[min(content_indent, len(line) - len(line.lstrip(" "))) :] for line in lines[1:]
        ]
        text = "\n".join([lines[0], *more]).strip()
        titled = TITLED.match(text)
        if titled and titled.group(2).strip():
            points.append({"title": titled.group(1).strip(), "text": titled.group(2).strip()})
        else:
            points.append({"text": text})
    return points, "\n".join(rest).strip("\n").rstrip()


def table_cells(line: str) -> list[str]:
    """A table row's cells, split at unescaped pipes; `\\|` in a cell is a literal pipe."""
    row = line.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return [cell.strip().replace("\\|", "|") for cell in UNESCAPED_PIPE.split(row)]


def table_rows(lines: list[str]) -> list[dict[str, str]]:
    """A Markdown table's rows as {header: cell}, without the separator row. Cells past the
    header are kept as `column_<n>`, so nothing in a malformed row is lost."""
    cells = [table_cells(line) for line in lines]
    if len(cells) < 2:
        return []
    header = [plain(name).casefold() for name in cells[0]]
    rows = [row for row in cells[1:] if not all(set(cell) <= set("-: ") for cell in row)]
    keys = [
        *header,
        *(f"column_{n + 1}" for n in range(len(header), max(map(len, rows), default=0))),
    ]
    return [dict(zip(keys, row, strict=False)) for row in rows]


def parse_references(body: str) -> dict[str, Any]:
    """The counts sentence, an entry per row of the table (or per `#N — Citation:` line),
    and any other text."""
    fences = Fences(lists=True)
    lines = [(line, fences.inside(line)) for line in body.splitlines()]
    # Table rows and `#N — Citation:` entries count only outside code; examples stay prose
    table = [line for line, code in lines if not code and line.strip().startswith("|")]
    entries = []
    for row in table_rows(table):
        # The columns the mapper knows, by its names; any other column as the report names it
        entry = {TABLE_FIELDS.get(key, slug(key) or key): value for key, value in row.items()}
        if "number" in entry:
            entry["number"] = entry["number"].lstrip("#")
        entries.append({key: value for key, value in entry.items() if value})
    # Prose is kept as written, blank lines and indentation included
    text: list[str] = []
    for line, code in lines:
        if code:
            text.append(line)
            continue
        if line.strip().startswith("|"):
            continue
        entry_line = ENTRY_LINE.match(BULLET.sub(r"\1", line).strip())
        if entry_line:
            number, citation, status = entry_line.groups()
            entries.append({"number": number, "citation": citation, "status": status})
        else:
            text.append(line)
    parsed: dict[str, Any] = {}
    first = next((index for index, line in enumerate(text) if line.strip()), None)
    if first is not None and CHECKED.search(plain(text[first])):
        parsed["summary"] = text.pop(first).strip()
    if entries:
        parsed["entries"] = entries
    prose = "\n".join(text).strip("\n").rstrip()
    if prose.strip():
        parsed["text"] = prose
    return parsed


def parse_comments(body: str) -> tuple[list[dict[str, str]], str]:
    """The numbered comments, each with its title, page, excerpt and explanation, and any
    text above the first."""
    comments: list[dict[str, Any]] = []
    above: list[str] = []
    lines: list[str] = []
    reader = CommentReader()
    for line in body.splitlines():
        # A comment starts at the list's own indentation, outside code: deeper numbered
        # items and code are part of the explanation (see CommentReader)
        start = reader.read(line)
        if start:
            if comments:
                comments[-1]["lines"] = lines
            _, number, title, page, page_end = start.groups()
            comments.append({"number": number, "title": title.strip(), "page": page})
            if page_end:
                comments[-1]["page_end"] = page_end
            lines = []
        elif comments:
            lines.append(line)
        elif line.strip():
            above.append(line)
    if comments:
        comments[-1]["lines"] = lines
    parsed = []
    for comment in comments:
        body_lines = comment.pop("lines")
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        excerpt = []
        while body_lines and body_lines[0].lstrip().startswith(">"):
            # Only the blockquote marker and its one optional space go; code spaces stay
            excerpt.append(BLOCKQUOTE.sub("", body_lines.pop(0), count=1))
        if excerpt:
            comment["excerpt"] = trim_blank_lines(excerpt)
        comment["text"] = trim_blank_lines(body_lines)
        parsed.append({key: value for key, value in comment.items() if value})
    return parsed, "\n".join(above).strip()


def parse_report(markdown: str) -> dict[str, Any]:
    """The report in its own structure (see the module docstring)."""
    report: dict[str, Any] = {}
    other: dict[str, str] = {}
    for heading, body in split_sections(markdown):
        if heading is None:
            lines = [line.strip() for line in body.splitlines()]
            lines = [line for line in lines if line and line not in WRAPPER]
            if lines and not lines[0].startswith("#"):
                report["title"] = lines.pop(0)
            keep(other, "preamble", "\n".join(lines))
        elif heading == "Overview":
            points, rest = parse_bullets(body)
            report.setdefault("overview", []).extend(points)
            keep(other, heading, rest)
        elif heading == "AI Text Detection":
            keep(report, "ai_text_detection", body.strip())
        elif heading in ("Fatal Flaws", "Reference Check") and SECTIONS[heading] in report:
            # One check per kind: a repeated section is kept, not merged or overwritten
            keep(other, heading, body.strip())
        elif heading == "Fatal Flaws":
            items, rest = parse_bullets(body)
            flaws: dict[str, Any] = {}
            if rest:
                flaws["text"] = rest
            if items:
                flaws["items"] = items
            if flaws:
                report["fatal_flaws"] = flaws
        elif heading == "Reference Check":
            references = parse_references(body)
            if references:
                report["reference_check"] = references
        elif heading == COMMENTS_GROUP:
            comments, rest = parse_comments(body)
            report.setdefault("comments", []).extend(comments)
            keep(other, heading, rest)
        else:
            keep(other, heading, body.strip())
    if other:
        report["other"] = other
    return report


# Mapping


def map_contributions(report: dict[str, Any], recorder: Recorder) -> list[dict[str, str]]:
    contributions = []
    for index, point in enumerate(report.get("overview", [])):
        source, target = f"overview[{index}]", f"opinion.contributions[{index}]"
        contribution = {}
        if point.get("title"):
            contribution["title"] = recorder.copy(
                f"{source}.title", f"{target}.title", point["title"]
            )
        contribution["text"] = recorder.copy(f"{source}.text", f"{target}.text", point["text"])
        contributions.append(contribution)
    return contributions


def ai_text_check(sentence: str, target: str, recorder: Recorder) -> dict[str, Any]:
    check: dict[str, Any] = {"id": "ai-text-detection", "kind": "ai_text_detection"}
    check["label"] = "AI Text Detection"
    detector = DETECTOR.search(sentence)
    if detector:
        name = recorder.parse(
            "ai_text_detection", f"{target}.performed_by.name", sentence, detector.group(1)
        )
        check["performed_by"] = {"name": name}
    check["summary"] = recorder.copy("ai_text_detection", f"{target}.summary", sentence)
    measurements = []
    for match in PERCENT.finditer(sentence):
        percent, label = match.groups()
        measurement = {
            "key": slug(label),
            "label": label,
            "value": round(float(percent) / 100, 6),
            "unit": "fraction",
        }
        measurement_target = f"{target}.measurements[{len(measurements)}]"
        measurements.append(
            recorder.parse("ai_text_detection", measurement_target, match.group(0), measurement)
        )
    if measurements:
        check["measurements"] = measurements
    return check


def fatal_flaw_check(
    flaws: dict[str, Any], target: str, weaknesses: list[dict[str, Any]], recorder: Recorder
) -> dict[str, Any]:
    """The screen, and a critical weakness for each flaw it lists."""
    check: dict[str, Any] = {"id": "fatal-flaws", "kind": "fatal_flaw_screen"}
    check["label"] = "Fatal Flaws"
    text = flaws.get("text", "")
    summary: list[tuple[str, str]] = []  # (source path, text)
    if text:
        summary.append(
            ("fatal_flaws.text", recorder.copy("fatal_flaws.text", f"{target}.summary", text))
        )
    finding_ids = []
    for index, item in enumerate(flaws.get("items", [])):
        source = f"fatal_flaws.items[{index}]"
        if not item.get("title") and NO_FATAL.match(item["text"]):
            # A bulleted verdict ("- No fatal … identified."), not a flaw
            verdict_text = recorder.copy(f"{source}.text", f"{target}.summary", item["text"])
            summary.append((f"{source}.text", verdict_text))
            continue
        point_target = f"findings.weaknesses[{len(weaknesses)}]"
        point: dict[str, Any] = {"id": f"fatal-flaw-{index + 1}"}
        if item.get("title"):
            point["title"] = recorder.copy(
                f"{source}.title", f"{point_target}.title", item["title"]
            )
        point["text"] = recorder.copy(f"{source}.text", f"{point_target}.text", item["text"])
        severity = recorder.lookup(
            source, f"{point_target}.severity", "Fatal Flaws", FATAL_SEVERITY
        )
        if severity:
            point["severity"] = severity
        weaknesses.append(point)
        finding_ids.append(point["id"])
    if summary:
        check["summary"] = "\n\n".join(line for _, line in summary)
    # The verdict may be any paragraph of the prose, but not part of a code example
    verdict = next(
        (
            (path, paragraph)
            for path, line in summary
            for paragraph in prose_paragraphs(line)
            if NO_FATAL.match(paragraph)
        ),
        None,
    )
    if finding_ids:
        check["outcome"] = recorder.parse(
            "fatal_flaws.items", f"{target}.outcome", "listed flaws", "issues_found"
        )
        check["finding_ids"] = finding_ids
    elif verdict:
        verdict_path, verdict_line = verdict
        check["outcome"] = recorder.parse(
            verdict_path, f"{target}.outcome", verdict_line, "no_issues"
        )
    return check


def reference_check(references: dict[str, Any], target: str, recorder: Recorder) -> dict:
    check: dict[str, Any] = {"id": "reference-check", "kind": "reference_verification"}
    check["label"] = "Reference Check"
    measurements = []
    summary = references.get("summary")
    if not summary and references.get("text"):
        # Prose without the counts sentence, such as "No references to check.": the summary
        check["summary"] = recorder.copy(
            "reference_check.text", f"{target}.summary", references["text"]
        )
    if summary:
        source = "reference_check.summary"
        check["summary"] = recorder.parse(source, f"{target}.summary", summary, plain(summary))
        sentence = plain(summary)
        checked = CHECKED.search(sentence)
        if checked:
            measurement = {"key": "checked", "value": int(checked.group(1))}
            measurements.append(
                recorder.parse(source, f"{target}.measurements[0]", checked.group(0), measurement)
            )
        counts = sentence.split(":", 1)[1] if ":" in sentence else ""
        for match in COUNT.finditer(counts):
            number, label = match.groups()
            measurement = {"key": slug(label), "value": int(number)}
            measurement_target = f"{target}.measurements[{len(measurements)}]"
            measurements.append(
                recorder.parse(source, measurement_target, match.group(0).strip(), measurement)
            )
    if measurements:
        check["measurements"] = measurements
    items = []
    for index, entry in enumerate(references.get("entries", [])):
        source, item_target = f"reference_check.entries[{index}]", f"{target}.items[{len(items)}]"
        raw_status = entry.get("status", "")
        if not raw_status:
            recorder.skip(source, "no status")
            continue
        link: dict[str, Any] = {"type": "bibliography", "ref": ""}
        if entry.get("number"):
            link["ref"] = recorder.copy(
                f"{source}.number", f"{item_target}.target.ref", entry["number"]
            )
        if entry.get("citation"):
            citation = recorder.copy(
                f"{source}.citation", f"{item_target}.target.work.citation", entry["citation"]
            )
            link["work"] = {"citation": citation}
        status = recorder.parse(
            f"{source}.status", f"{item_target}.status", raw_status, plain(raw_status)
        )
        item: dict[str, Any] = {"target": link, "status": status}
        flagged = status_flag(status)
        if flagged is not None:
            item["flagged"] = recorder.parse(
                f"{source}.status", f"{item_target}.flagged", raw_status, flagged
            )
        items.append(item)
    if items:
        check["items"] = items
    return check


def comment_link(
    comment: dict[str, str],
    source: str,
    target: str,
    recorder: Recorder,
    blocks: list[Block] | None,
) -> dict[str, Any] | None:
    """One evidence link from a comment's page and excerpt, or None when it has neither."""
    page, excerpt = comment.get("page"), comment.get("excerpt")
    if not page and not excerpt:
        return None
    link: dict[str, Any] = {"type": "paper_section", "ref": ""}
    label = next(
        (kind for pattern, kind in LABEL_TYPES if excerpt and pattern.match(excerpt)), None
    )
    if label:
        link["type"] = recorder.parse(f"{source}.excerpt", f"{target}.type", excerpt, label)
        link["ref"] = recorder.copy(f"{source}.excerpt", f"{target}.ref", excerpt)
    elif page:
        pages = f"Page {page}" + (f"–{comment['page_end']}" if comment.get("page_end") else "")
        link["ref"] = recorder.parse(f"{source}.page", f"{target}.ref", page, pages)
    if excerpt and not label:
        link["quote"] = recorder.copy(f"{source}.excerpt", f"{target}.quote", excerpt)
        recorder.anchor(f"{source}.excerpt", target, excerpt, blocks)
    if page:
        location = {
            "page": recorder.parse(f"{source}.page", f"{target}.location.page", page, int(page))
        }
        if comment.get("page_end") and int(comment["page_end"]) > int(page):
            location["page_end"] = recorder.parse(
                f"{source}.page_end",
                f"{target}.location.page_end",
                comment["page_end"],
                int(comment["page_end"]),
            )
        link["location"] = location
    return link


def map_comments(
    report: dict[str, Any], recorder: Recorder, blocks: list[Block] | None
) -> list[dict[str, Any]]:
    comments = []
    parsed = report.get("comments", [])
    # A comment's id follows its printed number when the numbers are unique; a list written
    # `1.`, `1.`, `1.` (valid Markdown) numbers its comments by position instead
    numbers = [comment.get("number") for comment in parsed]
    by_number = all(numbers) and len(set(numbers)) == len(numbers)
    for index, comment in enumerate(parsed):
        source, target = f"comments[{index}]", f"findings.comments[{len(comments)}]"
        if not comment.get("text"):
            # OCRS requires a point's text; the comment stays in extensions
            recorder.skip(source, "no explanation")
            continue
        point_id = f"comment-{comment['number'] if by_number else index + 1}"
        point: dict[str, Any] = {
            "id": recorder.parse(f"{source}.number", f"{target}.id", numbers[index], point_id)
        }
        if comment.get("title"):
            point["title"] = recorder.copy(f"{source}.title", f"{target}.title", comment["title"])
        if comment.get("text"):
            point["text"] = recorder.copy(f"{source}.text", f"{target}.text", comment["text"])
        point["group"] = [COMMENTS_GROUP]
        link = comment_link(comment, source, f"{target}.evidence_links[0]", recorder, blocks)
        if link:
            point["evidence_links"] = [link]
        comments.append(point)
    return comments


def map_reviewer3(output: str, review: dict[str, Any], blocks: list[Block] | None) -> MappingResult:
    """Fills `review`, the envelope map_with_record built, from Reviewer3's Markdown report."""
    if not isinstance(output, str):
        raise TypeError("Reviewer3 output is the report's Markdown text")
    report = parse_report(output)
    recorder = Recorder(checks_quotes=blocks is not None)
    review["text_format"] = dict(TEXT_FORMAT)
    if report.get("title"):
        review["target"]["title"] = recorder.copy("title", "target.title", report["title"])
    contributions = map_contributions(report, recorder)
    if contributions:
        review["opinion"]["contributions"] = contributions

    checks: list[dict[str, Any]] = []
    weaknesses: list[dict[str, Any]] = []

    def add(check: dict[str, Any]) -> None:
        # A check with nothing in it (say, a table whose rows all lack a status) is left
        # out; what it skipped stays in extensions
        if CHECK_CONTENT & check.keys():
            checks.append(check)

    if report.get("ai_text_detection"):
        add(ai_text_check(report["ai_text_detection"], f"checks[{len(checks)}]", recorder))
    if report.get("fatal_flaws"):
        target = f"checks[{len(checks)}]"
        add(fatal_flaw_check(report["fatal_flaws"], target, weaknesses, recorder))
    if report.get("reference_check"):
        target = f"checks[{len(checks)}]"
        add(reference_check(report["reference_check"], target, recorder))
    if checks:
        review["checks"] = checks

    findings: dict[str, list[dict[str, Any]]] = {}
    if weaknesses:
        findings["weaknesses"] = weaknesses
    comments = map_comments(report, recorder, blocks)
    if comments:
        findings["comments"] = comments
    if findings:
        review["findings"] = findings
    result = finish(review, recorder, report, ignored=set())
    keep_skipped_rows(result.review, report.get("reference_check", {}).get("entries", []))
    return result


def identity_of(row: dict[str, str]) -> tuple[str, str]:
    """A reference row's number and citation, as printed."""
    return row.get("number", ""), row.get("citation", "")


def keep_skipped_rows(review: dict[str, Any], entries: list[dict[str, str]]) -> None:
    """Keep what `to_reviewer3` needs to put each reference row back without guessing: a
    row skipped for having no status keeps its empty status, and a mapped row whose other
    columns were kept keeps its number and citation with them, so they go back to the right
    item even after items are removed, and when two rows share a number."""
    kept = (review.get("extensions") or {}).get("reviewer3", {}).get("reference_check", {})
    rows = list(kept.get("entries") or [None] * len(entries))
    shared = Counter(identity_of(entry) for entry in entries if entry.get("status"))
    changed = False
    for index, entry in enumerate(entries):
        if not entry.get("status"):
            rows[index] = {**(rows[index] or {}), "status": ""}
            changed = True
        elif (rows[index] or shared[identity_of(entry)] > 1) and any(identity_of(entry)):
            # Rows sharing a number and citation all keep them, so their order tells them apart
            identity = {key: entry[key] for key in ("number", "citation") if entry.get(key)}
            rows[index] = {**identity, **(rows[index] or {})}
            changed = True
    if changed:
        references = review.setdefault("extensions", {}).setdefault("reviewer3", {})
        references.setdefault("reference_check", {})["entries"] = rows


# OCRS → Reviewer3

# Findings written as Reviewer Comments, in this order, and the title one gets without its own
COMMENT_KINDS = {
    "comments": "Comment",
    "weaknesses": "Weakness",
    "questions": "Question",
    "changes": "Requested Change",
}
CHECK_SECTIONS = {
    "ai_text_detection": "AI Text Detection",
    "fatal_flaw_screen": "Fatal Flaws",
    "reference_verification": "Reference Check",
}
NO_FATAL_FLAWS = "No fatal methodological flaws were identified."
COMMENT_ID = re.compile(r"^comment-(\d+)$")
FLAW_ID = re.compile(r"^fatal-flaw-(\d+)$")


def demoted(text: str) -> str:
    """`text` with its own `###` headings made `####`, outside fenced code (read as the
    parser reads it), so free text from another review (Markdown too, often) does not
    start sections of the report."""
    fences = Fences(lists=True)
    return "\n".join(
        line if fences.inside(line) or not SECTION.match(line) else f"#{line}"
        for line in text.split("\n")
    )


def nested(text: str) -> str:
    """`text` with each line that would start a new comment (`2. **Title**`) indented by a
    space, with the lines of its list item, outside fenced code, so it stays in the comment
    and its item keeps its shape; Markdown renders it the same."""
    fences = Fences(lists=True)
    lines = []
    item: int | None = None  # content indentation of the item being shifted
    for line in text.split("\n"):
        indent = len(line) - len(line.lstrip(" "))
        if item is not None and line.strip() and indent < item:
            item = None
        code = fences.inside(line)
        header = COMMENT_START.match(line) if not code else None
        if header and not line[0].isspace():
            item = len(line) - len(line.lstrip(" ")) + len(header.group(2)) + 2
            lines.append(f" {line}")
        elif item is not None:
            lines.append(f" {line}" if line.strip() else line)
        else:
            lines.append(line)
    return "\n".join(lines)


def read_back(kind: str, body: str) -> dict[str, Any]:
    """The check the mapper reads out of `body` as the section of its kind."""
    report = parse_report(f"### {CHECK_SECTIONS[kind]}\n\n{body}\n")
    recorder = Recorder(checks_quotes=False)
    if kind == "ai_text_detection" and report.get("ai_text_detection"):
        return ai_text_check(report["ai_text_detection"], "check", recorder)
    if kind == "fatal_flaw_screen" and report.get("fatal_flaws"):
        return fatal_flaw_check(report["fatal_flaws"], "check", [], recorder)
    if kind == "reference_verification" and report.get("reference_check"):
        return reference_check(report["reference_check"], "check", recorder)
    return {}


def unsaid(check: dict[str, Any], body: str) -> dict[str, Any]:
    """What `check` says that `body`, its section as Reviewer3 writes it, does not: an outcome
    the section does not state, who ran it, measurements and items it does not give."""
    said = read_back(check["kind"], body)
    rest: dict[str, Any] = {}
    if check.get("outcome") and check["outcome"] != said.get("outcome"):
        rest["outcome"] = check["outcome"]
    performer = (check.get("performed_by") or {}).get("name")
    if performer and performer != (said.get("performed_by") or {}).get("name"):
        rest["performed_by"] = {"name": performer}
    given = [(m.get("key"), m.get("value")) for m in said.get("measurements") or []]
    measurements = [
        m for m in check.get("measurements") or [] if (m.get("key"), m.get("value")) not in given
    ]
    if measurements:
        rest["measurements"] = measurements
    if check.get("items") and check["kind"] != "reference_verification":
        rest["items"] = check["items"]
    return rest


def write_bullets(points: list[dict[str, Any]]) -> str:
    """`- **Title** — text` (or `- text`) for each point, its later lines indented under it.
    Text that opens with a code fence starts on its own line, or the fence would never
    open and its closing marker would open one instead."""

    def bullet(point: dict[str, Any]) -> str:
        text = indented(point["text"], "  ")
        first = point["text"].split("\n")[0].rstrip("\r")
        # Text that opens a fence, or that would make the marker's line a thematic break
        # (`- - - -`), starts on a line of its own
        if FENCE.match(first) or THEMATIC_BREAK.match(f"- {first}"):
            text = f"\n  {text}"
        if point.get("title"):
            title = indented(point["title"], "  ")
            return f"- **{title}** —" + (text if text.startswith("\n") else f" {text}")
        # An item may start empty; the marker's trailing space keeps it an item
        return f"- {text}"

    return "\n".join(bullet(point) for point in points)


def is_fraction(measurement: dict[str, Any]) -> bool:
    """A share of the text: a 0–1 number in `fraction` units, or with no unit."""
    value, unit = measurement.get("value"), measurement.get("unit")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return unit == "fraction" or (unit is None and 0 <= value <= 1)


def percent(value: float) -> str:
    return f"{round(value * 100, 4):g}%"


def write_ai_text(check: dict[str, Any]) -> str:
    """The check's own sentence, or one saying its fractions and who measured them."""
    if check.get("summary"):
        return check["summary"]
    shares, others = [], []
    for m in check.get("measurements") or []:
        name = m.get("label") or m["key"]
        if is_fraction(m):
            shares.append(f"{percent(m['value'])} {name}")
        else:
            others.append(f"{name}: {m['value']}" + (f" {m['unit']}" if m.get("unit") else ""))
    sentence = f"{' and '.join(shares)} text detected." if shares else ""
    if others:
        sentence = f"{sentence} {'; '.join(others)}.".strip()
    detector = (check.get("performed_by") or {}).get("name")
    if detector:
        sentence = f"{sentence} See the full {detector} report.".strip()
    return sentence


def write_fatal_flaws(check: dict[str, Any], flaws: list[dict[str, Any]]) -> str:
    """The check's prose, then its flaws as points.

    A flaw the mapper made has an ID `fatal-flaw-<n>`, its place among the section's points;
    a place no flaw takes was a bulleted verdict ("- No fatal … identified."), which the
    mapper put in the summary. Such verdicts go back to those places as points, so the
    flaws keep their IDs.
    """
    summary = check.get("summary")
    if not summary and not flaws and check.get("outcome") == "no_issues":
        summary = NO_FATAL_FLAWS
    places = {int(m.group(1)): flaw for flaw in flaws if (m := FLAW_ID.match(flaw.get("id", "")))}
    # Only the mapper's one-based places count; another ID (fatal-flaw-0) has none
    places = {n: flaw for n, flaw in places.items() if n >= 1}
    paragraphs = summary.split("\n\n") if summary else []
    verdicts = [i for i, p in enumerate(paragraphs) if NO_FATAL.match(p.strip())]
    # Count the empty places before listing them: an ID is any string, and one such as
    # fatal-flaw-1000000000 must not mean listing a billion places
    last = max(places, default=0)
    gaps = last - len(places)
    if gaps <= 0 or len(places) != len(flaws) or len(verdicts) < gaps:
        return join_blocks([summary, write_bullets(flaws)])
    # The bulleted verdicts came after the section's prose, in order, each a block that
    # runs from its verdict to the next (a verdict point may have paragraphs of its own)
    starts = verdicts[-gaps:]
    prose = "\n\n".join(paragraphs[: starts[0]])
    ends = [*starts[1:], len(paragraphs)]
    texts = iter("\n\n".join(paragraphs[a:b]) for a, b in zip(starts, ends, strict=True))
    points = [
        write_bullets([places[n]]) if n in places else f"- {indented(next(texts), '  ')}"
        for n in range(1, last + 1)
    ]
    return join_blocks([prose, "\n".join(points)])


def cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_reference_summary(check: dict[str, Any]) -> str | None:
    """The check's own sentence, or `Checked N references: n verified, …` from its counts."""
    if check.get("summary"):
        return check["summary"]
    counts = {m["key"]: m["value"] for m in check.get("measurements") or [] if "key" in m}
    if "checked" not in counts:
        return None
    rest = [f"{value} {key.replace('_', ' ')}" for key, value in counts.items() if key != "checked"]
    sentence = f"Checked {counts['checked']} references"
    return f"{sentence}: {', '.join(rest)}." if rest else f"{sentence}."


def reference_rows(check: dict[str, Any], kept: list[Any]) -> list[dict[str, str]]:
    """A row per item, with the columns the mapper did not read, and the rows it skipped
    for having no status, each where it was.

    Kept columns that came with a number and citation go to the item with that number and
    citation (an item that is gone takes them with it); the rest go to the items in order.
    """
    items = check.get("items") or []
    entries = [*kept, *([None] * len(items))]
    # A skipped row kept its empty status; a mapped one only the columns not read
    skipped = [isinstance(entry, dict) and "status" in entry for entry in entries]

    def identity(item: dict[str, Any]) -> tuple[str, str]:
        link = item.get("target") or {}
        return link.get("ref", ""), (link.get("work") or {}).get("citation", "")

    # The k-th kept row with a number and citation goes to the k-th item with them
    by_identity: dict[tuple[str, str], list[int]] = {}
    for i, item in enumerate(items):
        by_identity.setdefault(identity(item), []).append(i)
    seen: Counter[tuple[str, str]] = Counter()
    claimed: dict[int, int] = {}  # entry index -> item index
    for e, entry in enumerate(entries):
        if skipped[e] or not isinstance(entry, dict) or not any(identity_of(entry)):
            continue
        wanted = identity_of(entry)
        matches = by_identity.get(wanted, [])
        claimed[e] = matches[seen[wanted]] if seen[wanted] < len(matches) else -1
        seen[wanted] += 1
    free = iter([i for i in range(len(items)) if i not in claimed.values()])
    rows = []
    for e, entry in enumerate(entries):
        if skipped[e]:
            rows.append(dict(entry))
            continue
        index = claimed[e] if e in claimed else next(free, -1)
        if index < 0:
            continue
        item = items[index]
        link = item.get("target") or {}
        work = link.get("work") or {}
        row = {"number": link.get("ref", ""), "citation": work.get("citation", "")}
        row["citation"] = row["citation"] or work.get("title", "")
        row["status"] = item["status"]
        if item.get("notes"):
            row["notes"] = item["notes"]
        rows.append(row | (entry or {}))
    return rows


MAX_TABLE_CELLS = 100_000  # a report's reference table, far beyond any real one


def write_reference_check(check: dict[str, Any], kept: dict[str, Any]) -> str:
    summary = write_reference_summary(check)
    parts: list[str | None] = [summary]
    rows = reference_rows(check, kept.get("entries") or [])
    if rows:
        columns = ["number", "citation", "status"]
        columns += dict.fromkeys(key for row in rows for key in row if key not in columns)
        if len(rows) * len(columns) > MAX_TABLE_CELLS:
            # Every row has a cell in every column, so sparse entries would grow as a square
            raise ValueError(
                f"The reference check's {len(rows)} rows and {len(columns)} columns are more "
                f"than {MAX_TABLE_CELLS} cells to write as a table"
            )
        names = {"number": "#", "citation": "Citation", "status": "Status"}
        table = [
            "| " + " | ".join(names.get(key, key) for key in columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *("| " + " | ".join(cell(row.get(key, "")) for key in columns) + " |" for row in rows),
        ]
        parts.append("\n".join(table))
    parts.append(kept.get("text"))
    present = [part for part in parts if part]
    first_line = next((line for line in (summary or "").splitlines() if line.strip()), "")
    if not (summary and CHECKED.search(plain(first_line))):
        # Prose, not the counts sentence: its place does not matter to the mapper, so one
        # that leaves a fence open goes after the table, which (unlike a list) cannot take
        # in its indented lines
        if summary and open_fence(summary):
            others = [close_fence(part) for part in present if part is not summary]
            return "\n\n".join([*others, summary])
        return join_blocks(present)
    # The counts sentence comes first among the prose; one that leaves a fence open (a fence
    # line read as the counts) comes after the table, or the rows would be code. Prose kept
    # after it followed it in the report, in its code if the fence was open, so it stays
    # with it
    if rows and open_fence(summary):
        present.insert(0, present.pop(1))
    return "\n\n".join(present)


def excerpt_of(link: dict[str, Any]) -> str | None:
    """The comment's excerpt: the quote, or a figure, table or equation label."""
    if link.get("quote"):
        return link["quote"]
    ref = link.get("ref") or ""
    if link.get("type") in ("figure", "table", "equation"):
        if any(pattern.match(ref) for pattern, _ in LABEL_TYPES):
            return ref
    return None


def write_comment(number: int | str, comment: dict[str, Any]) -> str:
    """`N. **Title** — Page P`, the excerpt as a blockquote, then the explanation."""
    # A comment's title is one line of the report
    head = f"{number}. **{' '.join(comment['title'].split())}**"
    if comment.get("page"):
        pages = str(comment["page"])
        if comment.get("page_end") and int(comment["page_end"]) > int(comment["page"]):
            pages += f"–{comment['page_end']}"
        head += f" — Page {pages}"
    parts = [head]
    if comment.get("excerpt"):
        parts.append(
            "\n".join(f"> {line}" if line else ">" for line in comment["excerpt"].split("\n"))
        )
    elif comment.get("text", "").lstrip().startswith(">"):
        # An explanation that opens with a quote would be read back as the excerpt; an empty
        # excerpt before it keeps it the explanation
        parts.append(">")
    if comment.get("text"):
        parts.append(nested(demoted(comment["text"])))
    return "\n\n".join(parts)


def comment_fences(text: str) -> CommentReader:
    """The fence state at the end of `text`, read as parse_comments reads Reviewer
    Comments."""
    reader = CommentReader()
    for line in text.splitlines():
        reader.read(line)
    return reader


def close_comment_fence(text: str) -> str:
    """`text`, Reviewer Comments or part of it, with the fence its last explanation leaves
    open closed, the closing marker indented as the opening one was."""
    fences = comment_fences(text)
    if not fences.open_at_margin:
        return text
    return f"{text}\n{' ' * min(fences.indent, 3)}{fences.open}"


def comment_from(point: dict[str, Any], default_title: str) -> dict[str, Any]:
    """A comment from a finding: its first link gives the page and the excerpt."""
    comment: dict[str, Any] = {"title": point.get("title") or default_title, "text": point["text"]}
    links = point.get("evidence_links") or []
    if links:
        location = links[0].get("location") or {}
        comment["page"], comment["page_end"] = location.get("page"), location.get("page_end")
        comment["excerpt"] = excerpt_of(links[0])
    return comment


def write_comments(points: list[tuple[dict[str, Any], str]], kept: list[Any]) -> str:
    """The comments in the order the reviewer wrote them, with their own numbers.

    One the mapper skipped for having no explanation left its title and number in
    extensions, at its place in the list. A mapped comment's number is in its ID
    (`comment-7`); any other comment is numbered after the highest number in use.
    """
    numbered: list[tuple[dict[str, Any], str | None]] = []
    remaining = iter(points)

    def mapped(point: dict[str, Any], label: str) -> tuple[dict[str, Any], str | None]:
        number = COMMENT_ID.match(point.get("id", ""))
        return comment_from(point, label), number.group(1) if number else None

    def skipped(entry: Any) -> bool:
        return isinstance(entry, dict) and bool(entry.get("title"))

    def kept_number(entry: dict[str, Any]) -> str | None:
        number = str(entry.get("number") or "")
        return number if number.isdigit() else None

    # Mapped comments fill the places the mapper left them, in order. A printed number is
    # not a place (a list may run 3, 2, 1), so a comment removed before a skipped one moves
    # the skipped one; an unedited review comes back as it was
    for entry in kept:
        if skipped(entry):
            numbered.append((entry, kept_number(entry)))
        elif (point := next(remaining, None)) is not None:
            numbered.append(mapped(*point))
    numbered += [mapped(*point) for point in remaining]
    # Numbers are written as they were, repeats included: the mapper numbers comments by
    # position when their numbers repeat, so a list numbered 3, 3, 3 keeps its IDs
    # Printed numbers are kept as printed (`01`); new comments follow the highest
    known = [int(number) for _, number in numbered if number is not None]
    free = (str(n) for n in itertools.count(max(known, default=0) + 1))
    numbers = [number if number is not None else next(free) for _, number in numbered]
    written = [
        write_comment(number, comment)
        for (comment, _), number in zip(numbered, numbers, strict=True)
    ]
    # A fence one comment leaves open is closed, or it would swallow the comments after it
    return "\n\n".join([*(close_comment_fence(c) for c in written[:-1]), *written[-1:]])


def to_reviewer3(canonical: dict[str, Any]) -> str:
    """An OCRS review as Reviewer3's Markdown report.

    `target.title` is the paper's title and contributions are the Overview. The first
    check of each kind Reviewer3 runs is its section: AI Text Detection, Fatal Flaws (with
    the weaknesses the check names as its flaws) and Reference Check (its items as the
    table). A check without its own sentence gets one from its measurements, outcome or
    counts. Comments, the other weaknesses, questions and requested changes are Reviewer
    Comments, in that order; a comment's first evidence link gives its page and excerpt,
    and one without a title is titled by its kind. The summary, the full text, strengths
    and other checks, which Reviewer3 does not report, are written under headings of their
    own (the mapper keeps them in `extensions.reviewer3`). Severities, scores, the decision
    and text for the editors only are left out.
    """
    kept = extension(canonical, "reviewer3")
    other: dict[str, str] = dict(kept.get("other") or {})
    # The wrapper, title and text above the first section stay first; a fence the text
    # leaves open is closed when sections follow, or it would swallow them
    head = ["# Review Report"]
    title = (canonical.get("target") or {}).get("title")
    if title:
        head.append(title)
    head.append("---")
    if other.get("preamble"):
        head.append(other.pop("preamble"))
    sections: list[str] = []
    opinion = canonical.get("opinion") or {}
    contributions = [c for c in opinion.get("contributions") or [] if c.get("text")]
    overview_rest = other.pop("Overview", None)
    if contributions or overview_rest:
        body = join_blocks([overview_rest, write_bullets(contributions)])
        sections.append(f"### Overview\n\n{body}")

    checks: dict[str, dict[str, Any]] = {}
    extra_checks = []
    for check in canonical.get("checks") or []:
        if check["kind"] in CHECK_SECTIONS and check["kind"] not in checks:
            checks[check["kind"]] = check
        else:
            extra_checks.append(check)
    weaknesses = findings_of(canonical, "weaknesses")
    fatal_ids = {
        finding_id
        for check in canonical.get("checks") or []
        if check["kind"] == "fatal_flaw_screen"
        for finding_id in check.get("finding_ids") or []
    }

    def flaws_of(check: dict[str, Any]) -> list[dict[str, Any]]:
        named = set(check.get("finding_ids") or [])
        return [w for w in weaknesses if w.get("id") in named]

    def native(check: dict[str, Any], kept_references: dict[str, Any]) -> str:
        """The check as Reviewer3 writes its kind, or in prose when that says nothing (a
        check with only an outcome, say)."""
        if check["kind"] == "ai_text_detection":
            body = write_ai_text(check)
        elif check["kind"] == "fatal_flaw_screen":
            body = write_fatal_flaws(check, flaws_of(check))
        else:
            body = write_reference_check(check, kept_references)
        if not body:
            return check_text(check)
        rest = check_text(unsaid(check, body))
        return f"{close_fence(body)}\n\n{rest}" if rest else body

    def check_body(kind: str) -> str:
        check = checks.get(kind)
        if check is None and kind == "reference_verification" and kept.get("reference_check"):
            # A table whose rows all lack a status made no check; the mapper kept it
            return write_reference_check({}, kept["reference_check"])
        return native(check, kept.get("reference_check") or {}) if check else ""

    for kind, heading in CHECK_SECTIONS.items():
        body = check_body(kind)
        if body:
            sections.append(f"### {heading}\n\n{demoted(body)}")
        # A repeated section the mapper kept follows the one it mapped
        if heading in other and kind != "ai_text_detection":
            sections.append(f"### {heading}\n\n{other.pop(heading)}")

    points = [
        (point, label)
        for kind, label in COMMENT_KINDS.items()
        for point in findings_of(canonical, kind)
        if not (kind == "weaknesses" and point.get("id") in fatal_ids)
    ]
    above = other.pop(COMMENTS_GROUP, None)
    comments_section, comments_prose, comments_at = None, None, 0
    if points or above or kept.get("comments"):
        comments = write_comments(points, kept.get("comments") or [])
        if above and comments and open_fence(above):
            # Text that leaves a fence open came from a later Reviewer Comments section of its
            # own (the mapper merges repeats); it goes back as one, after the comments, rather
            # than closed above them
            comments_section = f"### {COMMENTS_GROUP}\n\n{comments}"
            comments_prose = f"### {COMMENTS_GROUP}\n\n{above}"
        else:
            # The text above the comments is closed only when comments follow it
            body = "\n\n".join(
                part
                for part in ((close_fence(above) if above and comments else above), comments)
                if part
            )
            comments_section = f"### {COMMENTS_GROUP}\n\n{body}"
        comments_at = len(sections)

    summary, text = overall_texts(canonical)
    if summary:
        add_section(other, "Summary", summary)
    if text:
        add_section(other, "Review", text)
    strengths = findings_of(canonical, "strengths")
    if strengths:
        add_section(other, "Strengths", write_bullets(strengths))
    # A second check of a kind Reviewer3 runs is written as Reviewer3 writes that kind, under
    # a numbered heading of its own; any other check in prose. The mapper keeps both
    repeats: Counter[str] = Counter()
    for check in extra_checks:
        kind = check["kind"]
        if kind in CHECK_SECTIONS:
            repeats[kind] += 1
            heading = f"{CHECK_SECTIONS[kind]} ({repeats[kind] + 1})"
            body = native(check, {})
        else:
            heading, body = check.get("label") or kind, check_text(check)
        if body:
            add_section(other, heading, body)
    sections += [f"### {heading}\n\n{demoted(text)}" for heading, text in other.items()]
    if comments_section:
        # Kept prose that leaves a fence open follows the comments, as its own section
        block = [comments_section] + ([comments_prose] if comments_prose else [])
        sections[comments_at:comments_at] = block

    # Reviewer Comments is read for code as parse_comments reads it; any other section as
    # plain Markdown
    def is_comments(block: str) -> bool:
        return block.startswith(f"### {COMMENTS_GROUP}\n")

    def section_open(block: str) -> bool:
        if is_comments(block):
            return comment_fences(block).open_at_margin
        return open_fence(block) is not None

    def section_close(block: str) -> str:
        return close_comment_fence(block) if is_comments(block) else close_fence(block)

    # A section followed by one with the same heading stays before it, closed: the mapper
    # takes the first Fatal Flaws or Reference Check as the check and keeps the rest
    headings = [section.split("\n", 1)[0] for section in sections]
    sections = [
        section_close(section) if headings[i] in headings[i + 1 :] else section
        for i, section in enumerate(sections)
    ]
    # A section that leaves a code fence open goes last, where it swallows no other
    if sections:
        head[-1] = close_fence(head[-1])  # the text above the first section, or the wrapper
        head.append(join_blocks(sections, is_open=section_open, close=section_close))
    return "\n\n".join(head) + "\n"
