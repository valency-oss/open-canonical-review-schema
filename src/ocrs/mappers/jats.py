# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Peer-review reports published as JATS `<sub-article>`s, as JATS4R recommends.

eLife, F1000Research, PeerJ, Copernicus and others publish each report, editor's assessment
and author response as a `<sub-article>` of the reviewed article's JATS XML. A payload is one
of them, with what the enclosing article says that the sub-article may not:

    {"sub_article": "<sub-article article-type=…>…</sub-article>",
     "article": {"doi": "10.7554/eLife.100443.2", "title": "…", "journal": "eLife"}}

`sub_articles` splits an article's XML into such payloads. The reader takes the report's type,
DOI, referee (name, ORCID, affiliation, or `<anonymous/>`), competing interests, date, the
version it reviews (`related-article`, else the article's DOI), its recommendation
(`custom-meta`) and its text: paragraphs, lists one item to a line, bold and italic as
Markdown, and the parts under headings such as "Summary:" as further parts of the narrative.
Its license goes in `provenance.license`, and its recommendation term in
`decision.source_label`. What OCRS has no field for is kept in `extensions.jats` so that
`to_jats` gives it back: the report's title, its license as the XML gives it, an eLife
Assessment's terms (`kwd-group`), the referee's role and name parts, and the author responses
nested in the report.
"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from ..identifiers import (
    DOI_PATTERN,
    generate_canonical_work_id,
    normalize_orcid,
    parse_canonical_work_id,
)
from ..schema import schema_id
from ..util import (
    first_paragraph,
    for_authors,
    narrative_parts,
    narrative_text,
    now_iso,
    section,
    source_decision,
    split_decision,
)

XLINK = "http://www.w3.org/1999/xlink"
HREF = f"{{{XLINK}}}href"
for _prefix, _uri in (
    ("xlink", XLINK),
    ("mml", "http://www.w3.org/1998/Math/MathML"),
    ("ali", "http://www.niso.org/schemas/ali/1.0/"),
):
    ET.register_namespace(_prefix, _uri)

# The kinds of sub-article and OCRS's review types. A referee's report is the default type
ARTICLE_TYPES = {
    "referee-report": None,
    "reviewer-report": None,
    "editor-report": "meta_review",
    "decision-letter": "recommendation",
    "author-comment": "author_comment",
    "reply": "author_comment",
    "response": "author_comment",
    "community-comment": "community_comment",
    "aggregated-review-documents": "aggregate",
}
REVIEW_TYPES = {
    "meta_review": "editor-report",
    "recommendation": "decision-letter",
    "author_comment": "author-comment",
    "community_comment": "community-comment",
    "aggregate": "aggregated-review-documents",
}
# Recommendations: F1000Research's statuses, and JATS4R's terms
RECOMMENDATIONS = {
    "approve": "accept",
    "approve-with-reservations": "weak_accept",
    "not-approved": "reject",
    "accept": "accept",
    "formal-accept": "accept",
    "accept-in-principle": "accept",
    "minor-revision": "minor_revision",
    "major-revision": "major_revision",
    "reject": "reject",
    "reject-with-resubmit": "revise",
    # OCRS's own grades, for those neither vocabulary has
    "strong-accept": "strong_accept",
    "borderline": "borderline",
    "weak-reject": "weak_reject",
    "strong-reject": "strong_reject",
}
TERMS = {
    "accept": "accept",
    "weak_accept": "approve-with-reservations",
    "minor_revision": "minor-revision",
    "major_revision": "major-revision",
    "reject": "reject",
    "revise": "reject-with-resubmit",
    "strong_accept": "strong-accept",
    "borderline": "borderline",
    "weak_reject": "weak-reject",
    "strong_reject": "strong-reject",
}
# The section titles that hold a kind of finding's text, as readers name them
FINDING_SECTIONS = {
    "strengths": {"strengths", "reasons to accept"},
    "weaknesses": {"weaknesses", "reasons to reject"},
    "questions": {"questions", "questions to authors"},
    "changes": {"requested changes"},
    "comments": {"comments"},
}
# Headings for findings, when they are all a review's text
FINDING_HEADINGS = {
    "strengths": "Strengths",
    "weaknesses": "Weaknesses",
    "questions": "Questions",
    "changes": "Requested changes",
    "comments": "Comments",
}
# An XML attribute name, with or without a namespace: what an extension may name
_ATTRIBUTE_NAME = re.compile(r"(?:\{[^{}\s<>\"']+\})?[A-Za-z_][A-Za-z0-9._-]*")
_NO_INTERESTS = re.compile(r"^\s*(?:no|none)\b", re.IGNORECASE)
_INTERESTS_LABEL = re.compile(r"^\s*competing interests\s*:\s*", re.IGNORECASE)
_ORDERED = re.compile(r"^\d+\.\s")
_BULLET = re.compile(r"^-\s")
_INLINE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
# A heading on a line of its own: "Summary:", "**Summary**:", "**Response to Reviewer #1:**"
_HEADING = re.compile(r"(?:\*\*)?([^\n]{1,60}?)(?::\*\*|\*\*:|:)")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _inline(element: ET.Element) -> str:
    """An element's text, bold as `**…**` and italic as `*…*`; other markup as its text."""
    parts = [element.text or ""]
    for child in element:
        inner = _inline(child)
        if child.tag == "bold" and inner.strip():
            inner = f"**{inner.strip()}**"
        elif child.tag == "italic" and inner.strip():
            inner = f"*{inner.strip()}*"
        parts += [inner, child.tail or ""]
    return "".join(parts)


