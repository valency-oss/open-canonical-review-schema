# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Acceptance and revision are independent, including through source mappers."""

import jsonschema
import pytest

from ocrs import map_from, map_to, validate_canonical


@pytest.fixture
def review():
    return {
        "review_id": "review-1",
        "version": "1.0.0",
        "created_at": "2026-10-12T12:00:00Z",
        "provenance": {"source_system": "example-journal"},
        "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
        "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
        "opinion": {"summary": "A sound paper."},
    }


@pytest.mark.parametrize("revision", [None, "none", "minor", "major", "unspecified"])
def test_acceptance_and_revision_are_independent(review, revision):
    review["decision"] = {"recommendation": "weak_accept"}
    if revision is not None:
        review["decision"]["revision_requirement"] = revision
    validate_canonical(review)
    if revision is not None:
        review["decision"].pop("recommendation")
        validate_canonical(review)


@pytest.mark.parametrize("recommendation", ["revise", "minor_revision", "major_revision"])
def test_revision_is_no_longer_an_acceptance_recommendation(review, recommendation):
    review["decision"] = {"recommendation": recommendation}
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(review)


@pytest.mark.parametrize("revision", ["no_revision", "unknown", "minor_revision", False])
def test_invalid_revision_requirement_is_rejected(review, revision):
    review["decision"] = {"revision_requirement": revision}
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(review)


@pytest.mark.parametrize(
    "system,field",
    [
        ("scholarone", "overallRecommendationLabel"),
        ("editorialmanager", "recommendation"),
        ("hotcrp", "overall_merit"),
        ("openreview", "recommendation"),
        ("cmt", "recommendation"),
    ],
)
@pytest.mark.parametrize(
    "label,revision",
    [("Minor Revision", "minor"), ("Major Revision", "major"), ("Revise", "unspecified")],
)
def test_revision_only_decisions_roundtrip(system, field, label, revision):
    payload = {field: label}
    if system == "openreview":
        payload = {"content": payload}
    canonical = map_from(system, payload)
    validate_canonical(canonical)
    assert canonical["decision"] == {"revision_requirement": revision, "source_label": label}
    restored = map_from(system, map_to(system, canonical))
    validate_canonical(restored)
    assert restored["decision"] == canonical["decision"]


@pytest.mark.parametrize(
    "system", ["scholarone", "editorialmanager", "hotcrp", "openreview", "cmt"]
)
def test_single_field_export_prioritizes_requested_revision(review, system):
    review["decision"] = {"recommendation": "weak_accept", "revision_requirement": "minor"}
    review["metrics"] = [
        {
            "key": "overall",
            "label": "Overall",
            "scale": {"type": "ordinal", "min": 1, "max": 5},
            "value": 4,
        }
    ]
    restored = map_from(system, map_to(system, review))
    assert restored["decision"]["revision_requirement"] == "minor"


@pytest.mark.parametrize(
    "system", ["scholarone", "editorialmanager", "hotcrp", "openreview", "cmt"]
)
def test_no_revision_export_retains_acceptance(review, system):
    review["decision"] = {"recommendation": "accept", "revision_requirement": "none"}
    restored = map_from(system, map_to(system, review))
    assert restored["decision"]["recommendation"] == "accept"
