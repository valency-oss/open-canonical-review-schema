# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the Reviewer3 mapper: Reviewer3's Markdown report to OCRS."""

from pathlib import Path

import pytest
from conftest import codec_map_from, codec_map_with_record, codec_validate

from ocrs import supported_sources
from ocrs.mapping import MappingStatus, Rule

REPORT = (Path(__file__).parent / "fixtures" / "ai" / "reviewer3_report.md").read_text()
RUN = {
    "review_id": "reviewer3-1",
    "source_system": "reviewer3",
    "work_id": "paper-1",
    "work_type": "preprint",
    "started_at": "2026-10-15T17:00:00Z",
    "ended_at": "2026-10-15T17:30:00Z",
}


def mapped(report=REPORT, **run):
    return codec_map_with_record("reviewer3", report, **{**RUN, **run})


def section(heading, body):
    """A minimal report with one section besides the title."""
    return f"# Review Report\n\nA paper\n\n---\n\n### {heading}\n\n{body}\n"


# An Overview with one contribution, for a report whose section under test says nothing
OVERVIEW = "\n### Overview\n\n- **A contribution** — Text.\n"


@pytest.fixture(scope="module")
def result():
    return mapped()


@pytest.fixture(scope="module")
def checks(result):
    return {check["kind"]: check for check in result.review["checks"]}


@pytest.fixture(scope="module")
def comments(result):
    return {comment["id"]: comment for comment in result.review["findings"]["comments"]}


def test_maps_the_whole_report(result):
    codec_validate(result.review)
    record = result.record
    assert record.status == MappingStatus.OK
    assert record.source_format == "reviewer3"
    assert record.gaps.unmapped == []
    assert record.gaps.coerced == []
    assert record.gaps.unanchored is None
    assert "extensions" not in result.review


def test_registered():
    assert "reviewer3" in supported_sources()


def test_title_and_text_format(result):
    title = "Multi-source forecasting of bay temperatures in the Brannock cold-storage depot"
    assert result.review["target"]["title"] == title
    assert result.review["text_format"] == {"markup": "markdown", "math": "tex"}


def test_overview_is_contributions_not_strengths(result):
    contributions = result.review["opinion"]["contributions"]
    assert [c["title"] for c in contributions] == [
        "Multi-Source Bay Temperature Forecasting Architecture",
        "Improved Long-Lead Forecast Accuracy",
        "Complementary Sensor Roles",
    ]
    assert contributions[1]["text"].startswith("The study demonstrates that at a 30-minute")
    assert "strengths" not in result.review["findings"]
    assert "summary" not in result.review["opinion"]


def test_ai_text_detection(checks):
    check = checks["ai_text_detection"]
    assert check["performed_by"] == {"name": "Pangram"}
    assert check["summary"].startswith("29% AI-generated and 0% AI-assisted")
    assert check["measurements"] == [
        {"key": "ai_generated", "label": "AI-generated", "value": 0.29, "unit": "fraction"},
        {"key": "ai_assisted", "label": "AI-assisted", "value": 0.0, "unit": "fraction"},
    ]
    assert "outcome" not in check  # numbers, no verdict


def test_fatal_flaws_none_found(checks):
    check = checks["fatal_flaw_screen"]
    assert check["outcome"] == "no_issues"
    assert check["summary"] == "No fatal methodological flaws were identified."
    assert "finding_ids" not in check


def test_reference_check(checks):
    check = checks["reference_verification"]
    assert check["summary"] == "Checked 52 references: 50 verified, 2 not found."
    assert check["measurements"] == [
        {"key": "checked", "value": 52},
        {"key": "verified", "value": 50},
        {"key": "not_found", "value": 2},
    ]
    assert "outcome" not in check
    first = check["items"][0]
    assert first["status"] == "Not Found"
    assert first["flagged"] is True
    assert first["target"]["type"] == "bibliography"
    assert first["target"]["ref"] == "9"
    assert first["target"]["work"]["citation"].startswith(
        "R. Vantongeren, K. Osei and L. Brask, “BCSD"
    )
    assert [item["target"]["ref"] for item in check["items"]] == ["9", "21"]


