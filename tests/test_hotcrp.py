# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for HotCRP mapper."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import narrative_fields

from ocrs import map_from, map_to, validate_canonical
from ocrs.mappers.hotcrp import from_hotcrp, to_hotcrp
from ocrs.util import narrative_text

FIXTURES = Path(__file__).parent / "fixtures" / "hotcrp"

# A summary, so reviews built to test something else have review content.
TEXT = {"summary": "A summary."}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


def test_hotcrp_minimal():
    """Test minimal HotCRP review conversion."""
    payload = load_fixture("minimal_review.json")
    canon = map_from("hotcrp", payload)
    validate_canonical(canon)

    assert canon["provenance"]["source_system"] == "hotcrp"
    assert canon["target"]["work_id"] == "internal_id:hotcrp_pid:42"
    assert canon["opinion"]["summary"]


def test_hotcrp_realistic():
    """Test realistic HotCRP review with all fields."""
    payload = load_fixture("realistic_review.json")
    canon = map_from("hotcrp", payload, keep_raw=True)
    validate_canonical(canon)

    # Check basic structure
    assert canon["provenance"]["source_system"] == "hotcrp"
    assert canon["provenance"]["source_review_id"] == "4527"
    assert canon["provenance"]["raw_payload"] == payload
    assert canon["target"]["work_id"] == "internal_id:hotcrp_pid:183"

    # Check narrative
    assert "narrative" in canon
    assert narrative_text(canon, "summary")
    assert narrative_text(canon, audience="editors")

    # Check findings
    assert "findings" in canon
    assert len(canon["findings"].get("strengths", [])) > 0
    assert len(canon["findings"].get("weaknesses", [])) > 0

    # Check decision
    assert "decision" in canon
    assert canon["decision"]["recommendation"] in (
        "accept",
        "weak_accept",
        "strong_accept",
    )

    # Check metrics
    assert len(canon["metrics"]) >= 2
    overall_metric = next((m for m in canon["metrics"] if m["key"] == "overall"), None)
    assert overall_metric is not None
    assert overall_metric["value"] == 4

    # Check review context (round)
    assert canon.get("review_context", {}).get("round") == 1


def test_hotcrp_strengths_weaknesses_parsing():
    """Test bullet list parsing for strengths/weaknesses."""
    payload = {
        "id": 1,
        "pid": 1,
        "overall_merit": "3. Weak Accept",
        "strengths": "- Point one\n- Point two\n- Point three",
        "weaknesses": "* First issue\n* Second issue",
        "comments": "Some comments here.",
    }
    canon = from_hotcrp(payload)
    validate_canonical(canon)

    assert len(canon["findings"]["strengths"]) == 3
    assert canon["findings"]["strengths"][0]["text"] == "Point one"
    assert len(canon["findings"]["weaknesses"]) == 2
    assert canon["findings"]["weaknesses"][0]["text"] == "First issue"


def test_hotcrp_expertise_mapping():
    """Test reviewer expertise level mapping."""
    payload = {
        "id": 2,
        "pid": 2,
        "overall_merit": "3. Weak Accept",
        "reviewer_expertise": "4. Expert",
        "comments": "Good paper.",
    }
    canon = from_hotcrp(payload)
    validate_canonical(canon)

    # The referee's expertise, as a level
    assert canon["referees"][0]["expertise"]["self_reported_level"] == "expert"

    # And as a metric of its own, apart from confidence
    expertise = next((m for m in canon["metrics"] if m["key"] == "expertise"), None)
    assert expertise is not None
    assert expertise["value"] == 4


def test_hotcrp_round_parsing():
    """Test review round parsing from various formats."""
    for round_val, expected in [
        ("R1", 1),
        ("R2", 2),
        ("main", 1),
        ("Round 2", 2),
        (3, 3),
    ]:
        payload = {
            "id": 3,
            "pid": 3,
            "round": round_val,
            "overall_merit": "3. Weak Accept",
            "comments": "Review comments.",
        }
        canon = from_hotcrp(payload)
        assert canon.get("review_context", {}).get("round") == expected


