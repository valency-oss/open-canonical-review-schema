#!/usr/bin/env python3
"""Fetch the real reviews in tests/fixtures/real/ again, from where they were published.

    uv run scripts/fetch_real_reviews.py

Each review is written as its mapper reads it, and `tests/fixtures/real/sources.json` records
where it came from, its license and when it was fetched:

- OpenReview: notes from the OpenReview API v2, as the Internet Archive saved the forum
  queries that openreview.net makes (the API itself asks scripts to pass a browser check).
  Each note is written as the API returned it, without the `details` the query asked for. The
  details hold each note's invitation, whose field definitions give `scale_bounds`.
- eLife: public reviews and eLife Assessments from the eLife API, as journal narratives.
- F1000Research: referee reports from the article's JATS XML, as journal narratives.
- JATS: eLife's and F1000Research's sub-articles, from each article's JATS XML, as `from_jats`
  takes them (`ocrs.mappers.jats.sub_articles`): the sub-article as XML, as the parser writes it
  back, and what the article says of itself.
- OpenAIReview: `paper.json` outputs from the ChicagoHAI/OpenAIReview repository, without the
  paper's own text in `paragraphs`, which the mapper does not read. The reviews are MIT, but
  the papers they quote are not known to be openly licensed, so the passages they quote are
  obscured (letters as x, digits as 0): each comment's `quote`, and what its title, its
  explanation and the overall feedback put in quotation marks.

A journal narrative is OCRS's own minimal format, not the publisher's: the review's text is
the publisher's, joined into one text with a blank line between paragraphs, and the rest of
the payload is taken from the publisher's record: the DOI of the version reviewed, the
journal, the review's own DOI as its ID, the reviewer's number when the review gives one, and
the date the review was published (for eLife, the date Crossref gives the review's DOI).
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ocrs.mappers.jats import sub_articles
from ocrs.util import parse_numeric_prefix

REAL = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "real"
RETRIEVED = "2026-10-20"
CC_BY = "CC BY 4.0"

# Forum queries the Internet Archive saved, as openreview.net makes them: (forum, capture time,
# the venue's domain, or None for a query by forum alone)
OPENREVIEW_FORUMS = [
    ("SJTSvRtGsN", "20251014140351", "ICLR.cc/2024/Conference"),
    ("45rvZkJbuX", "20250703023727", "ICLR.cc/2025/Conference"),
    ("y3oHMcoItR", "20260419040827", None),
    ("y8Rm4VNRPH", "20250116203216", "NeurIPS.cc/2024/Conference"),
    ("u7m2CG84BQ", "20250116203208", "NeurIPS.cc/2024/Datasets_and_Benchmarks_Track"),
    ("Ti67584b98", "20241206132449", "colmweb.org/COLM/2024/Conference"),
    ("rNsAQisgOo", "20250113174837", "TMLR"),
]
FORUM_QUERY = (
    "notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags"
    "&domain={domain}&forum={forum}&limit=1000&trash=true"
)
# The kinds of note that are reviews; comments and rebuttals are not
REVIEW_KINDS = ("Official_Review", "Review", "Meta_Review", "Decision")

# eLife article, version and the reviews to take from it
ELIFE = [("100443", ["sa0", "sa1", "sa2"]), ("110030", ["sa1"])]
# F1000Research article (as in its URL), version, and the referee reports to take from it
F1000 = [
    ("13-970", 2, ["10.5256/f1000research.178206.r367849"]),
    ("15-562", 1, ["10.5256/f1000research.194339.r477634"]),
    ("12-1170", 3, ["10.5256/f1000research.180054.r413354"]),
]
OPENAIREVIEW_COMMIT = "436a42f0a7222ae87b5008729f0cc5b521d7e160"
OPENAIREVIEW = ["smoothing-shifts-pdf.json", "apep-0001-pdf.json"]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ocrs-fixtures"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def scale_bounds(invitation: dict[str, Any]) -> dict[str, Any]:
    """The bounds and labels of each score field an invitation defines: its `enum` of numbers
    with descriptions (`{"value": 4, "description": "4: excellent"}`), or of strings that
    start with the number (`"4 excellent"`)."""
    bounds = {}
    content = ((invitation.get("edit") or {}).get("note") or {}).get("content") or {}
    for field, spec in content.items():
        value = spec.get("value") if isinstance(spec, dict) else None
        param = value.get("param") if isinstance(value, dict) else None
        enum = param.get("enum") if isinstance(param, dict) else None
        if not isinstance(enum, list):
            continue
        labels = {}
        for choice in enum:
            if isinstance(choice, dict):
                number, label = choice.get("value"), choice.get("description")
                if isinstance(label, str):
                    label = re.sub(rf"^\s*{number}\s*:\s*", "", label)
            else:
                number, label = parse_numeric_prefix(choice)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                labels[str(number)] = label
        if labels and len(labels) == len(enum):
            numbers = [float(n) if "." in n else int(n) for n in labels]
            bounds[field] = {
                "min": min(numbers),
                "max": max(numbers),
                "labels": {k: v for k, v in labels.items() if v},
            }
    return bounds


def note_kind(note: dict[str, Any]) -> str:
    return note["invitations"][0].rsplit("/-/", 1)[-1]


def fetch_openreview(sources: list[dict[str, Any]]) -> None:
    for forum, captured, domain in OPENREVIEW_FORUMS:
        query = (
            FORUM_QUERY.format(domain=quote(domain, safe=""), forum=forum)
            if domain
            else f"notes?forum={forum}"
        )
        api_url = f"https://api2.openreview.net/{query}"
        archived = f"https://web.archive.org/web/{captured}id_/{api_url}"
        notes = json.loads(fetch(archived))["notes"]
        folder = REAL / "openreview" / forum
        submission = next(n for n in notes if note_kind(n) == "Submission")
        content = {k: v.get("value") for k, v in submission["content"].items()}
        work = {"id": forum, "title": content.get("title")}
        work |= {k: content[k] for k in ("venue", "venueid") if content.get(k)}
        write(folder / "submission.json", work)
        forms = {}
        for note in notes:
            kind = note_kind(note)
            if kind not in REVIEW_KINDS:
                continue
            invitation = (note.get("details") or {}).get("invitation")
            if invitation and kind not in forms:
                forms[kind] = scale_bounds(invitation)
            name = f"{kind.lower()}_{note['id']}.json"
            write(folder / name, {k: v for k, v in note.items() if k != "details"})
            sources.append(
                {
                    "file": f"openreview/{forum}/{name}",
                    "system": "openreview",
                    "kind": "real",
                    "venue": content.get("venue"),
                    "url": f"https://openreview.net/forum?id={forum}&noteId={note['id']}",
                    "retrieved_from": archived,
                    "license": note.get("license"),
                    "retrieved": RETRIEVED,
                }
            )
        write(folder / "scale_bounds.json", forms)


def elife_text(blocks: list[dict[str, Any]]) -> str:
    """eLife's content blocks as text: paragraphs, and lists one item to a line."""
    parts = []
    for block in blocks:
        if block.get("type") == "paragraph":
            parts.append(block["text"])
        elif block.get("type") == "list":
            items = [
                elife_text(item) if isinstance(item, list) else item for item in block["items"]
            ]
            parts.append("\n".join(f"- {item}" for item in items))
        elif isinstance(block.get("content"), list):
            parts.append(elife_text(block["content"]))
    return "\n\n".join(parts)


