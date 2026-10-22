# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""JATS sub-articles: what the real ones in tests/fixtures/real/jats/ do not show."""

import xml.etree.ElementTree as ET

from conftest import codec_map_from, codec_map_to

from ocrs.mappers.jats import TERMS
from ocrs.util import narrative_text

XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'


def payload(front: str = "", body: str = "<p>Fine.</p>", article: dict | None = None, **attrs):
    attributes = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    xml = f"<sub-article {XLINK} {attributes}><front-stub>{front}</front-stub>"
    xml += f"<body>{body}</body></sub-article>"
    return {"sub_article": xml} | ({"article": article} if article else {})


def round_trip(review: dict) -> dict:
    return codec_map_from("jats", codec_map_to("jats", review))


def test_text_after_a_list_in_a_paragraph_is_kept():
    body = (
        '<p>Before.<list list-type="order"><list-item><p>One.</p></list-item>'
        "<list-item><p>Two.</p></list-item></list>After the list.</p>"
        "<sec><title>Methods</title><p>Clear.</p><p>Sound.</p></sec>"
    )
    review = codec_map_from("jats", payload(body=body, article_type="referee-report", id="r1"))
    assert narrative_text(review, "review") == (
        "Before.\n\n1. One.\n2. Two.\n\nAfter the list.\n\nMethods:\n\nClear.\n\nSound."
    )
    assert [p for p in review["narrative"] if "role" not in p] == [
        {"title": "Methods", "content": "Clear.\n\nSound."}
    ]
    assert round_trip(review)["narrative"] == review["narrative"]


def test_a_review_with_only_sections_is_written_with_a_body():
    review = codec_map_from("jats", payload(article_type="referee-report", id="r1"))
    review["narrative"] = [{"title": "Strengths", "content": "Clear."}]
    review["opinion"] = {}
    again = round_trip(review)
    assert [p for p in again["narrative"] if "role" not in p] == [
        p for p in review["narrative"] if "role" not in p
    ]


def test_a_date_without_a_type_is_kept():
    front = "<pub-date><day>3</day><month>2</month><year>2025</year></pub-date>"
    review = codec_map_from("jats", payload(front=front, article={"doi": "10.1234/j.1"}, id="r1"))
    assert review["created_at"] == "2025-02-03T00:00:00Z"
    assert round_trip(review)["created_at"] == "2025-02-03T00:00:00Z"


def test_a_corrected_doi_is_written_though_the_article_gave_one():
    review = codec_map_from("jats", payload(article={"doi": "10.1234/j.1"}, id="r1"))
    assert review["target"]["work_id"] == "doi:10.1234/j.1"
    review["target"]["identifiers"]["doi"]["value"] = "10.1234/j.2"
    review["target"]["work_id"] = "doi:10.1234/j.2"
    assert round_trip(review)["target"]["work_id"] == "doi:10.1234/j.2"


def test_a_recommendation_ocrs_does_not_know_goes_back_as_written():
    front = (
        "<custom-meta-group><custom-meta><meta-name>recommendation</meta-name>"
        "<meta-value>approve-in-part</meta-value></custom-meta></custom-meta-group>"
    )
    review = codec_map_from("jats", payload(front=front, id="r1"))
    # The source's term, with no recommendation OCRS can name
    assert review["decision"] == {"source_label": "approve-in-part"}
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    assert written.findtext(".//meta-value") == "approve-in-part"
    # A recommendation the review now makes replaces it
    review["decision"] = {"recommendation": "reject"}
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    assert written.findtext(".//meta-value") == "reject"


def test_a_shared_affiliation_is_written_once():
    front = (
        "<contrib-group>"
        "<contrib><name><surname>A</surname><given-names>Ann</given-names></name>"
        '<xref ref-type="aff" rid="a1">1</xref></contrib>'
        "<contrib><name><surname>B</surname><given-names>Bo</given-names></name>"
        '<xref ref-type="aff" rid="a1">1</xref></contrib>'
        '<aff id="a1"><label>1</label>Example University</aff></contrib-group>'
    )
    review = codec_map_from("jats", payload(front=front, id="r1"))
    assert [r["human_referee"]["affiliation"] for r in review["referees"]] == [
        "Example University",
        "Example University",
    ]
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    assert [aff.get("id") for aff in written.iter("aff")] == ["a1"]
    # One whose affiliation changed gets an ID of its own
    review["referees"][1]["human_referee"]["affiliation"] = "Another University"
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    assert [aff.get("id") for aff in written.iter("aff")] == ["a1", "a1-2"]
    assert [r["human_referee"]["affiliation"] for r in round_trip(review)["referees"]] == [
        "Example University",
        "Another University",
    ]


def test_a_review_with_no_doi_or_id_keeps_its_id():
    review = codec_map_from("jats", payload())
    again = round_trip(review)
    assert again["review_id"] == review["review_id"]
    assert "source_review_id" not in again["provenance"]


