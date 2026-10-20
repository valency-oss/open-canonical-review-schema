# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for ScholarOne mapper."""

import json
from pathlib import Path

import pytest
from conftest import narrative_fields

from ocrs import map_from, map_to, validate_canonical
from ocrs.mappers.scholarone import from_scholarone, to_scholarone
from ocrs.util import narrative_text

FIXTURES = Path(__file__).parent / "fixtures" / "scholarone"

# Comments to the author, so reviews built to test something else have review content.
TEXT = {"commentsToAuthor": "A summary."}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


def test_scholarone_minimal():
    """Test minimal ScholarOne review conversion."""
    payload = load_fixture("minimal_review.json")
    canon = map_from("scholarone", payload)
    validate_canonical(canon)

    assert canon["provenance"]["source_system"] == "scholarone"
    assert canon["target"]["work_id"] == "internal_id:documentId:DOC-123456"
    assert canon["opinion"]["summary"]
    assert canon["decision"] == {"revision_requirement": "major"}


def test_scholarone_realistic():
    """Test realistic ScholarOne review with all fields."""
    payload = load_fixture("realistic_review.json")
    canon = map_from("scholarone", payload, keep_raw=True)
    validate_canonical(canon)

    # Check basic structure
    assert canon["provenance"]["source_system"] == "scholarone"
    assert canon["provenance"]["raw_payload"] == payload
    assert canon["target"]["work_id"] == "internal_id:documentId:DOC-2024-789012"
    assert canon["target"]["venue"] == "Neurology AI"

    # Check reviewer ID construction
    assert canon["referees"][0]["referee_id"] == "reviewer_2"

    # Check narrative
    assert "narrative" in canon
    assert narrative_text(canon, "review")
    assert narrative_text(canon, audience="editors")

    # Check decision
    assert canon["decision"] == {"revision_requirement": "minor"}

    # Check metrics from criteria responses
    assert len(canon["metrics"]) >= 6
    originality_metric = next((m for m in canon["metrics"] if m["label"] == "Originality"), None)
    assert originality_metric is not None
    assert originality_metric["value"] == 4

    # Check overall metric
    overall_metric = next((m for m in canon["metrics"] if m["key"] == "overall"), None)
    assert overall_metric is not None
    assert overall_metric["value"] == 2


def test_scholarone_recommendation_codes():
    """Test recommendation code mapping."""
    for code, expected in [
        (1, {"recommendation": "accept"}),
        (2, {"revision_requirement": "minor"}),
        (3, {"revision_requirement": "major"}),
        (4, {"recommendation": "reject"}),
        (5, {"revision_requirement": "unspecified"}),
    ]:
        payload = {
            "documentId": f"DOC-{code}",
            "reviewerNumber": 1,
            "overallRecommendation": code,
            "commentsToAuthor": "Test comments.",
        }
        canon = from_scholarone(payload)
        validate_canonical(canon)
        assert canon["decision"] == expected


def test_scholarone_text_recommendation():
    """Test text-based recommendation label parsing."""
    test_cases = [
        ("Accept", {"recommendation": "accept"}),
        ("Minor Revision", {"revision_requirement": "minor"}),
        ("Major Revision", {"revision_requirement": "major"}),
        ("Reject", {"recommendation": "reject"}),
    ]
    for label, expected in test_cases:
        payload = {
            "documentId": f"DOC-{label}",
            "reviewerNumber": 1,
            "overallRecommendationLabel": label,
            "commentsToAuthor": "Test comments.",
        }
        canon = from_scholarone(payload)
        validate_canonical(canon)
        assert canon["decision"] == {**expected, "source_label": label}


def test_scholarone_criteria_normalization():
    """Test that criteria responses are properly normalized."""
    payload = {
        "documentId": "DOC-NORM",
        "reviewerNumber": 1,
        "overallRecommendation": 2,
        "commentsToAuthor": "Good paper.",
        "criteriaResponses": [
            {"criterionName": "Quality", "response": 4, "maxResponse": 5},
            {"criterionName": "Novelty", "response": 8, "maxResponse": 10},
        ],
    }
    canon = from_scholarone(payload)
    validate_canonical(canon)

    # Check normalization
    quality_metric = next((m for m in canon["metrics"] if m["label"] == "Quality"), None)
    assert quality_metric is not None
    # 4 out of 5 should normalize to 0.75
    assert quality_metric["normalized"]["value_0_1"] == 0.75

    novelty_metric = next((m for m in canon["metrics"] if m["label"] == "Novelty"), None)
    assert novelty_metric is not None
    # 8 out of 10 should normalize to ~0.78
    assert 0.77 < novelty_metric["normalized"]["value_0_1"] < 0.79