def registered(doi: str) -> str:
    """When Crossref says a DOI's work was published, as a time at midnight UTC."""
    record = json.loads(fetch(f"https://api.crossref.org/works/{doi}"))["message"]
    year, month, day = record["published"]["date-parts"][0]
    return f"{year}-{month:02d}-{day:02d}T00:00:00Z"


def fetch_elife(sources: list[dict[str, Any]]) -> None:
    for article_id, review_ids in ELIFE:
        article = json.loads(fetch(f"https://api.elifesciences.org/articles/{article_id}"))
        reviews = {r["id"]: r for r in article.get("publicReviews") or []}
        reviews[article["elifeAssessment"]["id"]] = article["elifeAssessment"]
        for review_id in review_ids:
            review = reviews[review_id]
            name = f"elife_{article_id}_{review_id}.json"
            payload = {
                "review_id": review["doi"],
                # The reviews are of the version they are published with
                "doi": article["doiVersion"],
                "journal": "eLife",
                "created_at": registered(review["doi"]),
                "full_text": elife_text(review["content"]),
            }
            # "Reviewer #2 (Public review):" names the reviewer by number
            numbered = re.match(r"(Reviewer #\d+)", review["title"])
            if numbered:
                payload["reviewer_id"] = numbered.group(1)
            write(REAL / "journal" / name, payload)
            sources.append(
                {
                    "file": f"journal/{name}",
                    "system": "journal_narrative",
                    "kind": "real",
                    "venue": "eLife",
                    "url": f"https://doi.org/{review['doi']}",
                    "retrieved_from": f"https://api.elifesciences.org/articles/{article_id}",
                    "license": article["copyright"]["license"].replace("-", " "),
                    "retrieved": RETRIEVED,
                }
            )