def test_a_changed_affiliation_takes_an_id_no_other_has():
    """Contributor 3's changed affiliation would have taken `a1-3`, which contributor 2's
    already has: its reference then named the wrong affiliation, and it was not written."""
    front = (
        "<contrib-group>"
        '<contrib><name><surname>A</surname></name><xref ref-type="aff" rid="a1"/></contrib>'
        '<contrib><name><surname>B</surname></name><xref ref-type="aff" rid="a1-3"/></contrib>'
        '<contrib><name><surname>C</surname></name><xref ref-type="aff" rid="a1"/></contrib>'
        '<aff id="a1">Example University</aff><aff id="a1-3">Third University</aff>'
        "</contrib-group>"
    )
    review = codec_map_from("jats", payload(front=front, id="r1"))
    review["referees"][2]["human_referee"]["affiliation"] = "Another University"
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    ids = [aff.get("id") for aff in written.iter("aff")]
    assert len(ids) == len(set(ids)) == 3
    assert [r["human_referee"]["affiliation"] for r in round_trip(review)["referees"]] == [
        "Example University",
        "Third University",
        "Another University",
    ]


def test_a_changed_affiliation_reuses_only_an_id_made_for_it():
    """`a10` is no ID of the `a1` family: a contributor of `a1` who moves to `a10`'s
    affiliation gets an ID of its own, not `a10` with `a1`'s label."""
    front = (
        "<contrib-group>"
        '<contrib><name><surname>A</surname></name><xref ref-type="aff" rid="a1">1</xref></contrib>'
        '<contrib><name><surname>B</surname></name><xref ref-type="aff" rid="a10">10</xref>'
        "</contrib>"
        '<contrib><name><surname>C</surname></name><xref ref-type="aff" rid="a1">1</xref></contrib>'
        '<aff id="a1"><label>1</label>Example University</aff>'
        '<aff id="a10"><label>10</label>Tenth University</aff>'
        "</contrib-group>"
    )
    review = codec_map_from("jats", payload(front=front, id="r1"))
    review["referees"][2]["human_referee"]["affiliation"] = "Tenth University"
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    references = [x.get("rid") for x in written.iter("xref")]
    assert references[1] == "a10" and references[2] not in ("a1", "a10")
    assert [r["human_referee"]["affiliation"] for r in round_trip(review)["referees"]] == [
        "Example University",
        "Tenth University",
        "Tenth University",
    ]


def test_an_extension_cannot_write_markup():
    """`extensions.jats` comes with the review, from anyone: an attribute name or a response
    in it must not put elements of its own into the sub-article."""
    review = codec_map_from("jats", payload(article={"doi": "10.1234/j.1"}, id="r1"))
    forged = 'x="1"><contrib><name><surname>Forged</surname></name></contrib><a b'
    review["target"]["identifiers"]["doi"]["value"] = "10.1234/j.2"
    review["target"]["work_id"] = "doi:10.1234/j.2"
    review["extensions"]["jats"]["related_article"] = {forged: "v", "id": "rel1"}
    review["extensions"]["jats"]["responses"] = ["<contrib><surname>Forged</surname></contrib>"]
    written = ET.fromstring(codec_map_to("jats", review)["sub_article"])
    assert not [s for s in written.iter("surname") if s.text == "Forged"]
    assert written.find("front-stub/related-article").attrib == {
        "id": "rel1",
        "{http://www.w3.org/1999/xlink}href": "10.1234/j.2",
    }


def test_every_recommendation_has_a_term():
    review = codec_map_from("jats", payload(id="r1"))
    for recommendation in (
        "strong_accept",
        "weak_accept",
        "borderline",
        "weak_reject",
        "strong_reject",
    ):
        review["decision"] = {"recommendation": recommendation}
        # Written as its term, which reads back as the recommendation in the source's words
        term = TERMS[recommendation]
        assert round_trip(review)["decision"] == {
            "recommendation": recommendation,
            "source_label": term,
        }


def test_a_review_of_findings_alone_is_written_with_them():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"], review["opinion"] = [], {}
    review["findings"] = {
        "weaknesses": [{"title": "No ablation", "text": "Table 3 shows the full model only."}]
    }
    again = round_trip(review)
    assert [p for p in again["narrative"] if "role" not in p] == [
        {"title": "Weaknesses", "content": "- **No ablation** Table 3 shows the full model only."}
    ]


def test_a_title_or_journal_changed_in_ocrs_is_written():
    article = {"doi": "10.1234/j.1", "title": "Old title", "journal": "Old Journal"}
    review = codec_map_from("jats", payload(article=article, id="r1"))
    review["target"]["title"], review["target"]["venue"] = "New title", "New Journal"
    again = round_trip(review)
    assert (again["target"]["title"], again["target"]["venue"]) == ("New title", "New Journal")
    assert again["target"]["work_id"] == "doi:10.1234/j.1"


def test_a_list_nested_in_a_list_item_is_kept():
    body = (
        '<list list-type="bullet"><list-item><p>Methods:</p><list list-type="bullet">'
        "<list-item><p>No ablation.</p></list-item><list-item><p>One dataset.</p></list-item>"
        "</list></list-item><list-item><p>Clear writing.</p></list-item></list>"
    )
    review = codec_map_from("jats", payload(body=body, id="r1"))
    assert narrative_text(review, "review") == (
        "- Methods: No ablation.; One dataset.\n- Clear writing."
    )
    assert round_trip(review)["narrative"] == review["narrative"]


