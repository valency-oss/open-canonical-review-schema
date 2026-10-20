# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Read an OpenReview forum page (saved HTML) and map its Official Reviews to OCRS.

`parse_forum_page` turns the page's rendered reply thread into `Forum` and `Note` objects.
It reads only what the page shows: a saved page holds the rendered Markdown and MathML,
not the API's JSON, and shows dates without a time zone.

`reviews_from_forum_page` maps each Official Review to an OCRS review. Every review links back
to its place on the page: `provenance.source_url` opens the forum at that note, and
`extensions.openreview` names, for each OCRS value, the page field it came from.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from ..catalog import alias_map, load_catalog
from ..identifiers import generate_canonical_work_id
from ..schema import schema_id
from ..util import is_score_field, match_alias, now_iso, parse_numeric_prefix, section
from .ai import Fences

MAPPER_VERSION = "0.1.0"
SOURCE_SYSTEM = "openreview"
REVIEW_REPLY_TYPE = "Official Review"
LOSSINESS_NOTES = (
    "Read from a saved OpenReview page, which holds the rendered text, not the API's JSON. "
    "Mathematics is rebuilt from the page's MathML, so it may differ from the TeX the reviewer "
    "wrote. The page gives dates without a time zone and scales without their bounds, so the "
    "dates use the time zone given to the mapper and scores have no `normalized` value. "
    "An image in a page saved with its files points to the saved copy, by a path from the "
    "output folder when scripts/openreview_page_to_ocrs.py wrote the review, else from the page."
)

# --- A small DOM ---------------------------------------------------------------------------

