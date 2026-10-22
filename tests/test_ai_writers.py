# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for writing OCRS reviews in the AI reviewers' own formats (`map_to`)."""

import copy
import json
from pathlib import Path

import pytest
from conftest import codec_map_from, codec_map_to, codec_map_with_record, codec_validate

from ocrs import supported_targets
from ocrs.mappers import deepreview, reviewer3
from ocrs.mappers.ai import extension, findings_of, indented, overall_texts, reviewer_model
from ocrs.mappers.openaireview import to_openaireview
from ocrs.util import narrative_text

FIXTURES = Path(__file__).parent / "fixtures"
AI = FIXTURES / "ai"
OPENAIREVIEW = json.loads((AI / "openaireview_paper.json").read_text())
DEEPREVIEW = (AI / "deepreview_report.md").read_text()
REVIEWER3 = (AI / "reviewer3_report.md").read_text()
RUN = {
    "review_id": "3152f8d9-a9e9-4d97-80be-e6b0d7290d42",
    "source_system": "example-platform",
    "work_id": "paper-1",
    "work_type": "preprint",
    "model_id": "us.anthropic.claude-opus-5-5",
    "started_at": "2026-10-03T01:00:00Z",
    "ended_at": "2026-10-03T01:08:00Z",
}


def mapped(source, output):
    return codec_map_with_record(source, copy.deepcopy(output), **RUN).review


def same_review(first, second):
    """The two reviews are the same, but for when each was imported."""
    first, second = copy.deepcopy(first), copy.deepcopy(second)
    for review in (first, second):
        review["provenance"].pop("imported_at")
    return first == second


def human_review():
    return codec_map_from(
        "openreview", json.loads((FIXTURES / "openreview/realistic_review.json").read_text())
    )


DEEPREVIEW_EDGES = """# HIGH LEVEL SUMMARY
---
Generated for the authors.
## Summary
Short summary.
## Strengths
Read with care.
* **Clear:** Well written.
## Weaknesses
* Overview weakness.
## Potential Issues And Suggestions
Read these first.
### [Methods] (Pages: 1-2)
Part intro text.
#### Potential Mistakes and Improvements

1. **Wrong sign (Section 2, Page 3):** The sign of Eq. 1 is flipped.
   It changes the result.

2. **Empty point:**

#### Minor Corrections and Typos

Tier text.
* **Page 4:** Typo in *"the the results are shown here"*; change "the the" to "the".
#### Unknown Tier
* Something odd.
### [Empty part]
## Limitations
Not discussed.
"""

REVIEWER3_EDGES = """# Review Report

A Paper Title

---

Generated on request.

### Overview

Intro.

- **Idea** — A new method.
- Plain contribution
  over two lines.

### AI Text Detection

12.5% AI-generated text detected. See the full Pangram report in the app.

### Fatal Flaws

- **Leakage** — Test data leaks into training.

### Reference Check

Checked **3** references: 1 verified, 1 not found.

| # | Citation | Status | Note |
| --- | --- | --- | --- |
| 1 | A. Author, A title with a \\| pipe (2020). | Verified (DOI) | ok |
| 2 | B. Author (2021). | Not Found | |
| 3 | C. Author (2022). | | no status |

Some trailing prose.

### Fatal Flaws

A repeated section.

### Reviewer Comments

Comments follow.

1. **Typo** — Page 3–4

> the the

Repeated word.

2. **Figure labels** — Page 5

> Fig 2

Panels are unlabeled.

3. **No explanation**

### Appendix

Extra.
"""


def test_ai_reviewers_are_targets():
    assert {"openaireview", "deepreview", "reviewer3"} <= set(supported_targets())


class TestOpenAIReview:
    def test_writes_back_what_was_mapped(self):
        expected = {k: v for k, v in OPENAIREVIEW.items() if k != "paragraphs"}
        expected["methods"] = {
            k: v for k, v in OPENAIREVIEW["methods"].items() if k.startswith("progressive__")
        }
        assert codec_map_to("openaireview", mapped("openaireview", OPENAIREVIEW)) == expected

    def test_round_trip(self):
        review = mapped("openaireview", OPENAIREVIEW)
        assert same_review(mapped("openaireview", codec_map_to("openaireview", review)), review)

    def test_skipped_comment_goes_back_where_it_was(self):
        output = copy.deepcopy(OPENAIREVIEW)
        [key] = [k for k in output["methods"] if k.startswith("progressive__")]
        comments = output["methods"][key]["comments"]
        comments[1]["explanation"] = ""
        back = codec_map_to("openaireview", mapped("openaireview", output))
        assert back["methods"][key]["comments"] == comments

    def test_comments_without_extensions_follow_kept_ones(self):
        review = mapped("openaireview", OPENAIREVIEW)
        review["findings"]["weaknesses"].append({"text": "One more."})
        [method] = codec_map_to("openaireview", review)["methods"].values()
        assert method["comments"][-1] == {"explanation": "One more."}

    def test_a_review_from_elsewhere(self):
        review = human_review()
        paper = codec_map_to("openaireview", review)
        [(key, method)] = paper["methods"].items()
        assert key == "progressive__unspecified"
        assert method["overall_feedback"] == review["opinion"]["summary"]
        points = [*findings_of(review, "weaknesses"), *findings_of(review, "questions")]
        assert [c["explanation"] for c in method["comments"]] == [p["text"] for p in points]
        again = codec_map_with_record("openaireview", paper, **RUN).review
        codec_validate(again)
        assert len(again["findings"]["weaknesses"]) == len(points)

    def test_model_title_tags_quote_and_tokens(self):
        review = {
            **mapped("openaireview", OPENAIREVIEW),
            "target": {"work_id": "doi:10.1234/x", "work_type": "preprint", "title": "T"},
            "findings": {
                "weaknesses": [
                    {
                        "title": "Gap",
                        "text": "A gap.",
                        "tags": ["logical", "other"],
                        "evidence_links": [
                            {"type": "figure", "ref": "Fig 1"},
                            {"type": "paper_section", "ref": "", "quote": "q"},
                        ],
                    }
                ]
            },
        }
        review.pop("extensions")
        paper = to_openaireview(review)
        assert paper["title"] == "T" and paper["slug"] == "paper"
        [(key, method)] = paper["methods"].items()
        assert key == "progressive__us.anthropic.claude-opus-5-5"
        assert method["model"] == "us.anthropic.claude-opus-5-5"
        assert method["comments"] == [
            {"title": "Gap", "quote": "q", "explanation": "A gap.", "comment_type": "logical"}
        ]
        assert (method["prompt_tokens"], method["completion_tokens"]) == (125024, 46844)

    def test_full_text_when_there_is_no_summary(self):
        review = human_review()
        review["opinion"] = {"text": "Full view."}
        review.pop("narrative")
        [method] = codec_map_to("openaireview", review)["methods"].values()
        assert method["overall_feedback"] == "Full view."


class TestDeepReview:
    @pytest.mark.parametrize("report", [DEEPREVIEW, DEEPREVIEW_EDGES], ids=["fixture", "edges"])
    def test_writes_back_the_same_report(self, report):
        written = codec_map_to("deepreview", mapped("deepreview", report))
        assert isinstance(written, str)
        assert deepreview.parse_report(written) == deepreview.parse_report(report)

    @pytest.mark.parametrize("report", [DEEPREVIEW, DEEPREVIEW_EDGES], ids=["fixture", "edges"])
    def test_round_trip(self, report):
        review = mapped("deepreview", report)
        assert same_review(mapped("deepreview", codec_map_to("deepreview", review)), review)

    def test_a_review_from_elsewhere(self):
        review = human_review()
        review["opinion"]["contributions"] = [{"title": "Idea", "text": "A method."}]
        review["findings"]["comments"] = [{"text": "A remark."}]
        review["checks"] = [{"kind": "statistics", "label": "Stats", "summary": "Fine."}]
        written = codec_map_to("deepreview", review)
        report = deepreview.parse_report(written)
        assert report["summary"] == review["opinion"]["summary"]
        assert [p["text"] for p in report["strengths"]] == [
            p["text"] for p in findings_of(review, "strengths")
        ]
        # The review's own `##` headings are kept as `###`, inside the Review section
        detailed = narrative_text(review, "review")
        assert report["other"]["Review"] == detailed.replace("## ", "### ")
        assert len(report["weaknesses"]) == len(findings_of(review, "weaknesses"))
        assert report["other"]["Contributions"] == "* **Idea:** A method."
        assert report["other"]["Comments"] == "* A remark."
        assert report["other"]["Stats"] == "Fine."
        assert "Questions" in report["other"]
        codec_validate(codec_map_with_record("deepreview", written, **RUN).review)

    def test_severity_and_group_place_a_point_under_potential_issues(self):
        review = human_review()
        review["findings"] = {
            "weaknesses": [
                {"text": "Overview.", "severity": "major", "summarizes": []},
                {"text": "Critical one.", "severity": "critical", "title": "Crit"},
                {"text": "Small one.", "severity": "info"},
                {"text": "Grouped.", "group": ["[Results]"], "severity": "minor"},
                {"text": "Two levels.", "group": ["[Results]", "Odd Tier"]},
                {"text": "Plain."},
            ]
        }
        report = deepreview.parse_report(codec_map_to("deepreview", review))
        assert [p["text"] for p in report["weaknesses"]] == ["Overview.", "Plain."]
        tiers = {
            (part["heading"], tier["heading"]): [item["text"] for item in tier["items"]]
            for part in report["issues"]
            for tier in part["tiers"]
        }
        assert tiers == {
            ("[General]", "Potential Mistakes and Improvements"): ["Critical one."],
            ("[General]", "Minor Corrections and Typos"): ["Small one."],
            ("[Results]", "Minor Corrections and Typos"): ["Grouped."],
            ("[Results]", "Odd Tier"): ["Two levels."],
        }
        mapped_back = codec_map_with_record("deepreview", codec_map_to("deepreview", review), **RUN)
        severities = [w.get("severity") for w in mapped_back.review["findings"]["weaknesses"]]
        assert severities == [None, None, "major", "minor", "minor", None]

    def test_demoted(self):
        assert deepreview.demoted("## A\n### B\n# C\ntext ## D") == "### A\n### B\n# C\ntext ## D"

    def test_places_and_title(self):
        point = {
            "title": "Sign",
            "text": "Flipped.",
            "evidence_links": [
                {"type": "paper_section", "ref": "Section 2, Page 3"},
                {"type": "equation", "ref": "Eq. 1"},
                {"type": "paper_section", "ref": "", "quote": "a quote"},
                {"type": "external", "ref": "Reference Paper: X, Y, 2020"},
            ],
        }
        assert deepreview.issue_head(point) == "Sign (Section 2, Page 3; Eq. 1)"
        assert deepreview.issue_head({"text": "x"}) is None

    @pytest.mark.parametrize(
        ("head", "text", "expected"),
        [
            (None, "Plain.", "* Plain."),
            ("H", "One line.", "* **H:** One line."),
            ("H", "- a list\n- of points", "* **H:**\n  - a list\n  - of points"),
            (
                "H",
                "Intro.\n  - indented\n  - list",
                "* **H:**\n  Intro.\n    - indented\n    - list",
            ),
            ("H", "", "* **H:**"),
            (None, "Intro.\n\n    code()", "* \n  Intro.\n\n      code()"),
            ("H", "```py\nx\n```", "* **H:**\n  ```py\n  x\n  ```"),
            (None, "```\nx\n```", "* \n  ```\n  x\n  ```"),
        ],
    )
    def test_write_item(self, head, text, expected):
        assert deepreview.write_item("*", head, text) == expected


