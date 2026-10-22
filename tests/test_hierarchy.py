# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""The public 0.9 records, source conversion, graph and evidence invariants."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from test_real_reviews import (
    REAL,
    REVIEWS,
    clock,  # noqa: F401
)
from test_roundtrip import (
    AI_REVIEWS,
    AI_RUN,
    SOURCE_REVIEWS,
    differences,
    frozen_clock,  # noqa: F401
    load,
    without_import_time,
)

from ocrs import map_from, map_to, map_with_record, schema_id, validate_canonical
from ocrs.migrate import migrate
from ocrs.report import value_at

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "ocrs09/adversarial.json").read_text())


def record(**content):
    base = {
        "$schema": schema_id(),
        "review_id": "review-1",
        "version": "1.0.0",
        "created_at": "2026-10-21T12:00:00Z",
        "provenance": {"source_system": "example"},
        "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
        "target": {"work_id": "unknown", "work_type": "article"},
        "opinion": {},
    }
    base.update(copy.deepcopy(content))
    if "target" in content:
        base["target"] = {"work_id": "unknown", "work_type": "article", **base["target"]}
    return base


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_discussed_adversarial_reviews_fit_the_actual_schema(case):
    validate_canonical(record(**case["mapping"]), text_sources=case.get("span_texts"))


def linked_record():
    return record(
        opinion={"metric_refs": ["m1"], "supported_by": ["w1"]},
        review_context={
            "metric_schemas": {
                "form": {
                    "definitions": {
                        "overall": {
                            "label": "Overall",
                            "scale": {
                                "type": "ordinal",
                                "min": 1,
                                "max": 10,
                                "values": [1, 3, 5, 6, 8, 10],
                            },
                        }
                    }
                }
            }
        },
        metrics=[
            {
                "id": "m1",
                "definition_ref": {"schema_id": "form", "key": "overall"},
                "value": 6,
                "supported_by": ["w1"],
            }
        ],
        findings={
            "weaknesses": [
                {
                    "id": "w1",
                    "text": "The claim is unsupported.",
                    "about": [{"type": "claim", "id": "c1"}, {"type": "check_result", "id": "r1"}],
                }
            ],
            "changes": [
                {
                    "id": "ch1",
                    "text": "Provide the missing test OR narrow the claim.",
                    "addresses": ["w1"],
                }
            ],
        },
        work_summary={"claims": [{"id": "c1", "text": "The result generalizes."}]},
        target={"artifacts": [{"id": "a1", "type": "code"}]},
        checks=[
            {
                "id": "ck1",
                "kind": "artifact_execution",
                "results": [
                    {
                        "id": "r1",
                        "status": "failed",
                        "evidence_links": [{"resource": {"type": "artifact", "id": "a1"}}],
                    }
                ],
            }
        ],
    )


def test_a_complete_graph_needs_no_reciprocal_lists():
    review = linked_record()
    validate_canonical(review)
    assert set(review["checks"][0]) == {"id", "kind", "results"}
    assert "metric_refs" not in review["findings"]["weaknesses"][0]
    assert "finding_refs" not in review["target"]["artifacts"][0]


@pytest.mark.parametrize(
    "mutation",
    [
        "dangling",
        "wrong_type",
        "duplicate",
        "upward",
        "missing_definition",
        "wrong_scale_value",
        "artifact_missing",
        "change_cycle",
    ],
)
def test_invalid_references_and_scores_are_rejected(mutation):
    r = linked_record()
    if mutation == "dangling":
        r["opinion"]["supported_by"] = ["missing"]
    elif mutation == "wrong_type":
        r["metrics"][0]["supported_by"] = ["ck1"]
    elif mutation == "duplicate":
        r["work_summary"]["claims"][0]["id"] = "w1"
    elif mutation == "upward":
        r["findings"]["weaknesses"][0]["about"] = [{"type": "metric", "id": "m1"}]
    elif mutation == "missing_definition":
        r["metrics"][0]["definition_ref"]["key"] = "missing"
    elif mutation == "wrong_scale_value":
        r["metrics"][0]["value"] = 7
    elif mutation == "artifact_missing":
        r["target"]["artifacts"] = []
    elif mutation == "change_cycle":
        r["findings"]["changes"][0]["addresses"] = ["ch1"]
    with pytest.raises(ValidationError):
        validate_canonical(r)


def test_positional_spans_count_unicode_code_points_and_check_the_exact_text():
    r = record(
        findings={
            "comments": [
                {
                    "id": "f1",
                    "text": "The passage is ambiguous.",
                    "evidence_links": [
                        {
                            "resource": {"type": "work"},
                            "location": {
                                "page": 2,
                                "section": "Methods",
                                "span": {"text_ref": "text-v2", "start": 2, "end": 5},
                            },
                            "quote": "ABC",
                        }
                    ],
                }
            ]
        }
    )
    validate_canonical(r, text_sources={"text-v2": "🧪\nABC"})
    with pytest.raises(ValidationError, match="quote"):
        validate_canonical(r, text_sources={"text-v2": "🧪\nABD"})
    with pytest.raises(ValidationError, match="length"):
        validate_canonical(r, text_sources={"text-v2": "🧪\nA"})
    r["findings"]["comments"][0]["evidence_links"][0]["location"]["span"]["end"] = 2
    with pytest.raises(ValidationError, match="greater"):
        validate_canonical(r)