def test_comments_are_unclassified_points(result, comments):
    assert list(comments) == [f"comment-{n}" for n in range(1, 7)]
    assert set(result.review["findings"]) == {"comments"}
    first = comments["comment-1"]
    assert first["title"] == "Symbolcollision for κ between time constant and threshold"
    assert first["text"].startswith("In Section 2.6, Eq. (6) (page 20), $\\kappa$")
    assert first["group"] == ["Reviewer Comments"]
    assert all("severity" not in comment for comment in comments.values())


def test_comment_without_page_or_excerpt_has_no_link(comments):
    assert "evidence_links" not in comments["comment-1"]


def test_comment_excerpt_and_page(comments):
    [link] = comments["comment-2"]["evidence_links"]
    assert link["type"] == "paper_section"
    assert link["ref"] == "Page 8"
    assert link["location"] == {"page": 8}
    assert link["quote"].startswith("sensor drift while keeping the aisle structure.")
    assert link["quote"].endswith("small Gaussian kernels on CTA floor-plan rasters")
    assert not comments["comment-2"]["text"].startswith(">")


def test_figure_label_excerpt_is_a_figure_link(comments):
    assert comments["comment-3"]["evidence_links"] == [
        {"type": "figure", "ref": "Fig 3", "location": {"page": 26}}
    ]


def test_parsed_values_are_recorded(result):
    parsed = {
        (step.source, step.target) for step in result.record.steps if step.rule == Rule.PARSED
    }
    assert ("ai_text_detection", "checks[0].performed_by.name") in parsed
    assert ("fatal_flaws.text", "checks[1].outcome") in parsed
    assert ("comments[2].excerpt", "findings.comments[2].evidence_links[0].resource.type") in parsed
    assert ("comments[1].page", "findings.comments[1].evidence_links[0].location.page") in parsed


def test_listed_fatal_flaws_are_critical_weaknesses():
    report = section(
        "Fatal Flaws",
        "- **Leakage between splits** — Test days sit between training days.\n"
        "- The baseline is tuned on the test set.",
    )
    result = mapped(report)
    codec_validate(result.review)
    [check] = result.review["checks"]
    weaknesses = result.review["findings"]["weaknesses"]
    assert check["outcome"] == "issues_found"
    assert check["finding_ids"] == ["fatal-flaw-1", "fatal-flaw-2"]
    assert [w["severity"] for w in weaknesses] == ["critical", "critical"]
    assert weaknesses[0]["title"] == "Leakage between splits"
    assert weaknesses[1]["text"] == "The baseline is tuned on the test set."


def test_fatal_flaws_without_a_verdict_get_no_outcome():
    result = mapped(section("Fatal Flaws", "The screen could not finish on this manuscript."))
    [check] = result.review["checks"]
    assert "outcome" not in check
    assert check["summary"] == "The screen could not finish on this manuscript."


def test_reference_rows_as_list_items():
    """The .docx renders the table's rows as `#N — Citation: … — Status: …` lines."""
    body = (
        "Checked **3** references: 2 verified, 1 not found.\n\n"
        "- #4 — Citation: A. Author, A thesis (2026). — Status: Not Found\n"
        "- #7 — Citation: B. Author, A paper (2020). — Status: Verified"
    )
    [check] = mapped(section("Reference Check", body)).review["checks"]
    assert [(i["target"]["ref"], i["status"], i["flagged"]) for i in check["items"]] == [
        ("4", "Not Found", True),
        ("7", "Verified", False),
    ]
    assert check["measurements"][0] == {"key": "checked", "value": 3}


def test_page_range():
    body = "1. **A point** — Pages 27–28\n\n> some text from the paper\n\nThe explanation."
    [comment] = mapped(section("Reviewer Comments", body)).review["findings"]["comments"]
    [link] = comment["evidence_links"]
    assert link["ref"] == "Page 27–28"
    assert link["location"] == {"page": 27, "page_end": 28}
    assert comment["text"] == "The explanation."


def test_unknown_sections_are_kept_in_extensions():
    report = REPORT + "\n### Questions for the Authors\n\nWhy 60 minutes?\n"
    result = mapped(report)
    other = result.review["extensions"]["reviewer3"]["other"]
    assert other == {"Questions for the Authors": "Why 60 minutes?"}
    assert [f.path for f in result.record.gaps.unmapped] == ["other.Questions for the Authors"]