def _item_text(item: ET.Element) -> str:
    """A list item as one line: its paragraphs, and the items of a list nested in it, joined
    with "; " (a line holds no nested list)."""
    if not len(item):
        return _squash(_inline(item))
    parts = [_squash(item.text or "")]
    for child in item:
        if child.tag == "list":
            parts.append("; ".join(_item_text(i) for i in child.findall("list-item")))
        else:
            parts.append(_squash(_inline(child)))
        parts.append(_squash(child.tail or ""))
    return " ".join(part for part in parts if part)


def _list_text(element: ET.Element) -> str:
    ordered = element.get("list-type") == "order"
    lines = []
    for number, item in enumerate(element.findall("list-item"), 1):
        text = _item_text(item)
        lines.append(f"{number}. {text}" if ordered else f"- {text}")
    return "\n".join(lines)


def _paragraph_blocks(paragraph: ET.Element) -> tuple[list[str], bool]:
    """A paragraph's blocks: its text, and each list in it with the text after it, in order,
    as F1000Research writes a list inside a paragraph. Also whether it held a list."""
    lists = paragraph.findall("list")
    if not lists:
        return [_squash(_inline(paragraph))], False
    blocks, run = [], ET.Element("p")
    run.text = paragraph.text
    for child in paragraph:
        if child.tag == "list":
            blocks += [_squash(_inline(run)), _list_text(child)]
            run = ET.Element("p")
            run.text = child.tail
        else:
            run.append(child)
    blocks.append(_squash(_inline(run)))
    return blocks, True


def _blocks(element: ET.Element) -> tuple[list[str], bool]:
    """The blocks of a body or section, in order: a paragraph to a block, a list's items one
    to a line, a quote's paragraphs as `> ` lines, and a section's title as a heading. Also
    whether its lists are inside paragraphs."""
    blocks: list[str] = []
    in_paragraphs = False
    for child in element:
        if child.tag == "p":
            found, has_list = _paragraph_blocks(child)
            blocks += found
            in_paragraphs = in_paragraphs or has_list
        elif child.tag == "list":
            blocks.append(_list_text(child))
        elif child.tag == "disp-quote":
            quoted = [_squash(_inline(p)) for p in child.findall("p")] or [_squash(_inline(child))]
            blocks.append("\n".join(f"> {line}" for line in quoted if line))
        elif child.tag == "sec":
            title = _squash(_inline(child.find("title"))) if child.find("title") is not None else ""
            if title:
                blocks.append(title if title.endswith(":") else f"{title}:")
            found, nested = _blocks(child)
            blocks += found
            in_paragraphs = in_paragraphs or nested
        elif child.tag != "title":
            blocks.append(_squash(_inline(child)))
    return blocks, in_paragraphs


def _body_text(body: ET.Element | None) -> tuple[str, bool]:
    """A body as text, and whether its lists are inside paragraphs."""
    blocks, in_paragraphs = _blocks(body) if body is not None else ([], False)
    return "\n\n".join(block for block in blocks if block), in_paragraphs


