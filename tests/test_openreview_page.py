# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for reading a saved OpenReview forum page into OCRS reviews."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import codec_validate

from ocrs import validate_canonical
from ocrs.hierarchy import legacy_view
from ocrs.mappers.openreview_page import (
    Field,
    Note,
    _Builder,
    _findings,
    _Links,
    parse_forum_page,
    to_markdown,
    utc_iso,
)
from ocrs.mappers.openreview_page import (
    reviews_from_forum_page as current_reviews_from_forum_page,
)
from ocrs.util import narrative_text


def reviews_from_forum_page(*args, **kwargs):
    reviews = current_reviews_from_forum_page(*args, **kwargs)
    for review in reviews:
        validate_canonical(review)
    return [legacy_view(review) for review in reviews]


ROOT = Path(__file__).parent.parent
PAGE = ROOT / "tests" / "fixtures" / "openreview" / "forum_page.html"
SCRIPT = ROOT / "scripts" / "openreview_page_to_ocrs.py"
FORUM_URL = "https://openreview.net/forum?id=Fx0rumP4ge"


@pytest.fixture(scope="module")
def html() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def reviews(html) -> list[dict]:
    return reviews_from_forum_page(html, imported_at="2026-10-18T00:00:00Z")


def markdown(fragment: str) -> str:
    builder = _Builder()
    builder.feed(f"<div>{fragment}</div>")
    return to_markdown(builder.root.elements()[0])


def test_forum_page_is_read(html):
    forum = parse_forum_page(html)

    assert forum.id == "Fx0rumP4ge"
    assert forum.url == FORUM_URL
    assert forum.title == "Sparse Attention That Learns Where To Look"
    assert forum.authors == [
        {"name": "Ada Example", "profile": "~Ada_Example1"},
        {"name": "Ben Sample", "profile": "~Ben_Sample2"},
    ]
    assert forum.venue == "The Example Conference on Machine Learning"
    assert forum.venue_id == "Example.cc/2025/Conference"
    assert forum.venue_label == "Example 2025 poster"
    assert forum.pdf_url == "https://openreview.net/pdf?id=Fx0rumP4ge"
    assert forum.get("Keywords") == "attention, efficiency"
    assert forum.get("Supplementary Material") == (
        "[zip](https://openreview.net/attachment?id=Fx0rumP4ge&name=supplementary_material)"
    )
    assert len(forum.sha256) == 64


def test_replies_keep_their_threads(html):
    forum = parse_forum_page(html)

    # Text in <script> is not a note, even when it looks like one.
    assert [(n.id, n.parent_id, n.reply_type) for n in forum.notes] == [
        ("DEC00000001", None, "Decision"),
        ("REV00000001", None, "Official Review"),
        ("REB00000001", "REV00000001", "Rebuttal"),
        ("ACK00000001", "REB00000001", "Mandatory Acknowledgement"),
        ("REV00000002", None, "Official Review"),
    ]
    assert [n.id for n in forum.replies("REV00000001")] == ["REB00000001", "ACK00000001"]
    assert forum.replies("REV00000002") == []
    # A note's fields are its own, not its replies'.
    review = forum.notes[1]
    assert review.get("Rebuttal") is None
    assert review.signature == "Reviewer abcd"
    assert review.heading == "Official Review of Submission12 by Reviewer abcd"


def test_one_review_per_official_review_and_each_validates(reviews):
    assert [r["review_id"] for r in reviews] == ["REV00000001", "REV00000002"]
    for review in reviews:
        codec_validate(review)
        assert review["provenance"]["source_system"] == "openreview"
        assert review["referees"][0] == {
            "referee_type": "human",
            "identity_mode": "pseudonymous",
            "referee_id": review["extensions"]["openreview"]["note"]["signature"],
        }


def test_review_links_back_to_its_note(reviews, html):
    review = reviews[0]
    ext = review["extensions"]["openreview"]

    assert review["provenance"]["source_review_id"] == "REV00000001"
    assert review["provenance"]["source_url"] == f"{FORUM_URL}&noteId=REV00000001"
    assert review["target"]["work_id"] == "internal_id:openreview_forum:Fx0rumP4ge"
    assert review["target"]["identifiers"]["internal_id"]["hyperlink"] == FORUM_URL
    assert review["target"]["title"] == "Sparse Attention That Learns Where To Look"
    assert ext["note"]["url"] == review["provenance"]["source_url"]
    assert ext["note"]["created"] == "03 Jul 2025, 02:28 (modified: 28 Oct 2025, 20:28)"
    assert ext["forum"]["pdf_url"] == "https://openreview.net/pdf?id=Fx0rumP4ge"
    assert ext["forum"]["decision"]["decision"] == "Accept (poster)"
    assert ext["source_page"]["sha256"] == parse_forum_page(html).sha256

    links = {(e["ocrs"], e["field"]): e for e in ext["source_fields"]}
    assert links[("opinion.summary", "Summary")]["how"] == "copied"
    assert links[("findings.weaknesses[2]", "Strengths And Weaknesses")]["heading"] == "Minor"
    assert links[("opinion.decision.recommendation", "Rating")]["how"] == "lookup"
    assert links[("findings.questions[1]", "Questions")]["how"] == "copied"


def test_fields_without_an_ocrs_home_are_kept(reviews):
    ext = reviews[0]["extensions"]["openreview"]

    assert ext["unmapped_fields"] == {"Code Of Conduct Acknowledgement": "Yes"}
    assert [(r["id"], r["replyto"], r["reply_type"]) for r in ext["replies"]] == [
        ("REB00000001", "REV00000001", "Rebuttal"),
        ("ACK00000001", "REB00000001", "Mandatory Acknowledgement"),
    ]
    assert ext["replies"][0]["url"] == f"{FORUM_URL}&noteId=REB00000001"
    assert ext["replies"][1]["content"] == {
        "Mandatory Acknowledgement": "I have read the rebuttal."
    }
    assert reviews[1]["extensions"]["openreview"]["replies"] == []