def test_quotes_are_checked_against_the_paper(comments):
    quote = comments["comment-6"]["evidence_links"][0]["quote"]
    blocks = [{"id": "p1", "kind": "body", "text": f"Earlier text. {quote} Later text."}]
    result = mapped(blocks=blocks)
    anchored = [step for step in result.record.steps if step.rule == Rule.ANCHORED_EXACT]
    assert [(step.source, step.result) for step in anchored] == [
        ("comments[5].excerpt", {"part": "body", "block_id": "p1"})
    ]
    # Comments 2, 4 and 5 quote text this one-paragraph "paper" lacks; comment 1 quotes
    # nothing, and comment 3's excerpt is the label `Fig 3`, not text.
    unanchored = [quote.source for quote in result.record.gaps.unanchored]
    assert unanchored == ["comments[1].excerpt", "comments[3].excerpt", "comments[4].excerpt"]


def test_keep_raw_keeps_the_markdown():
    out = codec_map_from("reviewer3", {"output": REPORT, **RUN}, keep_raw=True)
    assert out["provenance"]["raw_payload"] == {"text": REPORT}


def test_output_must_be_text():
    with pytest.raises(TypeError, match="Markdown text"):
        mapped({"not": "markdown"})


def test_escaped_pipe_stays_in_the_citation():
    body = (
        "Checked **1** references: 0 verified, 1 not found.\n\n"
        "| # | Citation | Status |\n| --- | --- | --- |\n"
        "| 3 | A. Author, Gain \\| loss in surveys (2020). | **Not Found** |"
    )
    [check] = mapped(section("Reference Check", body)).review["checks"]
    [item] = check["items"]
    assert item["target"]["work"]["citation"] == "A. Author, Gain | loss in surveys (2020)."
    assert item["status"] == "Not Found"


def test_extra_table_columns_are_kept_in_extensions():
    body = (
        "Checked **1** references: 0 verified, 1 not found.\n\n"
        "| # | Citation | Status | Note |\n| --- | --- | --- | --- |\n"
        "| 3 | A. Author, A paper (2020). | Not Found | Possibly a preprint |"
    )
    result = mapped(section("Reference Check", body))
    assert result.review["checks"][0]["items"][0]["status"] == "Not Found"
    entry = result.review["extensions"]["reviewer3"]["reference_check"]["entries"][0]
    assert entry["note"] == "Possibly a preprint"


def test_reference_check_of_prose_only():
    result = mapped(section("Reference Check", "No references to check."))
    codec_validate(result.review)
    [check] = result.review["checks"]
    assert check["summary"] == "No references to check."
    assert "measurements" not in check and "items" not in check


def test_a_comment_without_explanation_is_skipped_and_kept():
    body = "1. **Missing baseline**\n\n2. **Other point** — Page 3\n\nThe explanation."
    result = mapped(section("Reviewer Comments", body))
    codec_validate(result.review)
    [comment] = result.review["findings"]["comments"]
    assert comment["id"] == "comment-2"
    assert result.record.status == MappingStatus.PARTIAL
    assert [(s.source, s.reason) for s in result.record.skipped] == [
        ("comments[0]", "no explanation")
    ]
    kept = result.review["extensions"]["reviewer3"]["comments"][0]
    assert kept["title"] == "Missing baseline"


def test_multiline_points_keep_their_formatting():
    body = (
        "- **A contribution** — First paragraph,\n"
        "  still the first.\n"
        "\n"
        "  Second paragraph:\n"
        "\n"
        "      code_line()\n"
        "  - a nested item\n"
        "- **Another** — One line.\n"
        "\n"
        "Text after the list."
    )
    result = mapped(section("Overview", body))
    first, second = result.review["opinion"]["contributions"]
    assert first["text"] == (
        "First paragraph,\nstill the first.\n\nSecond paragraph:\n\n"
        "    code_line()\n- a nested item"
    )
    assert second == {"title": "Another", "text": "One line."}
    assert result.review["extensions"]["reviewer3"]["other"] == {"Overview": "Text after the list."}