_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "wbr",
}
_SKIP = {"script", "style", "noscript", "svg"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def elements(self) -> list[Node]:
        return [c for c in self.children if isinstance(c, Node)]

    def walk(self, stop: Any = None):
        """This node's descendants in document order, not entering those `stop` accepts."""
        for child in self.elements():
            yield child
            if stop is None or not stop(child):
                yield from child.walk(stop)

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return "".join(parts)

    def find(self, tag: str | None = None, cls: str | None = None, stop: Any = None) -> Node | None:
        return next(iter(self.find_all(tag, cls, stop)), None)

    def find_all(self, tag: str | None = None, cls: str | None = None, stop: Any = None):
        for node in self.walk(stop):
            if (tag is None or node.tag == tag) and (cls is None or cls in node.classes()):
                yield node


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.skipping = 0
        self.meta: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        if tag == "meta":
            self.meta.append(values)
        if self.skipping or tag in _SKIP:
            self.skipping += tag in _SKIP
            return
        node = Node(tag, values, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping or tag in _VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.stack[-1].children.append(data)


# --- Rendered Markdown and MathML back to text --------------------------------------------


_UNDERLINES = {"_", "‾", "¯", "―", "\u0332", "\u0331"}
_ACCENTS = {
    "^": "\\hat",
    "ˆ": "\\hat",
    "ˇ": "\\check",
    "˘": "\\breve",
    "¯": "\\bar",
    "‾": "\\bar",
    "→": "\\vec",
    "~": "\\tilde",
    "˜": "\\tilde",
    "˙": "\\dot",
    ".": "\\dot",
    "¨": "\\ddot",
    "´": "\\acute",
    "`": "\\grave",
}


_TEX_SPECIAL = {
    "\\": "\\backslash{}",
    "{": "\\{",
    "}": "\\}",
    "~": "\\sim{}",
    "^": "\\^{}",
}


def _tex_token(text: str) -> str:
    """A MathML token as TeX, with the characters TeX reads as commands made literal."""
    return "".join(_TEX_SPECIAL.get(c) or (f"\\{c}" if c in "#$%&_" else c) for c in text)


def _base(tex: str) -> str:
    """A script's base, braced unless it is one symbol or one command, so scripts do not stack."""
    single = len(tex) == 1 or re.fullmatch(r"\\[A-Za-z]+(?:\{[^{}]*\})?", tex)
    return tex if single else f"{{{tex}}}"


# `mathvariant` to a TeX template for the token. Bold script and bold fraktur have no command
# of their own, so they are bold (\boldsymbol) around the script or fraktur letters.
_VARIANTS = {
    "double-struck": "\\mathbb{{{}}}",
    "bold": "\\mathbf{{{}}}",
    "bold-italic": "\\boldsymbol{{{}}}",
    "script": "\\mathcal{{{}}}",
    "bold-script": "\\boldsymbol{{\\mathcal{{{}}}}}",
    "fraktur": "\\mathfrak{{{}}}",
    "bold-fraktur": "\\boldsymbol{{\\mathfrak{{{}}}}}",
    "sans-serif": "\\mathsf{{{}}}",
    "monospace": "\\mathtt{{{}}}",
}


def _scripts(kids: list[str], elements: list[Node]) -> str:
    """(sub, super) pairs as TeX scripts; an `<none/>` is an empty place."""
    places = ["" if e.tag == "none" else k for k, e in zip(kids, elements, strict=True)]
    out = []
    for sub, sup in zip(places[0::2], places[1::2], strict=False):
        out.append((f"_{{{sub}}}" if sub else "") + (f"^{{{sup}}}" if sup else ""))
    return "{}".join(out)


def _multiscripts(node: Node, kids: list[str]) -> str:
    """A tensor: the base with scripts after it, and those before it after `<mprescripts/>`."""
    elements = node.elements()
    split = next((i for i, e in enumerate(elements) if e.tag == "mprescripts"), len(elements))
    post = _scripts(kids[1:split], elements[1:split])
    pre = _scripts(kids[split + 1 :], elements[split + 1 :])
    return (f"{{}}{pre}" if pre else "") + _base(kids[0]) + post


def _mathml(node: Node, variant: str | None = None) -> str:
    """TeX-like text for a MathML element. `variant` is the `mathvariant` it inherits."""
    variant = node.attrs.get("mathvariant", variant)  # a token's own, or an mstyle's
    kids = [_mathml(c, variant) for c in node.elements()]
    tag = node.tag
    if tag in {"mi", "mn", "mo"}:
        raw = node.text().strip()
        token = _tex_token(raw)
        letter = tag in {"mi", "mn"}  # an operator has no variant in TeX
        upright = tag == "mi" and (variant == "normal" or (variant is None and len(raw) > 1))
        template = (letter and _VARIANTS.get(variant or "")) or (
            "\\mathrm{{{}}}" if upright else ""
        )
        return template.format(token) if template and token else token
    if tag in {"mtext", "ms"}:
        # Spaces in text are kept (a no-break space is a space); only runs of them are joined.
        words = re.sub(r"[ \t\r\n\f\v\u00a0]+", " ", node.text())
        return f"\\text{{{_tex_token(words)}}}" if words.strip() else ""
    if tag in {"msub", "msup"} and len(kids) == 2:
        return f"{_base(kids[0])}{'_' if tag == 'msub' else '^'}{{{kids[1]}}}"
    if tag == "msubsup" and len(kids) == 3:
        return f"{_base(kids[0])}_{{{kids[1]}}}^{{{kids[2]}}}"
    if tag == "mfrac" and len(kids) == 2:
        if node.attrs.get("linethickness", "").strip() in {"0", "0px", "0pt", "0em"}:
            return f"{{{kids[0]} \\atop {kids[1]}}}"  # no bar: a binomial coefficient
        return f"\\frac{{{kids[0]}}}{{{kids[1]}}}"
    if tag == "msqrt":
        return f"\\sqrt{{{''.join(kids)}}}"
    if tag == "mmultiscripts" and len(kids) >= 1:
        return _multiscripts(node, kids)
    if tag == "menclose":
        notation = set(node.attrs.get("notation", "").split())
        body = "".join(kids)
        if {"updiagonalstrike", "downdiagonalstrike"} <= notation:
            return f"\\xcancel{{{body}}}"
        if "updiagonalstrike" in notation:
            return f"\\cancel{{{body}}}"
        if "downdiagonalstrike" in notation:
            return f"\\bcancel{{{body}}}"
        if "box" in notation:
            return f"\\boxed{{{body}}}"
        return body
    if tag == "mphantom":  # takes up space but is not drawn
        return f"\\phantom{{{''.join(kids)}}}"
    if tag == "mtable":
        if any(c.tag == "mlabeledtr" for c in node.elements()):  # numbered equations
            return "\\begin{align} " + " \\\\ ".join(kids) + " \\end{align}"
        return "\\begin{matrix} " + " \\\\ ".join(kids) + " \\end{matrix}"
    if tag == "mtr":
        return " & ".join(kids)
    if tag == "mlabeledtr" and len(kids) >= 2:  # the first cell is the number
        number = node.elements()[0].text().strip().strip("()")
        return " & ".join(kids[1:]) + (f" \\tag{{{_tex_token(number)}}}" if number else "")
    if tag == "mroot" and len(kids) == 2:
        return f"\\sqrt[{kids[1]}]{{{kids[0]}}}"
    if tag == "munderover" and len(kids) == 3:
        return f"{_base(kids[0])}_{{{kids[1]}}}^{{{kids[2]}}}"
    if tag == "mover" and len(kids) == 2:
        accent = _ACCENTS.get(node.elements()[1].text().strip())
        if accent:  # a hat or arrow over the base, not a limit above it
            return f"{accent}{{{kids[0]}}}"
    if tag == "munder" and len(kids) == 2 and node.elements()[1].text().strip() in _UNDERLINES:
        return f"\\underline{{{kids[0]}}}"
    if tag in {"munder", "mover"} and len(kids) == 2:
        return f"{_base(kids[0])}{'_' if tag == 'munder' else '^'}{{{kids[1]}}}"
    return "".join(kids)


def _math(node: Node) -> str:
    """A MathJax container as `$…$` (or `$$…$$` for display math), from its assistive MathML."""
    assistive = node.find("mjx-assistive-mml")
    math = assistive.find("math") if assistive else None
    if math is None:
        return node.text().strip()
    tex = _mathml(math)
    if not tex.strip():
        return ""  # nothing is drawn
    return f"$${tex}$$" if node.attrs.get("display") == "true" else f"${tex}$"


# Characters Markdown would read as markup. Brackets matter only before a `(`, and `&` only when
# it starts an entity (`&copy;`), so a bare `[1]` or `R&D` stays as the page showed it.
_BREAK = "\x00"  # stands for a <br> until the block holding it is finished
_ESCAPE = re.compile(r"([\\`*_<$~]|\](?=\()|&(?=#?[A-Za-z0-9]+;))")
_ESCAPE_BRACKETS = re.compile(r"([\\`*_<$~\[\]]|&(?=#?[A-Za-z0-9]+;))")  # in a label


def _escape(text: str, brackets: bool = False) -> str:
    """`text` with the characters that Markdown would read as markup escaped, so that it renders
    as the page showed it (a rendered `<mask>` is text, not an HTML tag). In a link label or
    image alt text (`brackets`) a bracket is markup too; one pass, so a backslash and a bracket
    are each escaped once."""
    return (_ESCAPE_BRACKETS if brackets else _ESCAPE).sub(r"\\\1", text)


_BULLET_OR_QUOTE = re.compile(r"^( {0,3})(#{1,6}(?=\s|$)|>|[-+](?=\s|$))", re.MULTILINE)
_NUMBERED = re.compile(r"^( {0,3})(\d+)([.)])(?=\s|$)", re.MULTILINE)
_RULE_OR_UNDERLINE = re.compile(r"^( {0,3})([-=])(?=[-= \t]*\\?$)", re.MULTILINE)


def _paragraph(text: str) -> str:
    """A paragraph's text with a line-start `#`, `-`, `1.`, `>`, `---` or `===` escaped, so
    that it stays text and does not become a heading, list, quote or rule."""
    text = _BULLET_OR_QUOTE.sub(r"\1\\\2", text)
    return _RULE_OR_UNDERLINE.sub(r"\1\\\2", _NUMBERED.sub(r"\1\2\\\3", text))


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in re.findall(r"`+", text)), default=0)


