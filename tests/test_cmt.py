# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for CMT mapper."""

import json
from pathlib import Path

import pytest
from conftest import narrative_fields

from ocrs import map_from, map_to, validate_canonical
from ocrs.mappers.cmt import from_cmt, to_cmt
from ocrs.util import narrative_text

FIXTURES = Path(__file__).parent / "fixtures" / "cmt"

# A summary, so reviews built to test something else have review content.
TEXT = {"summary": "A summary."}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


def test_cmt_minimal():
    """Test minimal CMT review conversion."""
    payload = load_fixture("minimal_review.json")
    canon = map_from("cmt", payload)
    validate_canonical(canon)

    assert canon["provenance"]["source_system"] == "cmt"
    assert canon["target"]["work_id"] == "internal_id:paperId:42"
    assert canon["opinion"]["summary"]


def test_cmt_realistic():
    """Test realistic CMT review with all fields."""
    payload = load_fixture("realistic_review.json")
    canon = map_from("cmt", payload, keep_raw=True)
    validate_canonical(canon)

    # Check basic structure
    assert canon["provenance"]["source_system"] == "cmt"
    assert canon["provenance"]["source_review_id"] == "ICML2024_Rev_3847"
    assert canon["provenance"]["raw_payload"] == payload
    assert canon["target"]["work_id"] == "internal_id:paperId:2847"
    assert canon["target"]["venue"] == "ICML 2024"
    assert canon["target"]["track"] == "Main Conference"

    # Check narrative
    assert "narrative" in canon
    assert narrative_text(canon, "summary")
    assert narrative_text(canon, "review")
    assert narrative_text(canon, audience="editors")

    # Check decision
    assert "decision" in canon
    assert canon["decision"]["recommendation"] == "weak_accept"

    # Check metrics
    assert len(canon["metrics"]) >= 2
    overall_metric = next((m for m in canon["metrics"] if m["key"] == "overall"), None)
    assert overall_metric is not None
    assert overall_metric["value"] == 6