def jats_text(element: ET.Element) -> str:
    """A JATS body as text: a paragraph per `<p>`, a line per list item, numbered for an
    ordered list."""
    parts = []
    for child in element:
        if child.tag == "p" and child.find("list") is None:
            parts.append(" ".join("".join(child.itertext()).split()))
        elif child.tag == "list" or (child.tag == "p" and child.find("list") is not None):
            lists = [child] if child.tag == "list" else child.findall("list")
            for list_ in lists:
                ordered = list_.get("list-type") == "order"
                lines = [
                    f"{f'{n}.' if ordered else '-'} {' '.join(''.join(item.itertext()).split())}"
                    for n, item in enumerate(list_.findall("list-item"), 1)
                ]
                parts.append("\n".join(lines))
    return "\n\n".join(parts)


def fetch_f1000(sources: list[dict[str, Any]]) -> None:
    xlink = "{http://www.w3.org/1999/xlink}href"
    for article, version, dois in F1000:
        url = f"https://f1000research.com/articles/{article}/v{version}/xml"
        root = ET.fromstring(fetch(url))
        for report in root.iter("sub-article"):
            stub = report.find("front-stub")
            doi = stub.findtext("article-id") if stub is not None else None
            if report.get("article-type") != "reviewer-report" or doi not in dois:
                continue
            date = stub.find("pub-date")
            created = "{}-{:02d}-{:02d}T00:00:00Z".format(
                int(date.findtext("year")), int(date.findtext("month")), int(date.findtext("day"))
            )
            name = f"f1000_{doi.rsplit('.', 1)[-1]}.json"
            write(
                REAL / "journal" / name,
                {
                    "review_id": doi,
                    "doi": stub.find("related-article").get(xlink),
                    "journal": "F1000Research",
                    "created_at": created,
                    "full_text": jats_text(report.find("body")),
                },
            )
            sources.append(
                {
                    "file": f"journal/{name}",
                    "system": "journal_narrative",
                    "kind": "real",
                    "venue": "F1000Research",
                    "url": f"https://doi.org/{doi}",
                    "retrieved_from": url,
                    "license": CC_BY if "by/4.0" in stub.find(".//license").get(xlink) else None,
                    "retrieved": RETRIEVED,
                }
            )


# A passage put in quotation marks, of at least 12 characters: "…", “…”, ‘…’ or '…'
QUOTED = re.compile(r"[\"“][^\"”]{12,}?[\"”]|‘[^’]{12,}?’|(?<![A-Za-z])'[^']{12,}?'(?![A-Za-z])")