def test_findings_follow_the_reviewers_headings(reviews):
    findings = reviews[0]["findings"]

    assert [p["id"] for p in findings["strengths"]] == ["s1", "s2"]
    assert findings["strengths"][0]["title"] == "Novelty"
    assert findings["strengths"][0]["group"] == ["Strengths"]
    assert [p["id"] for p in findings["weaknesses"]] == ["w1", "w2", "w3"]
    assert findings["weaknesses"][0]["text"].endswith("notation.\n- Detail one.")
    assert "severity" not in findings["weaknesses"][0]
    assert findings["weaknesses"][2] == {
        "id": "w3",
        "text": "Eq. 7 is missing a summation index.",
        "severity": "minor",
        "group": ["Minor"],
    }
    # The lead-in line is not a heading; the references paragraph is not a point.
    assert [p["text"] for p in findings["questions"]] == [
        "How sensitive is it to the predictor?",
        "What are the wall-clock times?",
    ]
    assert all("group" not in p for p in findings["questions"])
    assert "[1] A. Reference." in narrative_text(reviews[0], "review")


def test_plain_labels_work_as_headings_too(reviews):
    findings = reviews[1]["findings"]

    assert [p["text"] for p in findings["strengths"]] == ["Clear writing."]
    assert [p["text"] for p in findings["weaknesses"]] == [
        "Only one dataset.",
        "No ablation of the predictor.",
    ]
    assert "questions" not in findings


def test_scores_keep_their_values_and_labels_without_inventing_a_scale(reviews):
    metrics = {m["label"]: m for m in reviews[0]["metrics"]}

    assert {label: (m["key"], m["value"]) for label, m in metrics.items()} == {
        "Quality": ("correctness", 3),
        "Clarity": ("clarity", 4),
        "Originality": ("novelty", 3),
        "Rating": ("overall", 5),
        "Confidence": ("confidence", 4),
    }
    assert metrics["Quality"]["scale"] == {
        "type": "ordinal",
        "anchors": [{"value": 3, "label": "good"}],
    }
    assert metrics["Rating"]["scale"]["anchors"][0]["label"].startswith("Accept: Technically")
    assert all("normalized" not in m and "min" not in m["scale"] for m in metrics.values())
    assert reviews[0]["decision"] == {
        "recommendation": "accept",
        "summary_rationale": "The rebuttal answered my questions.",
    }
    assert reviews[1]["decision"] == {"recommendation": "reject"}


def test_narrative_and_text_format(reviews):
    review = reviews[0]

    assert review["opinion"]["summary"] == narrative_text(review, "summary")
    assert narrative_text(review, "questions").startswith("Please answer:")
    assert [p for p in review["narrative"] if "role" not in p] == [
        {"title": "Limitations", "content": "Yes."}
    ]
    assert review["ethics_and_risk"] == {"notes": "NO or VERY MINOR ethics concerns only"}
    assert review["text_format"] == {"markup": "markdown", "math": "tex"}
    assert reviews[1]["text_format"] == {"markup": "markdown", "math": "none"}


def test_math_is_rebuilt_from_the_pages_mathml(reviews):
    forum_notes = {n.id: n for n in parse_forum_page(PAGE.read_text(encoding="utf-8")).notes}

    assert reviews[0]["opinion"]["summary"] == (
        "The paper predicts attention sparsity with a small network; the cost is $O(n)$ in the "
        "length *n*. Code is at https://example.org/code."
    )
    assert r"$T_{\mathrm{tr}}$" in reviews[0]["findings"]["weaknesses"][0]["text"]
    assert (
        forum_notes["REB00000001"].get("Rebuttal").endswith(r"Display math: $$\frac{a}{\sqrt{b}}$$")
    )


def test_dates_are_read_in_the_given_time_zone(html):
    utc = reviews_from_forum_page(html)
    pacific = reviews_from_forum_page(html, tz=ZoneInfo("America/Los_Angeles"))

    assert utc[0]["created_at"] == "2025-07-03T02:28:00Z"
    assert utc[0]["updated_at"] == "2025-10-28T20:28:00Z"
    assert utc[0]["extensions"]["openreview"]["source_page"]["timezone_assumed"] == "UTC"
    assert pacific[0]["created_at"] == "2025-07-03T09:28:00Z"  # PDT, UTC-7
    assert pacific[0]["updated_at"] == "2025-10-29T03:28:00Z"  # after the clocks changed
    assert pacific[0]["extensions"]["openreview"]["source_page"]["timezone_assumed"] == (
        "America/Los_Angeles"
    )
    # A note never edited shows one date, so it has no updated_at.
    assert "updated_at" not in utc[1]


def test_keep_raw_keeps_the_parsed_note(html):
    review = reviews_from_forum_page(html, keep_raw=True)[1]
    raw = review["provenance"]["raw_payload"]

    assert raw["id"] == "REV00000002"
    assert raw["content"]["Rating"] == "2: Reject: For instance, a paper with technical flaws."
    codec_validate(review)


def test_a_page_that_is_not_a_forum_is_refused():
    with pytest.raises(ValueError, match="Not an OpenReview forum page"):
        parse_forum_page("<html><body><p>Hello</p></body></html>")


