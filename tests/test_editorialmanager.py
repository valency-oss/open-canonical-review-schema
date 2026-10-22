# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for Editorial Manager mapper."""

import json
from pathlib import Path

import pytest
from conftest import codec_map_from, codec_map_to, codec_validate, narrative_fields

from ocrs.mappers.editorialmanager import from_editorialmanager, to_editorialmanager
from ocrs.util import narrative_text

FIXTURES = Path(__file__).parent / "fixtures" / "editorialmanager"

# Comments to the author, so reviews built to test something else have review content.
TEXT = {"commentsToAuthor": "A summary."}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


def test_editorialmanager_minimal():
    """Test minimal Editorial Manager review conversion."""
    payload = load_fixture("minimal_review.json")
    canon = codec_map_from("editorialmanager", payload)
    codec_validate(canon)

    assert canon["provenance"]["source_system"] == "editorialmanager"
    assert canon["target"]["work_id"] == "internal_id:manuscriptId:MS-2024-0042"
    assert canon["opinion"]["summary"]
    assert canon["decision"] == {"revision_requirement": "major", "source_label": "Major Revision"}


def test_editorialmanager_realistic():
    """Test realistic Editorial Manager review with all fields."""
    payload = load_fixture("realistic_review.json")
    canon = codec_map_from("editorialmanager", payload, keep_raw=True)
    codec_validate(canon)

    # Check basic structure
    assert canon["provenance"]["source_system"] == "editorialmanager"
    assert canon["provenance"]["source_review_id"] == "REV-2024-78543"
    assert canon["provenance"]["raw_payload"] == payload
    assert canon["target"]["work_id"] == "internal_id:manuscriptId:MS-2024-001234"
    assert canon["target"]["venue"] == "Journal of Coastal Research"

    # Check narrative
    assert "narrative" in canon
    assert narrative_text(canon, "review")
    assert narrative_text(canon, audience="editors")

    # Check decision
    assert canon["decision"] == {"revision_requirement": "major", "source_label": "Major Revision"}

    # Check round (revisionNumber 0 -> round 1)
    assert canon["review_context"]["round"] == 1

    # Check metrics from ratings
    assert len(canon["metrics"]) == 5
    novelty_metric = next((m for m in canon["metrics"] if m["label"] == "Novelty"), None)
    assert novelty_metric is not None
    assert novelty_metric["value"] == 3


def test_editorialmanager_revision():
    """Test Editorial Manager R2 revision review."""
    payload = load_fixture("realistic_revision.json")
    canon = codec_map_from("editorialmanager", payload)
    codec_validate(canon)

    # Check revision number mapping
    assert canon["review_context"]["round"] == 3  # revisionNumber 2 -> round 3

    # Check recommendation
    assert canon["decision"]["recommendation"] == "accept"

    # Check improved ratings
    methodology_metric = next((m for m in canon["metrics"] if m["label"] == "Methodology"), None)
    assert methodology_metric is not None
    assert methodology_metric["value"] == 5


def test_editorialmanager_recommendation_code():
    """Test recommendation code mapping."""
    for code, expected in [
        (1, {"recommendation": "accept"}),
        (2, {"revision_requirement": "minor"}),
        (3, {"revision_requirement": "major"}),
        (4, {"recommendation": "reject"}),
        (5, {"revision_requirement": "unspecified"}),
    ]:
        payload = {
            "reviewId": f"test_{code}",
            "manuscriptId": "MS-TEST",
            "recommendationCode": code,
            "commentsToAuthor": "Test comments.",
        }
        canon = from_editorialmanager(payload)
        codec_validate(canon)
        assert canon["decision"] == expected


def test_editorialmanager_text_recommendation():
    """Test text-based recommendation parsing."""
    test_cases = [
        ("Accept", {"recommendation": "accept"}),
        ("Minor Revision", {"revision_requirement": "minor"}),
        ("Major Revision", {"revision_requirement": "major"}),
        ("Reject", {"recommendation": "reject"}),
        ("Reject and Encourage Resubmission", {"revision_requirement": "unspecified"}),
    ]
    for text, expected in test_cases:
        payload = {
            "reviewId": f"test_{text}",
            "manuscriptId": "MS-TEST",
            "recommendation": text,
            "commentsToAuthor": "Test comments.",
        }
        canon = from_editorialmanager(payload)
        codec_validate(canon)
        # The recommendation in the source's own words is kept beside OCRS's reading of it
        assert canon["decision"] == {**expected, "source_label": text}