def _heading(block: str) -> str | None:
    found = _HEADING.fullmatch(block)
    return found.group(1).strip() if found else None


def _summary(text: str) -> str:
    """The text's first paragraph that is neither a heading nor a quote (an author response
    quotes the report it answers)."""
    blocks = [b for b in text.split("\n\n") if b.strip()]
    first = next((b for b in blocks if not _heading(b) and not b.startswith("> ")), text)
    return first_paragraph(first, max_len=500)


def _sections(text: str) -> list[dict[str, str]]:
    """The parts of a text under headings on lines of their own ("Summary:", "Strengths:")."""
    sections: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        if title := _heading(block):
            sections.append({"title": title, "content": ""})
        elif sections:
            content = sections[-1]["content"]
            sections[-1]["content"] = f"{content}\n\n{block}" if content else block
    return [s for s in sections if s["content"]]


def _text(element: ET.Element | None) -> str:
    return _squash("".join(element.itertext())) if element is not None else ""


def _affiliation(aff: ET.Element) -> str:
    """An affiliation's words without its label ("1"): its text, or its parts, such as its
    institution, city and country, joined with commas."""
    parts = [aff.text or ""]
    for child in aff:
        if child.tag != "label":
            parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    words = [_squash(part).strip(" ,") for part in parts]
    return ", ".join(word for word in words if word)


def _xml(element: ET.Element) -> str:
    """An element as XML, without the text that follows it in its parent."""
    element.tail = None
    return ET.tostring(element, encoding="unicode")


def _contributors(stub: ET.Element) -> list[dict[str, Any]]:
    group = stub.find("contrib-group")
    if group is None:
        return []
    affiliations = {aff.get("id"): aff for aff in group.findall("aff")}
    people = []
    for contrib in group.findall("contrib"):
        person: dict[str, Any] = {"anonymous": contrib.find("anonymous") is not None}
        name = contrib.find("name")
        if name is not None:
            person["surname"] = _text(name.find("surname"))
            person["given_names"] = _text(name.find("given-names"))
        role = contrib.find("role")
        if role is not None:
            person["role"] = {"text": _text(role), "specific_use": role.get("specific-use")}
        orcid = contrib.find("contrib-id[@contrib-id-type='orcid']")
        person["orcid_element"] = "contrib-id"
        if orcid is None:
            orcid = contrib.find("uri[@content-type='orcid']")
            person["orcid_element"] = "uri"
        if orcid is not None and normalize_orcid(_text(orcid)):
            person["orcid"] = normalize_orcid(_text(orcid))
        aff = contrib.find("aff")
        xref = contrib.find("xref[@ref-type='aff']")
        if aff is not None:
            person["affiliation"] = _affiliation(aff)
        elif xref is not None and xref.get("rid") in affiliations:
            referenced = affiliations[xref.get("rid")]
            person["affiliation"] = _affiliation(referenced)
            person["affiliation_ref"] = {
                "id": xref.get("rid"),
                "label": _text(referenced.find("label")),
            }
        people.append(person)
    return people


def _referee(person: dict[str, Any], interests: str | None) -> dict[str, Any]:
    names = [person.get("given_names"), person.get("surname")]
    name = " ".join(n for n in names if n)
    human = {"name": name} if name else {}
    for key in ("orcid", "affiliation"):
        if person.get(key):
            human[key] = person[key]
    mode = "open" if name else "single_blind" if person.get("anonymous") else "confidential"
    referee: dict[str, Any] = {
        "referee_type": "human",
        "identity_mode": mode,
        "human_referee": human,
    }
    if interests:
        referee["competing_interests_statement"] = interests
        referee["competing_interests_declared"] = not _NO_INTERESTS.match(interests)
    return referee