def test_a_forum_without_reviews_gives_none():
    page = PAGE.read_text(encoding="utf-8").replace("Official Review</span>", "Comment</span>")
    assert reviews_from_forum_page(page) == []


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("<p>One</p><p>Two <em>x</em> <strong>y</strong></p>", "One\n\nTwo *x* **y**"),
        ("<ul><li>a</li><li>b<ol><li>c</li></ol></li></ul>", "- a\n- b\n  1. c"),
        ('<ol start="3"><li>x</li><li>y</li></ol>', "3. x\n4. y"),
        ('<ol start="no"><li>x</li></ol>', "1. x"),
        (
            '<p>See <a href="https://e.org/x">the paper</a>.</p>',
            "See [the paper](https://e.org/x).",
        ),
        ("<p>line<br>break</p>", "line\\\nbreak"),
        ("<blockquote><p>quoted</p></blockquote><p>reply</p>", "> quoted\n\nreply"),
        ("<h4><strong>Head</strong></h4><p>x</p>", "#### **Head**\n\nx"),
        ("<p>Use <code>f(x)</code></p>", "Use `f(x)`"),
        ("<p>Use <code>a`b</code> or <code>`c`</code></p>", "Use ``a`b`` or `` `c` ``"),
        ("<pre><code>x = ```y```\n</code></pre>", "````\nx = ```y```\n````"),
        ("<p>  spaced \n   out  </p>", "spaced out"),
        ("<p>a</p><hr><p>b</p>", "a\n\n---\n\nb"),
        (
            "<p>keep <del>No baseline.</del> and <s>this</s> but not ~~ this</p>",
            r"keep ~~No baseline.~~ and ~~this~~ but not \~\~ this",
        ),
        (
            '<p>See <img src="https://openreview.net/attachment?id=x" alt="Figure 1"></p>',
            "See ![Figure 1](https://openreview.net/attachment?id=x)",
        ),
        ('<p><img src="a.png"></p>', "![](a.png)"),
        (
            '<p><a href="https://e.org/a_(b)">paper</a></p>',
            r"[paper](<https://e.org/a_(b)>)",
        ),
        ('<p><img src="a b(1).png" alt="x](y"></p>', "![x\\](y](<a%20b(1).png>)"),
        ('<p><img alt="only alt"></p>', "only alt"),
        (
            "<p># Weaknesses</p><p>- dash</p><p>2. two</p><p>&gt; q</p>",
            "\\# Weaknesses\n\n\\- dash\n\n2\\. two\n\n\\> q",
        ),
        ("<p>#</p><p>---</p><p>text<br>===</p><p>1.</p>", "\\#\n\n\\---\n\ntext\\\n\\===\n\n1\\."),
        ("<p>a<br>-- --<br> - - -<br>= =</p>", "a\\\n\\-- --\\\n \\- - -\\\n\\= ="),
        ("<p>trailing break<br></p><p><br>leading</p>", "trailing break\n\nleading"),
        (
            '<p>see <a href="https://e.org/x">prior work </a>supports this</p>',
            "see [prior work](https://e.org/x) supports this",
        ),
        ('<p>a<a href="https://e.org/x"> b</a></p>', "a [b](https://e.org/x)"),
        (
            "<ol><li>It has problems:<br><strong>No baselines</strong></li></ol>",
            "1. It has problems:\\\n   **No baselines**",
        ),
        (
            "<ol><li><p>It has problems:<br><strong>No baselines</strong></p></li></ol>",
            "1. It has problems:\\\n   **No baselines**",
        ),
        (
            '<p><a href="full.png"><img src="thumb.png" alt="Figure"></a> and '
            '<a href="https://e.org/x">see [1] <code>x[0]</code></a></p>',
            "[![Figure](thumb.png)](full.png) and [see \\[1\\] `x[0]`](https://e.org/x)",
        ),
        (
            '<ul><li><input type="checkbox" checked> done</li>'
            '<li><input type="checkbox"> todo</li></ul>',
            "- [x] done\n- [ ] todo",
        ),
        (
            '<ul><li><input type="checkbox" checked>done</li></ul>',
            "- [x] done",
        ),
        ("<p><strong>line<br></strong>break</p>", "**line**\\\nbreak"),
        ("<p><em>a<br></em><br><em>b</em></p>", "*a*\\\n\\\n*b*"),
        (
            "<p>x<sup>2</sup> and 10<sup>-3</sup> and H<sub>2</sub>O</p>",
            "x<sup>2</sup> and 10<sup>-3</sup> and H<sub>2</sub>O",
        ),
        ("<p>Use <code> a </code> and <code>x</code></p>", "Use `  a  ` and `x`"),
        (
            "<table><tr><td>a<br>b</td><td>c|d</td></tr></table>",
            "| a<br>b | c\\|d |\n| --- | --- |",
        ),
        ('<p><a href="https://e.org/x">see [1]</a></p>', r"[see \[1\]](https://e.org/x)"),
        ("<p>keep #hash, 3-4 and 2.5 as is</p>", "keep #hash, 3-4 and 2.5 as is"),
        (
            "<p>the &lt;mask&gt; token, 2*3 and snake_case</p>",
            r"the \<mask> token, 2\*3 and snake\_case",
        ),
        ("<p>Cost is $5 [1] and [a](b)</p>", r"Cost is \$5 [1] and [a\](b)"),
        (
            "<p>Use &amp;copy; and &amp;#169; but R&amp;D &amp; Q&amp;A;</p>",
            r"Use \&copy; and \&#169; but R&D & Q\&A;",
        ),
        (
            "<blockquote><ul><li>first</li><li>second</li></ul><p>then</p></blockquote>",
            "> - first\n> - second\n>\n> then",
        ),
        ('<p><a href="https://e.org/a_b">https://e.org/a_b</a></p>', "https://e.org/a_b"),
    ],
)
def test_rendered_html_becomes_markdown(fragment, expected):
    assert markdown(fragment) == expected


def test_script_writes_one_valid_file_per_review(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(PAGE), "-o", str(tmp_path), "--timezone=-07:00"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
    )

    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["REV00000001.json", "REV00000002.json"]
    review = json.loads((tmp_path / "REV00000001.json").read_text(encoding="utf-8"))
    codec_validate(review)
    assert review["created_at"] == "2025-07-03T09:28:00Z"
    assert f"{FORUM_URL}&noteId=REV00000001" in result.stdout
    assert "2 reviews" in result.stderr


def test_script_reports_a_page_without_reviews(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        PAGE.read_text(encoding="utf-8").replace("Official Review</span>", "Other</span>")
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page), "-o", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
    )

    assert result.returncode == 1
    assert "No Official Reviews" in result.stderr
    assert not (tmp_path / "out").exists()


def math(mathml: str) -> str:
    return markdown(
        f"<p><mjx-container><mjx-assistive-mml><math>{mathml}</math></mjx-assistive-mml>"
        "</mjx-container></p>"
    )


