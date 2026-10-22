# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Regression cases found while reviewing the 0.9 fixes stack."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import ValidationError
from test_09_candidate import candidate, validate_part
from test_hierarchy import legacy, linked_record
from test_roundtrip import AI_RUN, frozen_clock, load  # noqa: F401
from v08_schema import validate_canonical as validate_08

from ocrs import map_from, map_to, validate_canonical
from ocrs.hierarchy import legacy_view
from ocrs.migrate import migrate

ROOT = Path(__file__).parents[1]
DIMENSIONS_08 = (
    "correctness",
    "rigor",
    "clarity",
    "readability",
    "novelty",
    "significance",
    "impact",
    "reproducibility",
    "methodology",
    "evaluation",
    "writing",
    "presentation",
    "ethics",
    "overall",
    "confidence",
    "expertise",
    "other",
)


@pytest.mark.parametrize("dimension", (*DIMENSIONS_08, "review_confidence"))
def test_metric_dimensions_keep_the_closed_vocabulary_with_review_confidence(dimension):
    validate_part(
        "metricDefinition",
        {"label": "Source criterion", "dimension": dimension, "scale": {"type": "ordinal"}},
    )
    assert set(candidate()["$defs"]["metricDefinition"]["properties"]["dimension"]["enum"]) == {
        *DIMENSIONS_08,
        "review_confidence",
    }


@pytest.mark.parametrize("dimension", ("made_up", "custom:criterion", "reviewer_confidence"))
def test_metric_dimensions_reject_unlisted_values(dimension):
    with pytest.raises(ValidationError):
        validate_part(
            "metricDefinition",
            {"label": "Original criterion", "dimension": dimension, "scale": {"type": "ordinal"}},
        )


def test_deleting_a_migrated_text_only_summary_does_not_break_export():
    review = migrate(
        legacy(opinion={"text": "Original opinion."}, findings={"comments": [{"text": "A point."}]})
    )
    review["opinion"].pop("summary")
    validate_canonical(review)
    projected = legacy_view(review)
    assert "text" not in projected["opinion"]
    map_to("journal_narrative", review)


def test_repeated_legacy_reasons_keep_the_source_list_but_deduplicate_support_links():
    review = migrate(legacy(opinion={"high_level_reasons": ["A reason.", "A reason."]}))
    validate_canonical(review)
    assert len(review["opinion"]["supported_by"]) == 1
    assert legacy_view(review)["opinion"]["high_level_reasons"] == ["A reason.", "A reason."]


@pytest.mark.parametrize("location", ("finding", "claim", "contribution", "check"))
def test_explicit_legacy_schema_checks_ranges_in_all_its_evidence_locations(location):
    link = {"type": "paper_section", "ref": "Methods", "location": {"page": 5, "page_end": 2}}
    content = {
        "finding": {"findings": {"comments": [{"text": "A point.", "evidence_links": [link]}]}},
        "claim": {
            "claim_assessments": [
                {
                    "claim_id": "c1",
                    "claim_text": "A claim.",
                    "status": "supported",
                    "evidence_links": [link],
                }
            ]
        },
        "contribution": {
            "opinion": {"contributions": [{"text": "A method.", "evidence_links": [link]}]}
        },
        "check": {
            "checks": [
                {"kind": "reference_verification", "items": [{"target": link, "status": "found"}]}
            ]
        },
    }[location]
    # Construct a structurally valid legacy record, then reverse its page range.
    from test_hierarchy import record

    review = record(**content)
    review["$schema"] = review["$schema"].replace("v0.9.0", "v0.8.0")
    with pytest.raises(ValidationError, match="page_end"):
        validate_canonical(
            review, schema_path=ROOT / "versions/v0.8.0/canonical-review.schema.json"
        )


def test_deleting_an_ethics_finding_does_not_resurrect_its_old_assessment():
    review = migrate(
        legacy(
            opinion={"summary": "Summary."},
            ethics_and_risk={"ethical_concerns": True, "notes": "Consent missing."},
        )
    )
    del review["findings"]
    validate_canonical(review)
    assert "ethics_and_risk" not in legacy_view(review)


def test_deleting_a_claim_assessment_finding_removes_its_old_verdict():
    review = migrate(
        legacy(
            claim_assessments=[
                {
                    "claim_id": "c1",
                    "claim_text": "The model generalizes.",
                    "status": "supported",
                    "notes": "Confirmed in tests.",
                }
            ]
        )
    )
    del review["findings"]
    validate_canonical(review)
    claim = legacy_view(review)["claim_assessments"][0]
    assert claim["status"] == "not_evaluated"
    assert "notes" not in claim


def artifact_review():
    return migrate(
        legacy(
            opinion={"summary": "Summary."},
            artifact_assessments=[
                {
                    "artifact_type": "code",
                    "availability": "public",
                    "assessment": "adequate",
                    "checks": [{"key": "runs", "status": "pass"}],
                }
            ],
        )
    )


def test_deleting_an_artifact_assessment_finding_removes_its_old_verdict():
    review = artifact_review()
    del review["findings"]
    validate_canonical(review)
    assert legacy_view(review)["artifact_assessments"][0]["assessment"] == "not_evaluated"