def from_jats(payload: dict[str, Any], *, keep_raw: bool = False) -> dict[str, Any]:
    """Map one `<sub-article>` (`payload["sub_article"]`, with `payload["article"]`) to OCRS."""
    element = ET.fromstring(payload["sub_article"])
    if element.tag != "sub-article":
        raise ValueError(f"Expected a <sub-article>, got <{element.tag}>")
    article = payload.get("article") or {}
    stub = element.find("front-stub")
    stub = stub if stub is not None else ET.Element("front-stub")
    kept: dict[str, Any] = {"article": article} if article else {}

    doi = _text(stub.find("article-id[@pub-id-type='doi']"))
    source_id = element.get("id")
    publisher_id = _text(stub.find("article-id[@pub-id-type='publisher-id']"))
    if publisher_id:
        kept["publisher_id"] = publisher_id
    article_type = element.get("article-type")
    if article_type:
        kept["article_type"] = article_type

    # The version reviewed: the report's related article, else the article it is part of
    related = stub.find("related-article")
    work_doi = related.get(HREF) if related is not None else None
    if related is not None:
        kept["related_article"] = {k: v for k, v in related.attrib.items() if k != HREF}
    work_doi = work_doi or article.get("doi")
    identifiers: dict[str, Any] = {}
    if isinstance(work_doi, str) and DOI_PATTERN.match(work_doi):
        identifiers["doi"] = {"value": work_doi, "hyperlink": f"https://doi.org/{work_doi}"}
    target: dict[str, Any] = {
        "identifiers": identifiers,
        "work_id": generate_canonical_work_id(identifiers),
        "work_type": "article",
    }
    for key, field in (("title", "title"), ("journal", "venue")):
        if isinstance(article.get(key), str) and article[key].strip():
            target[field] = article[key].strip()

    date = stub.find("pub-date")
    created = None
    if date is not None and date.findtext("year"):
        month, day = int(date.findtext("month") or 1), int(date.findtext("day") or 1)
        created = f"{int(date.findtext('year')):04d}-{month:02d}-{day:02d}T00:00:00Z"
        # A date without a type is still a date the writer gives back
        kept["pub_date"] = {"pub_type": date.get("pub-type")} if date.get("pub-type") else {}

    title = _text(stub.find("title-group/article-title"))
    if title:
        kept["title"] = title
    interests = None
    for note in stub.findall("author-notes/fn[@fn-type='conflict']"):
        interests = _INTERESTS_LABEL.sub("", _text(note)) or None
    people = _contributors(stub)
    if people:
        kept["contributors"] = [
            {k: v for k, v in p.items() if k not in ("orcid", "affiliation", "anonymous")}
            for p in people
        ]
    if stub.find("permissions") is not None:
        permissions = {
            "copyright_statement": _text(stub.find("permissions/copyright-statement")) or None,
            "copyright_year": _text(stub.find("permissions/copyright-year")) or None,
            "licenses": [
                {"url": license_.get(HREF), "text": _text(license_.find("license-p")) or None}
                for license_ in stub.findall("permissions/license")
            ],
        }
        kept["permissions"] = {k: v for k, v in permissions.items() if v}
    keywords = [
        {"type": group.get("kwd-group-type"), "terms": [_text(k) for k in group.findall("kwd")]}
        for group in stub.findall("kwd-group")
    ]
    if keywords:
        kept["keywords"] = keywords
    recommendation = None
    for meta in stub.findall("custom-meta-group/custom-meta"):
        name, value = _text(meta.find("meta-name")), _text(meta.find("meta-value"))
        if "recommendation" in name.casefold() and value:
            kept["recommendation"] = {"name": name, "value": value}
            recommendation = RECOMMENDATIONS.get(value.casefold())

    text, lists_in_paragraphs = _body_text(element.find("body"))
    if lists_in_paragraphs:
        kept["lists_in_paragraphs"] = True
    responses = [_xml(child) for child in element.findall("sub-article")]
    if responses:
        kept["responses"] = responses

    review: dict[str, Any] = {
        "$schema": schema_id(),
        "review_id": doi or source_id or publisher_id or str(uuid.uuid4()),
        "version": "1.0.0",
        "created_at": created or now_iso(),
        "provenance": {
            "source_system": "jats",
            "imported_at": now_iso(),
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.2.0",
                "mapper_version": "0.1.0",
            },
        },
        "target": target,
        "opinion": {"summary": _summary(text)} if text else {},
    }
    if doi and DOI_PATTERN.match(doi):
        review["provenance"]["review_doi"] = doi
    if source_id:
        review["provenance"]["source_review_id"] = source_id
    review["referees"] = [_referee(p, interests) for p in people] or [_referee({}, interests)]
    # The license the report is published under: its URL, else its statement
    licenses = (kept.get("permissions") or {}).get("licenses") or [{}]
    if licenses[0].get("url"):
        review["provenance"]["license"] = {"url": licenses[0]["url"]}
    elif licenses[0].get("text"):
        review["provenance"]["license"] = {"name": licenses[0]["text"]}
    review_type = ARTICLE_TYPES.get(article_type or "")
    if review_type:
        review["review_context"] = {"review_type": review_type}
    if text:
        # The report, then its parts under their headings
        review["narrative"] = [
            section(text, role="review"),
            *(section(s["content"], title=s["title"]) for s in _sections(text)),
        ]
    # The recommendation, and the term the report gives it ("approve-with-reservations")
    decision = {"recommendation": recommendation}
    if (kept.get("recommendation") or {}).get("value"):
        decision["source_label"] = kept["recommendation"]["value"]
    if decision := split_decision(decision):
        review["decision"] = decision
    if kept:
        review["extensions"] = {"jats": kept}
    if keep_raw:
        review["provenance"]["raw_payload"] = payload
    return review