@pytest.mark.parametrize(
    ("mathml", "expected"),
    [
        ("<mroot><mi>x</mi><mn>3</mn></mroot>", r"$\sqrt[3]{x}$"),
        (
            "<munderover><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>n</mi></munderover>",
            "$∑_{i=1}^{n}$",
        ),
        ("<msup><mi>x</mi><mn>2</mn></msup>", "$x^{2}$"),
        ("<mfrac><mn>1</mn><mi>n</mi></mfrac>", r"$\frac{1}{n}$"),
        ("<mover><mi>x</mi><mo>^</mo></mover>", r"$\hat{x}$"),
        ("<mover><mi>v</mi><mo>→</mo></mover>", r"$\vec{v}$"),
        ("<mover><mi>x</mi><mo>¯</mo></mover>", r"$\bar{x}$"),
        ("<mover><mi>x</mi><mi>n</mi></mover>", "$x^{n}$"),
        (
            "<msub><mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow><mi>a</mi></msub>",
            "${x+y}_{a}$",
        ),
        (
            "<msup><msup><mi>x</mi><mi>a</mi></msup><mi>b</mi></msup>",
            "${x^{a}}^{b}$",
        ),
        ("<msub><mi>&#x3b1;</mi><mn>1</mn></msub>", "$α_{1}$"),
        ("<mi>%</mi><mo>{</mo><mo>}</mo><mi>a_b</mi>", r"$\%\{\}\mathrm{a\_b}$"),
        ("<mtext>if x</mtext>", r"$\text{if x}$"),
        (
            "<mmultiscripts><mi>T</mi><mi>i</mi><mi>j</mi><mprescripts/><mi>k</mi><mi>l</mi>"
            "</mmultiscripts>",
            r"${}_{k}^{l}T_{i}^{j}$",
        ),
        (
            "<mmultiscripts><mi>T</mi><mi>i</mi><none/><mprescripts/><none/><mi>l</mi>"
            "</mmultiscripts>",
            r"${}^{l}T_{i}$",
        ),
        (
            "<mtable><mlabeledtr><mtd><mtext>(1)</mtext></mtd><mtd><mi>x</mi><mo>=</mo>"
            "<mn>1</mn></mtd></mlabeledtr></mtable>",
            r"$\begin{align} x=1 \tag{1} \end{align}$",
        ),
        ('<menclose notation="updiagonalstrike"><mi>x</mi></menclose>', r"$\cancel{x}$"),
        ('<menclose notation="downdiagonalstrike"><mi>x</mi></menclose>', r"$\bcancel{x}$"),
        (
            '<menclose notation="updiagonalstrike downdiagonalstrike"><mi>x</mi></menclose>',
            r"$\xcancel{x}$",
        ),
        ('<menclose notation="box"><mi>x</mi></menclose>', r"$\boxed{x}$"),
        ("<menclose><mi>x</mi></menclose>", "$x$"),
        ("<mi>x</mi><mtext>&#160;is&#160;</mtext><mi>y</mi>", r"$x\text{ is }y$"),
        ("<mtext> </mtext>", ""),
        (
            '<mo>(</mo><mfrac linethickness="0"><mi>n</mi><mi>k</mi></mfrac><mo>)</mo>',
            r"$({n \atop k})$",
        ),
        ("<munder><mi>x</mi><mo>_</mo></munder>", r"$\underline{x}$"),
        ("<munder><mi>x</mi><mi>i</mi></munder>", "$x_{i}$"),
        (
            "<mi>x</mi><mphantom><mo>+</mo><mi>y</mi></mphantom><mo>=</mo><mi>z</mi>",
            r"$x\phantom{+y}=z$",
        ),
        ('<mi mathvariant="double-struck">R</mi>', r"$\mathbb{R}$"),
        ('<msup><mi mathvariant="double-struck">R</mi><mi>n</mi></msup>', r"$\mathbb{R}^{n}$"),
        (
            '<mstyle mathvariant="bold"><mi>v</mi><mo>+</mo><mi>w</mi></mstyle>',
            r"$\mathbf{v}+\mathbf{w}$",
        ),
        ('<mi mathvariant="normal">d</mi><mi>x</mi>', r"$\mathrm{d}x$"),
        ('<mi mathvariant="bold-script">A</mi>', r"$\boldsymbol{\mathcal{A}}$"),
        ('<mi mathvariant="bold-fraktur">g</mi>', r"$\boldsymbol{\mathfrak{g}}$"),
        (
            "<mtable><mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr>"
            "<mtr><mtd><mi>c</mi></mtd><mtd><mi>d</mi></mtd></mtr></mtable>",
            r"$\begin{matrix} a & b \\ c & d \end{matrix}$",
        ),
    ],
)
def test_mathml_structure_is_kept(mathml, expected):
    assert math(mathml) == expected


def test_questions_in_bold_are_still_questions():
    note = Note(
        "n1", None, "", "Official Review", "Reviewer abcd", "", "",
        [Field("Questions", "**What are the wall-clock times?**\n\n**Is it stable?**")],
    )  # fmt: skip
    found = _findings(note, _Links())

    assert [q["text"] for q in found["questions"]] == [
        "**What are the wall-clock times?**",
        "**Is it stable?**",
    ]


def test_a_lead_in_line_is_not_a_question():
    note = Note(
        "n1", None, "", "Official Review", "Reviewer abcd", "", "",
        [Field("Questions", "Please answer:\n\nWhy not?")],
    )  # fmt: skip
    assert [q["text"] for q in _findings(note, _Links())["questions"]] == ["Why not?"]