def _code_span(code: str) -> str:
    """Inline code between backticks longer than any run inside it."""
    ticks = "`" * (_longest_backtick_run(code) + 1)
    # Markdown drops one space from each end of code that has a space at both, so add one.
    spaced = code.startswith(" ") and code.endswith(" ") and code.strip()
    pad = " " if code.startswith("`") or code.endswith("`") or spaced else ""
    return f"{ticks}{pad}{code}{pad}{ticks}"


def _image(alt: str, src: str) -> str:
    """`![alt](src)`, with the alt text escaped and a source that has spaces or brackets in <>."""
    alt = _escape(alt, brackets=True)
    return f"![{alt}]({_destination(src)})"


def _destination(url: str) -> str:
    """A link destination, in <> when it has spaces or brackets that would end it early."""
    url = re.sub(r"&(?=#?[A-Za-z0-9]+;)", r"\\&", url)  # else "&amp;" is read as "&"
    if re.search(r"[\s()<>]", url):
        return "<" + url.replace("<", "%3C").replace(">", "%3E").replace(" ", "%20") + ">"
    return url


def _inline(node: Node, in_link: bool = False) -> str:
    """`in_link`: the text is a link's label, so its own brackets are escaped."""
    out: list[str] = []
    for position, child in enumerate(node.children):
        if isinstance(child, str):
            out.append(_escape(re.sub(r"\s+", " ", child.replace(_BREAK, "")), in_link))
            continue
        tag = child.tag
        if tag == "mjx-container":
            out.append(_math(child))
        elif tag in {"strong", "b"}:
            out.append(_wrap("**", _inline(child, in_link)))
        elif tag in {"sup", "sub"}:  # Markdown has none; inline HTML keeps them
            out.append(f"<{tag}>{_inline(child, in_link)}</{tag}>")
        elif tag in {"del", "s", "strike"}:
            out.append(_wrap("~~", _inline(child, in_link)))
        elif tag in {"em", "i"}:
            out.append(_wrap("*", _inline(child, in_link)))
        elif tag == "code":
            out.append(_code_span(child.text()))
        elif tag == "input" and child.attrs.get("type") == "checkbox":
            box = "[x]" if "checked" in child.attrs else "[ ]"  # a task list item
            after = node.children[position + 1 : position + 2]
            out.append(
                box if after and isinstance(after[0], str) and after[0][:1].isspace() else box + " "
            )
        elif tag == "br":
            out.append(_BREAK)  # a hard break, written when the block is finished
        elif tag == "a":
            raw, href = _inline(child, True), child.attrs.get("href", "")
            edge = f" \t\n{_BREAK}"  # edge spaces and breaks stay outside the link
            label = raw.strip(edge)
            lead, trail = raw[: len(raw) - len(raw.lstrip(edge))], raw[len(raw.rstrip(edge)) :]
            if not href or (re.match(r"https?://", href) and child.text().strip() == href):
                link = href or label  # a bare web address stands for itself
            else:
                link = f"[{label}]({_destination(href)})"
            out.append(f"{lead}{link}{trail}" if label else raw)
        elif tag == "img":
            alt, src = child.attrs.get("alt", ""), child.attrs.get("src", "")
            out.append(_image(alt, src) if src else _escape(alt, in_link))
        else:
            out.append(_inline(child, in_link))
    return "".join(out)


def _wrap(mark: str, text: str) -> str:
    """`text` between `mark`s, with its edge spaces and breaks left outside them."""
    edge = f" \t\n{_BREAK}"
    inner = text.strip(edge)
    if not inner:
        return text
    lead = text[: len(text) - len(text.lstrip(edge))]
    trail = text[len(text.rstrip(edge)) :]
    return f"{lead}{mark}{inner}{mark}{trail}"


def _finish(text: str, hard_break: str = "\\\n") -> str:
    """The text of a finished block: no space or break at its ends, breaks written out."""
    return text.strip(f" \t\n{_BREAK}").replace(_BREAK, hard_break)


_BLOCKS = {"p", "ul", "ol", "li", "blockquote", "pre", "table", "hr", "div"} | {
    f"h{n}" for n in range(1, 7)
}


def _blocks(node: Node, indent: str = "") -> list[str]:
    """The Markdown blocks of an element's children."""
    blocks: list[str] = []
    run = Node("span")  # consecutive inline children, joined into one paragraph
    for child in node.children:
        if isinstance(child, Node) and child.tag in _BLOCKS:
            _flush(run, blocks, indent)
            run = Node("span")
            blocks.extend(_block(child, indent))
        else:
            run.children.append(child)
    _flush(run, blocks, indent)
    return blocks


def _indented(text: str, indent: str) -> str:
    """`text` with `indent` before every line, so a hard break stays inside its list item."""
    return "\n".join(f"{indent}{line}" for line in text.split("\n"))


def _flush(run: Node, blocks: list[str], indent: str) -> None:
    text = _paragraph(_finish(_inline(run)))
    if text:
        blocks.append(_indented(text, indent))


def _block(node: Node, indent: str) -> list[str]:
    tag = node.tag
    if tag == "p":
        text = _paragraph(_finish(_inline(node)))
        return [_indented(text, indent)] if text else []
    if re.fullmatch(r"h[1-6]", tag):
        return [f"{indent}{'#' * int(tag[1])} {_finish(_inline(node))}"]
    if tag in {"ul", "ol"}:
        return ["\n".join(_list(node, indent))]
    if tag == "blockquote":
        quoted = "\n\n".join(_blocks(node)).splitlines()
        return ["\n".join(f"{indent}> {line}".rstrip() for line in quoted)]
    if tag == "pre":
        code = node.text().strip("\n")
        fence = "`" * max(3, _longest_backtick_run(code) + 1)
        lines = [fence, *code.split("\n"), fence]
        return ["\n".join(f"{indent}{line}" if line else "" for line in lines)]
    if tag == "hr":
        return [f"{indent}---"]
    if tag == "table":
        return _table(node, indent)
    return _blocks(node, indent)


def _start(node: Node) -> int:
    """The number an ordered list starts at: its `start` attribute, else 1."""
    try:
        return int(node.attrs.get("start", "1"))
    except ValueError:
        return 1


