# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the DeepReview mapper: Google DeepReview's Markdown report to OCRS."""

from pathlib import Path

import pytest
from conftest import codec_map_from, codec_map_with_record, codec_validate

from ocrs import render_mapping_markdown
from ocrs.anchors import Block
from ocrs.mapping import MappingStatus, Rule

REPORT = (Path(__file__).parent / "fixtures" / "ai" / "deepreview_report.md").read_text()
RUN = {
    "review_id": "deepreview-1",
    "source_system": "deepreview",
    "work_id": "paper-1",
    "work_type": "preprint",
    "started_at": "2026-10-15T17:40:00Z",
    "ended_at": "2026-10-15T18:05:00Z",
}
MISTAKES = "Potential Mistakes and Improvements"
MINOR = "Minor Corrections and Typos"
DATASETS = "[CTA & Yard Feed Datasets, Preprocessing, and Splitting Strategy] (Pages: 7-13)"


def mapped(report=REPORT, **run):
    return codec_map_with_record("deepreview", report, **{**RUN, **run})


def by_id(review):
    return {point["id"]: point for points in review["findings"].values() for point in points}


@pytest.fixture(scope="module")
def result():
    return mapped()


@pytest.fixture(scope="module")
def points(result):
    return by_id(result.review)


def test_maps_the_whole_report(result):
    codec_validate(result.review)
    assert result.record.status == MappingStatus.OK
    assert result.record.gaps.unmapped == []
    assert result.record.gaps.coerced == []
    assert "extensions" not in result.review
    assert result.review["opinion"]["summary"].startswith("This paper introduces a multi-source")
    findings = result.review["findings"]
    assert len(findings["strengths"]) == 4
    groups = [tuple(point.get("group", [])[1:]) for point in findings["weaknesses"]]
    assert groups.count(()) == 4
    assert groups.count((MISTAKES,)) == 16
    assert groups.count((MINOR,)) == 26


def test_weaknesses_are_overviews(points):
    overview = points["weakness-1"]
    assert overview["summarizes"] == []
    assert overview["text"].startswith("The alternating even/odd calendar-day data split")
    assert "severity" not in overview


def test_tier_gives_severity_and_group(points, result):
    leakage = points["issue-2.1.2"]
    assert leakage["title"].startswith("Multi-Day Weather and Delivery-Cycle Leakage")
    assert leakage["group"] == [DATASETS, MISTAKES]
    assert leakage["severity"] == "major"
    assert points["issue-2.2.1"]["severity"] == "minor"
    lookups = [step for step in result.record.steps if step.rule == Rule.LOOKUP]
    assert {(step.original, step.result) for step in lookups} == {
        (MISTAKES, "major"),
        (MINOR, "minor"),
    }


def test_text_keeps_the_reviewer_markdown(points):
    text = points["issue-1.1.1"]["text"]
    assert text.startswith("- **Observation:** In Section 1.2 (page 3)")
    assert "\n- **Potential Concern:** Under a free-jet spreading model" in text
    assert "\n  - For the reach from the door line" in text


def test_location_heading_gives_one_link_per_place(points):
    title = points["issue-1.1.1"]["title"]
    assert title == "Potential Inconsistency in Plume-Reach and Arrival-Time Estimates"
    links = [link for link in points["issue-1.1.1"]["evidence_links"] if link["ref"]]
    assert links == [
        {
            "type": "paper_section",
            "ref": "Section 1.2, Pages 3–4",
            "location": {"page": 3, "page_end": 4, "section": "1.2"},
        },
        {
            "type": "paper_section",
            "ref": "Section 1.5, Page 6",
            "location": {"page": 6, "section": "1.5"},
        },
    ]


@pytest.mark.parametrize(
    "point_id, link",
    [
        ("issue-1.2.1", {"type": "paper_section", "ref": "Abstract (Page 1)",
                         "location": {"page": 1, "section": "Abstract"}}),
        ("issue-2.2.5", {"type": "figure", "ref": "Page 11, Figure 1(a) caption",
                         "location": {"page": 11}}),
        ("issue-3.2.4", {"type": "equation", "ref": "Pages 19 & 20 (Equations 4, 6, and 7)"}),
        ("issue-4.1.3", {"type": "appendix", "ref": "Appendix A, pp. 34–35",
                         "location": {"page": 34, "page_end": 35}}),
    ],
)  # fmt: skip
def test_place_kinds_and_pages(points, point_id, link):
    assert link in points[point_id]["evidence_links"]