def test_hotcrp_to_and_back():
    """Test roundtrip conversion (lossy)."""
    payload = load_fixture("realistic_review.json")
    canon = map_from("hotcrp", payload)
    validate_canonical(canon)

    back = map_to("hotcrp", canon)

    # Verify basic structure preserved
    assert back.get("pid") == 183  # a number, as HotCRP gives it
    assert "overall_merit" in back or "comments" in back
    assert "strengths" in back or "weaknesses" in back


def test_hotcrp_additional_metrics():
    """Test that additional numeric fields become metrics."""
    payload = {
        "id": 4,
        "pid": 4,
        "overall_merit": "4. Accept",
        "novelty": "3. Some new ideas",
        "technical_quality": "4. Strong",
        "presentation": "3. Adequate",
        "comments": "The paper is well written.",
    }
    canon = from_hotcrp(payload)
    validate_canonical(canon)

    # Should have overall + 3 additional metrics
    assert len(canon["metrics"]) >= 4
    keys = {m["key"] for m in canon["metrics"]}
    assert "overall" in keys
    assert "novelty" in keys


def test_hotcrp_to_stub():
    """Test basic to_hotcrp stub functionality."""
    canon = {
        "review_id": "hotcrp_123",
        "version": "1.0.0",
        "created_at": "2024-12-25T00:00:00Z",
        "provenance": {
            "source_system": "hotcrp",
            "source_review_id": "123",
            "imported_at": "2024-12-25T00:00:00Z",
            "mapping": {
                "mapping_spec_id": "canonical-review.mapping.v1",
                "mapping_spec_version": "1.1.0",
                "mapper_version": "0.1.0",
            },
        },
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "internal_id:hotcrp_pid:42", "work_type": "article"},
        "opinion": {"summary": "Good paper."},
        "narrative": [
            {"role": "summary", "content": "Paper summary here."},
            {"role": "review", "content": "Detailed review text."},
        ],
        "findings": {
            "strengths": [{"text": "Strong point 1"}, {"text": "Strong point 2"}],
            "weaknesses": [{"text": "Weak point 1"}],
        },
        "decision": {"recommendation": "accept"},
        "metrics": [{"key": "overall", "aspect": "overall", "value": 4}],
        "review_context": {"round": 2},
    }
    back = to_hotcrp(canon)

    assert back["id"] == 123
    assert back["pid"] == 42
    assert back.get("paper_summary") == "Paper summary here."
    assert "strengths" in back
    assert "- Strong point 1" in back["strengths"]
    assert back["round"] == "R2"


def _canon(**overrides) -> dict:
    """Build a minimal canonical review for to_hotcrp tests."""
    canon = {
        "review_id": "hotcrp_7",
        "target": {"work_id": "internal_id:hotcrp_pid:9", "work_type": "article"},
        "opinion": {"summary": "Opinion summary."},
    }
    canon.update(overrides)
    return canon


class TestFromHotcrpTimestamps:
    """Timestamp field fallbacks."""

    def test_time_submitted_epoch(self):
        """timeSubmitted is used when submitted_at is missing."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "timeSubmitted": 1735689600})
        assert canon["created_at"].startswith("2025-01-01T00:00:00")

    def test_cdate_epoch(self):
        """cdate is the last timestamp fallback."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "cdate": 1735689600})
        assert canon["created_at"].startswith("2025-01-01T00:00:00")

    def test_no_timestamp_uses_now(self):
        """Without any timestamp field, created_at is the import time."""
        before = datetime.now(UTC)
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1})
        created = datetime.fromisoformat(canon["created_at"].replace("Z", "+00:00"))
        assert before <= created <= datetime.now(UTC)