def _list(node: Node, indent: str) -> list[str]:
    lines: list[str] = []
    number = _start(node)
    for item in node.elements():
        if item.tag != "li":
            continue
        marker = f"{number}." if node.tag == "ol" else "-"
        number += 1
        pad = indent + " " * (len(marker) + 1)
        parts = _blocks(item, pad)
        first = parts[0][len(pad) :] if parts else ""
        lines.append(f"{indent}{marker} {first}")
        for part in parts[1:]:
            if not _ITEM.match(part.lstrip()):  # a paragraph, not a nested list
                lines.append("")
            lines.append(part)
    return lines


def _table(node: Node, indent: str) -> list[str]:
    rows = [
        [_finish(_inline(cell), "<br>").replace("|", "\\|") for cell in row.elements()]
        for row in node.find_all("tr")
    ]
    rows = [r for r in rows if r]
    if not rows:
        return []
    lines = [f"{indent}| " + " | ".join(r) + " |" for r in rows]
    lines.insert(1, f"{indent}|" + " --- |" * len(rows[0]))
    return ["\n".join(lines)]


def to_markdown(node: Node) -> str:
    """The Markdown that OpenReview rendered into `node`."""
    return "\n\n".join(_blocks(node)).strip()


# --- The forum page -------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_SHOWN_DATE = re.compile(r"(\d{1,2}) ([A-Za-z]{3,})\.? (\d{4}), (\d{1,2}):(\d{2})")


@dataclass
class Field:
    """One labelled value in a note, as the page shows it: `Quality: 2: fair`."""

    label: str
    value: str  # Markdown for rendered text, plain text otherwise

    @property
    def key(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.label.casefold()).strip("_")


@dataclass
class Note:
    id: str
    parent_id: str | None  # the note this one replies to; None for a reply to the submission
    heading: str
    reply_type: str  # "Official Review", "Rebuttal", "Official Comment", ...
    signature: str  # who signed it, as shown: "Reviewer muqa", "Authors"
    created: str  # the date line as shown: "03 Jul 2025, 02:28 (modified: 28 Oct 2025, 20:28)"
    readers: str
    fields: list[Field]

    def get(self, label: str) -> str | None:
        wanted = label.casefold()
        return next((f.value for f in self.fields if f.label.casefold() == wanted), None)

    def dates(self, tz: tzinfo) -> tuple[datetime | None, datetime | None]:
        """When the note was created and last modified, read in the time zone `tz`."""
        found = [_shown_date(m, tz) for m in _SHOWN_DATE.finditer(self.created)]
        found = [d for d in found if d]
        return (found[0] if found else None, found[1] if len(found) > 1 else None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "replyto": self.parent_id,
            "heading": self.heading,
            "reply_type": self.reply_type,
            "signature": self.signature,
            "created": self.created,
            "readers": self.readers,
            "content": {f.label: f.value for f in self.fields},
        }


@dataclass
class Forum:
    id: str
    url: str
    title: str
    authors: list[dict[str, str]]  # name, and profile when the page links one
    venue: str | None  # the conference, as in the page's citation metadata
    venue_id: str | None  # OpenReview's ID for it: "NeurIPS.cc/2025/Conference"
    venue_label: str | None  # the submission's outcome line: "NeurIPS 2025 oral"
    pdf_url: str | None
    fields: list[Field]  # Keywords, TL;DR, Abstract, ...
    notes: list[Note]
    sha256: str  # of the HTML read, to say which saved page this came from

    def get(self, label: str) -> str | None:
        wanted = label.casefold()
        return next((f.value for f in self.fields if f.label.casefold() == wanted), None)

    def note_url(self, note_id: str) -> str:
        return f"https://openreview.net/forum?id={quote(self.id)}&noteId={quote(note_id)}"

    def replies(self, note_id: str) -> list[Note]:
        """Every note below `note_id` in the thread, in page order."""
        below = {note_id}
        found = []
        for note in self.notes:
            if note.parent_id in below:
                below.add(note.id)
                found.append(note)
        return found


def _shown_date(match: re.Match[str], tz: tzinfo) -> datetime | None:
    day, month, year, hour, minute = match.groups()
    number = _MONTHS.get(month[:3].casefold())
    if not number:
        return None
    return datetime(int(year), number, int(day), int(hour), int(minute), tzinfo=tz)


def _tz_name(tz: tzinfo) -> str:
    return getattr(tz, "key", None) or tz.tzname(None) or str(tz)


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_note(node: Node) -> bool:
    return "note" in node.classes() and "data-id" in node.attrs


def _fields(content: Node | None) -> list[Field]:
    """The label and value of each field in a `.note-content` block."""
    found = []
    for row in content.elements() if content else []:
        label = row.find("strong", "note-content-field")
        value = row.find(None, "note-content-value")
        if label is None or value is None:
            continue
        text = (
            to_markdown(value)
            if "markdown-rendered" in value.classes()
            else _finish(_inline(value))
        )
        found.append(Field(label.text().strip().rstrip(":").strip(), text.strip()))
    return found


def _note(node: Node) -> Note:
    parent = node.parent
    while parent is not None and not _is_note(parent):
        parent = parent.parent
    # Replies nest inside their parent's element, so look only at this note's own parts.
    heading = node.find("h4", stop=_is_note)
    invitation = node.find("span", "invitation", stop=_is_note)
    signatures = node.find("span", "signatures", stop=_is_note)
    created = node.find("span", "created-date", stop=_is_note)
    readers = node.find("span", "readers", stop=_is_note)
    return Note(
        id=node.attrs["data-id"],
        parent_id=parent.attrs["data-id"] if parent else None,
        heading=_squash(heading.text()) if heading else "",
        reply_type=_squash(invitation.text()) if invitation else "",
        signature=re.sub(r"^by\s+", "", _squash(signatures.text())) if signatures else "",
        created=_squash(created.text()) if created else "",
        readers=_squash(readers.text()) if readers else "",
        fields=_fields(node.find("div", "note-content", stop=_is_note)),
    )


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _forum_id(meta: dict[str, str], root: Node) -> str:
    candidates = [meta.get("citation_pdf_url", "")]
    candidates += [a.attrs.get("href", "") for a in root.find_all("a", "citation_pdf_url")]
    candidates += [
        unquote(a.attrs.get("data-bibtex", ""))
        for a in root.find_all("a")
        if "data-bibtex" in a.attrs
    ]
    for candidate in candidates:
        found = re.search(r"[?&]id=([\w-]+)", candidate)
        if found:
            return found.group(1)
    raise ValueError("Not an OpenReview forum page: no forum ID in its PDF link or BibTeX")