def load_script():
    spec = importlib.util.spec_from_file_location("openreview_page_to_ocrs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_time_follows_the_daylight_saving_rules_of_each_date(monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        local = load_script().parse_timezone("local")
        summer = datetime(2025, 7, 3, 2, 28, tzinfo=local)
        winter = datetime(2025, 12, 3, 2, 28, tzinfo=local)

        assert (utc_iso(summer), utc_iso(winter)) == (
            "2025-07-03T09:28:00Z",
            "2025-12-03T10:28:00Z",
        )
    finally:
        monkeypatch.undo()
        time.tzset()


def run_script(page: Path, out: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(page), "-o", str(out)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
    )


def test_recorded_hash_is_the_files_own_even_with_windows_line_endings(tmp_path):
    page = tmp_path / "page.html"
    page.write_bytes(PAGE.read_bytes().replace(b"\n", b"\r\n"))

    result = run_script(page, tmp_path / "out")

    assert result.returncode == 0, result.stderr
    review = json.loads((tmp_path / "out" / "REV00000001.json").read_text(encoding="utf-8"))
    assert review["extensions"]["openreview"]["source_page"]["sha256"] == (
        hashlib.sha256(page.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("bad_id", ["../outside", "/tmp/outside", "a/b", "..", ""])
def test_a_review_id_that_names_a_path_is_refused(tmp_path, bad_id):
    page = tmp_path / "page.html"
    page.write_text(PAGE.read_text(encoding="utf-8").replace("REV00000001", bad_id or " "))
    out = tmp_path / "out"

    result = run_script(page, out)

    assert result.returncode == 1
    assert "unsafe review IDs" in result.stderr
    assert not out.exists()
    assert not (tmp_path / "outside.json").exists()


def weaknesses(body: str) -> dict:
    note = Note(
        "n1", None, "", "Official Review", "Reviewer abcd", "", "",
        [Field("Strengths And Weaknesses", body)],
    )  # fmt: skip
    return _findings(note, _Links())


def test_a_subheading_stays_under_the_heading_it_follows():
    found = weaknesses(
        "**Weaknesses**\n\n**Missing baselines**\n\n1. No FlowMDM.\n\n"
        "**Evaluation**\n\n1. Only FID.\n2. Small user study.\n\n**Strengths**\n\n1. Clear."
    )

    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("No FlowMDM.", ["Weaknesses", "Missing baselines"]),
        ("Only FID.", ["Weaknesses", "Evaluation"]),
        ("Small user study.", ["Weaknesses", "Evaluation"]),
    ]
    assert [p["group"] for p in found["strengths"]] == [["Strengths"]]


def test_code_in_a_point_is_not_split_into_sections_or_points():
    found = weaknesses(
        "Weaknesses:\n\n1. It fails on this input:\n\n   ```python\n   # reproduce the failure\n"
        "   1. not a point\n\n   run()\n   ```\n\n2. A second point."
    )

    first, second = found["weaknesses"]
    assert first["text"].startswith("It fails on this input:")
    for line in ("# reproduce the failure", "1. not a point", "run()"):
        assert line in first["text"]
    assert second["text"] == "A second point."


def test_a_bare_number_is_a_score_but_a_sentence_that_starts_with_one_is_not():
    html = PAGE.read_text(encoding="utf-8")
    html = html.replace("5: Accept: Technically solid paper, with high impact.", "6")
    html = html.replace("4: You are confident in your assessment.", "3 years of experience")
    review = reviews_from_forum_page(html)[0]
    metrics = {m["label"]: m for m in review["metrics"]}

    assert metrics["Rating"]["value"] == 6
    assert "anchors" not in metrics["Rating"]["scale"]
    assert "Confidence" not in metrics
    assert review["extensions"]["openreview"]["unmapped_fields"]["Confidence"] == (
        "3 years of experience"
    )
    assert "recommendation" not in review["decision"]
    codec_validate(review)


def test_text_under_references_is_not_a_finding():
    found = weaknesses(
        "**Weaknesses**\n\n1. No FlowMDM.\n\n#### Minor\n\n1. A typo.\n\n"
        "#### References\n\n[1] A. Reference. A paper. 2024.\n\n2. Not a weakness either."
    )

    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("No FlowMDM.", ["Weaknesses"]),
        ("A typo.", ["Minor"]),
    ]


def test_a_subheading_that_mentions_references_stays_under_weaknesses():
    found = weaknesses("**Weaknesses**\n\n**Missing references to prior work**\n\n1. No FlowMDM.")

    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("No FlowMDM.", ["Weaknesses", "Missing references to prior work"])
    ]


def test_code_in_a_list_item_of_rendered_html_keeps_its_indentation():
    html = (
        "<ol><li>It fails:<pre><code># Strengths\n1. not a point\n\nrun()\n</code></pre></li>"
        "<li>A second point.</li></ol>"
    )
    text = markdown(html)

    assert text == (
        "1. It fails:\n\n   ```\n   # Strengths\n   1. not a point\n\n   run()\n   ```\n"
        "2. A second point."
    )
    found = weaknesses(f"**Weaknesses**\n\n{text}")
    assert [p["text"].splitlines()[0] for p in found["weaknesses"]] == [
        "It fails:",
        "A second point.",
    ]
    assert "strengths" not in found


def note_with(values: dict[str, str]) -> Note:
    return Note(
        "n1", None, "", "Official Review", "Reviewer abcd", "", "",
        [Field(label, text) for label, text in values.items()],
    )  # fmt: skip


def test_separate_strengths_and_weaknesses_fields_become_findings():
    links = _Links()
    note = note_with({"Strengths": "1. Clear.\n2. Novel.", "Weaknesses": "Only one dataset."})
    found = _findings(note, links)

    assert [p["text"] for p in found["strengths"]] == ["Clear.", "Novel."]
    assert [p["text"] for p in found["weaknesses"]] == ["Only one dataset."]
    assert {e["field"] for e in links.entries} == {"Strengths", "Weaknesses"}
    assert links.used == {"strengths", "weaknesses"}


def test_separate_fields_follow_a_combined_field():
    note = note_with(
        {
            "Strengths And Weaknesses": "**Weaknesses**\n\n1. From combined.",
            "Weaknesses": "From separate.",
        }
    )
    found = _findings(note, _Links())

    assert [(p["id"], p["text"]) for p in found["weaknesses"]] == [
        ("w1", "From combined."),
        ("w2", "From separate."),
    ]


def test_questions_inside_strengths_and_weaknesses_are_kept():
    found = weaknesses(
        "**Weaknesses**\n\n1. Only FID.\n\n**Questions**\n\n1. Why not LPIPS?\n2. Is it stable?"
    )

    assert [(q["id"], q["text"], q["group"]) for q in found["questions"]] == [
        ("q1", "Why not LPIPS?", ["Questions"]),
        ("q2", "Is it stable?", ["Questions"]),
    ]
    assert [p["text"] for p in found["weaknesses"]] == ["Only FID."]


def test_a_point_that_opens_with_code_is_still_a_point():
    found = weaknesses(
        "**Weaknesses**\n\n1. Plain point.\n2. ```\n   code line\n   ```\n3. Last point."
    )

    assert [p["text"].splitlines()[0] for p in found["weaknesses"]] == [
        "Plain point.",
        "```",
        "Last point.",
    ]
    assert "code line" in found["weaknesses"][1]["text"]


def test_separate_fields_are_also_kept_whole_in_the_narrative(html):
    value = '<div class="note-content-value markdown-rendered">'
    label = '<strong class="note-content-field">'
    field = f"Strengths:</strong>{value}<p>Why it is good:</p><ol><li>Clear.</li></ol></div></div>"
    page = html.replace("Quality:</strong>", f"{field}<div>{label}Quality:</strong>", 1)
    review = reviews_from_forum_page(page)[0]

    assert {"title": "Strengths", "content": "Why it is good:\n\n1. Clear."} in (
        [p for p in review["narrative"] if "role" not in p]
    )
    assert "Strengths" not in review["extensions"]["openreview"]["unmapped_fields"]
    codec_validate(review)


def test_a_point_keeps_the_relative_indentation_of_its_continuation_lines():
    found = weaknesses(
        "**Weaknesses**\n\n1. Outer point:\n   - inner\n     - deeper\n"
        "   ```\n     indented code\n   ```\n2. Next."
    )

    assert found["weaknesses"][0]["text"] == (
        "Outer point:\n- inner\n  - deeper\n```\n  indented code\n```"
    )