class TestReviewer3:
    @staticmethod
    def plain_report(markdown):
        """The parsed report, without the bold the mapper does not keep."""
        report = reviewer3.parse_report(markdown)
        references = report.get("reference_check", {})
        if "summary" in references:
            references["summary"] = reviewer3.plain(references["summary"])
        for entry in references.get("entries", []):
            entry["status"] = reviewer3.plain(entry["status"]) if "status" in entry else None
            if entry["status"] is None:
                del entry["status"]
        return report

    @pytest.mark.parametrize("report", [REVIEWER3, REVIEWER3_EDGES], ids=["fixture", "edges"])
    def test_writes_back_the_same_report(self, report):
        written = codec_map_to("reviewer3", mapped("reviewer3", report))
        assert isinstance(written, str)
        assert self.plain_report(written) == self.plain_report(report)

    @pytest.mark.parametrize("report", [REVIEWER3, REVIEWER3_EDGES], ids=["fixture", "edges"])
    def test_round_trip(self, report):
        review = mapped("reviewer3", report)
        assert same_review(mapped("reviewer3", codec_map_to("reviewer3", review)), review)

    def test_a_review_from_elsewhere(self):
        review = human_review()
        review["target"]["title"] = "The Paper"
        review["checks"] = [{"kind": "similarity", "label": "Similarity", "summary": "Low."}]
        written = codec_map_to("reviewer3", review)
        report = reviewer3.parse_report(written)
        assert report["title"] == "The Paper"
        points = [*findings_of(review, "weaknesses"), *findings_of(review, "questions")]
        assert [c["text"] for c in report["comments"]] == [p["text"] for p in points]
        assert {c["title"] for c in report["comments"]} <= {"Weakness", "Question"}
        assert report["other"]["Summary"] == review["opinion"]["summary"]
        assert report["other"]["Review"] == narrative_text(review, "review")
        assert report["other"]["Similarity"] == "Low."
        assert "Strengths" in report["other"]
        again = codec_map_with_record("reviewer3", written, **RUN).review
        codec_validate(again)
        assert len(again["findings"]["comments"]) == len(points)

    def test_checks_without_their_own_sentences(self):
        review = human_review()
        review["findings"] = {
            "weaknesses": [{"id": "w1", "text": "Leak.", "severity": "critical"}],
        }
        review["checks"] = [
            {
                "kind": "ai_text_detection",
                "performed_by": {"name": "Pangram"},
                "measurements": [
                    {"key": "ai_generated", "label": "AI-generated", "value": 0.125},
                    {"key": "flag", "value": True},
                ],
            },
            {"kind": "ai_text_detection", "summary": "A second run."},
            {"kind": "fatal_flaw_screen", "outcome": "issues_found", "finding_ids": ["w1"]},
            {
                "kind": "reference_verification",
                "measurements": [
                    {"key": "checked", "value": 3},
                    {"key": "not_found", "value": 1},
                ],
                "items": [
                    {
                        "target": {"type": "bibliography", "ref": "4", "work": {"title": "T"}},
                        "status": "Unverified",
                    }
                ],
            },
        ]
        written = codec_map_to("reviewer3", review)
        assert (
            "12.5% AI-generated text detected. flag: True. See the full Pangram report." in written
        )
        assert "Checked 3 references: 1 not found." in written
        assert "| 4 | T | Unverified |" in written
        assert "- Leak." in written
        again = codec_map_with_record("reviewer3", written, **RUN).review
        checks = {check["kind"]: check for check in again["checks"]}
        assert checks["ai_text_detection"]["performed_by"] == {"name": "Pangram"}
        assert checks["ai_text_detection"]["measurements"][0]["value"] == 0.125
        assert checks["fatal_flaw_screen"]["outcome"] == "issues_found"
        assert checks["reference_verification"]["items"][0]["flagged"] is True
        assert again["extensions"]["reviewer3"]["other"]["AI Text Detection (2)"] == "A second run."

    @pytest.mark.parametrize(
        ("check", "expected"),
        [
            ({"kind": "fatal_flaw_screen", "outcome": "no_issues"}, reviewer3.NO_FATAL_FLAWS),
            (
                {
                    "kind": "reference_verification",
                    "measurements": [{"key": "checked", "value": 5}],
                },
                "Checked 5 references.",
            ),
        ],
    )
    def test_sentence_made_from_a_check(self, check, expected):
        review = human_review()
        review["checks"] = [check]
        assert expected in codec_map_to("reviewer3", review)

    def test_detector_without_measurements(self):
        check = {"kind": "ai_text_detection", "performed_by": {"name": "Detector"}}
        assert reviewer3.write_ai_text(check) == "See the full Detector report."

    def test_check_its_kind_cannot_say_is_written_in_prose(self):
        review = human_review()
        review["checks"] = [
            {"kind": "reference_verification", "measurements": [{"key": "found", "value": 1}]},
            {"kind": "other", "outcome": "not_run"},
        ]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["reference_check"] == {"text": "- found: 1"}
        assert report["other"]["other"] == "Outcome: not run"

    def test_comment_links(self):
        def comment(*links):
            return reviewer3.comment_from({"text": "x", "evidence_links": list(links)}, "Comment")

        figure = comment({"type": "figure", "ref": "Figure 2", "location": {"page": 4}})
        assert (figure["excerpt"], figure["page"]) == ("Figure 2", 4)
        assert comment({"type": "figure", "ref": "the second figure"})["excerpt"] is None
        assert comment({"type": "paper_section", "ref": "Sec 1"})["excerpt"] is None
        assert reviewer3.comment_from({"text": "x", "title": "T"}, "Comment") == {
            "title": "T",
            "text": "x",
        }

    def test_demoted(self):
        text = "### A\n#### B\n```\n### code\n```\n## C"
        assert reviewer3.demoted(text) == "#### A\n#### B\n```\n### code\n```\n## C"

    def test_headings_in_a_comment_stay_in_it(self):
        review = human_review()
        review["findings"] = {"comments": [{"title": "T", "text": "Intro.\n\n### Detail\n\nMore."}]}
        written = codec_map_to("reviewer3", review)
        [comment] = reviewer3.parse_report(written)["comments"]
        assert comment["text"] == "Intro.\n\n#### Detail\n\nMore."

    def test_write_comment(self):
        comment = {"title": "T", "page": 3, "page_end": 3, "excerpt": "a\n\nb", "text": "Why."}
        assert reviewer3.write_comment(2, comment) == "2. **T** — Page 3\n\n> a\n>\n> b\n\nWhy."


class TestHelpers:
    def test_extension(self):
        assert extension({}, "x") == {}
        assert extension({"extensions": {"x": "not a dict"}}, "x") == {}
        assert extension({"extensions": {"x": {"a": 1}}}, "x") == {"a": 1}

    def test_reviewer_model(self):
        def review(*models):
            return {"referees": [{"ai_referee": {"system": {"models": list(models)}}}]}

        assert reviewer_model({}) is None
        assert reviewer_model(review({"role": "reviewer", "model_id": "unspecified"})) is None
        assert reviewer_model(review({"role": "critic", "model_id": "c"})) is None
        assert reviewer_model(review({"role": "reviewer", "model_id": "m"})) == "m"

    def test_findings_of_keeps_empty_points(self):
        review = {"findings": {"comments": [{"text": "a"}, {"text": ""}, "junk", {}]}}
        assert findings_of(review, "comments") == [{"text": "a"}, {"text": ""}]
        assert findings_of({}, "comments") == []

    def test_overall_texts(self):
        assert overall_texts({}) == (None, None)
        assert overall_texts({"opinion": {"summary": "s", "text": "s"}}) == ("s", None)
        narrative = [
            {"role": "summary", "content": "n"},
            {"role": "review", "content": "d"},
            {"role": "review", "audience": "editors", "content": "c"},
        ]
        assert overall_texts({"narrative": narrative}) == ("n", "d")
        assert overall_texts({"opinion": {"text": "t"}, "narrative": narrative}) == ("n", "t")

    def test_indented(self):
        assert indented("a\n\nb\n c", "  ") == "a\n\n  b\n   c"