def test_scholarone_review_id_construction():
    """Test review ID is constructed from document and reviewer number."""
    payload = {
        "documentId": "DOC-123",
        "submissionId": "SUB-456",
        "reviewerNumber": 3,
        "overallRecommendation": 1,
        "commentsToAuthor": "Good paper.",
    }
    canon = from_scholarone(payload)
    validate_canonical(canon)

    # Review ID should include document ID and reviewer number
    assert canon["review_id"] == "s1_DOC-123_r3"
    assert canon["provenance"]["source_review_id"] == "DOC-123_r3"


def test_scholarone_competing_interests():
    """Test competing interests handling."""
    # No conflicts
    payload1 = {
        "documentId": "DOC-COI1",
        "reviewerNumber": 1,
        "overallRecommendation": 1,
        "commentsToAuthor": "Good paper.",
        "competingInterests": "None declared",
    }
    canon1 = from_scholarone(payload1)
    assert canon1["referees"][0]["competing_interests_declared"] is False

    # Has conflicts
    payload2 = {
        "documentId": "DOC-COI2",
        "reviewerNumber": 1,
        "overallRecommendation": 1,
        "commentsToAuthor": "Good paper.",
        "competingInterests": "I have received consulting fees from the authors' institution.",
    }
    canon2 = from_scholarone(payload2)
    assert canon2["referees"][0]["competing_interests_declared"] is True
    assert "consulting fees" in canon2["referees"][0]["competing_interests_statement"]


def test_scholarone_to_and_back():
    """Test roundtrip conversion (lossy)."""
    payload = load_fixture("realistic_review.json")
    canon = map_from("scholarone", payload)
    validate_canonical(canon)

    back = map_to("scholarone", canon)

    # Verify basic structure preserved
    assert back["documentId"] == "DOC-2024-789012"
    assert "commentsToAuthor" in back
    assert back["overallRecommendation"] == 2
    assert back["overallRecommendationLabel"] == "Minor Revision"
    assert "criteriaResponses" in back


def test_scholarone_to_stub():
    """Test basic to_scholarone stub functionality."""
    canon = {
        "review_id": "s1_DOC-TEST_r2",
        "version": "1.0.0",
        "created_at": "2024-12-25T00:00:00Z",
        "provenance": {
            "source_system": "scholarone",
            "source_review_id": "DOC-TEST_r2",
            "imported_at": "2024-12-25T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {
            "work_id": "internal_id:documentId:DOC-TEST",
            "work_type": "article",
            "venue": "Test Journal",
        },
        "opinion": {"summary": "Good paper."},
        "narrative": [
            {"role": "review", "content": "The paper is well written."},
            {"role": "review", "audience": "editors", "content": "No concerns."},
        ],
        "decision": {"recommendation": "accept"},
        "metrics": [
            {
                # The overall score the reader makes of the recommendation's code
                "key": "overall",
                "label": "Overall Recommendation",
                "aspect": "overall",
                "value": 1,
                "scale": {"type": "ordinal", "min": 1, "max": 5},
            },
            {
                "key": "novelty",
                "label": "Originality",
                "aspect": "novelty",
                "value": 4,
                "scale": {"type": "ordinal", "min": 1, "max": 5},
            },
        ],
    }
    back = to_scholarone(canon)

    assert back["documentId"] == "DOC-TEST"
    assert back["reviewerNumber"] == 2
    assert back["journalName"] == "Test Journal"
    assert back["commentsToAuthor"] == "The paper is well written."
    assert back["commentsToEditor"] == "No concerns."
    assert back["overallRecommendation"] == 1
    # The code says the recommendation; a label is written only when the review gave one
    assert "overallRecommendationLabel" not in back
    assert len(back["criteriaResponses"]) == 1
    assert back["criteriaResponses"][0]["criterionName"] == "Originality"


def test_scholarone_reviewer_id_fallbacks():
    """Test reviewer ID falls back to reviewerId, reviewer_id, then reviewerOrcid."""
    for extra, expected in [
        ({"reviewer_number": 7}, "reviewer_7"),
        ({"reviewerId": "R-42"}, "R-42"),
        ({"reviewer_id": 99}, "99"),
        ({"reviewerOrcid": "0000-0002-1825-0097"}, "0000-0002-1825-0097"),
    ]:
        canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1", **extra})
        assert canon["referees"][0]["referee_id"] == expected


def test_scholarone_no_reviewer_id():
    """Test referee_id is omitted when the payload has no reviewer fields."""
    canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1"})
    assert "referee_id" not in canon["referees"][0]
    assert canon["referees"][0]["human_referee"] == {}


