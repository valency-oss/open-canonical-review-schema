# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the journal narrative mapper."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import codec_map_from, codec_map_to, narrative_fields

from ocrs.mappers.journal import to_journal_narrative
from ocrs.util import narrative_text

FIXTURES = Path(__file__).parent / "fixtures" / "journal"

# Review text, so reviews built to test something else have review content.
TEXT = {"full_text": "A review."}


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES / name).read_text())


class TestFromJournalNarrative:
    """Journal narrative to canonical conversion."""

    def test_minimal_fixture(self):
        """The fixture maps DOI, venue, opinion and narrative."""
        payload = load_fixture("minimal_review.json")
        canon = codec_map_from("journal_narrative", payload)
        assert canon["provenance"]["source_system"] == "journal_narrative"
        assert canon["target"]["work_id"] == "doi:10.5555/12345678"
        assert canon["target"]["venue"] == "Journal of Tests"
        assert canon["opinion"]["summary"] == (
            "This manuscript addresses an important problem. The methods are plausible but unclear."
        )
        assert narrative_text(canon, "review") == payload["full_text"]
        assert "referee_id" not in canon["referees"][0]
        assert "raw_payload" not in canon["provenance"]

    def test_full_payload(self):
        """IDs, reviewer, timestamps and raw payload are carried over."""
        payload = {
            "review_id": "rev-1",
            "source_review_id": "src-1",
            "reviewer_id": "referee-2",
            "created_at": "2024-03-01T12:00:00Z",
            "manuscript_id": "MS-2024-001",
            "venue": "Example Letters",
            "full_text": "  Short review.  ",
        }
        canon = codec_map_from("journal_narrative", payload, keep_raw=True)
        assert canon["review_id"] == "rev-1"
        assert canon["created_at"] == "2024-03-01T12:00:00Z"
        assert canon["provenance"]["source_review_id"] == "src-1"
        assert canon["provenance"]["raw_payload"] == payload
        assert canon["referees"][0]["referee_id"] == "referee-2"
        assert canon["target"]["identifiers"] == {
            "internal_id": {"field_name": "manuscript_id", "value": "MS-2024-001"}
        }
        assert canon["target"]["work_id"] == "internal_id:manuscript_id:MS-2024-001"
        assert canon["target"]["venue"] == "Example Letters"
        assert narrative_fields(canon) == {"detailed_review": "Short review."}

    def test_id_fallback(self):
        """id is used for review_id and source_review_id when they are missing."""
        canon = codec_map_from("journal_narrative", {**TEXT, "id": 42, "journal": "J"})
        assert canon["review_id"] == "42"
        assert canon["provenance"]["source_review_id"] == "42"

    def test_no_ids_generates_review_id(self):
        """Without any id a UUID review_id is generated."""
        canon = codec_map_from("journal_narrative", {**TEXT, "journal": "J"})
        assert len(canon["review_id"]) == 36
        assert canon["provenance"]["source_review_id"] == ""

    def test_work_id_fallback_and_invalid_doi(self):
        """An invalid DOI is ignored and a non-string work_id becomes internal_id."""
        canon = codec_map_from(
            "journal_narrative", {**TEXT, "doi": "nope", "work_id": 17, "journal": "J"}
        )
        assert canon["target"]["identifiers"] == {
            "internal_id": {"field_name": "work_id", "value": "17"}
        }
        assert canon["target"]["work_id"] == "internal_id:work_id:17"

    def test_no_identifiers(self):
        """Without DOI, manuscript_id or work_id the work is unknown."""
        canon = codec_map_from("journal_narrative", {**TEXT, "journal": "J"})
        assert canon["target"]["identifiers"] == {}
        assert canon["target"]["work_id"] == "unknown"

    def test_blank_text_and_non_string_fields(self):
        """Blank text is no review content, so the review is refused."""
        with pytest.raises(ValueError, match="has no review content"):
            codec_map_from(
                "journal_narrative",
                {"journal": "J", "created_at": 1700000000, "full_text": "  \n  "},
            )

    def test_non_string_created_at_is_replaced(self):
        """A non-string created_at is replaced with the import time."""
        before = datetime.now(UTC)
        canon = codec_map_from(
            "journal_narrative", {**TEXT, "journal": "J", "created_at": 1700000000}
        )
        created = datetime.fromisoformat(canon["created_at"].replace("Z", "+00:00"))
        assert before <= created <= datetime.now(UTC)

    def test_non_string_full_text_ignored(self):
        """A non-string full_text is treated as empty, so the review is refused."""
        with pytest.raises(ValueError, match="has no review content"):
            codec_map_from("journal_narrative", {"journal": "J", "full_text": ["a"]})