@pytest.mark.parametrize("data", ({"observed_accuracy": 0.9}, {"measurements": 123}))
@pytest.mark.parametrize("status", (None, "pass"))
def test_a_raw_artifact_result_exports_without_inventing_a_verdict_or_losing_data(data, status):
    review = artifact_review()
    result = review["checks"][0]["results"][0]
    if status is None:
        result.pop("status")
    else:
        result["status"] = status
    result["data"] = data
    validate_canonical(review)
    view = legacy_view(review)
    assert "checks" not in view["artifact_assessments"][0]
    check = view["checks"][0]
    text = check["summary"] if status is None else check["items"][0]["notes"]
    assert next(iter(data)) in text
    validate_08(view)


def test_additional_artifact_results_survive_projection():
    review = artifact_review()
    review["checks"][0]["results"].append({"id": "new-result", "data": {"accuracy": 0.9}})
    validate_canonical(review)
    view = legacy_view(review)
    assert view["checks"][0]["items"][0]["status"] == "pass"
    assert "accuracy" in view["checks"][0]["summary"]
    validate_08(view)


def test_generated_ids_remain_on_findings_that_a_new_change_addresses():
    review = migrate(legacy(findings={"weaknesses": [{"text": "The proof is missing."}]}))
    id = review["findings"]["weaknesses"][0]["id"]
    review["findings"]["changes"] = [
        {"id": "new-change", "text": "Add the proof.", "addresses": [id]}
    ]
    validate_canonical(review)
    view = legacy_view(review)
    assert view["findings"]["weaknesses"][0]["id"] == id
    validate_08(view)


def test_a_generated_reason_is_not_consumed_when_a_change_also_addresses_it():
    review = migrate(legacy(opinion={"high_level_reasons": ["The proof is missing."]}))
    id = review["opinion"]["supported_by"][0]
    review["findings"]["changes"] = [
        {"id": "new-change", "text": "Add the proof.", "addresses": [id]}
    ]
    validate_canonical(review)
    view = legacy_view(review)
    assert any(f["id"] == id for f in view["findings"]["comments"])
    validate_08(view)


@pytest.mark.parametrize("value", ("not a number", True, [6, True]))
def test_a_bounded_numeric_scale_rejects_non_numeric_values(value):
    review = linked_record()
    review["review_context"]["metric_schemas"]["form"]["definitions"]["overall"]["scale"].pop(
        "values"
    )
    review["metrics"][0]["value"] = value
    with pytest.raises(ValidationError, match="numeric"):
        validate_canonical(review)


def test_export_keeps_an_explicit_normalization_method_added_after_migration():
    review = migrate(
        legacy(
            metrics=[
                {
                    "key": "overall",
                    "label": "Overall",
                    "value": 3,
                    "scale": {"type": "ordinal", "min": 1, "max": 5},
                    "normalized": {"value_0_1": 0.5},
                }
            ]
        )
    )
    review["metrics"][0]["normalized"]["method"] = "linear_to_unit_interval"
    validate_canonical(review)
    assert legacy_view(review)["metrics"][0]["normalized"]["method"] == "linear_to_unit_interval"


def test_export_keeps_a_complete_interval_added_after_migration():
    review = migrate(
        legacy(
            metrics=[
                {
                    "key": "overall",
                    "label": "Overall",
                    "value": 3,
                    "scale": {"type": "ordinal", "min": 1, "max": 5},
                    "uncertainty": {"interval": {"low": 2}},
                }
            ]
        )
    )
    review["metrics"][0]["uncertainty"] = {"interval": {"low": 1, "high": 4}}
    validate_canonical(review)
    assert legacy_view(review)["metrics"][0]["uncertainty"]["interval"] == {"low": 1, "high": 4}


@pytest.mark.parametrize("artifact", (False, True))
def test_empty_legacy_check_notes_migrate_and_round_trip(artifact):
    if artifact:
        old = legacy(
            artifact_assessments=[
                {
                    "artifact_type": "code",
                    "availability": "public",
                    "assessment": "adequate",
                    "checks": [{"key": "runs", "status": "pass", "notes": ""}],
                }
            ]
        )
    else:
        old = legacy(
            checks=[
                {
                    "kind": "reference_verification",
                    "items": [
                        {
                            "target": {"type": "paper_section", "ref": "Methods"},
                            "status": "found",
                            "notes": "",
                        }
                    ],
                }
            ]
        )
    review = migrate(old)
    validate_canonical(review)
    assert legacy_view(review) == old


def test_large_numeric_values_follow_their_step_without_decimal_context_errors():
    review = linked_record()
    review["metrics"][0]["value"] = 10**30
    review["review_context"]["metric_schemas"]["form"]["definitions"]["overall"]["scale"] = {
        "type": "ratio",
        "min": 0,
        "max": 10**40,
        "step": 1,
    }
    validate_canonical(review)


@pytest.mark.parametrize("source", ("openreview", "deepreview"))
@pytest.mark.usefixtures("frozen_clock")
def test_current_public_records_match_reviewed_golden_fixtures(source, monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("ocrs.mappers.ai.datetime", FrozenDatetime)
    fixtures = ROOT / "tests/fixtures"
    if source == "openreview":
        review = map_from(source, load(fixtures / "openreview/realistic_review.json"))
    else:
        review = map_from(source, {"output": load(fixtures / "ai/deepreview_report.md"), **AI_RUN})
    expected = load(fixtures / f"ocrs09/golden-{source}.json")
    validate_canonical(expected)
    assert review == expected
