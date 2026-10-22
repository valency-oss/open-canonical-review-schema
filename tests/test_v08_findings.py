# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for finding titles and requested changes."""

import pytest
from jsonschema import ValidationError
from v08_schema import validate_canonical


def _review(finding):
    """Create a minimal valid review with one weakness."""
    return _review_with_findings({"weaknesses": [finding]})


def _review_with_findings(findings):
    """Create a minimal valid review with the given findings."""
    return {
        "review_id": "test_finding_001",
        "version": "1.0.0",
        "created_at": "2026-10-05T12:00:00Z",
        "provenance": {"source_system": "test"},
        "referees": [
            {
                "referee_type": "human",
                "identity_mode": "confidential",
                "human_referee": {},
            }
        ],
        "target": {
            "work_id": "internal_id:manuscript_id:paper_123",
            "work_type": "preprint",
            "version": "v2",
        },
        "opinion": {"summary": "Test review."},
        "findings": findings,
    }


def test_finding_without_title():
    validate_canonical(_review({"text": "Missing ablation."}))


def test_title():
    validate_canonical(_review({"title": "No ablation", "text": "Missing ablation."}))


def test_empty_title_is_rejected():
    with pytest.raises(ValidationError):
        validate_canonical(_review({"title": "", "text": "Missing ablation."}))


@pytest.mark.parametrize("severity", ["info", "trivial", "minor", "major", "critical"])
def test_change_severity(severity):
    change = {"text": "Fix the proof of Lemma 2.", "severity": severity}
    validate_canonical(_review_with_findings({"changes": [change]}))


@pytest.mark.parametrize(
    "change",
    [
        # Before 0.6, a change's priority was low to blocking; before 0.8, it had a priority
        {"text": "Fix the proof of Lemma 2.", "severity": "blocking"},
        {"text": "Fix the proof of Lemma 2.", "priority": "major"},
    ],
)
def test_old_priorities_are_rejected(change):
    with pytest.raises(ValidationError):
        validate_canonical(_review_with_findings({"changes": [change]}))


@pytest.mark.parametrize("old_name", ["required_changes", "optional_suggestions"])
def test_required_and_optional_changes_are_rejected(old_name):
    with pytest.raises(ValidationError):
        validate_canonical(_review_with_findings({old_name: [{"text": "Add an ablation."}]}))