class TestKeptAndMissing:
    def test_deepreview_part_with_only_a_skipped_point(self):
        report = (
            "## Potential Issues And Suggestions\n### [A]\n"
            "#### Potential Mistakes and Improvements\n\n1. **Point:** Text.\n"
            "### [B]\n#### Potential Mistakes and Improvements\n\n1. **Empty (Page 3):**\n"
        )
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert "## Summary" not in written
        assert deepreview.parse_report(written) == deepreview.parse_report(report)

    def test_openaireview_point_removed_after_mapping(self):
        review = mapped("openaireview", OPENAIREVIEW)
        review["findings"]["weaknesses"] = review["findings"]["weaknesses"][:1]
        review["opinion"] = {}
        [method] = codec_map_to("openaireview", review)["methods"].values()
        assert len(method["comments"]) == 1 and "overall_feedback" not in method

    def test_reviewer3_comment_removed_after_mapping(self):
        review = mapped("reviewer3", REVIEWER3_EDGES)
        review["findings"]["comments"] = review["findings"]["comments"][:1]
        comments = reviewer3.parse_report(codec_map_to("reviewer3", review))["comments"]
        assert [comment["title"] for comment in comments] == ["Typo", "No explanation"]

    def test_reviewer3_ai_text_without_a_detector(self):
        check = {"kind": "ai_text_detection", "measurements": [{"key": "ai", "value": 0.4}]}
        assert reviewer3.write_ai_text(check) == "40% ai text detected."


class TestWhereThingsGoBack:
    """Each point, row and method goes back where the reviewer had it."""

    def test_openaireview_writes_back_the_method_it_mapped_and_keeps_the_others(self):
        output = {
            "methods": {
                "zero_shot__m": {"overall_feedback": "Z.", "comments": [{"explanation": "z"}]},
                "progressive__m": {"overall_feedback": "P.", "comments": [{"explanation": "p"}]},
            }
        }
        review = mapped("openaireview", output)
        assert review["opinion"]["summary"] == "P."
        back = codec_map_to("openaireview", review)
        assert back["methods"] == output["methods"]
        assert same_review(mapped("openaireview", back), review)

    def test_openaireview_skipped_comment_with_no_known_fields(self):
        comments = [{"paragraph_index": 0}, {"explanation": "Actual.", "paragraph_index": 1}]
        output = {"methods": {"progressive__m": {"comments": comments}}}
        [method] = codec_map_to("openaireview", mapped("openaireview", output))["methods"].values()
        assert method["comments"] == [
            {"paragraph_index": 0, "explanation": ""},
            {"paragraph_index": 1, "explanation": "Actual."},
        ]

    def test_deepreview_new_point_takes_no_place_of_the_reports_own(self):
        review = mapped("deepreview", DEEPREVIEW_EDGES)
        mistakes = ["[Methods] (Pages: 1-2)", "Potential Mistakes and Improvements"]
        new = {"text": "A new point.", "group": mistakes}
        review["findings"]["weaknesses"].insert(0, new)
        report = deepreview.parse_report(codec_map_to("deepreview", review))
        [tier] = [
            tier
            for part in report["issues"]
            for tier in part["tiers"]
            if [part["heading"], tier["heading"]] == mistakes
        ]
        assert [item.get("title") for item in tier["items"]] == ["Wrong sign", "Empty point", None]
        assert tier["items"][-1]["text"] == "A new point."

    def test_reviewer3_reference_table_without_statuses_is_written_back(self):
        body = "| # | Citation | Status | Note |\n| --- | --- | --- | --- |\n"
        body += "| 1 | A. Author (2020). | | |\n| | | | lonely |\n"
        overview = "### Overview\n\n- **A contribution** — Text.\n\n"
        report = f"# Review Report\n\nA paper\n\n---\n\n{overview}### Reference Check\n\n{body}"
        review = mapped("reviewer3", report)
        assert "checks" not in review
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)

    def test_reviewer3_keeps_comment_numbers(self):
        report = REVIEWER3_EDGES.replace("1. **Typo**", "7. **Typo**")
        review = mapped("reviewer3", report)
        review["findings"]["comments"].append({"title": "New", "text": "Added."})
        again = mapped("reviewer3", codec_map_to("reviewer3", review))
        ids = [comment["id"] for comment in again["findings"]["comments"]]
        assert ids == ["comment-7", "comment-2", "comment-8"]

    def test_reviewer3_numbered_heading_in_a_comment_stays_in_it(self):
        review = human_review()
        text = "Intro.\n\n1. **First item**\n\nDetails."
        review["findings"] = {"comments": [{"title": "T", "text": text}]}
        [comment] = reviewer3.parse_report(codec_map_to("reviewer3", review))["comments"]
        assert comment["text"] == "Intro.\n\n 1. **First item**\n\nDetails."

    def test_reviewer3_measurements_keep_their_units(self):
        check = {
            "kind": "ai_text_detection",
            "measurements": [
                {"key": "ai", "label": "AI-generated", "value": 0.3, "unit": "fraction"},
                {"key": "words", "value": 42, "unit": "words"},
            ],
        }
        assert reviewer3.write_ai_text(check) == "30% AI-generated text detected. words: 42 words."

    @pytest.mark.parametrize("target", ["deepreview", "reviewer3"])
    def test_checks_with_one_heading_are_all_written(self, target):
        review = human_review()
        review["checks"] = [
            {"kind": "statistics", "summary": "First."},
            {"kind": "statistics", "summary": "Second."},
        ]
        written = codec_map_to(target, review)
        assert "First.\n\nSecond." in written

    def test_reviewer3_extra_column_is_one_column(self):
        rows = reviewer3.reference_rows({}, [{"number": "1", "status": "", "note": "a"}] * 2)
        written = reviewer3.write_reference_check({}, {"entries": rows})
        assert written.splitlines()[0] == "| # | Citation | Status | note |"


class TestCopilotRound:
    def test_deepreview_fenced_headings_are_code(self):
        review = human_review()
        review["narrative"] = [
            {"role": "review", "content": "Intro.\n\n```md\n## Example\n```\n\n## Real"}
        ]
        written = codec_map_to("deepreview", review)
        assert "```md\n## Example\n```" in written
        report = deepreview.parse_report(written)
        assert report["other"]["Review"] == "Intro.\n\n```md\n## Example\n```\n\n### Real"

    def test_deepreview_parser_ignores_fenced_headings(self):
        report = "## Summary\nText.\n\n```\n## Not a section\n```\n"
        assert deepreview.parse_report(report) == {"summary": "Text.\n\n```\n## Not a section\n```"}

    def test_reviewer3_check_summary_keeps_its_headings(self):
        review = human_review()
        summary = "Screen result.\n\n### Evidence\n\nAdditional details."
        review["checks"] = [{"kind": "fatal_flaw_screen", "summary": summary}]
        [check] = mapped("reviewer3", codec_map_to("reviewer3", review))["checks"]
        assert check["summary"] == "Screen result.\n\n#### Evidence\n\nAdditional details."

    def test_openaireview_deleted_comment_takes_its_fields_with_it(self):
        review = mapped("openaireview", OPENAIREVIEW)
        del review["findings"]["weaknesses"][0]
        [method] = codec_map_to("openaireview", review)["methods"].values()
        [key] = [k for k in OPENAIREVIEW["methods"] if k.startswith("progressive__")]
        original = OPENAIREVIEW["methods"][key]["comments"]
        assert [c["id"] for c in method["comments"]] == [c["id"] for c in original[1:]]
        assert [c["paragraph_index"] for c in method["comments"]] == [
            c["paragraph_index"] for c in original[1:]
        ]

    def test_openaireview_new_weakness_follows_the_reports_own(self):
        review = mapped("openaireview", OPENAIREVIEW)
        review["findings"]["weaknesses"].insert(0, {"text": "New."})
        [method] = codec_map_to("openaireview", review)["methods"].values()
        assert method["comments"][-1] == {"explanation": "New."}
        assert len(method["comments"]) == 4


class TestKeptIdentity:
    def test_reviewer3_columns_follow_their_row_when_an_item_is_removed(self):
        body = "| # | Citation | Status | Note |\n| --- | --- | --- | --- |\n"
        body += "| 1 | A (2020). | Verified | first |\n| 2 | B (2021). | Not Found | second |\n"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
        review = mapped("reviewer3", report)
        del review["checks"][0]["items"][0]
        [entry] = reviewer3.parse_report(codec_map_to("reviewer3", review))["reference_check"][
            "entries"
        ]
        assert entry == {
            "number": "2",
            "citation": "B (2021).",
            "status": "Not Found",
            "note": "second",
        }

    def test_deepreview_bare_empty_point_keeps_later_ids(self):
        report = (
            "## Potential Issues And Suggestions\n### [A]\n"
            "#### Minor Corrections and Typos\n\n* **One:** First.\n* \n* **Three:** Third.\n"
        )
        review = mapped("deepreview", report)
        ids = [point["id"] for point in review["findings"]["weaknesses"]]
        assert ids == ["issue-1.1.1", "issue-1.1.3"]
        assert same_review(mapped("deepreview", codec_map_to("deepreview", review)), review)


def test_deepreview_untitled_point_keeps_its_code_indentation():
    review = human_review()
    review["findings"] = {"strengths": [{"text": "Intro.\n\n    code_line()"}]}
    [point] = deepreview.parse_report(codec_map_to("deepreview", review))["strengths"]
    assert point == {"text": "Intro.\n\n    code_line()"}