@pytest.mark.parametrize(
    "source,folder",
    [
        ("cmt", "cmt"),
        ("hotcrp", "hotcrp"),
        ("openreview", "openreview"),
        ("editorialmanager", "editorialmanager"),
        ("scholarone", "scholarone"),
        ("journal_narrative", "journal"),
    ],
)
def test_public_source_imports_use_09_and_round_trip_original_values(source, folder):
    payload = json.loads((FIXTURES / folder / "minimal_review.json").read_text())
    review = map_from(source, payload)
    validate_canonical(review)
    assert "/v0.9.0/" in review["$schema"]
    assert not (
        {
            "decision",
            "claim_assessments",
            "artifact_assessments",
            "metric_catalog_ref",
            "ethics_and_risk",
        }
        & review.keys()
    )
    for m in review.get("metrics", []):
        assert {"id", "definition_ref", "value"} <= m.keys()
        assert not ({"key", "label", "scale", "evidence_links"} & m.keys())
    written = map_to(source, review)
    again = map_from(source, written)
    assert [m["value"] for m in again.get("metrics", [])] == [
        m["value"] for m in review.get("metrics", [])
    ]


def test_migration_preserves_probabilities_without_changing_their_proposition():
    old = record(
        claim_assessments=[
            {
                "claim_id": "c1",
                "claim_text": "The claim is true.",
                "status": "unsupported",
                "probability": 0.6,
                "credence": 0.8,
            }
        ]
    )
    old["$schema"] = old["$schema"].replace("v0.9.0", "v0.8.0")
    before = copy.deepcopy(old)
    new = migrate(old)
    validate_canonical(new)
    belief = next(f for f in new["findings"]["comments"] if "uncertainty" in f)
    assert belief["text"] == "The claim is true."
    assert belief["uncertainty"] == {"probability": 0.6, "credence": 0.8}
    assert old == before
    assert migrate(new) == new


@pytest.mark.parametrize(("source", "path", "form"), SOURCE_REVIEWS + AI_REVIEWS)
@pytest.mark.usefixtures("frozen_clock")
def test_current_records_round_trip_through_all_fixture_sources(source, path, form):
    def read(payload):
        args = (
            {"output": payload, **AI_RUN}
            if source in {"openaireview", "deepreview", "reviewer3"}
            else payload
        )
        return map_from(source, args, **form)

    review = read(load(path))
    again = read(map_to(source, review))
    assert differences(without_import_time(review), without_import_time(again)) == set()


@pytest.mark.parametrize(("source", "file", "form"), REVIEWS)
@pytest.mark.usefixtures("clock")
def test_current_records_round_trip_the_real_review_corpus(source, file, form):
    def read(payload):
        if "output_run" in form:
            return map_from(source, {"output": payload, **form["output_run"]})
        return map_from(source, payload, **form)

    review = read(json.loads((REAL / file).read_text()))
    again = read(map_to(source, review))
    assert differences(without_import_time(review), without_import_time(again)) == set()


@pytest.mark.parametrize("source,path,form", AI_REVIEWS)
def test_ai_mapping_records_point_into_the_current_records(source, path, form):
    result = map_with_record(source, load(path), **AI_RUN)
    for step in result.record.steps:
        assert value_at(result.review, step.target) is not None, step.target


def test_legacy_claim_and_finding_id_collisions_keep_typed_links_unambiguous():
    old = record(
        findings={"weaknesses": [{"id": "same", "text": "A limitation.", "claim_ids": ["same"]}]},
        claim_assessments=[{"claim_id": "same", "claim_text": "A claim.", "status": "unclear"}],
    )
    old["$schema"] = old["$schema"].replace("v0.9.0", "v0.8.0")
    new = migrate(old)
    validate_canonical(new)
    claim = new["work_summary"]["claims"][0]
    assert claim["id"] != "same"
    assert new["findings"]["weaknesses"][0]["about"] == [{"type": "claim", "id": claim["id"]}]


def test_wrapped_schema_still_checks_current_record_references(tmp_path):
    from ocrs.schema import load_schema

    wrapper = copy.deepcopy(load_schema())
    wrapper["$id"] = "https://example.org/custom-review-schema"
    path = tmp_path / "custom.schema.json"
    path.write_text(json.dumps(wrapper))
    review = linked_record()
    review["opinion"]["supported_by"] = ["missing"]
    try:
        with pytest.raises(ValidationError):
            validate_canonical(review, schema_path=path)
    finally:
        load_schema()