def test_presentation_is_matched_to_the_catalog_like_the_openreview_mapper_does(html):
    page = html.replace("Originality:</strong>", "Presentation:</strong>", 1)
    metrics = {m["label"]: m for m in reviews_from_forum_page(page)[0]["metrics"]}

    assert (metrics["Presentation"]["key"], metrics["Presentation"]["aspect"]) == (
        "clarity",
        "clarity",
    )


def test_bold_questions_under_a_questions_heading_are_kept():
    found = weaknesses("**Questions**\n\n**Is it stable?**\n\n**Why not LPIPS?**")

    assert [(q["text"], q["group"]) for q in found["questions"]] == [
        ("**Is it stable?**", ["Questions"]),
        ("**Why not LPIPS?**", ["Questions"]),
    ]


def test_a_heading_that_asks_a_question_still_starts_a_section():
    found = weaknesses("## Questions?\n\n1. Why not LPIPS?")

    assert [q["text"] for q in found["questions"]] == ["Why not LPIPS?"]


def test_score_names_match_the_catalog_by_whole_words(html):
    page = html.replace("Originality:</strong>", "Unsoundness:</strong>", 1)
    metrics = {m["label"]: m for m in reviews_from_forum_page(page)[0]["metrics"]}

    assert metrics["Unsoundness"]["key"] == "other"


def test_a_long_markdown_heading_still_starts_a_section():
    heading = (
        "Weaknesses and concerns regarding the experimental evaluation and baseline comparisons"
    )
    found = weaknesses(f"#### Strengths\n\n1. Clear.\n\n#### {heading}\n\n1. No baselines.")

    assert [p["text"] for p in found["strengths"]] == ["Clear."]
    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [("No baselines.", [heading])]


@pytest.mark.parametrize(
    ("rating", "value", "recommendation"),
    [
        ("-1: Weak reject", -1, "weak_reject"),
        ("4: Borderline: could go either way", 4, "borderline"),
        ("6: Strong Accept", 6, "strong_accept"),
    ],
)
def test_signed_and_borderline_ratings(html, rating, value, recommendation):
    page = html.replace("5: Accept: Technically solid paper, with high impact.", rating)
    review = reviews_from_forum_page(page)[0]
    overall = next(m for m in review["metrics"] if m["key"] == "overall")

    assert overall["value"] == value
    assert review["decision"]["recommendation"] == recommendation
    codec_validate(review)


def test_minor_strengths_are_strengths():
    found = weaknesses("#### Minor strengths\n\n1. Nice figures.\n\n#### Minor\n\n1. A typo.")

    assert [(p["text"], "severity" in p) for p in found["strengths"]] == [("Nice figures.", False)]
    assert [(p["text"], p["severity"]) for p in found["weaknesses"]] == [("A typo.", "minor")]


@pytest.mark.parametrize(
    ("signature", "mode"),
    [
        ("Reviewer abcd", "pseudonymous"),
        ("Area Chair x1Y2", "pseudonymous"),
        ("~Jane_Doe1", "open"),
        ("Anonymous", "confidential"),
        ("Jane Doe", "confidential"),
        ("Someone Unrecognised", "confidential"),
    ],
)
def test_only_disclosed_signatures_are_treated_as_disclosed(html, signature, mode):
    page = html.replace("by <span>Reviewer abcd</span>", f"by <span>{signature}</span>", 1)
    review = reviews_from_forum_page(page)[0]

    assert review["referees"][0]["identity_mode"] == mode
    assert review["referees"][0]["referee_id"] == signature


def test_closing_hashes_of_a_heading_are_not_part_of_it():
    found = weaknesses(
        "## Weaknesses ##\n\n1. No FlowMDM.\n\n#### References ####\n\n1. [1] A paper."
    )

    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("No FlowMDM.", ["Weaknesses"])
    ]


@pytest.mark.parametrize("offset", ["+00:99", "-24:00", "+12:60"])
def test_an_out_of_range_utc_offset_is_refused(offset):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError, match="invalid UTC offset"):
        load_script().parse_timezone(offset)


def test_a_valid_utc_offset_is_read():
    assert utc_iso(datetime(2025, 7, 3, 2, 28, tzinfo=load_script().parse_timezone("-07:30"))) == (
        "2025-07-03T09:58:00Z"
    )


@pytest.mark.parametrize("label", ["Review", "Main Review", "Detailed Review", "Comments"])
def test_a_report_in_a_single_field_is_the_detailed_review(html, label):
    start = html.index('<strong class="note-content-field">Strengths And Weaknesses:</strong>')
    end = html.index('<strong class="note-content-field">Quality:</strong>')
    field = f'<strong class="note-content-field">{label}:</strong><span class="note-content-value">'
    page = html[:start] + field + "One long report.</span></div><div>" + html[end:]
    review = reviews_from_forum_page(page)[0]

    assert narrative_text(review, "review") == "One long report."
    assert label not in review["extensions"]["openreview"]["unmapped_fields"]
    [index] = [i for i, part in enumerate(review["narrative"]) if part.get("role") == "review"]
    assert {"ocrs": f"narrative[{index}]", "field": label, "how": "copied"} in (
        review["extensions"]["openreview"]["source_fields"]
    )
    codec_validate(review)


def test_headings_match_whole_category_words():
    found = weaknesses(
        "**Weaknesses**\n\n**Minority-group evaluation**\n\n1. Missing.\n\n"
        "**Areas to strengthen**\n\n1. Baselines.\n\n**Minor strengths**\n\n1. Figures."
    )

    assert [(p["text"], p["group"], p.get("severity")) for p in found["weaknesses"]] == [
        ("Missing.", ["Weaknesses", "Minority-group evaluation"], None),
        ("Baselines.", ["Weaknesses", "Areas to strengthen"], None),
    ]
    assert [p["text"] for p in found["strengths"]] == ["Figures."]


def test_blank_lines_inside_a_list_item_are_kept():
    found = weaknesses("**Weaknesses**\n\n1. Evidence\n\n   ---\n\n   Conclusion\n2. Next.")

    assert found["weaknesses"][0]["text"] == "Evidence\n\n---\n\nConclusion"
    assert found["weaknesses"][1]["text"] == "Next."