def test_an_indented_list_is_still_a_list():
    body = "  - **First** — One.\n    - nested under the first\n  - **Second** — Two."
    first, second = mapped(section("Overview", body)).review["opinion"]["contributions"]
    assert first == {"title": "First", "text": "One.\n- nested under the first"}
    assert second == {"title": "Second", "text": "Two."}


def test_a_code_block_alone_under_a_point_keeps_its_indentation():
    body = "- **First** — One.\n\n      code_line()\n- **Second** — Two."
    first, _ = mapped(section("Overview", body)).review["opinion"]["contributions"]
    assert first["text"] == "One.\n\n    code_line()"


def test_repeated_list_numbers_get_unique_ids():
    body = "1. **First**\n\nOne.\n\n1. **Second**\n\nTwo.\n\n1. **Third**\n\nThree."
    result = mapped(section("Reviewer Comments", body))
    codec_validate(result.review)
    ids = [c["id"] for c in result.review["findings"]["comments"]]
    assert ids == ["comment-1", "comment-2", "comment-3"]


def test_a_repeated_check_section_is_kept_not_lost():
    report = section("Fatal Flaws", "No fatal methodological flaws were identified.")
    report += "\n### Fatal Flaws\n\nA second screen found a leak.\n"
    result = mapped(report)
    [check] = result.review["checks"]
    assert check["outcome"] == "no_issues"
    kept = result.review["extensions"]["reviewer3"]["other"]["Fatal Flaws"]
    assert kept == "A second screen found a leak."


def test_a_bulleted_no_flaws_verdict_is_the_verdict():
    result = mapped(section("Fatal Flaws", "- No fatal methodological flaws were identified."))
    [check] = result.review["checks"]
    assert check["outcome"] == "no_issues"
    assert check["summary"] == "No fatal methodological flaws were identified."
    assert "findings" not in result.review
    [outcome] = [step for step in result.record.steps if step.target == "checks[0].outcome"]
    assert outcome.source == "fatal_flaws.items[0].text"


def test_prose_keeps_its_paragraphs_and_indentation():
    body = "The check stopped early.\n\nIt resumed later:\n\n    retry --all"
    [check] = mapped(section("Reference Check", body)).review["checks"]
    assert check["summary"] == body
    flaws = "First paragraph.\n\nSecond paragraph.\n\n- **A flaw** — Leakage."
    [screen] = mapped(section("Fatal Flaws", flaws)).review["checks"]
    assert screen["summary"] == "First paragraph.\n\nSecond paragraph."


def test_a_reference_check_with_nothing_usable_is_left_out():
    body = "| # | Citation | Status |\n| --- | --- | --- |\n| 3 | A. Author, A paper (2020). | |"
    report = (
        section("Reference Check", body) + "\n### Reviewer Comments\n\n1. **A point**\n\nText.\n"
    )
    result = mapped(report)
    codec_validate(result.review)
    assert "checks" not in result.review
    assert (
        result.review["extensions"]["reviewer3"]["reference_check"]["entries"][0]["number"] == "3"
    )


def test_headings_in_code_blocks_are_code():
    body = (
        "1. **A point** — Page 2\n\nSuggested fix:\n\n```\n### Normalize inputs\nx = 1\n```\n\n"
        "2. **Another point**\n\nMore text."
    )
    result = mapped(section("Reviewer Comments", body))
    first, second = result.review["findings"]["comments"]
    assert "### Normalize inputs" in first["text"]
    assert second["title"] == "Another point"
    assert "extensions" not in result.review


def test_nested_numbered_items_stay_in_their_comment():
    body = (
        "1. **Outer point**\n\nTwo cases:\n\n   1. **First case**\n\n   2. **Second case**\n\n"
        "2. **Next point**\n\nText."
    )
    first, second = mapped(section("Reviewer Comments", body)).review["findings"]["comments"]
    assert "1. **First case**" in first["text"] and "2. **Second case**" in first["text"]
    assert [first["id"], second["id"]] == ["comment-1", "comment-2"]
    assert second["title"] == "Next point"


