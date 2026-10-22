# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Metric credence uses the requested name, description, and probability bounds."""

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from v08_schema import load_schema


def validate_metric(uncertainty):
    schema = load_schema()
    Draft202012Validator({"$ref": "#/$defs/metricAssessment", "$defs": schema["$defs"]}).validate(
        {
            "key": "overall",
            "label": "Overall",
            "scale": {"type": "ordinal", "min": 1, "max": 5},
            "value": 4,
            "uncertainty": uncertainty,
        }
    )


@pytest.mark.parametrize("credence", [0, 0.5, 1])
def test_credence_accepts_endpoints_and_preserves_interval_and_rationale(credence):
    validate_metric(
        {"credence": credence, "interval": {"low": 3, "high": 5}, "rationale": "Limited evidence."}
    )


@pytest.mark.parametrize("credence", [-0.1, 1.1, "0.5", True])
def test_invalid_credence_is_rejected(credence):
    with pytest.raises(jsonschema.ValidationError):
        validate_metric({"credence": credence})


def test_old_confidence_key_is_rejected():
    with pytest.raises(jsonschema.ValidationError):
        validate_metric({"confidence": 0.8})


def test_credence_remains_optional():
    validate_metric({"interval": {"low": 3, "high": 5}, "rationale": "Limited evidence."})


def test_credence_description_matches_requested_wording():
    field = load_schema()["$defs"]["metricAssessment"]["properties"]["uncertainty"]["properties"][
        "credence"
    ]
    assert (
        field["description"] == "Overall confidence in the score given from 0 to 1, "
        "with 0 being not at all confident, and 1 being certain"
    )