def test_a_paragraph_after_a_quote_or_nested_bullet_stays_apart_in_a_point():
    found = weaknesses(
        "**Weaknesses**\n\n1. Point one\n\n   > quotation\n\n   response\n"
        "2. Point two\n   - nested\n\n   after the bullet"
    )

    assert [p["text"] for p in found["weaknesses"]] == [
        "Point one\n\n> quotation\n\nresponse",
        "Point two\n- nested\n\nafter the bullet",
    ]


def test_numbered_prose_is_not_a_score():
    from ocrs.catalog import load_catalog
    from ocrs.mappers.openreview_page import _metrics

    note = note_with(
        {"Questions": "1: Why was this baseline omitted?", "Rating": "5: Accept", "Summary": "2"}
    )
    metrics = _metrics(note, _Links(), load_catalog())

    assert [(m["label"], m["value"]) for m in metrics] == [("Rating", 5)]
    assert [q["text"] for q in _findings(note, _Links())["questions"]] == [
        "1: Why was this baseline omitted?"
    ]


def test_labels_are_matched_without_regard_to_case(html):
    page = html.replace("Summary:</strong>", "SUMMARY:</strong>", 1)
    review = reviews_from_forum_page(page)[0]

    assert review["opinion"]["summary"]
    assert "SUMMARY" not in review["extensions"]["openreview"]["unmapped_fields"]


def test_numeric_identifiers_are_not_scores():
    from ocrs.catalog import load_catalog
    from ocrs.mappers.openreview_page import _metrics

    note = note_with({"Paper ID": "1234", "Rating": "5: Accept", "Created At": "1735689600000"})
    links = _Links()
    metrics = _metrics(note, links, load_catalog())

    assert [(m["label"], m["value"]) for m in metrics] == [("Rating", 5)]
    assert links.used == {"rating"}


def test_a_hard_break_in_a_list_item_keeps_the_continuation_in_the_finding():
    item = markdown(
        "<ol><li>It has problems:<br><strong>No baselines</strong></li><li>Next</li></ol>"
    )
    found = weaknesses(f"**Weaknesses**\n\n{item}")

    assert [p["text"] for p in found["weaknesses"]] == [
        "It has problems:\\\n**No baselines**",
        "Next",
    ]


def test_minor_questions_are_questions():
    found = weaknesses("#### Minor questions\n\n1. Why LPIPS?\n\n#### Minor\n\n1. A typo.")

    assert [(q["text"], q["group"]) for q in found["questions"]] == [
        ("Why LPIPS?", ["Minor questions"])
    ]
    assert [(p["text"], p["severity"]) for p in found["weaknesses"]] == [("A typo.", "minor")]


def test_images_saved_beside_the_page_resolve_from_the_output_folder(tmp_path):
    pages = tmp_path / "saved"
    (pages / "Paper_files").mkdir(parents=True)
    (pages / "Paper_files" / "f.png").write_bytes(b"png")
    page = pages / "page.html"
    page.write_text(
        PAGE.read_text(encoding="utf-8")
        .replace(
            "<p>The paper predicts",
            '<p><img src="Paper_files/f.png" alt="Fig"> The paper predicts',
            1,
        )
        .replace("A learned sparsity predictor.", '<img src="https://e.org/r.png" alt="R">', 1)
    )
    out = tmp_path / "elsewhere" / "reviews"

    result = run_script(page, out)

    assert result.returncode == 0, result.stderr
    review = json.loads((out / "REV00000001.json").read_text(encoding="utf-8"))
    summary = review["opinion"]["summary"]
    path = summary.split("](")[1].split(")")[0]
    assert (out / path).resolve() == (pages / "Paper_files" / "f.png").resolve()
    other = json.loads((out / "REV00000002.json").read_text(encoding="utf-8"))
    assert "![R](https://e.org/r.png)" in other["opinion"]["summary"]  # a remote image is left


def test_rebasing_leaves_remote_data_and_absolute_images_alone(html):
    base = "../saved"
    page = html.replace(
        "<p>The paper predicts",
        '<p><img src="https://e.org/a.png"><img src="data:image/png;base64,AA"><img src="/abs.png">'
        '<img src="rel/b.png"> The paper predicts',
        1,
    )
    summary = parse_forum_page(page, asset_base=base).notes[1].get("Summary")

    assert "![](https://e.org/a.png)" in summary
    assert "![](data:image/png;base64,AA)" in summary
    assert "![](/abs.png)" in summary
    assert "![](../saved/rel/b.png)" in summary


def test_the_page_folder_uri_is_the_asset_base_when_there_is_no_relative_path(
    monkeypatch, tmp_path
):
    script = load_script()

    def across_drives(*args, **kwargs):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    monkeypatch.setattr(script.os.path, "relpath", across_drives)

    base = script.asset_base(tmp_path / "page.html", tmp_path / "out")

    assert base == tmp_path.resolve().as_uri()
    html = PAGE.read_text(encoding="utf-8").replace(
        "<p>The paper predicts", '<p><img src="Paper_files/f.png"> The paper predicts', 1
    )
    summary = parse_forum_page(html, asset_base=base).notes[1].get("Summary")
    assert f"![]({base}/Paper_files/f.png)" in summary


def test_a_quoted_label_is_not_a_heading():
    found = weaknesses(
        "**Weaknesses**\n\n> Summary:\n\n1. No baselines.\n\n> **Strengths**\n\n2. More."
    )

    assert [p["text"] for p in found["weaknesses"]] == ["No baselines.", "More."]
    assert "strengths" not in found


def test_a_link_around_a_saved_image_is_rebased_with_it():
    html = PAGE.read_text(encoding="utf-8").replace(
        "<p>The paper predicts",
        '<p><a href="Paper_files/full.png"><img src="Paper_files/thumb.png"></a>'
        '<a href="https://e.org/x"><img src="Paper_files/t2.png"></a>'
        '<a href="#top"><img src="Paper_files/t3.png"></a> The paper predicts',
        1,
    )
    summary = parse_forum_page(html, asset_base="../saved").notes[1].get("Summary")

    assert "[![](../saved/Paper_files/thumb.png)](../saved/Paper_files/full.png)" in summary
    assert "[![](../saved/Paper_files/t2.png)](https://e.org/x)" in summary
    assert "[![](../saved/Paper_files/t3.png)](#top)" in summary