def test_scholarone_work_id_fallbacks():
    """Test document ID falls back through the alternative ID keys."""
    for key in ("document_id", "submissionId", "submission_id", "ms_id"):
        canon = map_from("scholarone", {**TEXT, key: "MS-77"})
        assert canon["target"]["identifiers"]["internal_id"] == {
            "field_name": "documentId",
            "value": "MS-77",
        }
        assert canon["target"]["work_id"] == "internal_id:documentId:MS-77"


def test_scholarone_empty_payload():
    """Test an empty payload is refused: a review must say something."""
    with pytest.raises(ValueError, match="has no review content"):
        map_from("scholarone", {})


def test_scholarone_text_only_payload():
    """Test a payload with only comments to the author maps with defaults."""
    canon = map_from("scholarone", TEXT)
    assert canon["target"]["identifiers"] == {}
    assert canon["target"]["work_id"] == "unknown"
    assert canon["opinion"] == {"summary": "A summary."}
    assert canon["metrics"] == []
    assert "decision" not in canon
    assert "competing_interests_declared" not in canon["referees"][0]
    # Random UUID review ID
    assert len(canon["provenance"]["source_review_id"]) == 36
    assert canon["review_id"] == "s1_" + canon["provenance"]["source_review_id"]


def test_scholarone_created_at_keys():
    """Test created_at is read from the alternative date keys."""
    for key in ("dateReviewReceived", "date_review_received", "reviewDate", "created_at"):
        canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1", key: "2024-12-20"})
        assert canon["created_at"] == "2024-12-20T00:00:00Z"


def test_scholarone_doi_identifier():
    """Test a valid DOI becomes the primary identifier; an invalid one is ignored."""
    canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1", "doi": "10.1234/abc.5"})
    assert canon["target"]["identifiers"]["doi"] == {
        "value": "10.1234/abc.5",
        "hyperlink": "https://doi.org/10.1234/abc.5",
    }
    assert canon["target"]["work_id"] == "doi:10.1234/abc.5"

    canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1", "doi": "not-a-doi"})
    assert "doi" not in canon["target"]["identifiers"]
    assert canon["target"]["work_id"] == "internal_id:documentId:DOC-1"


def test_scholarone_human_referee_fields():
    """Test ORCID, name and affiliation populate human_referee."""
    canon = map_from(
        "scholarone",
        {
            **TEXT,
            "documentId": "DOC-1",
            "reviewerOrcid": "https://orcid.org/0000-0002-1825-0097",
            "reviewerName": "Ada Lovelace",
            "reviewerAffiliation": "University of London",
        },
    )
    assert canon["referees"][0]["human_referee"] == {
        "orcid": "0000-0002-1825-0097",
        "name": "Ada Lovelace",
        "affiliation": "University of London",
    }

    # snake_case / short alternative keys
    canon = map_from(
        "scholarone",
        {
            **TEXT,
            "documentId": "DOC-1",
            "orcid": "0000-0002-1825-0097",
            "reviewer_name": "Grace Hopper",
            "affiliation": "Yale",
        },
    )
    assert canon["referees"][0]["human_referee"] == {
        "orcid": "0000-0002-1825-0097",
        "name": "Grace Hopper",
        "affiliation": "Yale",
    }


def test_scholarone_invalid_orcid_dropped():
    """Test an ORCID that does not normalize is left out of human_referee."""
    canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1", "orcid": "1234"})
    assert canon["referees"][0]["human_referee"] == {}


def test_scholarone_review_id_variants():
    """Test review ID from submission ID + reviewer number, and document ID alone."""
    canon = map_from("scholarone", {**TEXT, "submissionId": "SUB-9", "reviewerNumber": 4})
    assert canon["review_id"] == "s1_SUB-9_r4"

    canon = map_from("scholarone", {**TEXT, "documentId": "DOC-9"})
    assert canon["review_id"] == "s1_DOC-9"
    assert canon["provenance"]["source_review_id"] == "DOC-9"


def test_scholarone_narrative_variants():
    """Test narrative uses the first non-blank source and snake_case keys."""
    canon = map_from(
        "scholarone",
        {
            "documentId": "DOC-1",
            "commentsToAuthor": "   ",
            "comments_to_author": "Snake case comments.\n\nSecond paragraph.",
            "comments_to_editor": "For the editor only.",
            "summary": "A short summary.",
        },
    )
    assert narrative_fields(canon) == {
        "detailed_review": "Snake case comments.\n\nSecond paragraph.",
        "confidential_to_editors": "For the editor only.",
        "summary": "A short summary.",
    }
    # Opinion summary is the first paragraph of the first non-blank text
    assert canon["opinion"]["summary"] == "Snake case comments."