def test_editorialmanager_ratings_normalization():
    """Test that ratings are properly normalized."""
    payload = {
        "reviewId": "test_norm",
        "manuscriptId": "MS-TEST",
        "recommendation": "Accept",
        "commentsToAuthor": "Good paper.",
        "ratings": [
            {"question": "Quality", "score": 4, "maxScore": 5},
            {"question": "Novelty", "score": 8, "maxScore": 10},
        ],
    }
    canon = from_editorialmanager(payload)
    codec_validate(canon)

    # Check normalization
    quality_metric = next((m for m in canon["metrics"] if m["label"] == "Quality"), None)
    assert quality_metric is not None
    # 4 out of 5 should normalize to 0.75
    assert quality_metric["normalized"]["value_0_1"] == 0.75

    novelty_metric = next((m for m in canon["metrics"] if m["label"] == "Novelty"), None)
    assert novelty_metric is not None
    # 8 out of 10 should normalize to ~0.78
    assert 0.77 < novelty_metric["normalized"]["value_0_1"] < 0.79


def test_editorialmanager_to_and_back():
    """Test roundtrip conversion (lossy)."""
    payload = load_fixture("realistic_review.json")
    canon = codec_map_from("editorialmanager", payload)
    codec_validate(canon)

    back = codec_map_to("editorialmanager", canon)

    # Verify basic structure preserved
    assert back["manuscriptId"] == "MS-2024-001234"
    assert "commentsToAuthor" in back
    assert "recommendation" in back
    assert back["revisionNumber"] == 0


def test_editorialmanager_to_stub():
    """Test basic to_editorialmanager stub functionality."""
    canon = {
        "review_id": "em_REV123",
        "version": "1.0.0",
        "created_at": "2024-12-25T00:00:00Z",
        "provenance": {
            "source_system": "editorialmanager",
            "source_review_id": "REV123",
            "imported_at": "2024-12-25T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {
            "work_id": "internal_id:manuscriptId:MS-2024-TEST",
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
                "key": "overall",
                "label": "Overall Quality",
                "aspect": "overall",
                "value": 4,
                "scale": {"type": "ordinal", "min": 1, "max": 5},
            }
        ],
        "review_context": {"round": 2},
    }
    back = to_editorialmanager(canon)

    assert back["reviewId"] == "REV123"
    assert back["manuscriptId"] == "MS-2024-TEST"
    assert back["journalName"] == "Test Journal"
    assert back["commentsToAuthor"] == "The paper is well written."
    assert back["confidentialCommentsToEditor"] == "No concerns."
    assert back["recommendation"] == "Accept"
    assert back["revisionNumber"] == 1
    assert len(back["ratings"]) == 1
    assert back["ratings"][0]["question"] == "Overall Quality"
    assert back["ratings"][0]["score"] == 4


def test_editorialmanager_reviewer_id_fallbacks():
    """Test reviewer ID falls back to reviewer_id, then reviewerEmail."""
    for extra, expected in [
        ({"reviewerId": "R-1"}, "R-1"),
        ({"reviewer_id": 42}, "42"),
        ({"reviewerEmail": "ref@example.org"}, "ref@example.org"),
    ]:
        canon = codec_map_from("editorialmanager", {**TEXT, "manuscriptId": "MS-1", **extra})
        assert canon["referees"][0]["referee_id"] == expected


def test_editorialmanager_work_id_fallbacks():
    """Test manuscript ID falls back through the alternative ID keys."""
    for key in ("manuscript_id", "ms_id", "documentId"):
        canon = codec_map_from("editorialmanager", {**TEXT, key: "MS-77"})
        assert canon["target"]["identifiers"]["internal_id"] == {
            "field_name": "manuscriptId",
            "value": "MS-77",
        }
        assert canon["target"]["work_id"] == "internal_id:manuscriptId:MS-77"


def test_editorialmanager_empty_payload():
    """Test an empty payload is refused: a review must say something."""
    with pytest.raises(ValueError, match="has no review content"):
        codec_map_from("editorialmanager", {})


def test_editorialmanager_text_only_payload():
    """Test a payload with only comments to the author maps with defaults."""
    canon = codec_map_from("editorialmanager", TEXT)
    assert canon["target"]["identifiers"] == {}
    assert canon["target"]["work_id"] == "unknown"
    assert "referee_id" not in canon["referees"][0]
    assert canon["referees"][0]["human_referee"] == {}
    assert canon["opinion"] == {"summary": "A summary."}
    assert canon["metrics"] == []
    assert "decision" not in canon
    assert "review_context" not in canon
    # Random UUID review ID
    assert len(canon["provenance"]["source_review_id"]) == 36
    assert canon["review_id"] == "em_" + canon["provenance"]["source_review_id"]