def test_minor_points_have_a_location_and_no_title(points):
    point = points["issue-2.2.1"]
    assert "title" not in point
    assert point["evidence_links"][0]["ref"] == "Page 8, Section 2.1"
    assert point["text"].startswith('In *"Only bays with')


def test_quotes_from_the_paper(points):
    quotes = [link["quote"] for link in points["issue-1.1.1"]["evidence_links"] if "quote" in link]
    assert len(quotes) == 3
    assert quotes[0].startswith("For doors $2\\text{–}9\\text{ m}$ wide")


def test_proposed_wording_is_not_a_quote(points):
    quotes = [link.get("quote") for link in points["issue-4.2.6"]["evidence_links"]]
    assert "5–6% above persist / door-event" not in quotes
    assert points["issue-4.2.6"]["suggested_edits"] == [
        {"replacement": "5–6% above persist / door-event"}
    ]
    assert "8–10% above persist / door-event" in quotes
    assert '*"5–6% above persist / door-event"*' in points["issue-4.2.6"]["text"]


def test_suggested_edits(points):
    assert points["issue-1.2.2"]["suggested_edits"] == [
        {"replacement": "described in Ref. 21,"},
        {"replacement": "described by Marchetti,$^{21}$"},
    ]
    assert points["issue-3.2.3"]["suggested_edits"] == [
        {"original": "Residaul Block", "replacement": "Residual Block"},
        {"original": "Query: Bay Embeddigns", "replacement": "Bay Embeddings"},
        {"original": "Key: Bay Embeddigns", "replacement": "Bay Embeddings"},
        {"original": "Out: forcast", "replacement": "Out: forecast"},
    ]
    quotes = [link.get("quote") for link in points["issue-2.2.6"]["evidence_links"]]
    assert "clipped to $[0, 100]$ and divided by $100$" not in quotes


def test_cited_works(points):
    links = [link for link in points["weakness-4"]["evidence_links"] if link["type"] == "external"]
    assert [link["work"] for link in links] == [
        {
            "title": "Message Passing on Floor-Plan Graphs for Indoor Climate Prediction",
            "authors": ["Halvorsen et al."],
            "year": 2018,
        },
        {
            "title": "Lumped-Capacitance Models of Refrigerated Warehouses Under Door Infiltration",
            "authors": ["Vasquez-Thorne et al."],
            "year": 2020,
        },
    ]


def test_parsed_values_are_recorded(result):
    parsed = {
        (step.source, step.target, str(step.result))
        for step in result.record.steps
        if step.rule == Rule.PARSED
    }
    assert (
        "issues[0].tiers[0].items[0].location",
        "findings.weaknesses[4].evidence_links[0].location.page_end",
        "4",
    ) in parsed


def test_quotes_found_in_the_paper():
    sentence = "Only the final sweep and the target are smoothed, as described in Sect. 2.1."
    result = mapped(blocks=[Block(id="p13", text=f"Robust scaling follows. {sentence}")])
    anchored = [step for step in result.record.steps if step.rule == Rule.ANCHORED_EXACT]
    assert [(step.source, step.result) for step in anchored] == [
        ("issues[1].tiers[0].items[0].text", {"part": "body", "block_id": "p13"})
    ]
    quotes = [
        link
        for point in by_id(result.review).values()
        for link in point.get("evidence_links", [])
        if "quote" in link
    ]
    assert len(result.record.gaps.unanchored) == len(quotes) - 1