def test_reviewer3_contributions_opening_with_code_keep_what_follows():
    review = human_review()
    review["opinion"]["contributions"] = [
        {"title": "Code", "text": "```py\nx = 1\n```"},
        {"text": "```\ny\n```"},
        {"text": "Second."},
    ]
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert report["overview"] == review["opinion"]["contributions"]
    assert "Overview" not in report.get("other", {})


def test_openaireview_new_weakness_follows_even_when_nothing_was_kept():
    output = {"methods": {"progressive__m": {"comments": [{"explanation": "Original."}]}}}
    review = mapped("openaireview", output)
    review["findings"]["weaknesses"].insert(0, {"text": "New."})
    [method] = codec_map_to("openaireview", review)["methods"].values()
    assert [c["explanation"] for c in method["comments"]] == ["Original.", "New."]


class TestEdgesOfTheFormat:
    def test_reviewer3_explanation_opening_with_a_quote_stays_the_explanation(self):
        review = human_review()
        review["findings"] = {"comments": [{"title": "T", "text": "> The baseline is inadequate."}]}
        again = mapped("reviewer3", codec_map_to("reviewer3", review))
        [comment] = again["findings"]["comments"]
        assert comment["text"] == "> The baseline is inadequate."
        assert "evidence_links" not in comment

    def test_reviewer3_repeated_numbers_with_a_skipped_comment_keep_their_ids(self):
        body = "3. **One**\n\nFirst.\n\n3. **Two**\n\n3. **Three**\n\nThird."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n{body}\n"
        review = mapped("reviewer3", report)
        assert [c["id"] for c in review["findings"]["comments"]] == ["comment-1", "comment-3"]
        assert same_review(mapped("reviewer3", codec_map_to("reviewer3", review)), review)

    def test_deepreview_empty_point_at_the_very_end_is_kept(self):
        report = (
            "## Potential Issues And Suggestions\n### [A]\n"
            "#### Minor Corrections and Typos\n\n* **One:** First.\n* \n"
        )
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == deepreview.parse_report(report)
        assert same_review(mapped("deepreview", written), review)

    @pytest.mark.parametrize(("opening", "closing"), [(0, 2), (2, 0), (0, 3), (1, 1)])
    def test_fences_indented_differently_hide_no_section(self, opening, closing):
        text = f"{' ' * opening}```py\nx = 1\n{' ' * closing}```"
        review = human_review()
        review["findings"]["strengths"] = [{"title": "Code", "text": text}]
        review["opinion"]["contributions"] = [{"title": "Code", "text": text}]
        report = deepreview.parse_report(codec_map_to("deepreview", review))
        assert len(report["weaknesses"]) == len(findings_of(human_review(), "weaknesses"))
        r3 = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert len(r3["comments"]) == len(findings_of(human_review(), "weaknesses")) + len(
            findings_of(human_review(), "questions")
        )


class TestFifthReview:
    def test_deepreview_empty_strength_keeps_the_ids_after_it(self):
        report = "## Strengths\n* \n* Useful result.\n## Weaknesses\n* \n* Real weakness.\n"
        review = mapped("deepreview", report)
        assert [p["id"] for p in review["findings"]["strengths"]] == ["strength-1", "strength-2"]
        assert same_review(mapped("deepreview", codec_map_to("deepreview", review)), review)

    def test_reviewer3_empty_fatal_flaw_keeps_the_checks_finding_ids(self):
        body = "- **Leak** — Test data leaks.\n- \n- **Bias** — Selection bias."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Fatal Flaws\n\n{body}\n"
        review = mapped("reviewer3", report)
        assert same_review(mapped("reviewer3", codec_map_to("reviewer3", review)), review)

    def test_reviewer3_standalone_indented_fence_still_hides_headings(self):
        appendix = "  ```\n### Fatal Flaws\n- **Fake** — Not a flaw.\n  ```"
        overview = "### Overview\n\n- **A contribution** — Text.\n\n"
        report = f"# Review Report\n\nA paper\n\n---\n\n{overview}### Appendix\n\n{appendix}\n"
        review = mapped("reviewer3", report)
        assert "checks" not in review
        # A kept section is stripped, as always; the heading stays in the code
        assert review["extensions"]["reviewer3"]["other"]["Appendix"] == appendix.strip()

    def test_deepreview_standalone_indented_fence_still_hides_headings(self):
        report = "## Summary\nText.\n\n  ```\n## Not a section\n  ```\n"
        assert list(deepreview.parse_report(report)) == ["summary"]

    def test_reviewer3_rows_sharing_a_number_keep_their_own_columns(self):
        body = "| # | Citation | Status | Note |\n| --- | --- | --- | --- |\n"
        body += "| 7 | A (2020). | Verified | |\n| 7 | B (2021). | Not Found | second |\n"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)


class TestCopilotFourthRound:
    def test_deepreview_wrapped_title_keeps_its_lines(self):
        report = "## Strengths\n* **Clear\n  exposition:** Well written.\n"
        review = mapped("deepreview", report)
        assert review["findings"]["strengths"][0]["title"] == "Clear\nexposition"
        assert same_review(mapped("deepreview", codec_map_to("deepreview", review)), review)

    def test_reviewer3_wrapped_titles(self):
        review = human_review()
        review["opinion"]["contributions"] = [{"title": "Two\nlines", "text": "A method."}]
        review["findings"] = {"comments": [{"title": "Also\ntwo", "text": "Why."}]}
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["overview"] == [{"title": "Two\nlines", "text": "A method."}]
        assert report["comments"][0]["title"] == "Also two"

    def test_reviewer3_identical_rows_keep_their_statuses_and_columns(self):
        body = "| # | Citation | Status | Note |\n| --- | --- | --- | --- |\n"
        body += "| 7 | A. | Verified | |\n| 7 | A. | Not Found | second |\n"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)


class TestSixthReview:
    def test_reviewer3_parent_fence_after_a_nested_list_hides_no_section(self):
        overview = "- Main\n  - Nested\n\n  ```py\n  x\n    ```"
        report = (
            f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{overview}\n\n"
            "### Fatal Flaws\n\n- **Leak** — Test data leaks.\n"
        )
        review = mapped("reviewer3", report)
        assert [check["kind"] for check in review["checks"]] == ["fatal_flaw_screen"]
        assert review["findings"]["weaknesses"][0]["severity"] == "critical"

    def test_deepreview_parent_fence_after_a_nested_list_hides_no_section(self):
        report = "## Strengths\n* Main\n  * Nested\n\n  ```py\n  x\n    ```\n## Weaknesses\n* W.\n"
        assert deepreview.parse_report(report)["weaknesses"] == [{"text": "W."}]

    def test_heading_after_a_fence_led_list_item_is_demoted(self):
        review = human_review()
        text = "- ```py\n  x\n  ```\n\nResult:\n\n## Result\nImportant result."
        review["opinion"] = {"summary": text}
        review.pop("narrative")
        report = deepreview.parse_report(codec_map_to("deepreview", review))
        assert report["summary"] == text.replace("## Result", "### Result")
        review["opinion"] = {"summary": text.replace("## Result", "### Result")}
        r3 = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert r3["other"]["Summary"] == text.replace("## Result", "#### Result")

    def test_reviewer3_comments_numbered_down_with_a_skipped_one_keep_their_order(self):
        body = "3. **Three**\n\nFirst.\n\n2. **Two**\n\n1. **One**\n\nLast."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n{body}\n"
        review = mapped("reviewer3", report)
        assert [c["id"] for c in review["findings"]["comments"]] == ["comment-3", "comment-1"]
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    def test_reviewer3_fence_after_a_list_marker_in_a_comment(self):
        review = human_review()
        text = "- ```\n  1. **Not a comment**\n  ```"
        review["findings"] = {
            "comments": [{"title": "A", "text": text}, {"title": "B", "text": "Next."}]
        }
        comments = reviewer3.parse_report(codec_map_to("reviewer3", review))["comments"]
        assert [(c["title"], c["text"]) for c in comments] == [("A", text), ("B", "Next.")]

    def test_reviewer3_fence_after_a_list_marker_before_a_reference_table(self):
        summary = "Checked 1 references: 1 not found.\n\n- ```\n  | x | y |\n  ```"
        review = human_review()
        review["checks"] = [
            {
                "kind": "reference_verification",
                "summary": summary,
                "items": [{"target": {"type": "bibliography", "ref": "4"}, "status": "Not Found"}],
            }
        ]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["reference_check"]["entries"] == [{"number": "4", "status": "Not Found"}]


class TestPanelGate:
    def test_deepreview_places_alone_read_back_as_places(self):
        review = human_review()
        links = [{"type": "paper_section", "ref": r} for r in ("Page 2", "Figure 1")]
        review["findings"] = {
            "weaknesses": [{"text": "T.", "severity": "minor", "evidence_links": links}]
        }
        again = mapped("deepreview", codec_map_to("deepreview", review))
        [point] = again["findings"]["weaknesses"]
        assert "title" not in point
        assert [link["ref"] for link in point["evidence_links"]] == ["Page 2", "Figure 1"]

    def test_deepreview_wrapped_strength_keeps_the_sections_after_its_code(self):
        report = "## Strengths\n* Main point\nwraps here.\n\n  ```py\n  x\n    ```\n"
        report += "## Weaknesses\n* W.\n"
        assert deepreview.parse_report(report)["weaknesses"] == [{"text": "W."}]