def test_a_fence_closes_only_on_a_bare_marker():
    body = (
        "1. **A point**\n\nExample:\n\n```\n```python\n### Not a section\n"
        "2. **Not a comment**\n```\n\n"
        "2. **Real second point**\n\nText."
    )
    result = mapped(section("Reviewer Comments", body))
    first, second = result.review["findings"]["comments"]
    assert "### Not a section" in first["text"] and "2. **Not a comment**" in first["text"]
    assert second["title"] == "Real second point"


def test_an_inline_code_span_is_not_a_fence():
    report = section(
        "Reviewer Comments",
        "1. **A point**\n\nUse ```example``` here.\n\n2. **Second point**\n\nText.",
    )
    report += "\n### Fatal Flaws\n\nNo fatal methodological flaws were identified.\n"
    result = mapped(report)
    assert [c["title"] for c in result.review["findings"]["comments"]] == [
        "A point",
        "Second point",
    ]
    assert result.review["checks"][0]["outcome"] == "no_issues"


def test_bullets_in_code_are_not_points():
    flaws = (
        "No fatal methodological flaws were identified.\n\n```yaml\nsplits:\n- train\n- test\n```"
    )
    [check] = mapped(section("Fatal Flaws", flaws)).review["checks"]
    assert check["outcome"] == "no_issues"
    assert "- train" in check["summary"]
    overview = "- **A contribution** — Text.\n\n```\n- not a contribution\n```"
    result = mapped(section("Overview", overview))
    assert len(result.review["opinion"]["contributions"]) == 1
    assert "- not a contribution" in result.review["extensions"]["reviewer3"]["other"]["Overview"]


def test_reference_rows_in_code_are_prose():
    body = (
        "The check could not run.\n\n```\n| # | Citation | Status |\n| --- | --- | --- |\n"
        "| 1 | Example (2020). | Verified |\n- #2 — Citation: Example two. — Status: Verified\n```"
    )
    [check] = mapped(section("Reference Check", body)).review["checks"]
    assert "items" not in check
    assert "| 1 | Example (2020). | Verified |" in check["summary"]


def test_comments_keep_code_indentation():
    body = (
        "1. **A point** — Page 4\n\n>     first_call()\n>     second_call()\n\n"
        "    explained_call()\nThe explanation."
    )
    [comment] = mapped(section("Reviewer Comments", body)).review["findings"]["comments"]
    assert comment["evidence_links"][0]["quote"] == "    first_call()\n    second_call()"
    assert comment["text"] == "    explained_call()\nThe explanation."


def test_hard_line_breaks_are_kept():
    body = "1. **A point** — Page 4\n\n> first line  \n> second line\n\nOne line  \nnext line."
    [comment] = mapped(section("Reviewer Comments", body)).review["findings"]["comments"]
    assert comment["evidence_links"][0]["quote"] == "first line  \nsecond line"
    assert comment["text"] == "One line  \nnext line."


def test_a_soft_wrapped_verdict_bullet_is_one_verdict():
    flaws = "- No fatal methodological flaws were\nidentified.\n\nThe screen ran on all sections."
    [check] = mapped(section("Fatal Flaws", flaws)).review["checks"]
    assert check["outcome"] == "no_issues"
    assert check["summary"] == (
        "The screen ran on all sections.\n\nNo fatal methodological flaws were\nidentified."
    )


def test_a_code_only_explanation_keeps_its_indentation():
    body = "1. **A point**\n\n       def normalize(x):\n           return x"
    [comment] = mapped(section("Reviewer Comments", body)).review["findings"]["comments"]
    assert comment["text"] == "       def normalize(x):\n           return x"


@pytest.mark.parametrize(
    ("status", "flagged"),
    [
        ("Not Found", True),
        ("Unverified", True),
        ("Failed lookup", True),
        ("Verified (DOI)", False),
        ("Found", False),
        ("OK", False),
        ("Pending", None),
        ("No errors", False),
        ("No mismatch; verified by publisher", False),
        ("No match", True),
        ("Not verified", True),
        ("No errors or mismatches found", False),
        ("Without errors, issues and problems", False),
        ("No errors; mismatch in year", True),
        ("Mismatch resolved", False),
        ("Mismatch not resolved", True),
    ],
)
def test_reference_status_flags(status, flagged):
    body = (
        "Checked **1** references: 1 checked.\n\n"
        "| # | Citation | Status |\n| --- | --- | --- |\n"
        f"| 3 | A. Author, A paper (2020). | {status} |"
    )
    [item] = mapped(section("Reference Check", body)).review["checks"][0]["items"]
    assert item["status"] == status
    assert item.get("flagged") is flagged