def test_bold_strengths_and_unknown_parts():
    report = """# HIGH LEVEL SUMMARY
---
## Summary
A paper.

## Strengths
* **Clear idea:** The method is simple.

## Reviewer Notes
Something new.

## Potential Issues And Suggestions
### [Methods] (Pages: 2-5)
#### Questions For Authors

1. **Why this basis? (Section IV-B2, Page 4)**
   Please explain.

2. **An empty point (Page 5)**
"""
    result = mapped(report)
    review = result.review
    assert review["findings"]["strengths"] == [
        {"id": "strength-1", "title": "Clear idea", "text": "The method is simple."}
    ]
    [question] = review["findings"]["weaknesses"]
    assert question["group"] == ["[Methods] (Pages: 2-5)", "Questions For Authors"]
    assert "severity" not in question
    [coercion] = result.record.gaps.coerced
    assert coercion.original == "Questions For Authors"
    assert result.record.status == MappingStatus.PARTIAL
    assert [item.source for item in result.record.skipped] == ["issues[0].tiers[0].items[1]"]
    kept = review["extensions"]["deepreview"]
    assert kept["other"] == {"Reviewer Notes": "Something new."}
    assert kept["issues"][0]["tiers"][0]["items"][1] == {
        "title": "An empty point",
        "location": "Page 5",
        "text": "",
    }


def test_run_details():
    review = mapped(reviewer_version="2026-10").review
    system = review["referees"][0]["ai_referee"]["system"]
    assert system["critic_framework"] == {"name": "deepreview", "version": "2026-10"}
    assert system["models"] == [{"role": "reviewer", "model_id": "unspecified"}]
    framework = mapped().review["referees"][0]["ai_referee"]["system"]["critic_framework"]
    assert framework["version"] == "unspecified"


def test_map_from_keeps_the_report():
    review = codec_map_from("deepreview", {"output": REPORT, **RUN}, keep_raw=True)
    assert review["provenance"]["raw_payload"] == {"text": REPORT}


def test_output_must_be_markdown():
    with pytest.raises(TypeError):
        mapped({"summary": "A paper."})


def test_mapping_report(result):
    markdown = render_mapping_markdown(result)
    assert markdown.startswith("# deepreview review mapped to OCRS")
    assert "| parsed |" in markdown


def test_a_title_that_starts_like_a_place_keeps_its_title():
    report = """## Potential Issues And Suggestions
### [Data] (Pages: 9-16)
#### Potential Mistakes and Improvements

1. **Table 1 Conflicts with the Prose (Section 2.3, Page 15):**
   The normalizations differ.

#### Minor Corrections and Typos

- **Table I(a) and Table I(b), `Clipped` column:** Missing error bars.
"""
    [title_point, place_point] = mapped(report).review["findings"]["weaknesses"]
    assert title_point["title"] == "Table 1 Conflicts with the Prose"
    assert title_point["evidence_links"] == [
        {
            "type": "paper_section",
            "ref": "Section 2.3, Page 15",
            "location": {"page": 15, "section": "2.3"},
        }
    ]
    assert "title" not in place_point
    assert place_point["evidence_links"][0]["ref"] == "Table I(a) and Table I(b), `Clipped` column"


def test_text_before_the_first_section_is_kept():
    note = "Reviewer note: only the main manuscript was assessed."
    report = f"# HIGH LEVEL SUMMARY\n---\n{note}\n## Summary\nA paper.\n"
    result = mapped(report)
    assert result.review["extensions"]["deepreview"] == {"other": {"preamble": note}}
    assert [field.path for field in result.record.gaps.unmapped] == ["other.preamble"]
    assert "extensions" not in mapped("# HIGH LEVEL SUMMARY\n---\n## Summary\nA paper.\n").review


@pytest.mark.parametrize(
    "cited",
    [
        "(Reference Paper: First Study, Smith et al.; "
        "Reference Paper: Second Study, Jones et al., 2024)",
        "(Reference Paper: First Study, Smith et al.) and "
        "(Reference Paper: Second Study, Jones et al., 2024)",
        "(Reference Paper: First Study, Smith et al.) and "
        "(Reference Paper: Second Study, Jones et al., 2024) (Third Study, Lee et al., 2023)",
    ],
    ids=["same-parentheses", "separate-parentheses", "unmarked-after"],
)
def test_a_citation_without_a_year_does_not_swallow_the_next(cited):
    report = f"## Weaknesses\n* Missing baselines {cited}.\n"
    [weakness] = mapped(report).review["findings"]["weaknesses"]
    assert [link["work"] for link in weakness["evidence_links"]] == [
        {"title": "Second Study", "authors": ["Jones et al."], "year": 2024}
    ]