def _is_local(url: str) -> bool:
    """Whether `url` is a path beside the saved page, not a link, an absolute path or a fragment."""
    return bool(url) and not re.match(r"([a-z][a-z0-9+.-]*:|/|#|\?)", url, re.IGNORECASE)


def _rebase_images(root: Node, base: str) -> None:
    """Point each image saved beside the page (a relative `src`), and a link around one, at
    `base`, a path from where the review will be kept to the page's own folder."""
    prefix = base.rstrip("/")
    if not prefix:
        return
    links: list[Node] = []  # each link around an image, once however many images it holds
    for img in root.find_all("img"):
        if _is_local(img.attrs.get("src", "")):
            img.attrs["src"] = f"{prefix}/{img.attrs['src']}"
        link = img.parent
        while link is not None and link.tag != "a":
            link = link.parent
        if link is not None and not any(link is seen for seen in links):
            links.append(link)
    for link in links:
        if _is_local(link.attrs.get("href", "")):
            link.attrs["href"] = f"{prefix}/{link.attrs['href']}"


def parse_forum_page(html: str, *, asset_base: str | None = None) -> Forum:
    """Read a saved OpenReview forum page (the submission and its replies).

    A page saved with its files has image `src`s relative to the page. `asset_base`, a URL path
    from where the reviews will be kept to the page's folder, makes them resolve from there."""
    builder = _Builder()
    builder.feed(html)
    builder.close()
    root = builder.root
    if asset_base:
        _rebase_images(root, asset_base)
    meta: dict[str, str] = {}
    for tag in builder.meta:
        if tag.get("name") and tag["name"] not in meta:
            meta[tag["name"]] = tag.get("content", "")
    authors = [{"name": m["content"]} for m in builder.meta if m.get("name") == "citation_author"]
    forum_id = _forum_id(meta, root)

    forum_note = root.find("div", "forum-note")
    title = forum_note.find("h2", "citation_title") if forum_note else None
    for link in forum_note.find_all("a") if forum_note else []:
        profile = urlsplit(link.attrs.get("href", ""))
        if profile.path == "/profile":
            name = _squash(link.text())
            for author in authors:
                if author["name"] == name and "profile" not in author:
                    author["profile"] = parse_qs(profile.query).get("id", [""])[0]
    items = [_squash(i.text()) for i in forum_note.find_all("span", "item")] if forum_note else []
    banner = root.find("div", "banner")
    group = None
    for link in banner.find_all("a") if banner else []:
        group = parse_qs(urlsplit(link.attrs.get("href", "")).query).get("id", [None])[0]

    replies = next((n for n in root.walk() if n.attrs.get("id") == "forum-replies"), None)
    notes = [_note(n) for n in replies.find_all("div") if _is_note(n)] if replies else []
    return Forum(
        id=forum_id,
        url=f"https://openreview.net/forum?id={forum_id}",
        title=_squash(title.text()) if title else meta.get("citation_title", ""),
        authors=authors,
        venue=meta.get("citation_conference_title") or None,
        venue_id=group,
        venue_label=next((i for i in items if re.search(r"\b20\d\d\b", i) and ":" not in i), None),
        pdf_url=meta.get("citation_pdf_url") or None,
        fields=_fields(forum_note.find("div", "note-content") if forum_note else None),
        notes=notes,
        sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
    )


# --- Mapping a review to OCRS ---------------------------------------------------------------

# OpenReview's own words for a recommendation, as the first words of a rating's label
# ("5: Accept: Technically solid paper, ..." and "6: marginally above the acceptance threshold").
_RECOMMENDATIONS = {
    "strong accept": "strong_accept",
    "accept": "accept",
    "weak accept": "weak_accept",
    "borderline": "borderline",
    "borderline accept": "weak_accept",
    "marginally above the acceptance threshold": "weak_accept",
    "borderline reject": "weak_reject",
    "weak reject": "weak_reject",
    "marginally below the acceptance threshold": "weak_reject",
    "reject": "reject",
    "strong reject": "strong_reject",
}
# Scores whose names the metric catalog does not know.
_METRIC_KEYS = {"quality": "correctness", "soundness": "correctness", "rating": "overall"}
_HEADING = re.compile(r"^(?:#{1,6}\s*)?(?:\*\*|__)?([^*_#\n][^*\n]{0,60}?)(?:\*\*|__)?:?\s*$")
# Fields that hold the reviewer's text, which may start with a number.
_PROSE_FIELDS = {
    "summary",
    "strengths and weaknesses",
    "strengths",
    "weaknesses",
    "questions",
    "limitations",
    "paper formatting concerns",
    "ethical concerns",
    "final justification",
    "review",
    "main review",
    "detailed review",
    "comments",
    "comment",
    "rebuttal",
}
_SCORE = re.compile(r"\s*[+-]?\d+(?:\.\d+)?\s*(?::.*)?", re.DOTALL)
# Headings after which the points of "Strengths" or "Weaknesses" do not continue.
_ENDS_FINDINGS = re.compile(
    r"\W*(?:references?|bibliography|summary|conclusions?|recommendations?)\W*", re.IGNORECASE
)
# A Markdown heading of any length; the others (`Weaknesses:`, `**Weaknesses**`) must be short.
_ATX = re.compile(r"^#{1,6}\s+(?:\*\*|__)?(.+?)(?:\*\*|__)?:?(?:\s+#+)?\s*$")
# A label in nested emphasis: `***Weaknesses***`, `**_Weaknesses_**`.
_EMPHASISED = re.compile(r"^([*_]{1,3})([^*_\n][^*\n]{0,60}?)([*_]{1,3}):?\s*$")
_ITEM = re.compile(r"^(?:\d+[.)]|[-*•])\s+(.*)$")
_BOLD_LEAD = re.compile(r"^\*\*(.+?)\*\*\s*[:.]?\s*(\S.*)$", re.DOTALL)