class TestFromHotcrpReviewerAndTarget:
    """Reviewer identity, referee and target identifiers."""

    def test_reviewer_dict_skips_non_string_ids(self):
        """A non-string reviewer.user falls through to reviewer.email."""
        canon = map_from(
            "hotcrp", {**TEXT, "id": 1, "pid": 1, "reviewer": {"user": 5, "email": "r@x.org"}}
        )
        assert canon["referees"][0]["referee_id"] == "r@x.org"

    def test_reviewer_dict_without_ids_falls_back_to_top_level(self):
        """With no usable id in reviewer, top-level reviewer_id is used."""
        payload = {**TEXT, "id": 1, "pid": 1, "reviewer": {"name": "Ada"}, "reviewer_id": "rev-9"}
        canon = map_from("hotcrp", payload)
        assert canon["referees"][0]["referee_id"] == "rev-9"
        assert canon["referees"][0]["human_referee"] == {"name": "Ada"}

    def test_reviewer_email_top_level(self):
        """reviewerEmail is used when there is no reviewer object."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "reviewerEmail": "r@x.org"})
        assert canon["referees"][0]["referee_id"] == "r@x.org"

    def test_no_reviewer_id(self):
        """Without any reviewer identifier, referee_id is omitted."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1})
        assert "referee_id" not in canon["referees"][0]
        assert canon["referees"][0]["human_referee"] == {}

    def test_reviewer_identity_fields(self):
        """ORCID, name and affiliation come from the reviewer object."""
        payload = {
            **TEXT,
            "id": 1,
            "pid": 1,
            "reviewer": {
                "email": "ada@x.org",
                "orcid": "0000-0002-1825-0097",
                "name": "Ada Lovelace",
                "affiliation": "Analytical Engines Ltd",
            },
        }
        canon = map_from("hotcrp", payload)
        assert canon["referees"][0]["human_referee"] == {
            "orcid": "0000-0002-1825-0097",
            "name": "Ada Lovelace",
            "affiliation": "Analytical Engines Ltd",
        }

    def test_top_level_orcid_url_is_normalized(self):
        """A top-level reviewerOrcid URL is normalized when reviewer is not a dict."""
        payload = {
            **TEXT,
            "id": 1,
            "pid": 1,
            "reviewer": "anonymous",
            "reviewerOrcid": "https://orcid.org/0000-0002-1825-0097",
        }
        canon = map_from("hotcrp", payload)
        assert canon["referees"][0]["human_referee"] == {"orcid": "0000-0002-1825-0097"}

    def test_invalid_orcid_is_dropped(self):
        """An ORCID that fails normalization is not recorded."""
        payload = {**TEXT, "id": 1, "pid": 1, "reviewer": {"orcid": "not-an-orcid"}}
        canon = map_from("hotcrp", payload)
        assert canon["referees"][0]["human_referee"] == {}

    def test_doi_becomes_primary_identifier(self):
        """A valid DOI is added to identifiers and drives the work_id."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 5, "doi": "10.1145/3290605"})
        idents = canon["target"]["identifiers"]
        assert idents["doi"] == {
            "value": "10.1145/3290605",
            "hyperlink": "https://doi.org/10.1145/3290605",
        }
        assert idents["internal_id"] == {"field_name": "hotcrp_pid", "value": "5"}
        assert canon["target"]["work_id"] == "doi:10.1145/3290605"

    def test_invalid_doi_is_ignored(self):
        """A string that is not a DOI is not added to identifiers."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 5, "doi": "not a doi"})
        assert "doi" not in canon["target"]["identifiers"]
        assert canon["target"]["work_id"] == "internal_id:hotcrp_pid:5"

    def test_submission_id_fallback(self):
        """submission_id is used when pid/paperId/paper_id are missing."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "submission_id": "S-9"})
        assert canon["target"]["work_id"] == "internal_id:hotcrp_pid:S-9"

    def test_no_work_id(self):
        """Without a paper id the work_id is unknown and identifiers are empty."""
        canon = map_from("hotcrp", {**TEXT, "id": 1})
        assert canon["target"]["identifiers"] == {}
        assert canon["target"]["work_id"] == "unknown"

    def test_missing_id_generates_review_id(self):
        """Without an id a UUID review_id is generated and source_review_id is omitted."""
        canon = map_from("hotcrp", {**TEXT, "pid": 1})
        assert canon["review_id"].startswith("hotcrp_")
        assert len(canon["review_id"]) == len("hotcrp_") + 36
        assert "source_review_id" not in canon["provenance"]


class TestFromHotcrpText:
    """Opinion, narrative and findings."""

    def test_no_text_fields(self):
        """Without any text field or score, the review is refused: it says nothing."""
        with pytest.raises(ValueError, match="has no review content"):
            map_from("hotcrp", {"id": 1, "pid": 1})

    def test_no_text_fields_with_a_score(self):
        """With a score but no text, the opinion is absent, not invented."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "overall_merit": 4})
        assert canon["opinion"] == {}
        assert "narrative" not in canon
        assert "findings" not in canon

    def test_first_source_wins_for_each_narrative_field(self):
        """paper_summary beats summary; comments beats detailed_comments."""
        payload = {
            "id": 1,
            "pid": 1,
            "paper_summary": "  The paper summary.  ",
            "summary": "Ignored summary.",
            "detailed_comments": "Detailed comments.",
            "comments_to_pc": "For the PC only.",
            "questions_for_authors": "Why?",
        }
        canon = map_from("hotcrp", payload)
        assert narrative_fields(canon) == {
            "summary": "The paper summary.",
            "detailed_review": "Detailed comments.",
            "confidential_to_editors": "For the PC only.",
            "author_questions": "Why?",
        }
        assert canon["opinion"]["summary"] == "The paper summary."

    def test_detailed_comments_used_for_opinion(self):
        """detailed_comments is the last opinion fallback."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "detailed_comments": "Para 1.\n\nPara 2."})
        assert canon["opinion"]["summary"] == "Para 1."

    def test_list_findings(self):
        """List-valued findings become items; blank entries are dropped."""
        payload = {
            "id": 1,
            "pid": 1,
            "strengths": ["Clear", "  "],
            "weaknesses": [],
            "questions_for_authors": ["What about X?"],
        }
        canon = map_from("hotcrp", payload)
        assert canon["findings"] == {
            "strengths": [{"text": "Clear"}],
            "questions": [{"text": "What about X?"}],
        }

    def test_string_questions_split_into_items(self):
        """A questions string is split on newlines."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "questions": "Q one?\nQ two?"})
        assert canon["findings"]["questions"] == [{"text": "Q one?"}, {"text": "Q two?"}]