def obscure(text: str) -> str:
    """Text with its letters as x (X for capitals) and digits as 0, keeping its spacing,
    punctuation and mathematics' structure."""
    text = re.sub(r"[A-Z]", "X", text)
    text = re.sub(r"[a-z]", "x", text)
    return re.sub(r"[0-9]", "0", text)


def obscure_quotes(paper: dict[str, Any]) -> dict[str, Any]:
    """An OpenAIReview paper.json with the passages it quotes from the paper obscured."""
    for method in (paper.get("methods") or {}).values():
        if isinstance(method.get("overall_feedback"), str):
            method["overall_feedback"] = QUOTED.sub(
                lambda m: obscure(m.group()), method["overall_feedback"]
            )
        for comment in method.get("comments") or []:
            if isinstance(comment.get("quote"), str):
                comment["quote"] = obscure(comment["quote"])
            for key in ("title", "explanation"):
                if isinstance(comment.get(key), str):
                    comment[key] = QUOTED.sub(lambda m: obscure(m.group()), comment[key])
    return paper


def fetch_openaireview(sources: list[dict[str, Any]]) -> None:
    for name in OPENAIREVIEW:
        url = (
            "https://raw.githubusercontent.com/ChicagoHAI/OpenAIReview/"
            f"{OPENAIREVIEW_COMMIT}/examples/review_results/{name}"
        )
        paper = json.loads(fetch(url))
        paper.pop("paragraphs", None)
        write(REAL / "openaireview" / name, obscure_quotes(paper))
        sources.append(
            {
                "file": f"openaireview/{name}",
                "system": "openaireview",
                "kind": "real",
                "venue": None,
                "url": url,
                "retrieved_from": url,
                "license": "MIT (the repository); its quotes of the paper are obscured",
                "retrieved": RETRIEVED,
            }
        )


# JATS articles and the sub-articles to take from them, by their IDs
JATS = [
    ("elife", "https://elifesciences.org/articles/100443.xml", ["sa0", "sa1", "sa2", "sa3"]),
    ("f1000", "https://f1000research.com/articles/15-562/v1/xml", ["report477634"]),
    ("f1000", "https://f1000research.com/articles/13-970/v2/xml", ["report367849"]),
    ("f1000", "https://f1000research.com/articles/12-1170/v3/xml", ["report413354"]),
]


def fetch_jats(sources: list[dict[str, Any]]) -> None:
    for publisher, url, ids in JATS:
        for payload in sub_articles(fetch(url).decode("utf-8")):
            sub_id = ET.fromstring(payload["sub_article"]).get("id")
            if sub_id not in ids:
                continue
            name = f"{publisher}_{payload['article']['doi'].rsplit('.', 2)[-2]}_{sub_id}.json"
            write(REAL / "jats" / name, payload)
            sources.append(
                {
                    "file": f"jats/{name}",
                    "system": "jats",
                    "kind": "real",
                    "venue": payload["article"].get("journal"),
                    "url": url,
                    "retrieved_from": url,
                    "license": CC_BY,
                    "retrieved": RETRIEVED,
                }
            )


def main() -> None:
    sources: list[dict[str, Any]] = []
    fetch_openreview(sources)
    fetch_elife(sources)
    fetch_f1000(sources)
    fetch_jats(sources)
    fetch_openaireview(sources)
    kept = (
        json.loads((REAL / "sources.json").read_text()) if (REAL / "sources.json").exists() else []
    )
    # Fixtures this script does not fetch (documented samples) stay listed
    fetched = {source["file"] for source in sources}
    sources += [
        source for source in kept if source["file"] not in fetched and source["kind"] != "real"
    ]
    write(REAL / "sources.json", sorted(sources, key=lambda source: source["file"]))


if __name__ == "__main__":
    main()