def test_a_blockquote_after_a_point_is_its_own_block():
    overview = "- **A contribution** — Soft-wrapped\ntext.\n> Reviewer aside"
    result = mapped(section("Overview", overview))
    [contribution] = result.review["opinion"]["contributions"]
    assert contribution["text"] == "Soft-wrapped\ntext."
    assert result.review["extensions"]["reviewer3"]["other"]["Overview"] == "> Reviewer aside"


def test_a_verdict_in_a_later_paragraph_counts():
    flaws = (
        "Screened the full manuscript.\n\nNo fatal methodological flaws were identified.\n\n"
        "```\nNo fatal flaws in this example.\n```"
    )
    result = mapped(section("Fatal Flaws", flaws))
    [check] = result.review["checks"]
    assert check["outcome"] == "no_issues"
    [step] = [s for s in result.record.steps if s.target == "checks[0].outcome"]
    assert step.source == "fatal_flaws.text"
    assert step.original == "No fatal methodological flaws were identified."
    code_only = mapped(
        section("Fatal Flaws", "Screened.\n\n```\nNo fatal flaws were identified.\n```")
    )
    assert "outcome" not in code_only.review["checks"][0]


def test_a_shorter_fence_does_not_close_a_longer_one():
    body = "- **Point** — Text.\n\n  ````\n  ```\n  - not a point\n  ````\n"
    [contribution] = mapped(section("Overview", body)).review["opinion"]["contributions"]
    assert "- not a point" in contribution["text"]


def test_ai_text_detection_without_a_detector_or_percentages():
    [check] = mapped(section("AI Text Detection", "Detection was not run.")).review["checks"]
    assert check == {
        "id": "ai-text-detection",
        "kind": "ai_text_detection",
        "label": "AI Text Detection",
        "summary": "Detection was not run.",
    }


@pytest.mark.parametrize("heading", ["Fatal Flaws", "Reference Check"])
def test_an_empty_check_section_is_no_check(heading):
    assert "checks" not in mapped(section(heading, "") + OVERVIEW).review


def test_reference_rows_without_number_or_citation():
    body = "| # | Citation | Status |\n| --- | --- | --- |\n"
    body += "| | A. Author (2020). | Verified |\n| 7 | | Not Found |\n"
    [check] = mapped(section("Reference Check", body)).review["checks"]
    assert [item["target"] for item in check["items"]] == [
        {"type": "bibliography", "ref": "", "work": {"citation": "A. Author (2020)."}},
        {"type": "bibliography", "ref": "7"},
    ]


def test_a_comment_excerpt_without_a_page():
    body = "1. **Point**\n\n> some quoted words from the paper\n\nWhy it matters."
    [comment] = mapped(section("Reviewer Comments", body)).review["findings"]["comments"]
    assert comment["evidence_links"] == [
        {"type": "paper_section", "ref": "", "quote": "some quoted words from the paper"}
    ]


def test_reviewer_comments_of_prose_only_are_kept():
    review = mapped(section("Reviewer Comments", "No comments.") + OVERVIEW).review
    assert "findings" not in review
    assert review["extensions"]["reviewer3"]["other"] == {"Reviewer Comments": "No comments."}


def test_a_report_that_says_nothing_is_an_error():
    with pytest.raises(ValueError, match="reviewer3 review has no review content"):
        mapped(section("Reviewer Comments", "No comments."))


def test_a_reference_table_without_a_number_column():
    body = "| Citation | Status |\n| --- | --- |\n| A. Author (2020). | Not Found |\n"
    [check] = mapped(section("Reference Check", body)).review["checks"]
    [item] = check["items"]
    assert item["target"]["ref"] == "" and item["flagged"] is True