class TestFromHotcrpRecommendation:
    """Overall merit parsing into decision and metrics."""

    def test_plain_numeric_overall(self):
        """A bare number maps through the 1-5 scale with no justification."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "overall": 5})
        assert canon["decision"]["recommendation"] == "strong_accept"
        metric = canon["metrics"][0]
        assert metric["key"] == "overall"
        assert metric["value"] == 5
        assert metric["normalized"]["value_0_1"] == 1.0
        assert "justification" not in metric

    def test_numeric_label_without_recommendation_words(self):
        """A label with no recommendation words falls back to the numeric score."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "overall_merit": "1. Terrible"})
        assert canon["decision"]["recommendation"] == "strong_reject"
        assert canon["metrics"][0]["justification"] == "Terrible"

    def test_text_only_recommendation(self):
        """A text-only rating sets the recommendation but no metric."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "recommendation": "Strong Reject"})
        assert canon["decision"] == {
            "recommendation": "strong_reject",
            "source_label": "Strong Reject",
        }
        assert canon["metrics"] == []

    def test_unrecognized_text_is_borderline(self):
        """Unrecognized recommendation text defaults to borderline."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "rating": "Hmm"})
        assert canon["decision"] == {"recommendation": "borderline", "source_label": "Hmm"}

    def test_revision_text_becomes_revision_requirement(self):
        """A revision label is split out of the recommendation."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "score": "Minor revision"})
        assert canon["decision"] == {
            "revision_requirement": "minor",
            "source_label": "Minor revision",
        }

    def test_non_string_non_numeric_rating_is_ignored(self):
        """A rating that is neither text nor a number yields no decision."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "overall_merit": ["4"]})
        assert "decision" not in canon
        assert canon["metrics"] == []

    def test_no_rating(self):
        """Without any rating field there is no decision."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "comments": "Fine."})
        assert "decision" not in canon


class TestFromHotcrpExpertiseAndConfidence:
    """Reviewer expertise and confidence."""

    def test_numeric_expertise_without_label(self):
        """A bare expertise number gives an expertise metric and a level."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "expertise": 2})
        metric = canon["metrics"][0]
        assert metric["key"] == "expertise"
        assert metric["label"] == "Reviewer Expertise"
        assert metric["value"] == 2
        assert "justification" not in metric
        assert canon["referees"][0]["expertise"]["self_reported_level"] == "somewhat_familiar"

    def test_out_of_range_expertise_level_defaults(self):
        """An expertise number off the level map is reported as knowledgeable."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "reviewer_expertise": 7})
        assert canon["referees"][0]["expertise"]["self_reported_level"] == "knowledgeable"

    def test_text_only_expertise_is_ignored(self):
        """Expertise text without a number adds neither a metric nor a level."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "reviewer_expertise": "Expert"})
        assert canon["metrics"] == []
        assert "expertise" not in canon["referees"][0]

    def test_confidence_metric_and_decision_credence(self):
        """A separate confidence field adds a metric and decision.credence."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "confidence": "2. Low"})
        metric = canon["metrics"][0]
        assert metric["key"] == "confidence"
        assert metric["label"] == "Reviewer Confidence"
        assert metric["value"] == 2
        assert metric["justification"] == "Low"
        assert canon["decision"] == {"credence": 0.25}

    def test_numeric_confidence_without_label(self):
        """A bare confidence number has no justification."""
        canon = map_from("hotcrp", {"id": 1, "pid": 1, "confidence": 5})
        assert "justification" not in canon["metrics"][0]
        assert canon["decision"]["credence"] == 1.0

    def test_expertise_and_confidence_are_separate_metrics(self):
        """Expertise and confidence are each a metric of their own; confidence also sets
        decision.credence."""
        payload = {"id": 1, "pid": 1, "reviewer_expertise": "4. Expert", "confidence": 3}
        canon = map_from("hotcrp", payload)
        assert [(m["key"], m["label"]) for m in canon["metrics"]] == [
            ("expertise", "Reviewer Expertise"),
            ("confidence", "Reviewer Confidence"),
        ]
        assert canon["decision"]["credence"] == 0.5

    def test_text_only_confidence_is_ignored(self):
        """Confidence text without a number adds nothing."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "confidence": "High"})
        assert canon["metrics"] == []
        assert "decision" not in canon