class TestRepeatedChecks:
    def test_reviewer3_second_checks_keep_what_they_say(self):
        review = human_review()
        review["findings"] = {
            "weaknesses": [
                {"id": "w1", "text": "First flaw.", "severity": "critical"},
                {"id": "w2", "text": "Second flaw.", "severity": "critical"},
            ]
        }
        review["checks"] = [
            {"kind": "fatal_flaw_screen", "outcome": "issues_found", "finding_ids": ["w1"]},
            {"kind": "fatal_flaw_screen", "outcome": "issues_found", "finding_ids": ["w2"]},
            {
                "kind": "reference_verification",
                "measurements": [{"key": "checked", "value": 2}],
            },
            {
                "kind": "reference_verification",
                "measurements": [{"key": "checked", "value": 5}],
                "items": [{"target": {"type": "bibliography", "ref": "3"}, "status": "Not Found"}],
            },
            {
                "kind": "statistics",
                "outcome": "issues_found",
                "measurements": [{"key": "p", "value": 0.04}],
            },
        ]
        written = codec_map_to("reviewer3", review)
        report = reviewer3.parse_report(written)
        assert report["fatal_flaws"]["items"] == [{"text": "First flaw."}]
        assert report["other"]["Fatal Flaws (2)"] == "- Second flaw."
        assert "| 3 |  | Not Found |" in report["other"]["Reference Check (2)"]
        assert report["other"]["statistics"] == "Outcome: issues found\n\n- p: 0.04"
        assert "comments" not in report

    def test_deepreview_checks_keep_what_they_say(self):
        review = human_review()
        review["checks"] = [
            {
                "kind": "reference_verification",
                "label": "References",
                "summary": "Checked.",
                "performed_by": {"name": "Tool"},
                "items": [
                    {
                        "target": {"type": "bibliography", "ref": "4"},
                        "status": "Not Found",
                        "flagged": True,
                        "notes": "No DOI",
                    }
                ],
            }
        ]
        report = deepreview.parse_report(codec_map_to("deepreview", review))
        assert report["other"]["References"] == (
            "Checked.\n\nPerformed by: Tool\n\n- 4: Not Found (flagged) — No DOI"
        )


class TestSecondGate:
    def test_reviewer3_numbered_item_with_code_in_a_comment_keeps_its_shape(self):
        review = human_review()
        text = "Steps:\n\n1. **Prepare**\n   ```py\n   x = 1\n   ```\n\nDone."
        review["findings"] = {
            "comments": [{"title": "A", "text": text}, {"title": "B", "text": "Next."}]
        }
        written = codec_map_to("reviewer3", review)
        report = reviewer3.parse_report(written)
        assert [c["title"] for c in report["comments"]] == ["A", "B"]
        shifted = "Steps:\n\n 1. **Prepare**\n    ```py\n    x = 1\n    ```\n\nDone."
        assert report["comments"][0]["text"] == shifted

    def test_reviewer3_header_right_after_an_unclosed_list_fence_starts_a_comment(self):
        body = "1. **A**\n\n- ```\n  code\n2. **B**\n\nNext."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n{body}\n"
        comments = reviewer3.parse_report(report)["comments"]
        assert [c["title"] for c in comments] == ["A", "B"]

    @pytest.mark.parametrize(
        "kind", ["fatal_flaw_screen", "ai_text_detection", "reference_verification"]
    )
    def test_reviewer3_outcome_only_checks_are_written(self, kind):
        review = human_review()
        review["checks"] = [
            {"kind": kind, "outcome": "inconclusive"},
            {"kind": kind, "outcome": "not_run"},
        ]
        written = codec_map_to("reviewer3", review)
        assert "Outcome: inconclusive" in written
        assert "Outcome: not run" in written


class TestCopilotSummaries:
    def test_reviewer3_bulleted_verdict_keeps_the_flaw_ids(self):
        body = "- No fatal methodological flaws were identified.\n- **Caveat** — Missing baseline."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Fatal Flaws\n\n{body}\n"
        review = mapped("reviewer3", report)
        assert review["checks"][0]["finding_ids"] == ["fatal-flaw-2"]
        assert same_review(mapped("reviewer3", codec_map_to("reviewer3", review)), review)

    def test_reviewer3_reference_item_notes_are_written(self):
        review = human_review()
        review["checks"] = [
            {
                "kind": "reference_verification",
                "items": [
                    {
                        "target": {"type": "bibliography", "ref": "4"},
                        "status": "Not Found",
                        "notes": "The DOI resolves to a different paper.",
                    }
                ],
            }
        ]
        [entry] = reviewer3.parse_report(codec_map_to("reviewer3", review))["reference_check"][
            "entries"
        ]
        assert entry["notes"] == "The DOI resolves to a different paper."

    def test_reviewer3_zero_padded_numbers_keep_their_ids(self):
        body = "01. **One**\n\nFirst.\n\n02. **Two**\n\n03. **Three**\n\nThird."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n{body}\n"
        review = mapped("reviewer3", report)
        assert [c["id"] for c in review["findings"]["comments"]] == ["comment-01", "comment-03"]
        assert same_review(mapped("reviewer3", codec_map_to("reviewer3", review)), review)

    @pytest.mark.parametrize("section", ["Overview", "Fatal Flaws"])
    def test_reviewer3_bullet_opening_a_fence_is_a_point(self, section):
        body = "- ```python\n  x = 1\n  ```\n- **Second** — Plain."
        report = f"# Review Report\n\nA paper\n\n---\n\n### {section}\n\n{body}\n"
        parsed = reviewer3.parse_report(report)
        points = parsed["overview"] if section == "Overview" else parsed["fatal_flaws"]["items"]
        assert points == [
            {"text": "```python\nx = 1\n```"},
            {"title": "Second", "text": "Plain."},
        ]


class TestThirdGate:
    @pytest.mark.parametrize("section", ["Overview", "Fatal Flaws"])
    def test_reviewer3_peer_bullet_after_unclosed_code_is_its_own_point(self, section):
        body = "- ```\n  code\n- **Second** — Peer."
        report = f"# Review Report\n\nA paper\n\n---\n\n### {section}\n\n{body}\n"
        parsed = reviewer3.parse_report(report)
        points = parsed["overview"] if section == "Overview" else parsed["fatal_flaws"]["items"]
        assert points == [{"text": "```\ncode"}, {"title": "Second", "text": "Peer."}]

    def test_reviewer3_writes_what_a_checks_section_cannot_say(self):
        review = human_review()
        review["checks"] = [
            {"kind": "fatal_flaw_screen", "summary": "Screen ran.", "outcome": "inconclusive"},
            {
                "kind": "ai_text_detection",
                "summary": "Mostly human.",
                "performed_by": {"name": "Detector"},
                "measurements": [{"key": "ai", "label": "AI", "value": 0.3, "unit": "fraction"}],
            },
        ]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["fatal_flaws"]["text"] == "Screen ran.\n\nOutcome: inconclusive"
        assert report["ai_text_detection"] == (
            "Mostly human.\n\nPerformed by: Detector\n\n- AI: 0.3 fraction"
        )

    def test_reviewer3_nothing_is_added_when_the_section_says_it_all(self):
        review = mapped("reviewer3", REVIEWER3)
        written = codec_map_to("reviewer3", review)
        assert "Outcome:" not in written and "Performed by:" not in written


class TestFinalCopilotRound:
    @pytest.mark.parametrize("section", ["Overview", "Fatal Flaws"])
    def test_reviewer3_sibling_that_opens_a_fence_is_its_own_point(self, section):
        body = "- ```python\n  x = 1\n- ```js\n  y\n  ```"
        report = f"# Review Report\n\nA paper\n\n---\n\n### {section}\n\n{body}\n"
        parsed = reviewer3.parse_report(report)
        points = parsed["overview"] if section == "Overview" else parsed["fatal_flaws"]["items"]
        assert points == [{"text": "```python\nx = 1"}, {"text": "```js\ny\n```"}]

    def test_reviewer3_multi_paragraph_verdict_keeps_its_place(self):
        body = (
            "- No fatal methodological flaws were identified.\n\n  Additional caveat.\n"
            "- **Caveat** — Missing baseline."
        )
        report = f"# Review Report\n\nA paper\n\n---\n\n### Fatal Flaws\n\n{body}\n"
        review = mapped("reviewer3", report)
        assert review["checks"][0]["finding_ids"] == ["fatal-flaw-2"]
        assert same_review(mapped("reviewer3", codec_map_to("reviewer3", review)), review)


def test_reviewer3_a_huge_flaw_id_lists_no_places():
    review = human_review()
    review["findings"] = {"weaknesses": [{"id": "fatal-flaw-1000000000", "text": "Leak."}]}
    review["checks"] = [
        {
            "kind": "fatal_flaw_screen",
            "summary": "Screened.",
            "finding_ids": ["fatal-flaw-1000000000"],
        }
    ]
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert report["fatal_flaws"] == {"text": "Screened.", "items": [{"text": "Leak."}]}