class TestToJournalNarrative:
    """Canonical to journal narrative conversion."""

    def test_doi_from_canonical_work_id(self):
        """Without identifiers, the DOI is read from a doi work_id."""
        canon = {"review_id": "r1", "target": {"work_id": "doi:10.1234/abc", "venue": "J"}}
        back = to_journal_narrative(canon)
        assert back["doi"] == "10.1234/abc"
        assert back["journal"] == "J"
        assert back["review_id"] == "r1"

    def test_no_doi_for_internal_work_id(self):
        """A non-DOI work_id gives no DOI."""
        canon = {"target": {"work_id": "internal_id:manuscript_id:MS-1"}}
        assert to_journal_narrative(canon)["doi"] is None

    def test_no_doi_for_non_canonical_work_id(self):
        """A work_id that is not canonical gives no DOI."""
        assert to_journal_narrative({"target": {"work_id": "legacy-id"}})["doi"] is None

    def test_detailed_review_preferred(self):
        """narrative.detailed_review is used as full_text, stripped."""
        canon = {
            "created_at": "2024-03-01T12:00:00Z",
            "narrative": [{"role": "review", "content": "  Detail.  "}],
            "opinion": {"text": "Opinion text.", "summary": "Summary."},
        }
        back = to_journal_narrative(canon)
        assert back["full_text"] == "Detail."
        assert back["created_at"] == "2024-03-01T12:00:00Z"

    def test_opinion_text_fallback(self):
        """opinion.text is used when the detailed review is blank."""
        canon = {
            "narrative": [{"role": "review", "content": "   "}],
            "opinion": {"text": " Opinion text. ", "summary": "Summary."},
        }
        assert to_journal_narrative(canon)["full_text"] == "Opinion text."

    def test_opinion_summary_fallback(self):
        """opinion.summary is used when there is no opinion text."""
        canon = {"narrative": None, "opinion": {"text": "  ", "summary": "Summary."}}
        assert to_journal_narrative(canon)["full_text"] == "Summary."

    def test_no_text(self):
        """With no text anywhere, full_text is empty and other fields are None."""
        back = to_journal_narrative({"opinion": None})
        assert back == {
            "doi": None,
            "journal": None,
            "review_id": None,
            "created_at": None,
            "full_text": "",
        }

    def test_roundtrip(self):
        """DOI, venue, review_id and text survive a from/to round trip."""
        payload = load_fixture("minimal_review.json") | {"review_id": "rt-1"}
        back = codec_map_to("journal_narrative", codec_map_from("journal_narrative", payload))
        assert back["doi"] == payload["doi"]
        assert back["journal"] == payload["journal"]
        assert back["review_id"] == "rt-1"
        assert back["full_text"] == payload["full_text"]


def test_without_a_journal_there_is_no_venue():
    canon = codec_map_from("journal_narrative", {"doi": "10.1234/abc", "full_text": "Fine."})
    assert "venue" not in canon["target"]


def test_a_numeric_reviewer_id_is_kept_as_text():
    canon = codec_map_from(
        "journal_narrative", {"journal": "J", "reviewer_id": 5, "full_text": "Ok."}
    )
    assert canon["referees"][0]["referee_id"] == "5"