class TestFromHotcrpExtraMetrics:
    """Additional numeric fields mapped to catalog metrics."""

    def _metric(self, payload: dict) -> dict:
        canon = map_from("hotcrp", {"id": 1, "pid": 1, **payload})
        assert len(canon["metrics"]) == 1
        return canon["metrics"][0]

    def test_exact_alias(self):
        """An exact catalog alias maps to its metric key and aspect."""
        metric = self._metric({"originality": "4. High"})
        assert (metric["key"], metric["aspect"], metric["label"]) == (
            "novelty",
            "novelty",
            "originality",
        )
        assert metric["justification"] == "High"

    def test_fuzzy_alias(self):
        """A label containing an alias maps to that alias's metric."""
        metric = self._metric({"originality_score": 3})
        assert metric["key"] == "novelty"
        assert metric["label"] == "originality score"
        assert "justification" not in metric

    def test_unknown_label_is_other(self):
        """A label matching nothing in the catalog is 'other'."""
        metric = self._metric({"zzyzx": 2})
        assert (metric["key"], metric["aspect"]) == ("other", "other")

    def test_empty_label_is_other(self):
        """A key that is empty after cleanup maps to 'other'."""
        metric = self._metric({"_": 2})
        assert (metric["key"], metric["aspect"], metric["label"]) == ("other", "other", "")

    def test_out_of_range_value_is_clamped(self):
        """Normalized values are clamped to [0, 1]."""
        metric = self._metric({"clarity": 9})
        assert metric["key"] == "clarity"
        assert metric["normalized"]["value_0_1"] == 1.0

    def test_non_numeric_fields_are_skipped(self):
        """Text fields without a numeric prefix do not become metrics."""
        canon = map_from("hotcrp", {**TEXT, "id": 1, "pid": 1, "topic": "Databases"})
        assert canon["metrics"] == []