# OCRS → JATS


def _add(parent: ET.Element, tag: str, text: str | None = None, **attrib: str) -> ET.Element:
    child = ET.SubElement(parent, tag, {k.replace("_", "-"): v for k, v in attrib.items()})
    if text is not None:
        child.text = text
    return child


def _add_inline(parent: ET.Element, text: str) -> None:
    """Text into an element, `**…**` as `<bold>` and `*…*` as `<italic>`."""
    last: ET.Element | None = None
    position = 0
    for match in _INLINE.finditer(text):
        before = text[position : match.start()]
        if last is None:
            parent.text = (parent.text or "") + before
        else:
            last.tail = (last.tail or "") + before
        last = ET.SubElement(parent, "bold" if match.group(1) else "italic")
        last.text = match.group(1) or match.group(2)
        position = match.end()
    rest = text[position:]
    if last is None:
        parent.text = (parent.text or "") + rest
    else:
        last.tail = (last.tail or "") + rest


def _body(text: str, lists_in_paragraphs: bool) -> ET.Element:
    body = ET.Element("body")
    for block in [b for b in text.split("\n\n") if b.strip()]:
        lines = block.split("\n")
        # A list of two or more items, numbered from 1: a numbered line alone is a paragraph
        ordered = len(lines) > 1 and all(
            line.startswith(f"{n}. ") for n, line in enumerate(lines, 1)
        )
        if all(line.startswith("> ") for line in lines):
            quote = _add(body, "disp-quote")
            for line in lines:
                _add_inline(_add(quote, "p"), line[2:])
        elif ordered or (len(lines) > 1 and all(_BULLET.match(line) for line in lines)):
            holder = _add(body, "p") if lists_in_paragraphs else body
            list_ = _add(holder, "list", list_type="order" if ordered else "bullet")
            for line in lines:
                item_text = line.split(" ", 1)[1] if " " in line else ""
                _add_inline(_add(_add(list_, "list-item"), "p"), item_text)
        else:
            _add_inline(_add(body, "p"), block)
    return body


def _write_contributor(
    group: ET.Element,
    referee: dict[str, Any],
    person: dict[str, Any],
    index: int,
    affiliations: dict[str, str],
    reserved: set[str],
) -> None:
    """One `<contrib>`. `affiliations` holds the referenced affiliations written so far, by
    ID: one that several contributors share is written once. `reserved` holds the IDs the
    source gave its affiliations, which a new one must not take."""
    human = referee.get("human_referee") or {}
    contrib = _add(group, "contrib", contrib_type="author")
    name = human.get("name")
    parts = [person.get("given_names"), person.get("surname")]
    if name and " ".join(p for p in parts if p) == name:
        surname, given = person.get("surname") or "", person.get("given_names") or ""
    elif name:
        given, _, surname = name.rpartition(" ")
    if name:
        name_ = _add(contrib, "name")
        _add(name_, "surname", surname)
        if given:
            _add(name_, "given-names", given)
    elif referee.get("identity_mode") == "single_blind":
        _add(contrib, "anonymous")
    reference = person.get("affiliation_ref") or {}
    aff_id = reference.get("id") or f"aff{index}"
    affiliation = human.get("affiliation")
    if reference and affiliations.get(aff_id) not in (None, affiliation):
        # The ID names another affiliation now: this one takes one of its own, or the one an
        # earlier contributor's changed affiliation took
        base = aff_id
        written = [
            i
            for i, a in affiliations.items()
            if a == affiliation and i.startswith(f"{base}-") and i not in reserved
        ]
        aff_id = written[0] if written else f"{base}-{index}"
        number = index
        while not written and (aff_id in affiliations or aff_id in reserved):
            number += 1
            aff_id = f"{base}-{number}"
    if affiliation and reference:
        _add(contrib, "xref", reference.get("label") or None, ref_type="aff", rid=aff_id)
    role = person.get("role") or {}
    if role.get("text"):
        attrib = {"specific_use": role["specific_use"]} if role.get("specific_use") else {}
        _add(contrib, "role", role["text"], **attrib)
    if human.get("orcid"):
        url = f"https://orcid.org/{human['orcid']}"
        if person.get("orcid_element") == "uri":
            _add(contrib, "uri", url, content_type="orcid")
        else:
            _add(contrib, "contrib-id", url, contrib_id_type="orcid")
    if affiliation:
        if reference and aff_id in affiliations:
            return
        if reference:
            affiliations[aff_id] = affiliation
            aff = _add(group, "aff", id=aff_id)
            if reference.get("label"):
                _add(aff, "label", reference["label"]).tail = human["affiliation"]
            else:
                aff.text = human["affiliation"]
        else:
            _add(contrib, "aff", human["affiliation"])