def _unescape(text: str) -> str:
    return re.sub(r"\\([^\w\s])", r"\1", text)


def _finding_kind(heading: str) -> tuple[str, str | None] | None:
    """The findings list a heading in "Strengths And Weaknesses" belongs to, and its severity.

    Whole words only: "Minority-group evaluation" and "Areas to strengthen" name neither."""

    def has(pattern: str) -> bool:
        return bool(re.search(rf"\b(?:{pattern})\b", heading, re.IGNORECASE))

    if has("strengths?"):  # before "minor": "Minor strengths" are strengths
        return "strengths", None
    if has("questions?"):  # likewise "Minor questions"
        return "questions", None
    if has("minor|typos?"):
        return "weaknesses", "minor"
    if has("weakness(?:es)?|concerns?|limitations?"):
        return "weaknesses", None
    return None


def _sections(markdown: str) -> list[tuple[str | None, int | None, list[str]]]:
    """Split Markdown into (heading, level, lines) at heading lines and at short lines like
    `Weaknesses:`. The level is the number of #s of a Markdown heading, None for the others.

    Text before the first heading has the heading None."""
    sections: list[tuple[str | None, int | None, list[str]]] = [(None, None, [])]
    fences = Fences(lists=True)
    for line in markdown.splitlines():
        if fences.inside(line):  # code is content, whatever it looks like
            sections[-1][2].append(line)
            continue
        # A label followed by a <br> ends in a hard-break marker, which is not part of it.
        run = len(line) - len(line.rstrip("\\"))
        label_line = line[:-1] if run % 2 else line  # an odd run ends in a hard-break marker
        is_atx = bool(_ATX.match(label_line))
        found = None
        if label_line == label_line.lstrip() and not label_line.startswith(">"):  # not quoted
            found = (_ATX if is_atx else _HEADING).match(label_line.strip())
            if not found:
                found = _EMPHASISED.match(label_line.strip())
        is_label = bool(found) and (
            is_atx or label_line.rstrip().endswith(":") or label_line.startswith(("**", "__"))
        )
        text = ""
        if found:  # the label's text: group 1, or group 2 of a label in nested emphasis
            text = found.group(2) if found.re is _EMPHASISED else found.group(1)
        # A bold line that asks something is a question, not a heading.
        is_question = bool(found) and not is_atx and text.rstrip().endswith("?")
        if found and is_label and not is_question and not _ITEM.match(label_line):
            level = len(label_line) - len(label_line.lstrip("#")) if is_atx else None
            sections.append((_unescape(_squash(text)), level, []))
        else:
            sections[-1][2].append(line)
    return sections


def _outdent(line: str, width: int) -> str:
    """`line` without the indentation of its list item's text, keeping any further indentation."""
    indent = len(line) - len(line.lstrip(" "))
    return line[min(width, indent) :].rstrip()


def _items(lines: list[str]) -> list[str]:
    """The points in a section: its list items, or else its paragraphs (verbatim Markdown)."""
    items: list[list[str]] = []
    widths: list[int] = []  # each item's marker width, which its continuation lines are indented by
    paragraphs: list[list[str]] = [[]]
    in_item = False
    blank_before = False  # a blank line since the last line of the open item
    fences = Fences(lists=True)
    for line in lines:
        item = _ITEM.match(line)
        opened = fences.open is not None
        # Code stays whole, inside the point it belongs to. A list marker that opens a fence
        # ("2. ```") still starts a point; lines inside an open fence are always code.
        if fences.inside(line) and (opened or not item):
            if items and (in_item or line.startswith((" ", "\t"))):
                if blank_before:
                    items[-1].append("")
                blank_before = False
                items[-1].append(_outdent(line, widths[-1]))
                in_item = True
            else:
                paragraphs[-1].append(line.rstrip())
            continue
        if item:
            items.append([item.group(1)])
            widths.append(item.start(1))
            in_item = True
            blank_before = False
        elif not line.strip():
            blank_before = in_item or blank_before
            in_item = False
            if paragraphs[-1]:
                paragraphs.append([])
        elif in_item or (items and line.startswith((" ", "\t"))):
            if blank_before:  # a paragraph or block after a blank line, still in the item
                items[-1].append("")
            items[-1].append(_outdent(line, widths[-1]))  # a wrapped line or a nested list
            in_item = True
            blank_before = False
        else:
            paragraphs[-1].append(line.strip())
            blank_before = False
    # With no list, each paragraph is a point, except a lead-in such as "Please answer:".
    chosen = items or [p for p in paragraphs if p and not p[-1].rstrip().endswith(":")]
    return ["\n".join(part).strip() for part in chosen]


def _point(text: str, ident: str) -> dict[str, Any]:
    point: dict[str, Any] = {"id": ident, "text": text}
    lead = _BOLD_LEAD.match(text)
    if lead:
        point["title"] = _squash(lead.group(1)).rstrip(":.")
    return point


def _recommendation(label: str | None) -> str | None:
    if not label:
        return None
    first = label.split(":")[0].split(",")[0].strip().casefold()
    return _RECOMMENDATIONS.get(first)


def _signature_mode(signature: str) -> str:
    """How the reviewer is identified. Only what the page affirms is taken as disclosed: a
    pseudonym such as "Reviewer abcd", or an OpenReview profile ID ("~Jane_Doe1"). A signature
    that is neither is treated as confidential, so no identity is assumed to be public."""
    if re.fullmatch(r"(?:Reviewer|Area Chair|Senior Area Chair)\s+\w+", signature):
        return "pseudonymous"
    return "open" if re.fullmatch(r"~[\w.-]+", signature) else "confidential"