@pytest.mark.parametrize("label", ["**Weaknesses**", "Weaknesses:", "#### Weaknesses"])
def test_a_label_followed_by_a_line_break_is_a_heading(label):
    found = weaknesses(f"{label}\\\nNo baseline.\n\n**Strengths**\\\nClear.")

    assert [p["text"] for p in found["weaknesses"]] == ["No baseline."]
    assert [p["text"] for p in found["strengths"]] == ["Clear."]


def test_only_headings_below_a_category_belong_to_it():
    found = weaknesses(
        "## Weaknesses\n\n### Experiments\n\n#### Baselines\n\n1. No FlowMDM.\n\n"
        "#### Metrics\n\n1. Only FID.\n\n## Additional resources\n\nCode: https://e.org/x"
    )

    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("No FlowMDM.", ["Weaknesses", "Experiments", "Baselines"]),
        ("Only FID.", ["Weaknesses", "Experiments", "Metrics"]),
    ]


def test_a_link_around_several_saved_images_is_rebased_once():
    html = PAGE.read_text(encoding="utf-8").replace(
        "<p>The paper predicts",
        '<p><a href="Paper_files/full.png"><img src="Paper_files/a.png">'
        '<img src="Paper_files/b.png"></a> The paper predicts',
        1,
    )
    summary = parse_forum_page(html, asset_base="..").notes[1].get("Summary")

    assert "(../Paper_files/full.png)" in summary
    assert "../../" not in summary


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        (
            '<p><a href="Paper_files/r.pdf">Paper_files/r.pdf</a></p>',
            r"[Paper\_files/r.pdf](Paper_files/r.pdf)",
        ),
        ('<p><a href="#top">#top</a></p>', "[#top](#top)"),
        ('<p><a href="https://e.org/x">https://e.org/x</a></p>', "https://e.org/x"),
    ],
)
def test_only_web_addresses_stand_for_themselves(fragment, expected):
    assert markdown(fragment) == expected


def test_an_enclosing_category_returns_after_a_nested_one():
    found = weaknesses(
        "## Weaknesses\n\n### Minor\n\n1. A typo.\n\n### Experimental evaluation\n\n"
        "1. Only FID.\n\n## Strengths\n\n1. Clear."
    )

    assert [(p["text"], p["group"], p.get("severity")) for p in found["weaknesses"]] == [
        ("A typo.", ["Weaknesses", "Minor"], "minor"),
        ("Only FID.", ["Weaknesses", "Experimental evaluation"], None),
    ]
    assert [(p["text"], p["group"]) for p in found["strengths"]] == [("Clear.", ["Strengths"])]


@pytest.mark.parametrize(
    ("mathml", "expected"),
    [
        ("<mi>sin</mi><mi>x</mi>", r"$\mathrm{sin}x$"),
        ('<mi mathvariant="italic">sin</mi>', "$sin$"),
        ("<mi>x</mi>", "$x$"),
    ],
)
def test_multi_letter_identifiers_are_upright(mathml, expected):
    assert math(mathml) == expected


def test_a_heading_after_a_bold_subheading_still_ends_the_category():
    found = weaknesses(
        "## Weaknesses\n\n**Evaluation**\n\n1. Only FID.\n\n## Additional resources\n\n1. Code."
    )

    assert [p["text"] for p in found["weaknesses"]] == ["Only FID."]


def test_a_heading_after_a_category_label_still_ends_a_numbered_heading():
    found = weaknesses(
        "## Weaknesses\n\n**Minor**\n\n1. A typo.\n\n## Additional resources\n\n1. Code."
    )

    assert [(p["text"], p["group"], p.get("severity")) for p in found["weaknesses"]] == [
        ("A typo.", ["Weaknesses", "Minor"], "minor")
    ]


def test_brackets_and_backslashes_in_labels_and_alt_text_are_each_escaped_once():
    assert markdown('<p><a href="https://e.org/x">a\\[1]</a></p>') == r"[a\\\[1\]](https://e.org/x)"
    assert markdown('<p><img src="x.png" alt="a\\[1]"></p>') == r"![a\\\[1\]](x.png)"


def test_block_markers_after_a_hard_break_and_leading_spaces_stay_text():
    # Runs of spaces in the page are one space, which Markdown allows before a marker.
    assert markdown("<p>a<br>   # b<br> &gt; c<br>  - d<br> 1. e</p>") == (
        "a\\\n \\# b\\\n \\> c\\\n \\- d\\\n 1\\. e"
    )


def test_a_category_label_replaces_the_label_before_it_and_its_numbered_subheadings():
    found = weaknesses(
        "**Weaknesses**\n\n### Details\n\n1. Only FID.\n\n**Strengths**\n\n1. Clear.\n\n"
        "### More\n\n1. Fast."
    )

    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("Only FID.", ["Weaknesses", "Details"])
    ]
    assert [(p["text"], p["group"]) for p in found["strengths"]] == [
        ("Clear.", ["Strengths"]),
        ("Fast.", ["Strengths", "More"]),
    ]


@pytest.mark.parametrize("label", ["***Weaknesses***", "**_Weaknesses_**", "__*Weaknesses*__:"])
def test_a_label_in_nested_emphasis_is_a_heading(label):
    found = weaknesses(f"**Strengths**\n\n1. Clear.\n\n{label}\n\n1. No baselines.")

    assert [p["text"] for p in found["strengths"]] == ["Clear."]
    assert [(p["text"], p["group"]) for p in found["weaknesses"]] == [
        ("No baselines.", ["Weaknesses"])
    ]


def test_entity_like_ampersands_in_destinations_are_escaped():
    assert markdown('<p><a href="https://e.org/?a=1&amp;amp;b=2">x</a></p>') == (
        r"[x](https://e.org/?a=1\&amp;b=2)"
    )
    assert markdown('<p><img src="https://e.org/i.png?w=1&amp;copy;" alt="f"></p>') == (
        r"![f](https://e.org/i.png?w=1\&copy;)"
    )
    assert markdown('<p><a href="https://e.org/?a=1&amp;b=2">x</a></p>') == (
        "[x](https://e.org/?a=1&b=2)"
    )


def test_alt_text_of_an_image_without_a_source_is_escaped():
    assert markdown('<p><img alt="a <b> *c* [d]"></p>') == r"a \<b> \*c\* [d]"
    assert markdown('<p><a href="https://e.org/x"><img alt="a [d]"></a></p>') == (
        r"[a \[d\]](https://e.org/x)"
    )