def test_repeated_sections_add_up():
    report = """## Strengths
* One.
## Reviewer Notes
First note.
## Strengths
* Two.
## Reviewer Notes
Second note.
"""
    review = mapped(report).review
    assert [point["text"] for point in review["findings"]["strengths"]] == ["One.", "Two."]
    assert review["extensions"]["deepreview"]["other"] == {
        "Reviewer Notes": "First note.\n\nSecond note."
    }


@pytest.mark.parametrize(
    "prose, edits",
    [
        ('Replace "duplicate text" with "".', [{"original": "duplicate text", "replacement": ""}]),
        ('Compare "baseline A" and "baseline B" to "baseline C".', None),
        ('Do not replace "correlation" with "causation".', None),
        ('Do not simply replace "A" with "B".', None),
        ('You cannot replace "correlation" with "causation".', None),
        ('Don’t replace "correlation" with "causation".', None),
        ('Do not (see Table 1; the data are correlational) replace "A" with "B".', None),
        ('To avoid confusion, replace "A" with "B".', [{"original": "A", "replacement": "B"}]),
        (
            'The terminology is not consistent, so change "A" to "B".',
            [{"original": "A", "replacement": "B"}],
        ),
        (
            'The manuscript says *"These results are not significant."* '
            'Change "not significant" to "inconclusive".',
            [{"original": "not significant", "replacement": "inconclusive"}],
        ),
        (
            'Replace *"the method proves the claim"* with\n  *"the method supports the claim"*.',
            [
                {
                    "original": "the method proves the claim",
                    "replacement": "the method supports the claim",
                }
            ],
        ),
        ('Do not, even in Section 2.3, replace "correlation" with "causation".', None),
        ('Do not, as in Sect. 2 or Fig. 3, replace "A" with "B".', None),
        (
            "Do not, in the revised discussion of the ablation results and the long appendix "
            'tables that follow them, replace "A" with "B".',
            None,
        ),
        (
            'Do not retain the sentence "this is wrong." Replace "A" with "B".',
            [{"original": "A", "replacement": "B"}],
        ),
        (
            'This is not clear. Replace "A" with "B".',
            [{"original": "A", "replacement": "B"}],
        ),
        (
            'Change "in 13" to "in Eq. (13)" and "Eq. 13" to "Eq. (13)".',
            [
                {"original": "in 13", "replacement": "in Eq. (13)"},
                {"original": "Eq. 13", "replacement": "Eq. (13)"},
            ],
        ),
    ],
    ids=[
        "deletion",
        "comparison",
        "negated",
        "negated-later",
        "cannot",
        "typographic-apostrophe",
        "parenthetical-semicolon",
        "purpose-clause",
        "unrelated-negation",
        "quoted-negation",
        "soft-wrap",
        "section-number",
        "abbreviations",
        "negated-long",
        "closing-quote",
        "other-clause",
        "chained",
    ],
)
def test_edit_phrasing(prose, edits):
    report = (
        "## Potential Issues And Suggestions\n### [Text] (Pages: 1-2)\n"
        f"#### Minor Corrections and Typos\n\n- **Page 1:** {prose}\n"
    )
    [point] = mapped(report).review["findings"]["weaknesses"]
    assert point.get("suggested_edits") == edits


def test_split_places_are_recorded_as_parsed(result):
    location = "Section 1.2, Pages 3–4; Section 1.5, Page 6"
    steps = [
        (step.target, step.rule, step.original, step.result)
        for step in result.record.steps
        if step.source == "issues[0].tiers[0].items[0].location"
        and step.target.endswith(".location.label")
    ]
    assert steps == [
        (
            "findings.weaknesses[4].evidence_links[0].location.label",
            Rule.PARSED,
            location,
            "Section 1.2, Pages 3–4",
        ),
        (
            "findings.weaknesses[4].evidence_links[1].location.label",
            Rule.PARSED,
            location,
            "Section 1.5, Page 6",
        ),
    ]


def test_a_list_of_sections_is_not_one_section():
    report = """## Potential Issues And Suggestions
### [Methods] (Pages: 2-5)
#### Potential Mistakes and Improvements

1. **Unclear smoothing (Section 2.1 and 2.3, Page 4):**
   The two sections differ.
"""
    [point] = mapped(report).review["findings"]["weaknesses"]
    assert point["evidence_links"][0]["location"] == {"page": 4}