def test_scholarone_narrative_first_key_wins():
    """Test commentsToAuthor takes precedence over comments_to_author."""
    canon = map_from(
        "scholarone",
        {"documentId": "DOC-1", "commentsToAuthor": "Camel.", "comments_to_author": "Snake."},
    )
    assert narrative_fields(canon) == {"detailed_review": "Camel."}


def test_scholarone_opinion_from_summary():
    """Test opinion summary falls back to the summary field."""
    canon = map_from("scholarone", {"documentId": "DOC-1", "summary": "Only a summary."})
    assert canon["opinion"]["summary"] == "Only a summary."


def test_scholarone_string_recommendation_code():
    """Test a non-numeric overallRecommendation adds no overall metric."""
    canon = map_from(
        "scholarone",
        {
            "documentId": "DOC-1",
            "overallRecommendation": "Accept",
            "overallRecommendationLabel": "Accept",
        },
    )
    assert canon["decision"] == {"recommendation": "accept", "source_label": "Accept"}
    assert canon["metrics"] == []


def test_scholarone_overall_metric_justification():
    """Test the overall metric is inverted-normalized and carries the label."""
    canon = map_from(
        "scholarone",
        {"documentId": "DOC-1", "overallRecommendation": 1, "overallRecommendationLabel": "Yes"},
    )
    overall = canon["metrics"][0]
    assert overall["key"] == "overall"
    assert overall["value"] == 1
    assert overall["normalized"]["value_0_1"] == 1.0
    assert overall["justification"] == "Yes"


def test_scholarone_criteria_edge_cases():
    """Test criteria parsing: skips, alternative keys, labels and fuzzy matching."""
    payload = {
        "documentId": "DOC-1",
        "criteriaResponses": [
            "not a dict",
            {"criterionName": "Clarity"},  # no response
            {"criterionName": "Clarity", "response": "Excellent"},  # text only
            {"criterionName": "Novelty", "response": "4. Good", "label": "Solid"},
            {"name": "Writing Quality Score", "score": 7, "max_response": 10},
            {"criterionName": "Bananas", "response": 2},
        ],
    }
    canon = map_from("scholarone", payload)
    metrics = {m["label"]: m for m in canon["metrics"]}
    assert list(metrics) == ["Novelty", "Writing Quality Score", "Bananas"]

    novelty = metrics["Novelty"]
    assert novelty["key"] == "novelty"
    assert novelty["aspect"] == "novelty"
    assert novelty["value"] == 4
    assert novelty["justification"] == "Good - Solid"

    writing = metrics["Writing Quality Score"]
    assert writing["key"] == "readability"  # fuzzy alias "writing quality"
    assert writing["aspect"] == "readability"
    assert writing["scale"]["max"] == 10
    assert "justification" not in writing

    other = metrics["Bananas"]
    assert other["key"] == "other"
    assert other["aspect"] == "other"


def test_scholarone_competing_interests_none():
    """Test a bare "None" competing-interests statement is not a declaration."""
    canon = map_from("scholarone", {**TEXT, "documentId": "DOC-1", "competingInterests": "None"})
    assert canon["referees"][0]["competing_interests_declared"] is False
    assert "competing_interests_statement" not in canon["referees"][0]