_MARKER = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")


def _items(text: str) -> set[str]:
    """The whole items of a text, as findings could be written in it: each line without its
    list marker, and each paragraph, with their spacing squashed."""
    lines = {_squash(_MARKER.sub("", line)) for line in text.splitlines()}
    paragraphs = {_squash(_MARKER.sub("", p)) for p in re.split(r"\n\s*\n", text)}
    return {item for item in lines | paragraphs if item}


def _findings_text(findings: dict[str, Any], held: dict[str, set[str]] | None = None) -> str:
    """Findings as text, for a review that has no other: each kind under its heading, a point
    to a line, with its title in bold. `held` holds, by kind, the items of the text the
    review already gives that kind's findings in (its sections): a point that is one of them
    is not written again."""
    blocks = []
    for kind, heading in FINDING_HEADINGS.items():
        lines = []
        for point in findings.get(kind) or []:
            if not isinstance(point, dict):
                continue
            words = " ".join(str(point.get("text") or "").split())
            if words and words in (held or {}).get(kind, set()):
                continue
            title = " ".join(str(point.get("title") or "").split())
            line = f"**{title}** {words}".strip() if title else words
            if line:
                lines.append(f"- {line}")
        if lines:
            blocks.append(f"{heading}:\n\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def to_jats(canonical: dict[str, Any]) -> dict[str, Any]:
    """An OCRS review as a JATS `<sub-article>` payload, as `from_jats` reads it.

    A review read from JATS gets back what OCRS has no field for (its title, license,
    assessment terms, recommendation term, the referee's role, nested responses) from
    `extensions.jats`; one from elsewhere is a referee report, or the sub-article type its
    review type names, with a JATS4R recommendation term."""
    kept = (canonical.get("extensions") or {}).get("jats") or {}
    context = canonical.get("review_context") or {}
    article_type = kept.get("article_type")
    if ARTICLE_TYPES.get(article_type or "", "missing") != context.get("review_type"):
        article_type = REVIEW_TYPES.get(context.get("review_type"), "referee-report")
    provenance = canonical.get("provenance") or {}
    element = ET.Element("sub-article", {"article-type": article_type})
    if provenance.get("source_review_id"):
        element.set("id", provenance["source_review_id"])
    stub = _add(element, "front-stub")
    doi = provenance.get("review_doi")
    if doi:
        _add(stub, "article-id", doi, pub_id_type="doi")
    # A review with neither a DOI nor a sub-article ID keeps its own ID as the publisher's
    publisher_id = kept.get("publisher_id")
    if not publisher_id and not doi and not provenance.get("source_review_id"):
        publisher_id = canonical.get("review_id")
    if publisher_id:
        _add(stub, "article-id", publisher_id, pub_id_type="publisher-id")
    if kept.get("title"):
        _add(_add(stub, "title-group"), "article-title", kept["title"])

    referees = canonical.get("referees") or [{}]
    people = kept.get("contributors") or []
    named = [r for r in referees if (r.get("human_referee") or {}) or r.get("identity_mode")]
    if any(r.get("human_referee") or r.get("identity_mode") == "single_blind" for r in named):
        group = _add(stub, "contrib-group")
        affiliations: dict[str, str] = {}
        reserved = {(p.get("affiliation_ref") or {}).get("id") for p in people} - {None}
        for index, referee in enumerate(named, 1):
            person = people[index - 1] if index <= len(people) else {}
            _write_contributor(group, referee, person, index, affiliations, reserved)
        if not len(group):
            stub.remove(group)
    interests = next(
        (
            r["competing_interests_statement"]
            for r in referees
            if r.get("competing_interests_statement")
        ),
        None,
    )
    if interests:
        note = _add(_add(stub, "author-notes"), "fn", fn_type="conflict")
        p = _add(note, "p")
        _add(p, "bold", "Competing interests: ")
        p[-1].tail = interests

    created = canonical.get("created_at")
    pub_date = kept.get("pub_date")
    # A report read from JATS has a date if it gave one (eLife's give none); others always do
    if isinstance(created, str) and created[:10] and (pub_date is not None or not kept):
        year, month, day = created[:10].split("-")
        pub_type = (pub_date or {}).get("pub_type")
        date = _add(stub, "pub-date", **({"pub_type": pub_type} if pub_type else {}))
        _add(date, "day", str(int(day)))
        _add(date, "month", str(int(month)))
        _add(date, "year", year)
    kept_permissions = kept.get("permissions") or {}
    license_ = (canonical.get("provenance") or {}).get("license") or {}
    # The license as the reader takes it from the kept permissions: the first one's URL, else
    # its statement
    first = (kept_permissions.get("licenses") or [{}])[0]
    read = {"url": first["url"]} if first.get("url") else {}
    read = read or ({"name": first["text"]} if first.get("text") else {})
    if license_ != read:
        # A license changed in OCRS, or a review from elsewhere: the license as OCRS holds it
        licenses = [{"url": license_.get("url"), "text": license_.get("name")}] if license_ else []
        kept_permissions = {**kept_permissions, "licenses": licenses}
    if any(kept_permissions.values()):
        permissions = _add(stub, "permissions")
        if kept_permissions.get("copyright_statement"):
            _add(permissions, "copyright-statement", kept_permissions["copyright_statement"])
        if kept_permissions.get("copyright_year"):
            _add(permissions, "copyright-year", kept_permissions["copyright_year"])
        for license_ in kept_permissions.get("licenses") or []:
            element_ = _add(permissions, "license")
            if license_.get("url"):
                element_.set(HREF, license_["url"])
            if license_.get("text"):
                _add(element_, "license-p", license_["text"])

    target = canonical.get("target") or {}
    work_doi = ((target.get("identifiers") or {}).get("doi") or {}).get("value")
    if not work_doi:  # a work named by its ID alone, `doi:10.…`
        parsed = parse_canonical_work_id(str(target.get("work_id", "")))
        work_doi = parsed[2] if parsed and parsed[0] == "doi" else None
    related = kept.get("related_article")
    # The version reviewed, unless the article it is part of already says it
    if work_doi and (related is not None or work_doi != (kept.get("article") or {}).get("doi")):
        attrib = related or {
            "related-article-type": "peer-reviewed-article",
            "ext-link-type": "doi",
        }
        # Names from an extension are written only if they are attribute names: the writer
        # escapes values, not names
        attrib = {
            k: str(v)
            for k, v in attrib.items()
            if isinstance(k, str) and _ATTRIBUTE_NAME.fullmatch(k) and k != HREF
        }
        link = ET.SubElement(stub, "related-article", attrib)
        link.set(HREF, work_doi)
    for group in kept.get("keywords") or []:
        kwds = _add(
            stub, "kwd-group", **({"kwd_group_type": group["type"]} if group.get("type") else {})
        )
        for term in group.get("terms") or []:
            _add(kwds, "kwd", term)

    decision = source_decision(canonical.get("decision") or {})
    recommendation = decision.get("recommendation")
    source_term = kept.get("recommendation") or {}
    term = decision.get("source_label") or source_term.get("value")
    says = RECOMMENDATIONS.get((term or "").casefold())
    if recommendation and says != recommendation:
        term = TERMS.get(recommendation)
    elif not recommendation and says is not None:
        term = None  # the review no longer recommends what the source's term says
    # A term OCRS does not know says no recommendation, and goes back as the source wrote it
    if term:
        meta = _add(_add(stub, "custom-meta-group"), "custom-meta")
        _add(meta, "meta-name", source_term.get("name") or "peer-review-recommendation")
        _add(meta, "meta-value", term)

    opinion = canonical.get("opinion") or {}
    # The report: the parts of the review's text that are the review, as the authors may read
    # them, in order
    reports = [
        p["content"]
        for p in narrative_parts(canonical)
        if p.get("role") == "review" and for_authors(p) and p["content"].strip()
    ]
    text = "\n\n".join(reports) or opinion.get("text")

    def headed(part: dict[str, Any]) -> str:
        return f"{part['title']}:\n\n{part['content']}" if part.get("title") else part["content"]

    if isinstance(text, str) and text.strip():
        # Then the questions for the authors and the other parts they may read, but for the
        # sections the reader cuts from the text itself (those of a report read from JATS)
        cut = [(c["title"], c["content"]) for c in _sections(text)]
        others = [
            s
            for s in narrative_parts(canonical)
            if s.get("role") in (None, "questions", "other")
            and for_authors(s)
            and s["content"].strip()
            and (s.get("title"), s["content"]) not in cut
        ]
        text = "\n\n".join([text, *map(headed, others)])
    else:
        # A review without a full text: its summary, then its other parts, each under its
        # heading when it has one, or else its findings; the summary is left out when it is
        # the start of one of them (a reader may take it from the first finding)
        written = [
            s
            for s in narrative_parts(canonical)
            if s.get("role") in (None, "questions", "other") and for_authors(s) and s["content"]
        ]
        # Findings whose text no section holds come after the sections
        held = {
            kind: {
                item
                for s in written
                if str(s.get("title") or "").casefold().replace("_", " ").strip() in titles
                for item in _items(s["content"])
            }
            for kind, titles in FINDING_SECTIONS.items()
        }
        parts_ = [headed(s) for s in written]
        parts_.append(_findings_text(canonical.get("findings") or {}, held))
        rest = "\n\n".join(part for part in parts_ if part)
        summary = opinion.get("summary") or narrative_text(canonical, "summary")
        # The summary is repeated when it is one of the items that follow, or the start of one
        # cut where a reader cuts a summary it takes from a finding (200 characters)
        said = _squash(summary) if isinstance(summary, str) else ""
        items = _items(rest)
        repeated = bool(said) and (
            said in items or (len(summary) >= 200 and any(item.startswith(said) for item in items))
        )
        parts = [summary] if isinstance(summary, str) and summary.strip() and not repeated else []
        text = "\n\n".join([*parts, rest] if rest else parts)
    if isinstance(text, str) and text.strip():
        element.append(_body(text.strip(), bool(kept.get("lists_in_paragraphs"))))
    for response in kept.get("responses") or []:
        # Only a sub-article (the response it was) goes back inside this one
        nested = ET.fromstring(response) if isinstance(response, str) else None
        if nested is not None and nested.tag == "sub-article":
            element.append(nested)

    payload: dict[str, Any] = {"sub_article": ET.tostring(element, encoding="unicode")}
    # What the article says of itself: its DOI as it was given (the version reviewed is the
    # related article), and the work's title and journal as the review now has them
    kept_article = kept.get("article") or {}
    article = {
        "doi": kept_article.get("doi") if kept_article else work_doi,
        "title": target.get("title"),
        "journal": target.get("venue"),
    }
    article = {k: v for k, v in article.items() if v}
    if article:
        payload["article"] = article
    return payload


def sub_articles(article_xml: str) -> list[dict[str, Any]]:
    """A JATS article's sub-articles (not those nested in another, such as an author response
    to a report), each as a payload for `from_jats`, with the article's version DOI (else its
    DOI), title and journal."""
    root = ET.fromstring(article_xml)
    meta = root.find("front/article-meta")
    ids = meta.findall("article-id[@pub-id-type='doi']") if meta is not None else []
    version = [i for i in ids if i.get("specific-use") == "version"]
    article = {
        "doi": _text((version or ids)[0]) if ids else None,
        "title": _text(meta.find("title-group/article-title")) if meta is not None else None,
        "journal": _text(root.find("front/journal-meta/journal-title-group/journal-title")),
    }
    article = {k: v for k, v in article.items() if v}
    return [{"sub_article": _xml(sub), "article": article} for sub in root.findall("sub-article")]
