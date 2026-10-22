# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""The released metric and artifact component contracts."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

CANDIDATE = Path(__file__).parents[1] / "src/ocrs/schemas/canonical-review.schema.json"


def candidate():
    return json.loads(CANDIDATE.read_text())


def validate_part(name, value):
    schema = candidate()
    Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}).validate(value)


def test_candidate_is_a_valid_schema_and_keeps_the_published_version_unchanged():
    Draft202012Validator.check_schema(candidate())
    published = Path(__file__).parents[1] / "versions/v0.8.0/canonical-review.schema.json"
    assert json.loads(published.read_text())["$id"].endswith("/v0.8.0/canonical-review.schema.json")
    assert hashlib.sha256(published.read_bytes()).hexdigest() == (
        "32ed637fa4077a72386a31d6b8fa00e83795c534383daf60ae34752e9aecdbdb"
    )


def test_one_form_holds_the_full_nonuniform_scale_for_multiple_observations():
    form = {
        "source": {"name": "Example form", "year": 2026, "version": "v1"},
        "definitions": {
            "soundness": {
                "label": "Soundness",
                "dimension": "correctness",
                "prompt": "How sound is the argument?",
                "scale": {
                    "type": "ordinal",
                    "min": 1,
                    "max": 10,
                    "values": [1, 3, 5, 6, 8, 10],
                    "anchors": [{"value": 1, "label": "Poor"}, {"value": 10, "label": "Excellent"}],
                },
            }
        },
    }
    before = copy.deepcopy(form)
    validate_part("metricSchema", form)
    for index, value in enumerate([3, 8]):
        validate_part(
            "metricAssessment",
            {
                "id": f"m{index}",
                "definition_ref": {"schema_id": "form", "key": "soundness"},
                "value": value,
            },
        )
    assert form == before


@pytest.mark.parametrize(
    "metric",
    [
        {"id": "m1", "value": 3},
        {"id": "m1", "definition_ref": {"key": "overall"}, "value": 3},
        {
            "id": "m1",
            "definition_ref": {"schema_id": "f", "key": "overall"},
            "value": 3,
            "scale": {"type": "ordinal"},
        },
    ],
)
def test_metric_observations_require_a_complete_reference_and_do_not_repeat_scales(metric):
    with pytest.raises(ValidationError):
        validate_part("metricAssessment", metric)


def test_a_local_metric_does_not_require_an_external_venue():
    validate_part(
        "metricSchema",
        {
            "definitions": {
                "custom": {
                    "label": "Local rating",
                    "scale": {"type": "categorical", "values": ["yes", "not_evaluated"]},
                }
            }
        },
    )


def test_artifact_identity_does_not_require_a_url_or_an_assessment():
    validate_part(
        "artifact", {"id": "a1", "type": "code", "reported_availability": "not_available"}
    )
    validate_part("artifact", {"id": "a2", "type": "data", "version": "v2"})


@pytest.mark.parametrize(
    "artifact", [{"type": "code"}, {"id": "a1"}, {"id": "a1", "type": "code", "assessment": "poor"}]
)
def test_artifacts_require_addressable_identity_and_keep_assessments_elsewhere(artifact):
    with pytest.raises(ValidationError):
        validate_part("artifact", artifact)