def test_editorialmanager_created_at_keys():
    """Test created_at is read from the alternative date keys."""
    for key in ("dateReceived", "date_received", "reviewDate", "created_at"):
        canon = codec_map_from(
            "editorialmanager", {**TEXT, "manuscriptId": "MS-1", key: "2024-12-20"}
        )
        assert canon["created_at"] == "2024-12-20T00:00:00Z"


def test_editorialmanager_review_id_fallbacks():
    """Test review ID falls back to review_id, then id."""
    for key in ("review_id", "id"):
        canon = codec_map_from("editorialmanager", {**TEXT, "manuscriptId": "MS-1", key: 501})
        assert canon["review_id"] == "em_501"
        assert canon["provenance"]["source_review_id"] == "501"


def test_editorialmanager_doi_identifier():
    """Test a valid DOI becomes the primary identifier; an invalid one is ignored."""
    canon = codec_map_from(
        "editorialmanager", {**TEXT, "manuscriptId": "MS-1", "doi": "10.1234/abc.5"}
    )
    assert canon["target"]["identifiers"]["doi"] == {
        "value": "10.1234/abc.5",
        "hyperlink": "https://doi.org/10.1234/abc.5",
    }
    assert canon["target"]["work_id"] == "doi:10.1234/abc.5"

    canon = codec_map_from("editorialmanager", {**TEXT, "manuscriptId": "MS-1", "doi": "not-a-doi"})
    assert "doi" not in canon["target"]["identifiers"]
    assert canon["target"]["work_id"] == "internal_id:manuscriptId:MS-1"