class TestPR47Followups:
    """Points Copilot left on PR 47 after it was last updated."""

    def test_thematic_breaks_are_no_list_items(self):
        deep = "## Summary\nText.\n\n- - -\n\n  ```\n## Weaknesses\n```\n\n## Strengths\n* S.\n"
        assert sorted(deepreview.parse_report(deep)) == ["strengths", "summary"]
        appendix = "* * *\n\n  ```\n### Fatal Flaws\n- **Fake** — Not a flaw.\n```"
        overview = "### Overview\n\n- **A contribution** — Text.\n\n"
        r3 = f"# Review Report\n\nA paper\n\n---\n\n{overview}### Appendix\n\n{appendix}\n"
        review = mapped("reviewer3", r3)
        assert "checks" not in review and "findings" not in review

    def test_deepreview_summary_ending_in_open_code_stays_last(self):
        report = "## Strengths\n* Useful.\n\n## Summary\nText.\n\n```py\nx"
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == deepreview.parse_report(report)
        assert same_review(mapped("deepreview", written), review)

    def test_deepreview_open_code_from_elsewhere_swallows_no_section(self):
        review = human_review()
        review["opinion"] = {"summary": "Text.\n\n```py\nx"}
        review.pop("narrative")
        report = deepreview.parse_report(codec_map_to("deepreview", review))
        assert len(report["strengths"]) == len(findings_of(review, "strengths"))
        assert report["summary"] == "Text.\n\n```py\nx"

    def test_reviewer3_overview_ending_in_open_code_round_trips(self):
        body = "- **A** — First.\n- **B** — Second.\n\n```py\nunclosed"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    def test_reviewer3_open_code_from_elsewhere_swallows_nothing_after_it(self):
        review = human_review()
        review["opinion"] = {"summary": "Text.\n\n```py\nx"}
        review.pop("narrative")
        review["findings"] = {
            "strengths": [{"text": "Good."}],
            "comments": [
                {"title": "A", "text": "Ends in code:\n\n```py\nx"},
                {"title": "B", "text": "Next."},
            ],
        }
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert [c["title"] for c in report["comments"]] == ["A", "B"]
        assert report["comments"][0]["text"] == "Ends in code:\n\n```py\nx\n```"
        assert report["other"]["Strengths"] == "- Good."
        assert report["other"]["Summary"] == "Text.\n\n```py\nx"

    def test_reviewer3_fatal_flaw_0_is_written(self):
        review = human_review()
        review["findings"] = {"weaknesses": [{"id": "fatal-flaw-0", "text": "Leak."}]}
        review["checks"] = [
            {"kind": "fatal_flaw_screen", "summary": "Screened.", "finding_ids": ["fatal-flaw-0"]}
        ]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["fatal_flaws"] == {"text": "Screened.", "items": [{"text": "Leak."}]}

    def test_deepreview_skipped_point_of_places_alone_keeps_them_as_places(self):
        report = (
            "## Potential Issues And Suggestions\n### [A]\n"
            "#### Minor Corrections and Typos\n\n* **One:** First.\n* **(Page 2; Figure 1):**\n"
        )
        review = mapped("deepreview", report)
        assert same_review(mapped("deepreview", codec_map_to("deepreview", review)), review)


class TestPR48Review:
    def test_thematic_break_with_crlf_endings_is_no_list_item(self):
        deep = "## Summary\nText.\n\n- - -\n\n  ```\n## Weaknesses\n```\n\n## Strengths\n* S.\n"
        crlf = deep.replace("\n", "\r\n")
        assert [h for h, _ in deepreview.split_sections(crlf, 2)] == [None, "Summary", "Strengths"]

    def test_reviewer3_reference_prose_ending_in_open_code_round_trips(self):
        body = "No references to check.\n\n```py\nx"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    def test_reviewer3_indented_open_fence_in_a_comment_swallows_no_comment(self):
        review = human_review()
        review["findings"] = {
            "comments": [{"title": "A", "text": "   ```py\n   x"}, {"title": "B", "text": "Next."}]
        }
        report = reviewer3.parse_report(
            codec_map_to("reviewer3", review) + "\n### Appendix\n\nX.\n"
        )
        assert [c["title"] for c in report["comments"]] == ["A", "B"]
        assert report["comments"][0]["text"] == "   ```py\n   x\n   ```"
        assert report["other"]["Appendix"] == "X."

    def test_reviewer3_comments_prose_ending_in_open_code_round_trips(self):
        body = "Pending comments.\n```py\nx"
        overview = "### Overview\n\n- **A contribution** — Text.\n\n"
        report = f"# Review Report\n\nA paper\n\n---\n\n{overview}### Reviewer Comments\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)


@pytest.mark.parametrize(
    ("source", "report"),
    [
        ("reviewer3", "# Review Report\n\nA paper\n\n---\n\nPending review.\n```py\nx"),
        ("deepreview", "# HIGH LEVEL SUMMARY\n---\nPending review.\n```py\nx"),
    ],
)
def test_preamble_only_report_ending_in_open_code_has_no_content(source, report):
    # Text above the first section is kept, not mapped, so a report of only that says
    # nothing about the work: content can't follow an open fence without being swallowed
    parse = {"reviewer3": reviewer3.parse_report, "deepreview": deepreview.parse_report}[source]
    assert parse(report)["other"] == {"preamble": "Pending review.\n```py\nx"}
    with pytest.raises(ValueError, match="no review content"):
        mapped(source, report)


def test_reviewer3_reference_table_then_open_ended_prose_round_trips():
    body = "| # | Citation | Status |\n| --- | --- | --- |\n| 1 | A (2020). | Not Found |\n\n"
    body += "Notes.\n\n```py\nx"
    report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
    review = mapped("reviewer3", report)
    written = codec_map_to("reviewer3", review)
    assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
    assert same_review(mapped("reviewer3", written), review)


@pytest.mark.parametrize("indent", ["  ", "   "])
def test_reviewer3_indented_open_summary_stays_out_of_the_flaws(indent):
    review = human_review()
    review["findings"] = {"weaknesses": [{"id": "w1", "text": "Leak."}]}
    summary = f"{indent}```py\n{indent}x"
    review["checks"] = [{"kind": "fatal_flaw_screen", "summary": summary, "finding_ids": ["w1"]}]
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert report["fatal_flaws"]["items"] == [{"text": "Leak."}]
    assert report["fatal_flaws"]["text"] == f"{summary}\n{indent}```"


@pytest.mark.parametrize("indent", ["  ", "   "])
def test_reviewer3_overview_of_only_indented_open_code_round_trips(indent):
    # The flaw gives the review content; the Overview, written first by default, goes last
    flaws = "### Fatal Flaws\n\n- **Leak** — Text.\n\n"
    overview = f"### Overview\n\n{indent}```py\n{indent}x"
    report = f"# Review Report\n\nA paper\n\n---\n\n{flaws}{overview}"
    review = mapped("reviewer3", report)
    written = codec_map_to("reviewer3", review)
    assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
    assert same_review(mapped("reviewer3", written), review)


@pytest.mark.parametrize("heading", ["Strengths", "Weaknesses"])
def test_deepreview_kept_text_opening_code_before_points_round_trips(heading):
    report = f"## {heading}\nNotes.\n```py\n  x\n* Useful.\n\n## Summary\nShort."
    review = mapped("deepreview", report)
    written = codec_map_to("deepreview", review)
    assert deepreview.parse_report(written) == deepreview.parse_report(report)
    assert same_review(mapped("deepreview", written), review)


@pytest.mark.parametrize("text", ["- - -\n\n  ```py\n  x\n```", "---\n\nMore."])
def test_reviewer3_point_opening_with_a_thematic_break_keeps_the_next_point(text):
    review = human_review()
    review["opinion"]["contributions"] = [{"text": text}, {"text": "Second."}]
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert report["overview"][-1] == {"text": "Second."}
    assert len(report["overview"]) == 2


def test_reviewer3_closer_added_to_a_comment_opens_no_section_fence():
    review = human_review()
    review["findings"] = {
        "comments": [
            {"title": "A", "text": "   ```py\nx"},
            {"title": "B", "text": "Before.\n\n```\n### Fake\n```\n\nAfter."},
        ]
    }
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert "Fake" not in report.get("other", {})
    assert [c["title"] for c in report["comments"]] == ["A", "B"]
    assert report["comments"][1]["text"] == "Before.\n\n```\n### Fake\n```\n\nAfter."


@pytest.mark.parametrize(
    "appendix",
    [
        "1. **Step**\n   ```py\n   x",
        "1. **Step**\n   ```py\n   x\n      ```\n\nAfter the list.",
    ],
)
def test_reviewer3_numbered_list_outside_comments_keeps_its_code_scope(appendix):
    report = (
        f"# Review Report\n\nA paper\n\n---\n\n### Appendix\n\n{appendix}\n\n"
        "### Fatal Flaws\n\n- **Leak** — Test data leaks.\n"
    )
    parsed = reviewer3.parse_report(report)
    assert parsed["fatal_flaws"]["items"] == [{"title": "Leak", "text": "Test data leaks."}]


def test_reviewer3_final_comment_left_open_swallows_no_section_after_it():
    review = human_review()
    review["opinion"] = {"summary": "Short summary."}
    review.pop("narrative")
    review["findings"] = {"comments": [{"title": "A", "text": "   ```py\n   x"}]}
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert report["other"]["Summary"] == "Short summary."
    # Reviewer Comments, left open, goes last, so its last explanation keeps its open code
    assert report["comments"][0]["text"] == "   ```py\n   x"


class TestCommentReader:
    NESTED = "- Steps\n  1. **Prepare**\n  ```py\n  x"

    def test_nested_numbered_line_in_an_explanation_keeps_its_list(self):
        report = (
            "# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n"
            f"1. **A**\n\n{self.NESTED}\n\n### Fatal Flaws\n\n- **Leak** — Test data leaks.\n"
        )
        parsed = reviewer3.parse_report(report)
        assert parsed["fatal_flaws"]["items"] == [{"title": "Leak", "text": "Test data leaks."}]
        assert parsed["comments"][0]["text"] == self.NESTED

    def test_nested_numbered_line_adds_no_closer_before_the_next_comment(self):
        body = f"1. **A**\n\n{self.NESTED}\n\n2. **B**\n\nNext."
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n{body}\n"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    def test_closed_comment_fence_beside_an_open_summary(self):
        review = human_review()
        review["opinion"] = {"summary": "S.\n\n```py\ny"}
        review.pop("narrative")
        review["findings"] = {"comments": [{"title": "A", "text": "   ```py\nx\n   ```"}]}
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["comments"][0]["text"] == "   ```py\nx\n   ```"
        assert report["other"]["Summary"] == "S.\n\n```py\ny"