def _minimal_canonical(**overrides) -> dict:
    """Build a minimal valid canonical review for to_scholarone tests."""
    canon = {
        "review_id": "s1_DOC-X",
        "version": "1.0.0",
        "created_at": "2024-12-25T00:00:00Z",
        "provenance": {
            "source_system": "scholarone",
            "source_review_id": "DOC-X",
            "imported_at": "2024-12-25T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "internal_id:documentId:DOC-X", "work_type": "article"},
        "opinion": {"summary": "Summary text."},
    }
    canon.update(overrides)
    return canon


def test_scholarone_to_minimal():
    """Test to_scholarone on a minimal review omits optional fields."""
    back = map_to("scholarone", _minimal_canonical())
    assert back == {
        "documentId": "DOC-X",
        "dateReviewReceived": "2024-12-25",
        "commentsToAuthor": "Summary text.",
    }


def test_scholarone_to_review_id_without_reviewer_number():
    """Test review IDs without a numeric _r suffix produce no reviewerNumber."""
    for rid in ("DOC-X", "s1_DOC_rough"):
        back = map_to("scholarone", _minimal_canonical(review_id=rid))
        assert "reviewerNumber" not in back
        assert back["documentId"] == "DOC-X"


def test_scholarone_to_review_id_unprefixed_reviewer_number():
    """Test a reviewer number is parsed from a review ID without the s1_ prefix."""
    back = map_to("scholarone", _minimal_canonical(review_id="DOC-X_r3"))
    assert back["reviewerNumber"] == 3


def test_scholarone_to_opinion_text_fallback():
    """Test commentsToAuthor falls back to opinion.text before opinion.summary."""
    canon = _minimal_canonical(opinion={"summary": "Summary text.", "text": "Full opinion."})
    assert map_to("scholarone", canon)["commentsToAuthor"] == "Full opinion."


def test_scholarone_to_decision_variants():
    """Test revision requirements and unmapped recommendations in to_scholarone."""
    # A review from ScholarOne without an overall score had no code: its recommendation came
    # from the label, so the label is written, and reading it gives no score it did not have
    back = map_to("scholarone", _minimal_canonical(decision={"revision_requirement": "minor"}))
    assert "overallRecommendation" not in back
    assert back["overallRecommendationLabel"] == "Minor Revision"
    # From elsewhere the code says it; a label is written only when no code applies
    other = _minimal_canonical(decision={"revision_requirement": "minor"})
    other["provenance"] = {**other["provenance"], "source_system": "openreview"}
    back = map_to("scholarone", other)
    assert back["overallRecommendation"] == 2
    assert "overallRecommendationLabel" not in back

    back = map_to("scholarone", _minimal_canonical(decision={"recommendation": "weak_accept"}))
    assert "overallRecommendation" not in back
    assert back["overallRecommendationLabel"] == "Weak Accept"


def test_scholarone_to_metric_edge_cases():
    """Test non-dict metrics are skipped and maxResponse defaults to 5."""
    canon = _minimal_canonical(
        metrics=[
            "not a dict",
            {"key": "novelty", "aspect": "novelty", "value": 3},
            {"key": "clarity", "label": "Clarity", "value": 7, "scale": "bad"},
        ]
    )
    back = to_scholarone(canon)
    assert back["criteriaResponses"] == [
        {"criterionName": "novelty", "response": 3, "maxResponse": 5},
        {"criterionName": "Clarity", "response": 7, "maxResponse": 5},
    ]


def test_scholarone_to_no_comments():
    """Test commentsToAuthor is omitted when there is no narrative or opinion text."""
    back = to_scholarone(_minimal_canonical(opinion=None))
    assert "commentsToAuthor" not in back


def test_scholarone_code_outside_1_to_5_is_no_recommendation():
    """The codes are lower-is-better; one outside 1-5 is unknown, not accept or reject."""
    for code in (0, 9):
        canon = map_from("scholarone", {**TEXT, "documentId": "D", "overallRecommendation": code})
        assert "decision" not in canon
        assert canon["metrics"] == []


def test_scholarone_unknown_code_falls_back_to_the_label():
    canon = map_from(
        "scholarone",
        {"documentId": "D", "overallRecommendation": 9, "overallRecommendationLabel": "Reject"},
    )
    assert canon["decision"]["recommendation"] == "reject"
    assert canon["metrics"] == []


def test_scholarone_empty_or_short_criterion_names_are_other():
    criteria = [
        {"criterionName": "", "response": 3},
        {"criterionName": "a", "response": 3},
        {"criterionName": "Originality of the work", "response": 0},
    ]
    canon = map_from("scholarone", {"documentId": "D", "criteriaResponses": criteria})
    assert [(m["key"], m["value"]) for m in canon["metrics"]] == [
        ("other", 3),
        ("other", 3),
        ("novelty", 0),
    ]


def test_scholarone_reviewer_number_zero_is_kept():
    canon = map_from("scholarone", {**TEXT, "documentId": "D", "reviewerNumber": 0})
    assert canon["referees"][0]["referee_id"] == "reviewer_0"
    assert canon["review_id"].endswith("D_r0")
    assert map_to("scholarone", canon)["reviewerNumber"] == 0


def test_a_recommendation_ocrs_cannot_name_goes_back_in_its_words():
    payload = {"documentId": "D1", "reviewerNumber": 1, "commentsToAuthor": "Text."}
    payload["overallRecommendationLabel"] = "Needs discussion"
    canon = from_scholarone(payload)
    assert canon["decision"] == {"source_label": "Needs discussion"}
    written = to_scholarone(canon)
    assert written["overallRecommendationLabel"] == "Needs discussion"
    assert "overallRecommendation" not in written
    assert from_scholarone(written)["decision"] == canon["decision"]