def test_editorialmanager_human_referee_fields():
    """Test ORCID, name and affiliation populate human_referee."""
    canon = codec_map_from(
        "editorialmanager",
        {
            **TEXT,
            "manuscriptId": "MS-1",
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
    canon = codec_map_from(
        "editorialmanager",
        {
            **TEXT,
            "manuscriptId": "MS-1",
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


def test_editorialmanager_invalid_orcid_dropped():
    """Test an ORCID that does not normalize is left out of human_referee."""
    canon = codec_map_from("editorialmanager", {**TEXT, "manuscriptId": "MS-1", "orcid": "1234"})
    assert canon["referees"][0]["human_referee"] == {}


def test_editorialmanager_unknown_code_falls_back_to_text():
    """Test an unmapped recommendationCode falls back to the text recommendation."""
    canon = codec_map_from(
        "editorialmanager",
        {"manuscriptId": "MS-1", "recommendationCode": 9, "recommendation": "Reject"},
    )
    assert canon["decision"] == {"recommendation": "reject", "source_label": "Reject"}


def test_editorialmanager_narrative_variants():
    """Test narrative uses the first non-blank source and snake_case keys."""
    canon = codec_map_from(
        "editorialmanager",
        {
            "manuscriptId": "MS-1",
            "commentsToAuthor": "   ",
            "comments_to_author": "Snake case comments.\n\nSecond paragraph.",
            "confidential_comments_to_editor": "For the editor only.",
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


def test_editorialmanager_narrative_first_key_wins():
    """Test commentsToAuthor takes precedence over comments_to_author."""
    canon = codec_map_from(
        "editorialmanager",
        {"manuscriptId": "MS-1", "commentsToAuthor": "Camel.", "comments_to_author": "Snake."},
    )
    assert narrative_fields(canon) == {"detailed_review": "Camel."}


def test_editorialmanager_opinion_from_comments():
    """Test opinion summary falls back to the generic comments field."""
    canon = codec_map_from("editorialmanager", {"manuscriptId": "MS-1", "comments": "Generic."})
    assert canon["opinion"]["summary"] == "Generic."
    # "comments" is not a narrative source
    assert "narrative" not in canon


def test_editorialmanager_ratings_edge_cases():
    """Test ratings parsing: skips, alternative keys, labels and alias matching."""
    payload = {
        "manuscriptId": "MS-1",
        "ratings": [
            "not a dict",
            {"question": "Clarity"},  # no score
            {"question": "Clarity", "score": "Excellent"},  # text only
            {"question": "Originality", "score": "4. Good", "label": "Solid"},
            {"criterionName": "Writing Quality Score", "score": 7, "max_score": 10},
            {"question": "Clarity", "score": 3},
            {"question": "Bananas", "score": 2},
        ],
    }
    canon = codec_map_from("editorialmanager", payload)
    metrics = canon["metrics"]
    assert [m["label"] for m in metrics] == [
        "Originality",
        "Writing Quality Score",
        "Clarity",
        "Bananas",
    ]

    originality = metrics[0]
    assert originality["key"] == "novelty"  # exact alias
    assert originality["aspect"] == "novelty"
    assert originality["value"] == 4
    assert originality["justification"] == "Good - Solid"

    writing = metrics[1]
    assert writing["key"] == "readability"  # fuzzy alias "writing quality"
    assert writing["scale"]["max"] == 10
    assert "justification" not in writing

    clarity = metrics[2]
    assert clarity["key"] == "clarity"  # exact catalog key
    assert clarity["aspect"] == "clarity"

    assert metrics[3]["key"] == "other"
    assert metrics[3]["aspect"] == "other"


def _minimal_canonical(**overrides) -> dict:
    """Build a minimal valid canonical review for to_editorialmanager tests."""
    canon = {
        "review_id": "em_REV-X",
        "version": "1.0.0",
        "created_at": "2024-12-25T00:00:00Z",
        "provenance": {
            "source_system": "editorialmanager",
            "source_review_id": "REV-X",
            "imported_at": "2024-12-25T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "internal_id:manuscriptId:MS-X", "work_type": "article"},
        "opinion": {"summary": "Summary text."},
    }
    canon.update(overrides)
    return canon


def test_editorialmanager_to_minimal():
    """Test to_editorialmanager on a minimal review omits optional fields."""
    back = codec_map_to("editorialmanager", _minimal_canonical())
    assert back == {
        "reviewId": "REV-X",
        "manuscriptId": "MS-X",
        "dateReceived": "2024-12-25",
        "commentsToAuthor": "Summary text.",
    }


def test_editorialmanager_to_unprefixed_review_id():
    """Test a review ID without the em_ prefix is passed through unchanged."""
    back = codec_map_to("editorialmanager", _minimal_canonical(review_id="s1_DOC-1_r2"))
    assert back["reviewId"] == "s1_DOC-1_r2"


def test_editorialmanager_to_opinion_text_fallback():
    """Test commentsToAuthor falls back to opinion.text before opinion.summary."""
    canon = _minimal_canonical(opinion={"summary": "Summary text.", "text": "Full opinion."})
    assert codec_map_to("editorialmanager", canon)["commentsToAuthor"] == "Full opinion."


def test_editorialmanager_to_revision_requirement():
    """Test a revision requirement is written back as a recommendation label."""
    canon = _minimal_canonical(decision={"revision_requirement": "major"})
    assert codec_map_to("editorialmanager", canon)["recommendation"] == "Major Revision"


def test_editorialmanager_to_metric_edge_cases():
    """Test non-dict metrics are skipped and maxScore defaults to 5."""
    canon = _minimal_canonical(
        metrics=[
            "not a dict",
            {"key": "novelty", "aspect": "novelty", "value": 3},
            {"key": "clarity", "label": "Clarity", "value": 7, "scale": "bad"},
        ]
    )
    back = to_editorialmanager(canon)
    assert back["ratings"] == [
        {"question": "novelty", "score": 3, "maxScore": 5},
        {"question": "Clarity", "score": 7, "maxScore": 5},
    ]


def test_editorialmanager_to_no_comments():
    """Test commentsToAuthor is omitted when there is no narrative or opinion text."""
    back = to_editorialmanager(_minimal_canonical(opinion=None))
    assert "commentsToAuthor" not in back


def test_editorialmanager_empty_or_short_questions_are_other():
    ratings = [{"question": "", "score": 3}, {"question": "ab", "score": 3}]
    canon = codec_map_from("editorialmanager", {"manuscriptId": "M", "ratings": ratings})
    assert [m["key"] for m in canon["metrics"]] == ["other", "other"]


def test_a_recommendation_ocrs_cannot_name_goes_back_in_its_words():
    payload = {"documentId": "D1", "reviewerNumber": 1, "recommendation": "Needs discussion"}
    payload["commentsToAuthor"] = "Text."
    canon = from_editorialmanager(payload)
    assert canon["decision"] == {"source_label": "Needs discussion"}
    written = to_editorialmanager(canon)
    assert written["recommendation"] == "Needs discussion"
    assert "recommendationCode" not in written
    assert from_editorialmanager(written)["decision"] == canon["decision"]


def test_a_part_with_the_role_other_is_a_score_sheet_answer():
    canon = from_editorialmanager(
        {"documentId": "D1", "reviewerNumber": 1, "commentsToAuthor": "T."}
    )
    canon["narrative"].append({"role": "other", "title": "Is the data shared?", "content": "Yes."})
    assert to_editorialmanager(canon)["scoreSheetCustomQuestions"] == [
        {"questionText": "Is the data shared?", "scoreSheetCustomAnswer": {"answerText": "Yes."}}
    ]
