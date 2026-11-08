# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Inputs a caller does not control cost time in proportion to their size, and cannot
reach outside the process: the cases a security scan raised against the mappers, the HTML
reader and validation. Each slow case took seconds to hours before; the bounds here leave
a wide margin over what the fixed code takes."""

import json
import time
import urllib.request
from contextlib import contextmanager

import pytest
from jsonschema import ValidationError

from ocrs import load_schema, validate_canonical
from ocrs.anchors import MAX_FUZZY_PAIRS, Block, BlockKind, find_quote, share_found_in_order
from ocrs.gaps import leftover
from ocrs.mappers import deepreview, reviewer3
from ocrs.mappers.jats import from_jats, sub_articles
from ocrs.mappers.openreview_page import Forum, Note, _Builder, parse_forum_page, to_markdown
from ocrs.schema import _validator_for


@contextmanager
def within(seconds: float):
    start = time.perf_counter()
    yield
    assert time.perf_counter() - start < seconds


# --- Validation -----------------------------------------------------------------------------


def test_loading_another_schema_leaves_default_validation_alone(tmp_path):
    permissive = tmp_path / "permissive.schema.json"
    permissive.write_text(json.dumps({"$id": "https://example.org/permissive"}))
    assert load_schema(permissive) == {"$id": "https://example.org/permissive"}
    with pytest.raises(ValidationError):
        validate_canonical({"not": "a review"})


def test_a_custom_schema_never_downloads_a_reference(tmp_path, monkeypatch):
    fetched = []

    def urlopen(request, *args, **kwargs):
        fetched.append(request)
        raise OSError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    remote = tmp_path / "remote.schema.json"
    remote.write_text(json.dumps({"$ref": "http://169.254.169.254/latest/meta-data"}))
    with pytest.raises(Exception, match="169.254.169.254"):
        validate_canonical({}, schema_path=remote)
    assert fetched == []


@pytest.mark.parametrize(
    ("items", "unique"),
    [
        ([1, 1.0], False),
        ([1, True], True),
        ([0, False], True),
        ([{"a": 1, "b": [2]}, {"b": [2], "a": 1}], False),
        ([{"a": 1}, {"a": True}], True),
        ([[1, 2], [2, 1]], True),
        (["a", "b", "a"], False),
    ],
)
def test_unique_items_keeps_json_equality(items, unique):
    validator = _validator_for({"type": "array", "uniqueItems": True})
    assert validator.is_valid(items) is unique


def test_unique_items_of_objects_take_linear_time():
    # jsonschema compares objects pair by pair: 200 million comparisons here
    validator = _validator_for({"type": "array", "uniqueItems": True})
    with within(2):
        assert validator.is_valid([{"type": "claim", "id": f"c{i}"} for i in range(20_000)])


# --- The OpenReview page reader -------------------------------------------------------------


def test_stray_end_tags_do_not_rescan_the_open_elements():
    builder = _Builder()
    with within(2):
        builder.feed("<div>" * 20_000 + "</span>" * 20_000)
    builder = _Builder()
    builder.feed("<p>a</span>b<b>c</p>d")
    [p] = [c for c in builder.root.children if not isinstance(c, str)]
    assert p.children[:2] == ["a", "b"] and p.children[2].tag == "b"
    assert builder.root.children[-1] == "d"  # the </p> closed the <b> left open in it


def page(notes: str, head: str = "") -> str:
    return (
        f'<html><head><meta name="citation_pdf_url" content="https://openreview.net/pdf?id=F1">'
        f"{head}</head><body>"
        f'<div class="forum-note"><h2 class="citation_title">T</h2></div>'
        f'<div id="forum-replies">{notes}</div></body></html>'
    )


def note(note_id: str, inner: str = "") -> str:
    return (
        f'<div class="note" data-id="{note_id}">'
        f'<span class="invitation">Official Review</span>{inner}</div>'
    )


def test_a_note_id_used_twice_is_refused():
    with pytest.raises(ValueError, match="'n1' twice"):
        parse_forum_page(page(note("n1") + note("n1")))


def test_authors_of_one_name_share_the_first_profile_linked():
    head = "".join(
        f'<meta name="citation_author" content="{name}">' for name in ["A B", "C D", "A B"]
    )
    html = page("", head).replace(
        '<h2 class="citation_title">T</h2>',
        '<a href="/profile?id=~A_B1">A B</a><a href="/profile?id=~A_B2">A B</a>'
        '<a href="/profile?id=~C_D1">C D</a>',
    )
    assert parse_forum_page(html).authors == [
        {"name": "A B", "profile": "~A_B1"},
        {"name": "C D", "profile": "~C_D1"},
        {"name": "A B", "profile": "~A_B1"},
    ]


def flat_note(note_id: str, parent: str | None, kind: str = "Official Review") -> Note:
    return Note(note_id, parent, "", kind, "", "", "", [])


def forum(notes: list[Note]) -> Forum:
    return Forum("F1", "", "", [], None, None, None, None, [], notes, "")


def test_each_reviews_replies_are_found_without_reading_the_whole_page():
    reviews = [flat_note(f"r{i}", "F1") for i in range(20_000)]
    replies = [flat_note(f"c{i}", f"r{i}", "Official Comment") for i in range(20_000)]
    thread = forum(reviews + replies)
    with within(2):
        found = [thread.replies(review.id) for review in reviews]
    assert all(r == [reply] for r, reply in zip(found, replies, strict=True))
    assert thread.decision is None


def test_replies_stay_in_page_order_and_a_note_that_answers_itself_ends():
    notes = [
        flat_note("r", "F1"),
        flat_note("a", "r"),
        flat_note("b", "a"),
        flat_note("c", "r"),
        flat_note("loop", "loop"),
    ]
    assert [n.id for n in forum(notes).replies("r")] == ["a", "b", "c"]
    assert [n.id for n in forum(notes).replies("loop")] == ["loop"]


def markdown(html: str) -> str:
    builder = _Builder()
    builder.feed(f"<div>{html}</div>")
    return to_markdown(builder.root)


def test_a_bare_address_with_markup_in_it_is_written_as_a_link():
    url = "https://example.org/&lt;img src=x onerror=alert(1)&gt;"
    # Text, not a tag: the label's "<" is escaped and the destination's percent-encoded
    assert markdown(f'<a href="{url}">{url}</a>') == (
        "[https://example.org/\\<img src=x onerror=alert(1)>]"
        "(<https://example.org/%3Cimg%20src=x%20onerror=alert(1)%3E>)"
    )
    plain = "https://openreview.net/forum?id=a_b&amp;noteId=c"
    assert markdown(f'<a href="{plain}">{plain}</a>') == (
        "https://openreview.net/forum?id=a_b&noteId=c"
    )


def test_math_never_writes_an_html_angle_bracket():
    mathml = (
        "<mjx-container><mjx-assistive-mml><math><mi>a</mi><mo>&lt;</mo><mi>b</mi>"
        "</math></mjx-assistive-mml></mjx-container>"
    )
    assert markdown(mathml) == "$a\\lt{}b$"
    assert markdown("<mjx-container>&lt;script&gt;</mjx-container>") == "\\<script>"


def test_inline_code_stays_in_one_paragraph():
    assert markdown("<p>Run <code>a\n\nb</code> now</p>") == "Run `a  b` now"


# --- Reviewer3 ------------------------------------------------------------------------------


def test_reviewer3_patterns_take_linear_time():
    with within(2):
        assert not reviewer3.COMMENT_START.match("1. **Title**" + " " * 50_000 + "!")
        assert not list(reviewer3.PERCENT.finditer("1" * 50_000))
        assert not list(reviewer3.COUNT.finditer("1 a" + " " * 50_000 + "!"))
        assert not list(reviewer3.COUNT.finditer("1" * 50_000))


def test_reviewer3_patterns_read_what_they_did():
    header = reviewer3.COMMENT_START.match("2. **Unclear baseline** — Pages 3–4  ")
    assert header.groups() == ("", "2", "Unclear baseline", "3", "4")
    assert reviewer3.COMMENT_START.match("1. **Title**  ").group(4) is None
    counts = " 10 verified, 1 not  found; 2 unverifiable."
    assert [m.groups() for m in reviewer3.COUNT.finditer(counts)] == [
        ("10", "verified"),
        ("1", "not  found"),
        ("2", "unverifiable"),
    ]
    found = [m.groups() for m in reviewer3.PERCENT.finditer("1.2.3% human, 97 % AI")]
    assert found == [("2.3", "human"), ("97", "AI")]


def test_a_sparse_reference_table_too_large_to_write_is_refused():
    entries = [{"status": "", f"column {i}": "x"} for i in range(400)]
    with pytest.raises(ValueError, match="cells to write as a table"):
        reviewer3.write_reference_check({}, {"entries": entries})
    assert reviewer3.write_reference_check({}, {"entries": entries[:3]}).count("\n") == 4


# --- DeepReview -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "head", ["Page 1" + "and1" * 40 + "!", "Table I" + " and I" * 40 + "!", "Page 1" * 2000]
)
def test_a_place_heading_takes_linear_time(head):
    with within(2):
        assert not deepreview.PLACES_ONLY.match(head)


@pytest.mark.parametrize(
    ("head", "places"),
    [
        ("Page 1, Column 2", True),
        ("Table I(a) and Table I(b)", True),
        ("Sections 3, 4 and 5", True),
        ("Figure X2", True),
        ("Appendix A.1 & B", True),
        ("Table 1 Conflicts with the Prose", False),
    ],
)
def test_place_headings_are_read_as_before(head, places):
    assert bool(deepreview.PLACES_ONLY.match(head)) is places


def test_many_rewrites_in_one_issue_take_linear_time():
    text = 'Change "a" to "b". ' * 5_000 + 'Do not change "c" to "d".'
    with within(2):
        phrases = list(deepreview.edit_phrases(text))
    assert len(phrases) == 5_001
    assert not any(negated for *_, negated, _ in phrases[:-1])
    assert phrases[-1][3] is True


# --- JATS -----------------------------------------------------------------------------------

ENTITY = '<!DOCTYPE sub-article [<!ENTITY big "aaaaaaaaaa">]>'


def test_jats_that_declares_an_entity_is_refused():
    body = "<sub-article><front-stub/><body><p>&big;</p></body></sub-article>"
    with pytest.raises(ValueError, match="may not declare entities"):
        from_jats({"sub_article": ENTITY + body})
    with pytest.raises(ValueError, match="may not declare entities"):
        sub_articles(ENTITY.replace("sub-article", "article") + "<article/>")


def test_ill_formed_jats_is_still_an_xml_error():
    with pytest.raises(SyntaxError):  # ElementTree's ParseError
        from_jats({"sub_article": "<sub-article><body>"})


def test_a_shared_affiliation_is_read_once_and_kept_once():
    contribs = "".join(
        f'<contrib contrib-type="author"><name><surname>S{i}</surname></name>'
        '<xref ref-type="aff" rid="a1"/></contrib>'
        for i in range(3)
    )
    front = f'<contrib-group>{contribs}<aff id="a1"><label>1</label>Uni, City</aff></contrib-group>'
    xml = f"<sub-article><front-stub>{front}</front-stub><body><p>Fine.</p></body></sub-article>"
    referees = from_jats({"sub_article": xml})["referees"]
    affiliations = [referee["human_referee"]["affiliation"] for referee in referees]
    assert affiliations == ["Uni, City"] * 3
    assert len({id(a) for a in affiliations}) == 1


# --- Gaps and anchors -----------------------------------------------------------------------


def test_coverage_is_looked_up_rather_than_scanned():
    output = {"comments": [{"text": f"t{i}", "extra": i} for i in range(20_000)]}
    read = {f"comments[{i}].text" for i in range(20_000)}
    with within(2):
        left = leftover(output, read, set())
    assert left == {"comments": [{"extra": i} for i in range(20_000)]}


@pytest.mark.parametrize(
    ("path", "read", "covered"),
    [
        ("a.b", {"a"}, True),
        ("a[2].b", {"a[2]"}, True),
        ("ab", {"a"}, False),
        ("a.b.c", {"a.b"}, True),  # a key with a dot in it, as before
        ("a", {"a.b"}, False),
    ],
)
def test_coverage_keeps_its_path_rules(path, read, covered):
    from ocrs.gaps import _covered

    assert _covered(path, read) is covered


def test_a_fuzzy_comparison_too_costly_to_make_is_not_made():
    quote, text = "ab" * 2_000, "ab" * 2_000 + "c"
    assert len(quote) * len(text) > MAX_FUZZY_PAIRS
    with within(1):
        assert share_found_in_order(quote, text) == 0.0
    block = Block(id="b1", kind=BlockKind.BODY, text="x" + text)
    with within(1):
        assert find_quote(quote + "d", [block]) == (None, 0.0)
    assert share_found_in_order("quoted text", "the quoted text here") == 1.0