def test_findings_no_section_holds_are_written_after_the_sections():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [{"title": "strengths", "content": "- Clear."}]
    review["opinion"] = {}
    review["findings"] = {"strengths": [{"text": "Clear."}], "weaknesses": [{"text": "Small."}]}
    sections = [p for p in round_trip(review)["narrative"] if "role" not in p]
    assert sections == [
        {"title": "strengths", "content": "- Clear."},
        {"title": "Weaknesses", "content": "- Small."},
    ]


def test_a_doi_in_the_work_id_alone_is_written():
    review = codec_map_from("jats", payload(id="r1"))
    review["target"] = {"work_id": "doi:10.1234/j.9", "work_type": "article"}
    assert round_trip(review)["target"]["work_id"] == "doi:10.1234/j.9"


def test_findings_a_section_does_not_hold_are_written_too():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [{"title": "strengths", "content": "- Clear."}]
    review["opinion"] = {}
    review["findings"] = {"strengths": [{"text": "Clear."}, {"text": "Novel."}]}
    sections = [p for p in round_trip(review)["narrative"] if "role" not in p]
    assert sections == [
        {"title": "strengths", "content": "- Clear."},
        {"title": "Strengths", "content": "- Novel."},
    ]


def test_a_finding_inside_a_longer_item_is_not_held_by_it():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [
        {"title": "strengths", "content": "- Novel. The approach needs evidence."}
    ]
    review["opinion"] = {}
    review["findings"] = {"strengths": [{"text": "Novel."}]}
    sections = [p for p in round_trip(review)["narrative"] if "role" not in p]
    assert sections[-1] == {"title": "Strengths", "content": "- Novel."}


def test_a_summary_that_starts_a_finding_is_still_written():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"], review["opinion"] = [], {"summary": "No"}
    review["findings"] = {"weaknesses": [{"text": "No ablation."}]}
    assert narrative_text(round_trip(review), "review").startswith("No\n\nWeaknesses:")


def test_a_part_with_no_title_or_role_is_written():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"], review["opinion"] = [{"content": "A sound method."}], {}
    assert narrative_text(round_trip(review), "review") == "A sound method."


def test_every_part_that_is_the_review_is_written():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [
        {"role": "review", "content": "First report."},
        {"role": "review", "content": "Second report."},
    ]
    assert narrative_text(round_trip(review), "review") == "First report.\n\nSecond report."


def test_a_part_the_authors_may_not_read_is_not_published():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [
        {"role": "review", "audience": "reviewers", "content": "For the other reviewers."},
        {"title": "To the editor", "audience": "editors", "content": "Reject it."},
        {"title": "Strengths", "content": "Clear."},
    ]
    review["opinion"] = {}
    written = codec_map_to("jats", review)["sub_article"]
    assert "Clear." in written
    assert "other reviewers" not in written and "Reject it." not in written


def test_a_license_changed_in_ocrs_is_written():
    front = (
        '<permissions><copyright-statement>© The authors</copyright-statement><license xlink:href="'
        'https://creativecommons.org/licenses/by/4.0/"><license-p>CC BY</license-p></license>'
        "</permissions>"
    )
    review = codec_map_from("jats", payload(front=front, id="r1"))
    assert review["provenance"]["license"] == {
        "url": "https://creativecommons.org/licenses/by/4.0/"
    }
    assert round_trip(review)["provenance"]["license"] == review["provenance"]["license"]
    review["provenance"]["license"] = {"name": "CC0 1.0"}
    again = round_trip(review)
    assert again["provenance"]["license"] == {"name": "CC0 1.0"}
    # What OCRS has no field for stays
    assert again["extensions"]["jats"]["permissions"]["copyright_statement"] == "© The authors"


def test_questions_for_the_authors_are_written():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"], review["opinion"] = [{"role": "questions", "content": "Why 3?"}], {}
    assert narrative_text(round_trip(review), "review") == "Why 3?"
    review["narrative"].insert(0, {"role": "review", "content": "A sound method."})
    review["narrative"][1]["title"] = "Questions"
    assert narrative_text(round_trip(review), "review") == (
        "A sound method.\n\nQuestions:\n\nWhy 3?"
    )


def test_a_part_with_no_role_is_written_after_the_review():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [
        {"role": "review", "content": "A sound method."},
        {"title": "limitations", "content": "One dataset."},
    ]
    again = round_trip(review)
    assert narrative_text(again, "review") == "A sound method.\n\nlimitations:\n\nOne dataset."
    # A report read from JATS: its parts are in its text, and are not written twice
    assert round_trip(again)["narrative"] == again["narrative"]


def test_a_part_whose_words_the_review_uses_is_still_written():
    review = codec_map_from("jats", payload(id="r1"))
    review["narrative"] = [
        {"role": "review", "content": "The paper has limitations."},
        {"title": "Limitations", "content": "limitations"},
    ]
    assert narrative_text(round_trip(review), "review") == (
        "The paper has limitations.\n\nLimitations:\n\nlimitations"
    )