class TestFromHotcrpRound:
    """Round parsing edge cases."""

    def test_plain_digit_string(self):
        """A digit string other than '1' is parsed as an int."""
        assert map_from("hotcrp", {**TEXT, "id": 1, "round": "4"})["review_context"] == {"round": 4}

    def test_unparseable_round(self):
        """A round label that is not a number is dropped."""
        assert "review_context" not in map_from("hotcrp", {**TEXT, "id": 1, "round": "final"})

    def test_non_string_round(self):
        """A float round is dropped."""
        assert "review_context" not in map_from("hotcrp", {**TEXT, "id": 1, "round": 2.5})

    def test_round_merges_with_expertise(self):
        """Round goes in review_context, and expertise on the referee."""
        canon = map_from("hotcrp", {"id": 1, "round": "R3", "expertise": 3})
        assert canon["review_context"] == {"round": 3}
        assert canon["referees"][0]["expertise"] == {"self_reported_level": "knowledgeable"}


class TestToHotcrp:
    """Canonical to HotCRP conversion."""

    def test_minimal(self):
        """A minimal record maps the opinion summary to comments only."""
        back = to_hotcrp(_canon())
        assert back == {"id": 7, "pid": 9, "comments": "Opinion summary."}

    def test_non_hotcrp_review_id_kept(self):
        """A review_id without the hotcrp_ prefix is kept as is."""
        assert to_hotcrp(_canon(review_id="other_1"))["id"] == "other_1"

    def test_opinion_text_preferred_over_summary(self):
        """Without a detailed review, opinion.text is used for comments."""
        back = to_hotcrp(_canon(opinion={"summary": "Short.", "text": "Long text."}))
        assert back["comments"] == "Long text."

    def test_no_comments_without_opinion_or_narrative(self):
        """No comments field when there is no text at all."""
        back = to_hotcrp(_canon(opinion=None, narrative=None))
        assert "comments" not in back

    def test_confidential_and_questions(self):
        """Confidential narrative and question findings are mapped."""
        canon = _canon(
            narrative=[{"role": "review", "audience": "editors", "content": "PC only."}],
            findings={
                "questions": [{"text": "Q1"}, {"text": ""}, "bad"],
                "strengths": [],
            },
        )
        back = to_hotcrp(canon)
        assert back["confidential_comments"] == "PC only."
        assert back["questions"] == "- Q1"
        assert "strengths" not in back

    def test_recommendation_without_overall_metric(self):
        """Without an overall metric, overall_merit is the label only."""
        canon = _canon(
            decision={"recommendation": "weak_accept"},
            metrics=[{"key": "novelty", "value": 3}, {"key": "overall", "value": None}],
        )
        assert to_hotcrp(canon)["overall_merit"] == "Weak Accept"

    def test_revision_requirement_maps_to_recommendation(self):
        """A revision requirement becomes the overall_merit label."""
        canon = _canon(
            decision={"revision_requirement": "major"},
            metrics=[{"key": "overall", "value": 2}],
        )
        assert to_hotcrp(canon)["overall_merit"] == "2. Major Revision"

    def test_no_recommendation(self):
        """Without a recommendation, the overall score is written alone."""
        canon = _canon(decision={"credence": 0.5}, metrics=[{"key": "overall", "value": 4}])
        assert to_hotcrp(canon)["overall_merit"] == 4

    def test_expertise_and_confidence_metrics_to_their_fields(self):
        """The first expertise and confidence metrics with a value go to reviewer_expertise
        and confidence."""
        canon = _canon(
            metrics=[
                {"key": "confidence", "value": None},
                {"key": "confidence", "value": 4},
                {"key": "confidence", "value": 2},
                {"key": "expertise", "value": 3},
            ]
        )
        back = to_hotcrp(canon)
        assert back["confidence"] == 4
        assert back["reviewer_expertise"] == 3

    def test_no_round(self):
        """A review_context without a round adds no round field."""
        back = to_hotcrp(_canon(review_context={"expertise": {}}))
        assert "round" not in back

    def test_roundtrip_preserves_scores(self):
        """Scores, expertise and round survive a from/to round trip."""
        payload = {
            "id": 11,
            "pid": 12,
            "overall_merit": "4. Accept",
            "reviewer_expertise": "3. Knowledgeable",
            "round": "R2",
            "comments": "Solid.",
        }
        back = to_hotcrp(from_hotcrp(payload))
        assert back["id"] == 11
        assert back["pid"] == 12
        assert back["overall_merit"] == "4. Accept"
        assert back["reviewer_expertise"] == "3. Knowledgeable"
        assert back["round"] == "R2"
        assert back["comments"] == "Solid."


