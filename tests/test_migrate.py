# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Reviews written for OCRS 0.7 migrate to 0.8 and mean the same thing.

The reviews are those `test_schema_restatement` builds to compare 0.7.1 with 0.7.2: the
examples and the README blocks as 0.7 had them, and every review one edit away from small
reviews that use the content rule's every branch, work identifiers, the AI referee,
probability and credence, and expertise. Every one 0.7.2 accepts must migrate to a review 0.8
accepts. (The reviews are compared by their JSON Schemas: some break a rule only
`validate_canonical` states, such as a contribution naming a claim the review lacks, which 0.7
rejected too.)
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_schema_restatement import BASES, one_edit_away

from ocrs import load_schema, validate_canonical
from ocrs.migrate import migrate
from ocrs.schema import has_content
from ocrs.util import narrative_text

ROOT = Path(__file__).parent.parent
V072 = json.loads((ROOT / "versions/v0.7.2/canonical-review.schema.json").read_text())


@pytest.fixture(scope="module")
def reviews_valid_in_072():
    validator = Draft202012Validator(V072)
    reviews = [r for base, roots in BASES for r in (base, *one_edit_away(base, roots))]
    return [r for r in reviews if validator.is_valid(r)]


def test_every_072_review_migrates_to_a_valid_080_review(reviews_valid_in_072):
    assert len(reviews_valid_in_072) > 300
    current = Draft202012Validator(load_schema())
    for review in reviews_valid_in_072:
        migrated = migrate(review)
        current.validate(migrated)
        # A review with content still has it, and migrating again changes nothing
        assert has_content(migrated)
        assert migrate(migrated) == migrated


def test_the_review_given_is_not_changed(reviews_valid_in_072):
    for review in reviews_valid_in_072[:50]:
        before = json.dumps(review, sort_keys=True)
        migrate(review)
        assert json.dumps(review, sort_keys=True) == before


REVIEW_07 = {
    "review_id": "r1",
    "version": "1.0.0",
    "created_at": "2026-10-06T12:00:00Z",
    "provenance": {"source_system": "example-journal"},
    "referee": {
        "referee_type": "human",
        "identity_mode": "double_blind",
        "human_referee": {"expertise": {"self_reported_level": "expert"}},
    },
    "target": {"work_id": "internal_id:manuscript_id:p1", "work_type": "article"},
    "opinion": {"contributions": [{"text": "A method.", "claim_id": "c1"}]},
    "claim_assessments": [{"claim_id": "c1", "claim_text": "It is faster.", "status": "supported"}],
    "decision": {"recommendation": "accept", "confidence": 0.7},
    "findings": {
        "weaknesses": [{"id": "w1", "text": "No ablation."}],
        "changes": [
            {
                "text": "Add an ablation.",
                "priority": "major",
                "applies_to": {"section": "4.2", "finding_id": "w1", "claim_id": "c1"},
            }
        ],
    },
    "ethics_and_risk": {
        "ethical_concerns": True,
        "required_mitigations": [{"text": "Describe consent.", "priority": "minor"}],
    },
    "narrative": {
        "summary": "Summary.",
        "detailed_review": "The review.",
        "confidential_to_editors": "For the editors.",
        "sections": [{"title": "Limitations", "content": "Yes."}],
    },
}


def test_a_072_review_migrates_field_by_field():
    review = migrate(REVIEW_07)
    validate_canonical(review)
    [referee] = review["referees"]
    assert referee["expertise"] == {"self_reported_level": "expert"}
    assert "expertise" not in referee["human_referee"]
    assert review["decision"] == {"recommendation": "accept", "credence": 0.7}
    assert review["opinion"]["contributions"] == [{"text": "A method.", "claim_ids": ["c1"]}]
    change, mitigation = review["findings"]["changes"]
    assert change == {
        "text": "Add an ablation.",
        "severity": "major",
        "evidence_links": [{"type": "paper_section", "ref": "4.2"}],
        "claim_ids": ["c1"],
        "addresses": ["w1"],
    }
    assert mitigation == {"text": "Describe consent.", "severity": "minor", "scope": "ethics"}
    assert review["ethics_and_risk"] == {"ethical_concerns": True}
    assert narrative_text(review, "summary") == "Summary."
    assert narrative_text(review, "review") == "The review."
    assert narrative_text(review, audience="editors") == "For the editors."
    assert review["narrative"][-1] == {"title": "Limitations", "content": "Yes."}


def test_review_context_expertise_moves_onto_each_referee():
    review = {
        **REVIEW_07,
        "referee": {"referee_type": "human", "identity_mode": "open"},
        "review_context": {"expertise": {"self_reported_level": "knowledgeable"}},
    }
    migrated = migrate(review)
    assert migrated["referees"][0]["expertise"] == {"self_reported_level": "knowledgeable"}
    assert "review_context" not in migrated


def test_a_hotcrp_expertise_scored_as_a_confidence_is_an_expertise():
    from ocrs import map_to

    expertise = {
        "key": "confidence",
        "label": "Reviewer Expertise",
        "aspect": "confidence",
        "scale": {"type": "ordinal", "min": 1, "max": 4},
        "value": 3,
    }
    review = {
        **REVIEW_07,
        "provenance": {"source_system": "hotcrp"},
        "metric_catalog_ref": "metric-catalog.core.v1",
        "metrics": [expertise, {**expertise, "label": "Reviewer Confidence"}],
    }
    migrated = migrate(review)
    validate_canonical(migrated)
    assert migrated["metric_catalog_ref"] == "metric-catalog.core.v1.1"
    assert [(m["key"], m["aspect"]) for m in migrated["metrics"]] == [
        ("expertise", "expertise"),
        ("confidence", "confidence"),
    ]
    written = map_to("hotcrp", migrated)
    assert written["reviewer_expertise"] == 3
    assert written["confidence"] == 3


def test_a_mitigation_with_another_scope_is_still_an_ethics_change():
    review = {
        **REVIEW_07,
        "ethics_and_risk": {
            "required_mitigations": [{"text": "Rerun with consent.", "scope": "experiment"}]
        },
    }
    [_, mitigation] = migrate(review)["findings"]["changes"]
    assert mitigation == {"text": "Rerun with consent.", "scope": "experiment", "tags": ["ethics"]}


def test_a_jats_review_keeps_its_license():
    from ocrs import map_to

    license_ = {"url": "https://creativecommons.org/licenses/by/4.0/", "text": "CC BY"}
    review = {
        **REVIEW_07,
        "provenance": {"source_system": "jats"},
        "extensions": {"jats": {"permissions": {"licenses": [license_]}}},
    }
    migrated = migrate(review)
    assert migrated["provenance"]["license"] == {"url": license_["url"]}
    assert (
        'href="https://creativecommons.org/licenses/by/4.0/"'
        in map_to("jats", migrated)["sub_article"]
    )