@pytest.mark.parametrize(
    "place, section",
    [("Section 2.3(a), Page 4", "2.3(a)"), ("Section 2.3–2.5, Pages 13–15", "2.3–2.5")],
)
def test_sections_keep_subsections_and_ranges(place, section):
    report = (
        "## Potential Issues And Suggestions\n### [Methods] (Pages: 2-15)\n"
        f"#### Potential Mistakes and Improvements\n\n1. **Unclear ({place}):**\n   Text.\n"
    )
    [point] = mapped(report).review["findings"]["weaknesses"]
    assert point["evidence_links"][0]["location"]["section"] == section


def test_mapping_report_has_one_heading_per_finding(result):
    markdown = render_mapping_markdown(result)
    section = markdown.split("### `issues[1].tiers[0].items[0]`")[1].split("### ")[0]
    assert "| `text` | `text` | copied |" in section
    assert "| `issues[1].heading` | `group[0]` | copied |" in section
    assert "### `issues[1].tiers[0].items[0]` → `findings.weaknesses[7]`" in markdown
    assert "### `issues[1].tiers[0].items[1]` → `findings.weaknesses[8]`" in markdown


def test_a_wrapped_negation_still_counts():
    report = (
        "## Potential Issues And Suggestions\n### [Results] (Pages: 5-6)\n"
        "#### Potential Mistakes and Improvements\n\n"
        '1. **Causal wording (Page 5):**\n   Do not\n   replace "correlation" with "causation".\n'
        '   - Instead, replace "proves" with "suggests".\n'
    )
    [point] = mapped(report).review["findings"]["weaknesses"]
    assert point["suggested_edits"] == [{"original": "proves", "replacement": "suggests"}]


def test_wording_a_point_warns_against_is_not_a_quote():
    prose = (
        'Do not replace *"the effect is driven by humidity"* with '
        '*"the effect is caused by humidity alone"*; the data are correlational.'
    )
    report = (
        "## Potential Issues And Suggestions\n### [Results] (Pages: 5-6)\n"
        f"#### Minor Corrections and Typos\n\n- **Page 5:** {prose}\n"
    )
    [point] = mapped(report).review["findings"]["weaknesses"]
    assert "suggested_edits" not in point
    quotes = [link["quote"] for link in point["evidence_links"] if "quote" in link]
    assert quotes == ["the effect is driven by humidity"]


def test_a_quote_with_the_same_words_as_a_replacement_is_kept():
    prose = (
        'The Abstract says *"the effect is driven by humidity"*, so replace '
        '*"the effect is mostly unexplained"* with *"the effect is driven by humidity"*.'
    )
    report = (
        "## Potential Issues And Suggestions\n### [Results] (Pages: 1-6)\n"
        f"#### Minor Corrections and Typos\n\n- **Page 5:** {prose}\n"
    )
    [point] = mapped(report).review["findings"]["weaknesses"]
    quotes = [link["quote"] for link in point["evidence_links"] if "quote" in link]
    assert quotes == ["the effect is driven by humidity", "the effect is mostly unexplained"]
    assert point["suggested_edits"] == [
        {
            "original": "the effect is mostly unexplained",
            "replacement": "the effect is driven by humidity",
        }
    ]


def issues_report(item):
    """A minimal report with one point under Potential Issues."""
    return (
        "## Potential Issues And Suggestions\n### [Methods]\n"
        f"#### Potential Mistakes and Improvements\n\n1. {item}\n"
    )


def test_an_unbalanced_parenthesis_ends_the_title():
    [point] = mapped(issues_report("**Odd title x)**: Text.")).review["findings"]["weaknesses"]
    assert point["title"] == "Odd title x)" and "evidence_links" not in point


def test_an_empty_place_is_left_out():
    [point] = mapped(issues_report("**Title (Page 3; ):** Text.")).review["findings"]["weaknesses"]
    assert [link["ref"] for link in point["evidence_links"]] == ["Page 3"]


def test_a_rewrite_proposed_twice_is_one_edit():
    item = '**Typo:** Change "teh" to "the". Again: change "teh" to "the".'
    [point] = mapped(issues_report(item)).review["findings"]["weaknesses"]
    assert point["suggested_edits"] == [{"original": "teh", "replacement": "the"}]