def test_hotcrp_identifiers_and_dates_are_not_scores():
    canon = map_from(
        "hotcrp",
        {
            "pid": 1,
            "doi": "10.1145/3290605",
            "cdate": 1735689600,
            "created_at": "2024-12-25T00:00:00Z",
            "submission_id": "77",
            "novelty": "4. High",
        },
    )
    assert [m["label"] for m in canon["metrics"]] == ["novelty"]


def test_hotcrp_numeric_contact_id_is_the_referee():
    canon = map_from("hotcrp", {**TEXT, "pid": 1, "contactId": 77})
    assert canon["referees"][0]["referee_id"] == "77"
    assert canon["metrics"] == []


def test_hotcrp_null_finding_items_are_left_out():
    canon = map_from("hotcrp", {"pid": 1, "strengths": ["a", None]})
    assert canon["findings"]["strengths"] == [{"text": "a"}]


def test_hotcrp_a_null_merit_does_not_hide_the_next_score():
    canon = map_from("hotcrp", {"pid": 1, "overall_merit": None, "overall": 4})
    assert canon["decision"]["recommendation"] == "accept"
    assert [m["value"] for m in canon["metrics"] if m["key"] == "overall"] == [4]


def test_hotcrp_keeps_both_question_fields():
    """A form with `questions` and `questions_for_authors` gives both, and gets both back."""
    payload = {
        "id": 1,
        "pid": 2,
        "comments": "Fine.",
        "questions": "- Why this baseline?",
        "questions_for_authors": "- How does it scale?",
    }
    canon = map_from("hotcrp", payload)
    assert [f["text"] for f in canon["findings"]["questions"]] == [
        "Why this baseline?",
        "How does it scale?",
    ]
    back = to_hotcrp(canon)
    assert back["questions"] == "- Why this baseline?"
    assert back["questions_for_authors"] == "- How does it scale?"
    assert map_from("hotcrp", back)["findings"] == canon["findings"]