class _Links:
    """Which page field each OCRS value came from."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []
        self.used: set[str] = set()

    def add(self, ocrs: str, label: str, how: str = "copied", **extra: str) -> None:
        self.entries.append({"ocrs": ocrs, "field": label, "how": how, **extra})
        self.used.add(label.casefold())


def _metric_key(name: str, aliases: dict[str, str], aspects: dict[str, str]) -> tuple[str, bool]:
    """The catalog key for a score's name, and whether it was matched loosely."""
    if name in _METRIC_KEYS:
        return _METRIC_KEYS[name], False
    if name in aliases:
        return aliases[name], False
    if name in aspects:
        return name, False
    key = match_alias(name, aliases)  # the OpenReview mapper's whole-word matching
    return (key, True) if key else ("other", False)


def _metrics(note: Note, links: _Links, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    aliases = alias_map(catalog)
    aspects = {m["key"]: m.get("aspect", "other") for m in catalog.get("metrics", [])}
    metrics = []
    for item in note.fields:
        number, label = parse_numeric_prefix(item.value)
        # A score is a number alone ("6") or a number and its label ("5: Accept"), not any
        # text that starts with a number.
        if number is None or not _SCORE.fullmatch(item.value):
            continue
        if not is_score_field(item.label) or item.label.casefold() in _PROSE_FIELDS:
            continue
        if "\n" in item.value:
            continue  # "1: Why was this omitted?" in Questions is a question, not a rating
        name = item.label.casefold()
        key, fuzzy = _metric_key(name, aliases, aspects)
        scale: dict[str, Any] = {"type": "ordinal"}
        if label:
            scale["anchors"] = [{"value": number, "label": label}]
        metrics.append(
            {
                "key": key,
                "label": item.label,
                "aspect": aspects.get(key, "other"),
                "scale": scale,
                "value": number,
            }
        )
        how = "lookup" if fuzzy or name in _METRIC_KEYS else "parsed"
        links.add(f"metrics[{len(metrics) - 1}]", item.label, how)
    return metrics


def _drop_replaced_labels(stack: list[tuple[Any, str, Any]], kind: Any) -> None:
    """Remove, from the first plain or bold label that a new one replaces, it and everything
    below it. A category label replaces any label; another label replaces unrecognised ones."""
    cut = next((i for i, e in enumerate(stack) if e[0] is None and (kind or e[2] is None)), None)
    if cut is not None:
        del stack[cut:]


def _findings(note: Note, links: _Links) -> dict[str, list[dict[str, Any]]]:
    findings: dict[str, list[dict[str, Any]]] = {}
    counters = {"strengths": "s", "weaknesses": "w", "questions": "q"}

    def add(kind: str, text: str, label: str, group: list[str], severity: str | None) -> None:
        points = findings.setdefault(kind, [])
        point = _point(text, f"{counters[kind]}{len(points) + 1}")
        if severity:
            point["severity"] = severity
        if group:
            point["group"] = group
        points.append(point)
        links.used.add(label.casefold())
        extra = {"heading": group[-1]} if group else {}
        how = "lookup" if severity else "copied"
        links.entries.append(
            {"ocrs": f"findings.{kind}[{len(points) - 1}]", "field": label, "how": how, **extra}
        )

    body = note.get("Strengths And Weaknesses")
    if body:
        # The headings the current section is under, outermost first: (level, text, kind), where
        # the kind is None for a heading that names no category. Only a heading of the same
        # or a shallower level than another ends it; plain and bold labels have no level and
        # replace only the labels before them.
        stack: list[tuple[int | None, str, tuple[str, str | None] | None]] = []
        for heading, level, lines in _sections(body):
            if not heading or _ENDS_FINDINGS.fullmatch(heading):
                stack = []  # text under a heading such as References is not a finding
                continue
            kind = _finding_kind(heading)
            if level is not None:
                # A heading ends the nearest heading of its level or deeper, and the labels
                # between; with none, only a label of another style beside it ends.
                cut = next(
                    (
                        i
                        for i, entry in enumerate(stack)
                        if entry[0] is not None and entry[0] >= level
                    ),
                    None,
                )
                if cut is not None:
                    del stack[cut:]
                else:
                    _drop_replaced_labels(stack, kind)
            else:  # a label replaces the label before it, and the headings below that one
                _drop_replaced_labels(stack, kind)
            if kind is None and not stack:
                continue  # beside or above the category: not a finding
            stack.append((level, heading, kind))
            category = next((k for _, _, k in reversed(stack) if k), None)
            if category is None:
                continue
            group = [text for _, text, _ in stack]
            for text in _items(lines):
                add(category[0], text, "Strengths And Weaknesses", group, category[1])
    for label, kind in (("Strengths", "strengths"), ("Weaknesses", "weaknesses")):
        text = note.get(label)  # a form with separate fields, after any combined field
        for point in _items(text.splitlines()) if text else []:
            add(kind, point, label, [], None)
    questions = note.get("Questions")
    if questions:
        # Not split at headings: a bold line here is a question, and a lead-in line is no heading.
        for text in _items(questions.splitlines()):
            add("questions", text, "Questions", [], None)
    return findings


def review_from_note(
    forum: Forum,
    note: Note,
    *,
    tz: tzinfo = UTC,
    keep_raw: bool = False,
    imported_at: str | None = None,
) -> dict[str, Any]:
    """Map one Official Review in `forum` to an OCRS review."""
    catalog = load_catalog()
    links = _Links()
    created, modified = note.dates(tz)
    lossiness = LOSSINESS_NOTES
    if created is None:
        lossiness += " The note shows no date, so created_at is the time of mapping."

    review: dict[str, Any] = {
        "$schema": schema_id(),
        "review_id": note.id,
        "version": "1.0.0",
        "created_at": utc_iso(created) if created else (imported_at or now_iso()),
    }
    if modified and modified != created:
        review["updated_at"] = utc_iso(modified)
    review["provenance"] = {
        "source_system": SOURCE_SYSTEM,
        "source_review_id": note.id,
        "source_url": forum.note_url(note.id),
        "imported_at": imported_at or now_iso(),
        "mapping": {
            "mapping_spec_id": "canonical-review.mapping.v1",
            "mapping_spec_version": "1.2.0",
            "mapper_version": MAPPER_VERSION,
            "lossiness_notes": lossiness,
        },
    }
    if keep_raw:
        review["provenance"]["raw_payload"] = note.as_dict()
    review["referees"] = [
        {
            "referee_type": "human",
            "identity_mode": _signature_mode(note.signature),
            **({"referee_id": note.signature} if note.signature else {}),
        }
    ]
    identifiers = {
        "internal_id": {
            "field_name": "openreview_forum",
            "value": forum.id,
            "hyperlink": forum.url,
        }
    }
    review["target"] = {
        "work_id": generate_canonical_work_id(identifiers),
        "identifiers": identifiers,
        "work_type": "proceedings_article",
        **({"title": forum.title} if forum.title else {}),
        **({"venue": forum.venue} if forum.venue else {}),
    }
    review["review_context"] = {"review_type": "initial", "stage": "pre_publication"}

    metrics = _metrics(note, links, catalog)
    if metrics:
        review["metric_catalog_ref"] = catalog.get("catalog_id")
        review["metrics"] = metrics

    decision: dict[str, Any] = {}
    rating = note.get("Rating")
    recommendation = _recommendation(parse_numeric_prefix(rating)[1]) if rating else None
    if recommendation:
        decision["recommendation"] = recommendation
        links.add("decision.recommendation", "Rating", "lookup")
    justification = note.get("Final Justification")
    if justification:
        decision["summary_rationale"] = justification
        links.add("decision.summary_rationale", "Final Justification")
    if decision:
        review["decision"] = decision

    summary = note.get("Summary")
    review["opinion"] = {"summary": summary} if summary else {}
    if summary:
        links.add("opinion.summary", "Summary")

    findings = _findings(note, links)
    if findings:
        review["findings"] = findings

    # The review's own text, each field as a part under the page's name for it
    narrative: list[dict[str, Any]] = []

    def part(label: str, role: str | None = None) -> None:
        links.add(f"narrative[{len(narrative)}]", label)
        narrative.append(section(note.get(label), title=label, role=role))

    for label, role in [
        ("Summary", "summary"),
        ("Strengths And Weaknesses", "review"),
        ("Questions", "questions"),
    ]:
        if note.get(label):
            part(label, role)
    if not any(p.get("role") == "review" for p in narrative):
        # Forms whose report is one field, as the API mapper reads
        label = next(
            (x for x in ("Review", "Main Review", "Detailed Review", "Comments") if note.get(x)),
            None,
        )
        if label:
            part(label, "review")
    # The separate Strengths and Weaknesses fields of some forms: whole, as findings take
    # only their points.
    for label in ("Limitations", "Paper Formatting Concerns", "Strengths", "Weaknesses"):
        if note.get(label):
            part(label)
    if narrative:
        review["narrative"] = narrative

    ethics = note.get("Ethical Concerns")
    if ethics:
        review["ethics_and_risk"] = {"notes": ethics}
        links.add("ethics_and_risk.notes", "Ethical Concerns")

    text = "\n".join(f.value for f in note.fields)
    review["text_format"] = {
        "markup": "markdown",
        "math": "tex" if re.search(r"(?<!\\)\$", text) else "none",
    }

    decision_note = next((n for n in forum.notes if n.reply_type == "Decision"), None)
    review["extensions"] = {
        "openreview": {
            "mapper_version": MAPPER_VERSION,
            "forum": {
                "id": forum.id,
                "url": forum.url,
                "title": forum.title,
                "authors": forum.authors,
                "venue_id": forum.venue_id,
                "venue_label": forum.venue_label,
                "keywords": forum.get("Keywords"),
                "pdf_url": forum.pdf_url,
                **(
                    {
                        "decision": {
                            "note_id": decision_note.id,
                            "url": forum.note_url(decision_note.id),
                            "decision": decision_note.get("Decision"),
                            "comment": decision_note.get("Comment"),
                        }
                    }
                    if decision_note
                    else {}
                ),
            },
            "note": {
                "id": note.id,
                "url": forum.note_url(note.id),
                "heading": note.heading,
                "reply_type": note.reply_type,
                "signature": note.signature,
                "created": note.created,
                "readers": note.readers,
                "replyto": note.parent_id,
            },
            "source_page": {
                "sha256": forum.sha256,
                "timezone_assumed": getattr(tz, "key", None) or tz.tzname(None) or str(tz),
            },
            "source_fields": links.entries,
            "unmapped_fields": {
                f.label: f.value for f in note.fields if f.label.casefold() not in links.used
            },
            "replies": [
                {**r.as_dict(), "url": forum.note_url(r.id)} for r in forum.replies(note.id)
            ],
        }
    }
    return review


def reviews_from_forum(
    forum: Forum,
    *,
    tz: tzinfo = UTC,
    keep_raw: bool = False,
    imported_at: str | None = None,
) -> list[dict[str, Any]]:
    """An OCRS review for each Official Review on the page, in page order."""
    return [
        review_from_note(forum, note, tz=tz, keep_raw=keep_raw, imported_at=imported_at)
        for note in forum.notes
        if note.reply_type == REVIEW_REPLY_TYPE
    ]


def reviews_from_forum_page(
    html: str,
    *,
    tz: tzinfo = UTC,
    keep_raw: bool = False,
    imported_at: str | None = None,
) -> list[dict[str, Any]]:
    """Map the Official Reviews on a saved OpenReview forum page to OCRS reviews.

    `tz` is the time zone to read the page's dates in, which the page does not state: use the one
    it was viewed in. Validate each review with `validate_canonical`."""
    return reviews_from_forum(
        parse_forum_page(html), tz=tz, keep_raw=keep_raw, imported_at=imported_at
    )


__all__ = [
    "Field",
    "Forum",
    "Note",
    "parse_forum_page",
    "review_from_note",
    "reviews_from_forum",
    "reviews_from_forum_page",
    "to_markdown",
    "utc_iso",
]
