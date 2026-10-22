"""Regression checks for the immutable published 0.8 schema and its reference rules.

These tests deliberately retain the retired fields. The current hierarchy is exercised
directly in test_hierarchy.py; no production validation is replaced or monkeypatched.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ocrs.schema import check_legacy_references

PATH = Path(__file__).parents[1] / "versions/v0.8.0/canonical-review.schema.json"


def load_schema():
    return json.loads(PATH.read_text())


def validate_canonical(review, *, schema_path=None):
    schema = json.loads(Path(schema_path).read_text()) if schema_path else load_schema()
    Draft202012Validator(schema).validate(review)
    check_legacy_references(review, evidence_schema=load_schema())