def test_cmt_identifiers_extraction():
    """Test that target identifiers are properly extracted."""
    payload = {
        "reviewId": "test_id",
        "paperId": 42,
        "doi": "10.1234/test.2024",
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    # Check identifiers are populated
    identifiers = canon["target"]["identifiers"]
    assert identifiers["doi"]["value"] == "10.1234/test.2024"
    assert identifiers["doi"]["hyperlink"] == "https://doi.org/10.1234/test.2024"
    assert identifiers["internal_id"]["field_name"] == "paperId"
    assert identifiers["internal_id"]["value"] == "42"

    # work_id is the primary identifier, so the DOI wins over the CMT paper ID
    assert canon["target"]["work_id"] == "doi:10.1234/test.2024"


def test_cmt_identifiers_without_doi():
    """Test identifier extraction when DOI is not present."""
    payload = {
        "reviewId": "test_id",
        "paperId": 99,
        "overallEvaluation": "4: Accept",
        "commentsToAuthors": "Good paper.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    identifiers = canon["target"]["identifiers"]
    assert "doi" not in identifiers
    assert identifiers["internal_id"]["field_name"] == "paperId"
    assert identifiers["internal_id"]["value"] == "99"


def test_cmt_identifiers_invalid_doi():
    """Test that invalid DOIs are not included in identifiers."""
    payload = {
        "reviewId": "test_id",
        "paperId": 100,
        "doi": "invalid-doi",  # Not a valid DOI format
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    identifiers = canon["target"]["identifiers"]
    assert "doi" not in identifiers
    assert identifiers["internal_id"]["value"] == "100"


def test_cmt_human_referee_orcid():
    """Test ORCID normalization and validation in human referee."""
    payload = {
        "reviewId": "test_id",
        "paperId": 1,
        "reviewerOrcid": "0000-0001-5000-0007",  # Valid ORCID
        "reviewerName": "Dr. Jane Smith",
        "reviewerAffiliation": "MIT",
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    human_referee = canon["referees"][0]["human_referee"]
    assert human_referee["orcid"] == "0000-0001-5000-0007"
    assert human_referee["name"] == "Dr. Jane Smith"
    assert human_referee["affiliation"] == "MIT"


def test_cmt_human_referee_orcid_url_format():
    """Test ORCID normalization from URL format."""
    payload = {
        "reviewId": "test_id",
        "paperId": 1,
        "orcid": "https://orcid.org/0000-0001-5000-0007",  # URL format
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    human_referee = canon["referees"][0]["human_referee"]
    assert human_referee["orcid"] == "0000-0001-5000-0007"


def test_cmt_human_referee_invalid_orcid():
    """Test that invalid ORCIDs are not included."""
    payload = {
        "reviewId": "test_id",
        "paperId": 1,
        "reviewerOrcid": "0000-0001-5000-0008",  # Invalid checksum
        "reviewerName": "Dr. Jane Smith",
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    human_referee = canon["referees"][0]["human_referee"]
    assert "orcid" not in human_referee  # Invalid ORCID should be excluded
    assert human_referee["name"] == "Dr. Jane Smith"


def test_cmt_human_referee_alternative_field_names():
    """Test alternative field names for reviewer identity."""
    payload = {
        "reviewId": "test_id",
        "paperId": 1,
        "reviewer_name": "Prof. John Doe",  # Snake case
        "affiliation": "Stanford University",  # Alternative field name
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    human_referee = canon["referees"][0]["human_referee"]
    assert human_referee["name"] == "Prof. John Doe"
    assert human_referee["affiliation"] == "Stanford University"


def test_cmt_work_id_from_submission_id():
    """Test work_id extraction from submissionId field."""
    payload = {
        "reviewId": "test_id",
        "submissionId": "SUB-2024-001",  # Use submissionId instead of paperId
        "overallEvaluation": "5: Borderline",
        "commentsToAuthors": "Test review.",
    }
    canon = from_cmt(payload)
    validate_canonical(canon)

    assert canon["target"]["work_id"] == "internal_id:paperId:SUB-2024-001"
    assert canon["target"]["identifiers"]["internal_id"]["value"] == "SUB-2024-001"


def test_cmt_to_and_back():
    """Test roundtrip conversion (lossy)."""
    payload = load_fixture("realistic_review.json")
    canon = map_from("cmt", payload)
    validate_canonical(canon)

    back = map_to("cmt", canon)

    # Verify basic structure preserved
    assert back.get("paperId") == 2847  # a number, as CMT gives it
    assert back.get("conferenceName") == "ICML 2024"
    assert "commentsToAuthors" in back or "summary" in back


def test_cmt_to_stub():
    """Test basic to_cmt stub functionality."""
    canon = {
        "review_id": "cmt_123",
        "version": "1.0.0",
        "created_at": "2024-12-25T00:00:00Z",
        "provenance": {
            "source_system": "cmt",
            "source_review_id": "123",
            "imported_at": "2024-12-25T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "internal_id:paperId:42", "work_type": "other"},
        "opinion": {"summary": "Good paper."},
        "narrative": [
            {"role": "summary", "content": "Paper summary here."},
            {"role": "review", "content": "Detailed review text."},
            {"role": "review", "audience": "editors", "content": "Comments to chairs."},
        ],
        "decision": {"recommendation": "accept"},
        "metrics": [{"key": "overall", "aspect": "overall", "value": 4}],
    }
    back = to_cmt(canon)

    assert back["reviewId"] == "cmt_123"
    assert back["paperId"] == 42
    assert back.get("summary") == "Good paper."  # Uses opinion.summary
    assert back.get("commentsToAuthors") == "Detailed review text."
    assert back.get("commentsToChairs") == "Comments to chairs."


def test_cmt_without_paper_id_or_text():
    """Test that a CMT row with no text, recommendation or scores is refused."""
    with pytest.raises(ValueError, match="has no review content"):
        map_from("cmt", {"reviewId": "r1"})


def test_cmt_without_paper_id():
    """Test a CMT row with only a summary: no paper ID, decision or metrics."""
    canon = map_from("cmt", {"reviewId": "r1", "summary": "A summary."})

    assert canon["target"]["identifiers"] == {}
    assert canon["target"]["work_id"] == "unknown"
    assert canon["opinion"] == {"summary": "A summary."}
    assert "decision" not in canon
    assert "referee_id" not in canon["referees"][0]
    assert "raw_payload" not in canon["provenance"]
    assert canon["metrics"] == []


def test_cmt_id_and_created_at_fallbacks():
    """Test the id fallback for the review ID and a non-string createdAt."""
    canon = map_from(
        "cmt", {"id": 7, "paperId": 1, "createdAt": 1735689600, "reviewerId": 99, **TEXT}
    )

    assert canon["review_id"] == "7"
    assert canon["provenance"]["source_review_id"] == "7"
    assert canon["created_at"] != 1735689600
    assert canon["created_at"].endswith("Z")
    assert canon["referees"][0]["referee_id"] == "99"


def test_cmt_review_text_fallback_sets_opinion():
    """Test that reviewText is the detailed review and its first paragraph the opinion."""
    payload = {
        "reviewId": "r1",
        "paperId": 1,
        "reviewText": "  First paragraph.\n\nSecond paragraph.  ",
        "commentsToChairs": " Possible overlap with prior work. ",
    }
    canon = map_from("cmt", payload)

    assert canon["opinion"]["summary"] == "First paragraph."
    assert narrative_fields(canon) == {
        "detailed_review": "First paragraph.\n\nSecond paragraph.",
        "confidential_to_editors": "Possible overlap with prior work.",
    }


def test_cmt_summary_wins_over_review_text_for_opinion():
    """Test that the summary, not the review text, is the opinion when both exist."""
    payload = {"reviewId": "r1", "paperId": 1, "summary": "Short.", "commentsToAuthors": "Long."}
    canon = map_from("cmt", payload)
    assert canon["opinion"]["summary"] == "Short."
    assert narrative_text(canon, "review") == "Long."


def test_cmt_text_recommendation():
    """Test that a text-only recommendation maps without an overall metric."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "recommendation": "Weak Reject"})
    assert canon["decision"] == {"recommendation": "weak_reject", "source_label": "Weak Reject"}
    assert canon["metrics"] == []


def test_cmt_unrecognized_text_recommendation_is_borderline():
    """Test that unmapped recommendation text defaults to borderline."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "recommendation": "Unsure"})
    # The words are kept, though they say no recommendation OCRS knows
    assert canon["decision"] == {"recommendation": "borderline", "source_label": "Unsure"}


def test_cmt_non_text_recommendation_is_ignored():
    """Test that a recommendation that is neither a number nor text adds no decision."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "recommendation": ["Accept"], **TEXT})
    assert "decision" not in canon
    assert canon["metrics"] == []


def test_cmt_recommendation_text_wins_over_number():
    """Test that the label after the score decides the CMT recommendation."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "overallEvaluation": "3: Reject"})
    assert canon["decision"]["recommendation"] == "reject"
    overall = canon["metrics"][0]
    assert overall["value"] == 3
    assert overall["normalized"]["value_0_1"] == 0.5


def test_cmt_bare_number_recommendation():
    """Test that a bare score maps through the numeric rubric."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "overallEvaluation": 9})
    assert canon["decision"]["recommendation"] == "strong_accept"


def test_cmt_unmappable_number_recommendation_is_borderline():
    """Test that a score on an unknown scale is borderline with an unnormalized metric."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "overallEvaluation": 42})
    assert canon["decision"]["recommendation"] == "borderline"
    overall = canon["metrics"][0]
    assert overall["scale"] == {"type": "interval"}
    assert "normalized" not in overall


def test_cmt_revision_recommendation_is_a_revision_requirement():
    """Test that a revision recommendation becomes a revision requirement."""
    payload = {"reviewId": "r1", "paperId": 1, "recommendation": "Major revision"}
    canon = map_from("cmt", payload)
    assert canon["decision"] == {"revision_requirement": "major", "source_label": "Major revision"}


def test_cmt_confidence_ratio():
    """Test that a 0-1 confidence becomes the decision's credence."""
    payload = {"reviewId": "r1", "paperId": 1, "recommendation": "Accept", "confidence": 0.8}
    canon = map_from("cmt", payload)
    assert canon["decision"] == {
        "recommendation": "accept",
        "source_label": "Accept",
        "credence": 0.8,
    }
    conf = canon["metrics"][0]
    assert conf["key"] == "confidence"
    assert conf["scale"] == {"type": "ratio", "min": 0, "max": 1, "step": 0.01}


def test_cmt_non_numeric_confidence_is_ignored():
    """Test that text-only confidence adds neither a metric nor a decision."""
    canon = map_from("cmt", {"reviewId": "r1", "paperId": 1, "confidence": "high", **TEXT})
    assert canon["metrics"] == []
    assert "decision" not in canon


def test_cmt_unbounded_confidence_has_no_decision_confidence():
    """Test that confidence on an unknown scale is kept only as a raw metric."""
    payload = {"reviewId": "r1", "paperId": 1, "recommendation": "Accept", "confidence": 50}
    canon = map_from("cmt", payload)
    assert canon["decision"] == {"recommendation": "accept", "source_label": "Accept"}
    conf = canon["metrics"][0]
    assert conf["value"] == 50
    assert "normalized" not in conf


def test_cmt_extra_metrics():
    """Test that other numeric fields map to catalog or 'other' metrics."""
    payload = {
        "reviewId": "r1",
        "paperId": 1,
        "originality": "4: Good",
        "word_count": 1200,
        "ethicsFlag": "No",
    }
    canon = map_from("cmt", payload)
    by_label = {m["label"]: m for m in canon["metrics"]}

    assert by_label["originality"]["key"] == "novelty"
    assert by_label["originality"]["aspect"] == "novelty"
    assert by_label["originality"]["justification"] == "Good"
    assert by_label["originality"]["normalized"]["value_0_1"] == 0.75
    assert by_label["word count"]["key"] == "other"
    assert by_label["word count"]["aspect"] == "other"
    assert "normalized" not in by_label["word count"]
    assert "ethicsFlag" not in by_label


def cmt_canonical(**fields) -> dict:
    """Build a minimal valid canonical review, overriding top-level fields."""
    canon = {
        "review_id": "cmt_1",
        "version": "1.0.0",
        "created_at": "2025-01-01T00:00:00Z",
        "provenance": {
            "source_system": "cmt",
            "imported_at": "2025-01-01T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "internal_id:paperId:42", "work_type": "other"},
        "opinion": {"summary": "Good paper."},
    }
    canon.update(fields)
    validate_canonical(canon)
    return canon


def test_to_cmt_opinion_text_fallback():
    """Test that opinion text is the comments to authors without a detailed review."""
    canon = cmt_canonical()
    canon["opinion"] = {"text": "Opinion text."}
    back = to_cmt(canon)

    assert back["commentsToAuthors"] == "Opinion text."
    assert "summary" not in back
    assert "recommendation" not in back
    assert "overallEvaluation" not in back
    # What the review does not say is left out, not written as null
    assert "reviewerId" not in back
    assert "conferenceName" not in back


def test_to_cmt_metrics():
    """Test that every score is written, the overall one labelled with the recommendation."""
    scale = {"type": "ordinal", "min": 1, "max": 5}
    canon = cmt_canonical(
        decision={"recommendation": "accept"},
        metrics=[
            {"key": "overall", "label": "Overall", "aspect": "overall", "scale": scale, "value": 4},
            {
                "key": "confidence",
                "label": "Conf",
                "aspect": "confidence",
                "scale": scale,
                "value": 3,
            },
            {"key": "overall", "label": "Again", "aspect": "overall", "scale": scale, "value": 1},
            {"key": "novelty", "label": "Novelty", "aspect": "novelty", "scale": scale, "value": 2},
        ],
    )
    canon["metrics"].insert(0, "not a metric")
    back = to_cmt(canon)

    # The label carries the recommendation, so no separate field repeats it
    assert "recommendation" not in back
    assert back["overallEvaluation"] == "4: Accept"
    assert back["confidence"] == 3
    # A review read from CMT gives its other scores under their own names
    assert back["Novelty"] == 2
    assert map_from("cmt", back)["decision"]["recommendation"] == "accept"


def test_to_cmt_revision_requirement_labels_the_score():
    """Test that a revision requirement is written as the score's label and round-trips."""
    scale = {"type": "ordinal", "min": 1, "max": 10}
    canon = cmt_canonical(
        decision={"revision_requirement": "minor"},
        metrics=[
            {"key": "overall", "label": "Overall", "aspect": "overall", "scale": scale, "value": 6}
        ],
    )
    back = to_cmt(canon)

    assert "recommendation" not in back
    assert back["overallEvaluation"] == "6: Minor Revision"

    again = map_from("cmt", back)
    assert again["decision"] == {"revision_requirement": "minor"}
    assert again["metrics"][0]["value"] == 6


def test_cmt_identifiers_and_dates_are_not_scores():
    """A DOI, an ORCID or a paper ID starts with digits but is never a metric."""
    canon = map_from(
        "cmt",
        {
            "reviewId": "r",
            "paper_id": 3,
            "doi": "10.1234/test.2024",
            "reviewerOrcid": "0000-0001-5000-0007",
            "createdOn_date": "2024-01-02",
            "originality": "4: Good",
        },
    )
    assert [m["label"] for m in canon["metrics"]] == ["originality"]


def test_cmt_a_zero_score_is_a_score():
    canon = map_from("cmt", {"reviewId": 0, "paperId": 1, "overallEvaluation": 0})
    assert canon["review_id"] == "0"
    assert canon["provenance"]["source_review_id"] == "0"
    assert [m["value"] for m in canon["metrics"] if m["key"] == "overall"] == [0]


def test_cmt_booleans_are_not_scores():
    canon = map_from("cmt", {"reviewId": "r", "paperId": 1, "conflict": True, **TEXT})
    assert canon["metrics"] == []


def test_cmt_timestamps_are_not_scores():
    canon = map_from(
        "cmt",
        {
            "reviewId": "r",
            "paperId": 1,
            "timestamp": 1735689600,
            "reviewTime": 1735689600,
            "created_timestamp": 1735689600,
            "valid": 3,
            "format": 4,
        },
    )
    assert [m["label"] for m in canon["metrics"]] == ["valid", "format"]


def test_cmt_field_names_match_aliases_by_whole_words():
    canon = map_from("cmt", {"reviewId": "r", "paperId": 1, "soundness_score": 3, "ab": 2})
    assert [(m["label"], m["key"]) for m in canon["metrics"]] == [
        ("soundness score", "correctness"),
        ("ab", "other"),
    ]


def test_cmt_a_boolean_score_does_not_hide_the_recommendation():
    canon = map_from(
        "cmt",
        {"reviewId": "r", "paperId": 1, "overallEvaluation": False, "recommendation": "Accept"},
    )
    assert canon["decision"]["recommendation"] == "accept"


def test_cmt_ids_and_times_set_off_by_separators_are_not_scores():
    canon = map_from(
        "cmt",
        {"reviewId": "r", "paperId": 1, "paper-id": 5, "Paper ID": 6, "CREATED_AT": 7, "valid": 3},
    )
    assert [m["label"] for m in canon["metrics"]] == ["valid"]


def test_text_for_the_other_reviewers_is_not_sent_to_the_authors():
    canon = map_from("cmt", load_fixture("minimal_review.json"))
    canon["narrative"] = [
        {"role": "review", "audience": "reviewers", "content": "Between us reviewers."},
        {"role": "review", "content": "For the authors."},
    ]
    assert to_cmt(canon)["commentsToAuthors"] == "For the authors."


def test_every_part_that_is_the_review_goes_in_the_comments():
    canon = map_from("cmt", load_fixture("minimal_review.json"))
    canon["narrative"] = [
        {"role": "review", "content": "First report."},
        {"role": "review", "audience": "public", "content": "Second report."},
    ]
    assert to_cmt(canon)["commentsToAuthors"] == "First report.\n\nSecond report."


def test_blank_comments_to_the_authors_give_way_to_the_review_text():
    canon = from_cmt(
        {"reviewId": "r1", "paperId": 1, "commentsToAuthors": "  ", "reviewText": "Sound."}
    )
    assert narrative_text(canon, "review") == "Sound."
    assert canon["opinion"]["summary"] == "Sound."