class TestThematicBreaksAndRepeats:
    def test_reviewer3_overview_with_a_break_and_fenced_heading_round_trips(self):
        body = "- **A** — First.\n- - -\n\n  ```python\n### Fake\n  ```"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}\n"
        parsed = reviewer3.parse_report(report)
        assert "Fake" not in parsed.get("other", {})
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == parsed
        assert same_review(mapped("reviewer3", written), review)

    def test_deepreview_strengths_with_a_break_and_fenced_heading_round_trip(self):
        report = "## Strengths\n* A.\n- - -\n\n  ```python\n## Fake\n  ```\n## Weaknesses\n* W.\n"
        parsed = deepreview.parse_report(report)
        assert "Fake" not in parsed.get("other", {})
        assert parsed["strengths"] == [{"text": "A."}]
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == parsed
        assert same_review(mapped("deepreview", written), review)

    def test_reviewer3_crlf_thematic_break_text_keeps_the_next_point(self):
        review = human_review()
        text = "- - -\r\n\r\n  ```py\r\n  x\r\n```"
        review["opinion"]["contributions"] = [{"text": text}, {"text": "Second."}]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["overview"][-1] == {"text": "Second."}
        assert len(report["overview"]) == 2

    def test_reviewer3_repeated_comments_section_with_open_prose_round_trips(self):
        report = (
            "# Review Report\n\nA paper\n\n---\n\n### Reviewer Comments\n\n1. **A**\n\nText.\n\n"
            "### Reviewer Comments\n\nPending.\n```py\nx"
        )
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)


@pytest.mark.parametrize("text", ["***", "**", "***\r"])
def test_deepreview_point_whose_marker_line_would_be_a_break_round_trips(text):
    report = f"## Strengths\n- {text}\n- Useful result.\n"
    review = mapped("deepreview", report)
    assert len(review["findings"]["strengths"]) == 2
    written = codec_map_to("deepreview", review)
    assert deepreview.parse_report(written) == deepreview.parse_report(report)
    assert same_review(mapped("deepreview", written), review)


@pytest.mark.parametrize("indent", ["  ", "   "])
def test_reviewer3_reference_table_then_indented_open_code_round_trips(indent):
    table = "| # | Citation | Status |\n| --- | --- | --- |\n| 1 | A (2020). | Not Found |"
    body = f"{table}\n\n{indent}```py\n{indent}x"
    report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
    review = mapped("reviewer3", report)
    written = codec_map_to("reviewer3", review)
    assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
    assert same_review(mapped("reviewer3", written), review)


def test_reviewer3_reference_fence_whose_info_string_reads_as_counts_round_trips():
    body = "```text Checked 2 references\nexample"
    report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
    review = mapped("reviewer3", report)
    written = codec_map_to("reviewer3", review)
    assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
    assert same_review(mapped("reviewer3", written), review)


class TestOutdentedBreaks:
    def test_deepreview_outdented_break_ends_the_point(self):
        report = "## Strengths\n- A.\n - - -\n   ```\n## Fake\n   ```\n## Weaknesses\n* W.\n"
        parsed = deepreview.parse_report(report)
        assert parsed["strengths"] == [{"text": "A."}]
        assert "Fake" not in parsed.get("other", {})
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == parsed
        assert same_review(mapped("deepreview", written), review)

    def test_reviewer3_outdented_break_ends_the_point(self):
        body = "- A.\n - - -\n   ```\n### Fake\n   ```"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}\n"
        parsed = reviewer3.parse_report(report)
        assert parsed["overview"] == [{"text": "A."}]
        assert "Fake" not in parsed.get("other", {})
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == parsed
        assert same_review(mapped("reviewer3", written), review)

    def test_reviewer3_table_before_a_fence_read_as_counts_round_trips(self):
        table = "| # | Citation | Status |\n| --- | --- | --- |\n| 1 | A (2020). | Not Found |"
        body = f"{table}\n\n```text Checked 2 references\nexample"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Reference Check\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)


class TestScopeAndOrder:
    def test_deepreview_lazy_continuation_keeps_its_code_in_the_point(self):
        report = (
            "## Strengths\n* Useful.\nContinuation.\n  ```py\n  x\n## Summary\nShort.\n\n```py\ny"
        )
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == deepreview.parse_report(report)
        assert same_review(mapped("deepreview", written), review)

    @pytest.mark.parametrize(
        ("heading", "first", "summary"),
        [
            ("Fatal Flaws", "- **Leak** — Test data leaks.", "Screened.\n\n```py\nx"),
            (
                "Reference Check",
                "Checked 2 references: 2 verified.",
                "Checked 2 references: 2 verified.\n\n```py\nx",
            ),
        ],
    )
    def test_reviewer3_open_primary_check_stays_before_its_repeat(self, heading, first, summary):
        report = (
            f"# Review Report\n\nA paper\n\n---\n\n### {heading}\n\n{first}\n\n"
            f"### {heading}\n\nRepeat.\n"
        )
        review = mapped("reviewer3", report)
        [check] = review["checks"]
        check["summary"] = summary
        again = mapped("reviewer3", codec_map_to("reviewer3", review))
        [again_check] = again["checks"]
        assert again_check["kind"] == check["kind"]
        assert again["extensions"]["reviewer3"]["other"][heading] == "Repeat."
        if heading == "Fatal Flaws":
            assert [w["text"] for w in again["findings"]["weaknesses"]] == ["Test data leaks."]


@pytest.mark.parametrize(
    "strengths",
    [
        "* A.\n  ```py\n  x\n  ```\nOutside the list.",
        "* Useful.\n---\nOutside the list.",
    ],
)
def test_deepreview_prose_after_a_point_that_ended_stays_out_of_it(strengths):
    report = f"## Strengths\n{strengths}\n"
    parsed = deepreview.parse_report(report)
    assert parsed["other"]["Strengths"] == "Outside the list."
    review = mapped("deepreview", report)
    written = codec_map_to("deepreview", review)
    assert deepreview.parse_report(written) == parsed


class TestItemFenceState:
    def test_numbered_item_keeps_its_list_relative_fence(self):
        report = "## Strengths\n1. A.\n      ```py\n      x\n      ```\nOutside the list.\n"
        parsed = deepreview.parse_report(report)
        assert parsed["other"]["Strengths"] == "Outside the list."
        assert parsed["strengths"][0]["text"].startswith("A.")

    def test_bold_marker_item_keeps_its_lazy_continuation(self):
        parsed = deepreview.parse_report("## Strengths\n- **\nContinuation.\n")
        assert len(parsed["strengths"]) == 1
        assert "other" not in parsed

    def test_long_soft_wrapped_point_is_read_once_per_line(self, monkeypatch):
        from ocrs.mappers import ai

        calls = 0
        inside = ai.Fences.inside

        def counting(self, line):
            nonlocal calls
            calls += 1
            return inside(self, line)

        monkeypatch.setattr(ai.Fences, "inside", counting)
        lines = 400
        deepreview.parse_report("## Strengths\n* Start.\n" + "more text\n" * lines)
        assert calls < 5 * lines


@pytest.mark.parametrize(
    "strengths",
    [
        "* A.\n\n      code()\nOutside the list.",
        "* A.\n\n  ## Heading\nOutside the list.",
    ],
)
def test_deepreview_prose_after_a_points_code_or_heading_is_not_lazy(strengths):
    parsed = deepreview.parse_report(f"## Strengths\n{strengths}\n")
    assert parsed["other"]["Strengths"] == "Outside the list."


@pytest.mark.parametrize("separator", ["  ---", "  ***", "  - - -", "  # Heading"])
def test_deepreview_prose_after_an_indented_break_or_heading_is_not_lazy(separator):
    parsed = deepreview.parse_report(f"## Strengths\n* Useful.\n{separator}\nOutside the list.\n")
    assert parsed["other"]["Strengths"] == "Outside the list."


class TestLastCopilotCorners:
    def test_reviewer3_prose_after_an_indented_heading_is_not_lazy(self):
        body = "- A.\n  # Heading\nOutside.\n  ```py\n  x\n### Fake\nunclosed"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}"
        parsed = reviewer3.parse_report(report)
        assert parsed["overview"][0]["text"] == "A.\n# Heading"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == parsed
        assert same_review(mapped("reviewer3", written), review)

    def test_cr_only_open_fence_is_found_and_contained(self):
        from ocrs.mappers.ai import close_fence, open_fence

        text = "Text.\r\r```py\rx"
        assert open_fence(text) == "```"
        assert close_fence(text).endswith("\n```")
        review = human_review()
        review["findings"] = {
            "comments": [{"title": "A", "text": text}, {"title": "B", "text": "Next."}]
        }
        comments = reviewer3.parse_report(codec_map_to("reviewer3", review))["comments"]
        assert [c["title"] for c in comments] == ["A", "B"]

    def test_reviewer3_open_tail_after_an_outdented_break_round_trips(self):
        body = "- A.\n - - -\n   ```py\n   x"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)


@pytest.mark.parametrize("underline", ["  ===", "  --", "  -"])
def test_deepreview_prose_after_a_setext_heading_in_a_point_is_not_lazy(underline):
    parsed = deepreview.parse_report(f"## Strengths\n* Heading\n{underline}\nOutside the list.\n")
    assert parsed["other"]["Strengths"] == "Outside the list."
    assert len(parsed["strengths"]) == 1


