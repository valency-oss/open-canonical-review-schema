# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Review-run seeds have one home, including for lightweight AI references."""

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from ocrs import validate_canonical


@pytest.fixture
def review():
    return json.loads((Path(__file__).parent.parent / "examples/ai-review.json").read_text())


def test_review_seeds_validate_with_full_ai_provenance(review):
    review["referees"][0]["reproducibility"] = {
        "seed": 42,
        "seeds": [{"stage": "retrieval", "seed": 100}, {"stage": "generation", "seed": 200}],
    }
    validate_canonical(review)


def test_review_seeds_validate_with_ai_reference(review):
    review["referees"][0]["ai_referee"] = {"reference": {"third_party_id": "reviewer-1"}}
    review["referees"][0]["reproducibility"] = {
        "seed": "42",
        "seeds": [{"stage": "generation", "seed": "200"}],
    }
    validate_canonical(review)


@pytest.mark.parametrize(
    "field,value", [("seed", 42), ("seeds", [{"stage": "generation", "seed": 200}])]
)
def test_execution_seeds_are_rejected(review, field, value):
    review["referees"][0]["ai_referee"]["execution"][field] = value
    with pytest.raises(ValidationError):
        validate_canonical(review)