@pytest.mark.parametrize("indent", ["  ", "   "])
def test_reviewer3_summary_led_by_an_item_indented_break_stays_out_of_the_flaws(indent):
    review = human_review()
    review["findings"] = {"weaknesses": [{"id": "w1", "text": "Leak."}]}
    summary = f"{indent}- - -\n{indent}```py\n{indent}x"
    review["checks"] = [{"kind": "fatal_flaw_screen", "summary": summary, "finding_ids": ["w1"]}]
    report = reviewer3.parse_report(codec_map_to("reviewer3", review))
    assert report["fatal_flaws"]["items"] == [{"text": "Leak."}]
    assert report["fatal_flaws"]["text"].startswith(summary)


@pytest.mark.parametrize("brk", ["    - - -", "    * * *"])
def test_deepreview_break_inside_a_nested_point_ends_its_paragraph(brk):
    report = f"## Strengths\n* A.\n  - Nested point.\n{brk}\nOutside the list.\n"
    assert deepreview.parse_report(report)["other"]["Strengths"] == "Outside the list."


class TestQuotesAndHeldCode:
    @pytest.mark.parametrize("parse", ["deepreview", "reviewer3"])
    def test_nested_break_creates_no_list_level(self, parse):
        if parse == "deepreview":
            report = "## Strengths\n* Parent\n  - Child\n    - - -\nOutside the list.\n"
            assert deepreview.parse_report(report)["other"]["Strengths"] == "Outside the list."
        else:
            body = "- Parent\n  - Child\n    - - -\nOutside the list."
            report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}\n"
            assert reviewer3.parse_report(report)["other"]["Overview"] == "Outside the list."

    def test_deepreview_break_like_line_inside_code_keeps_the_block_whole(self):
        report = "## Strengths\n* A.\n ```\n - - -\n ```\n"
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == deepreview.parse_report(report)
        assert same_review(mapped("deepreview", written), review)

    def test_reviewer3_break_like_line_inside_code_keeps_the_block_whole(self):
        report = "# Review Report\n\nA paper\n\n---\n\n### Overview\n\n- A.\n ```\n - - -\n ```\n"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    @pytest.mark.parametrize("quote", ["  > # Heading", "  > ---"])
    def test_prose_after_a_quoted_heading_or_break_is_not_lazy(self, quote):
        report = f"## Strengths\n* A.\n{quote}\nOutside the list.\n"
        assert deepreview.parse_report(report)["other"]["Strengths"] == "Outside the list."

    def test_a_quoted_paragraph_still_continues_lazily(self):
        report = "## Strengths\n* A.\n  > quoted\nlazy line\n"
        parsed = deepreview.parse_report(report)
        assert "other" not in parsed


class TestAncestorsTabsQuotedFences:
    def test_break_under_a_nested_numbered_item_is_read_against_its_ancestor(self):
        report = "## Strengths\n* A.\n  1. Nested.\n    - - -\nOutside the list.\n"
        assert deepreview.parse_report(report)["other"]["Strengths"] == "Outside the list."

    def test_tab_indented_summary_stays_out_of_the_flaws(self):
        review = human_review()
        review["findings"] = {"weaknesses": [{"id": "w1", "text": "Leak."}]}
        summary = "\tNotes.\n\n```py\nx"
        review["checks"] = [
            {"kind": "fatal_flaw_screen", "summary": summary, "finding_ids": ["w1"]}
        ]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["fatal_flaws"]["items"] == [{"text": "Leak."}]

    def test_prose_after_a_quoted_fence_is_not_lazy(self):
        report = "## Strengths\n* Useful.\n  > ```py\nOutside the list.\n"
        assert deepreview.parse_report(report)["other"]["Strengths"] == "Outside the list."


class TestPreludeAndTail:
    def test_reviewer3_overview_prelude_and_open_tail_round_trip(self):
        body = "  Notes.\n\n- A.\n - - -\n   ```py\n   x"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    def test_reviewer3_fatal_flaws_prelude_and_open_tail_round_trip(self):
        body = "  Notes.\n\n- **Leak** — Test data leaks.\n - - -\n   ```py\n   x"
        report = f"# Review Report\n\nA paper\n\n---\n\n### Fatal Flaws\n\n{body}"
        review = mapped("reviewer3", report)
        written = codec_map_to("reviewer3", review)
        assert reviewer3.parse_report(written) == reviewer3.parse_report(report)
        assert same_review(mapped("reviewer3", written), review)

    def test_deepreview_rule_inside_a_points_code_keeps_the_block_whole(self):
        report = "## Strengths\n* A.\n ```py\n ---\n ```\n"
        review = mapped("deepreview", report)
        written = codec_map_to("deepreview", review)
        assert deepreview.parse_report(written) == deepreview.parse_report(report)
        assert same_review(mapped("deepreview", written), review)

    def test_tab_led_summary_stays_out_of_the_flaw(self):
        review = human_review()
        review["findings"] = {"weaknesses": [{"id": "w1", "text": "Leak."}]}
        review["checks"] = [
            {"kind": "fatal_flaw_screen", "summary": "\tNotes.\n\n```py\nx", "finding_ids": ["w1"]}
        ]
        report = reviewer3.parse_report(codec_map_to("reviewer3", review))
        assert report["fatal_flaws"]["items"] == [{"text": "Leak."}]


def test_deepreview_prose_after_a_tab_indented_heading_in_a_point_is_not_lazy():
    parsed = deepreview.parse_report("## Strengths\n* A.\n\t# Heading\nOutside.\n")
    assert parsed["other"]["Strengths"] == "Outside."


def test_deepreview_rule_and_code_inside_a_points_fence_keep_the_block_whole():
    report = "## Strengths\n* A.\n ```text\n ---\n example()\n ```\n"
    review = mapped("deepreview", report)
    written = codec_map_to("deepreview", review)
    assert deepreview.parse_report(written) == deepreview.parse_report(report)
    assert same_review(mapped("deepreview", written), review)


class TestLinearSplitAndQuotedCode:
    @staticmethod
    def count_fence_reads(monkeypatch):
        from ocrs.mappers import ai

        calls = {"n": 0}
        inside = ai.Fences.inside

        def counting(self, line):
            calls["n"] += 1
            return inside(self, line)

        monkeypatch.setattr(ai.Fences, "inside", counting)
        return calls

    def test_open_tail_split_reads_each_line_a_bounded_number_of_times(self, monkeypatch):
        from ocrs.mappers.ai import join_blocks

        # An indented fence opened first leaves every boundary's head open, so no split
        # qualifies and every boundary is tried
        paragraphs = 400
        block = "  ```py\n\n" + "\n\n".join(["  code()"] * paragraphs)
        calls = self.count_fence_reads(monkeypatch)
        join_blocks([block, "- Leak."])
        assert calls["n"] < 20 * paragraphs

    def test_a_final_open_block_is_left_without_splitting(self, monkeypatch):
        from ocrs.mappers.ai import join_blocks

        block = "  " + "\n\n  ".join(["Notes."] * 400) + "\n\n```py\nx"
        assert join_blocks(["- Leak.", block]).endswith(block)

    @pytest.mark.parametrize("reader", ["deepreview", "reviewer3"])
    def test_prose_after_quoted_indented_code_is_not_lazy(self, reader):
        if reader == "deepreview":
            parsed = deepreview.parse_report(
                "## Strengths\n* A.\n\n  >     code()\nOutside the list.\n"
            )
            assert parsed["other"]["Strengths"] == "Outside the list."
        else:
            body = "- A.\n\n  >     code()\nOutside the list."
            report = f"# Review Report\n\nA paper\n\n---\n\n### Overview\n\n{body}\n"
            assert reviewer3.parse_report(report)["other"]["Overview"] == "Outside the list."

    def test_a_quoted_paragraph_still_continues_lazily_after_quoted_code_rules(self):
        parsed = deepreview.parse_report("## Strengths\n* A.\n  > quoted\nlazy line\n")
        assert "other" not in parsed


@pytest.mark.parametrize(
    "quote",
    [
        "  > Heading\n  > ===",
        "  > ```py\n  > x = 1",
        "  > ```py\n  > x = 1\n  > ```",
        "  > ~~~py\n  > example()",
    ],
)
def test_deepreview_prose_after_a_quoted_heading_or_code_is_not_lazy(quote):
    parsed = deepreview.parse_report(f"## Strengths\n* A.\n{quote}\nOutside the list.\n")
    assert parsed["other"]["Strengths"] == "Outside the list."


@pytest.mark.parametrize(
    "quote",
    [
        "  > ````py\n  > ```\n  > example()",
        "  >     code()",
    ],
)
def test_deepreview_quoted_code_ends_the_paragraph(quote):
    parsed = deepreview.parse_report(f"## Strengths\n* A.\n{quote}\nOutside the list.\n")
    assert parsed["other"]["Strengths"] == "Outside the list."


def test_deepreview_quoted_paragraph_continues_into_indented_quoted_text():
    parsed = deepreview.parse_report("## Strengths\n* A.\n  > quoted\n  >     more\nlazy line\n")
    assert "other" not in parsed


class TestGateQuoteState:
    def test_a_nested_quotes_fence_ends_with_the_nested_quote(self):
        report = "## Strengths\n* A.\n  > > ```py\n  > > x\n  > parent text\nlazy line\n"
        # The parent quote's text is a paragraph again, so the lazy line continues it
        assert "other" not in deepreview.parse_report(report)

    @pytest.mark.parametrize(
        "quote",
        ["  > quoted\n\n  >     code()", "  > Heading\n  > ===\n  >     code()"],
    )
    def test_quoted_code_after_a_quote_paragraph_ended_is_code(self, quote):
        parsed = deepreview.parse_report(f"## Strengths\n* A.\n{quote}\nOutside the list.\n")
        assert parsed["other"]["Strengths"] == "Outside the list."
