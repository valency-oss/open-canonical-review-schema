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
from ocrs.hierarchy import legacy_view
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


def up_down_up(review):
    """0.9 → the 0.8 view source writers use → 0.9 again, and that view once more."""
    from v08_schema import validate_canonical as validate_08

    down = legacy_view(review)
    validate_08(down)
    again = migrate(down)
    validate_canonical(again)
    assert differences(review, again) == set()
    assert differences(down, legacy_view(again)) == set()


@pytest.mark.parametrize(("source", "path", "form"), SOURCE_REVIEWS + AI_REVIEWS)
def test_fixture_reviews_go_down_to_08_and_back_up_unchanged(source, path, form):
    payload = load(path)
    if source in {"openaireview", "deepreview", "reviewer3"}:
        payload = {"output": payload, **AI_RUN}
    up_down_up(map_from(source, payload, **form))


@pytest.mark.parametrize(("source", "file", "form"), REVIEWS)
@pytest.mark.usefixtures("clock")
def test_real_reviews_go_down_to_08_and_back_up_unchanged(source, file, form):
    payload = json.loads((REAL / file).read_text())
    if "output_run" in form:
        up_down_up(map_from(source, {"output": payload, **form["output_run"]}))
    else:
        up_down_up(map_from(source, payload, **form))


def legacy(**content):
    """A record in the published 0.8 shape, checked against that schema."""
    from v08_schema import validate_canonical as validate_08

    old = record(**content)
    old["$schema"] = old["$schema"].replace("v0.9.0", "v0.8.0")
    validate_08(old)
    return old


def test_several_empty_legacy_claim_ids_are_not_ambiguous_links():
    new = migrate(
        legacy(
            claim_assessments=[
                {"claim_id": "", "claim_text": "A.", "status": "supported"},
                {"claim_id": "", "claim_text": "B.", "status": "supported"},
            ]
        )
    )
    validate_canonical(new)
    ids = [c["id"] for c in new["work_summary"]["claims"]]
    assert len(set(ids)) == 2 and "" not in ids
    assert [c["claim_id"] for c in legacy_view(new)["claim_assessments"]] == ["", ""]


def test_a_legacy_normalization_without_a_method_says_the_method_is_unstated():
    metric = {
        "key": "overall",
        "label": "Overall",
        "scale": {"type": "ordinal", "min": 1, "max": 5},
        "value": 3,
        "normalized": {"value_0_1": 0.5},
    }
    new = migrate(legacy(metrics=[metric]))
    validate_canonical(new)
    assert new["metrics"][0]["normalized"] == {"value_0_1": 0.5, "method": "unspecified"}
    assert legacy_view(new)["metrics"][0]["normalized"] == {"value_0_1": 0.5}


def test_generated_ids_are_named_for_their_kind_and_only_overall_scores_join_the_opinion():
    scale = {"type": "ordinal", "min": 1, "max": 5}
    new = migrate(
        legacy(
            findings={"weaknesses": [{"text": "W."}], "strengths": [{"text": "S."}]},
            metrics=[
                {"key": "overall", "label": "Overall", "scale": scale, "value": 4},
                {"key": "confidence", "label": "Confidence", "scale": scale, "value": 2},
            ],
        )
    )
    assert new["findings"]["weaknesses"][0]["id"] == "weakness-1"
    assert new["findings"]["strengths"][0]["id"] == "strength-1"
    overall = next(m["id"] for m in new["metrics"] if m["value"] == 4)
    assert new["opinion"]["metric_refs"] == [overall]


def test_retained_fields_follow_their_finding_when_findings_are_inserted():
    old = legacy(findings={"changes": [{"text": "Add a consent statement.", "scope": "ethics"}]})
    new = migrate(old)
    new["findings"]["changes"].insert(0, {"id": "new-change", "text": "Fix the typo."})
    validate_canonical(new)
    changes = legacy_view(new)["findings"]["changes"]
    assert "scope" not in changes[0]
    assert changes[1]["scope"] == "ethics"


def test_an_edited_migrated_record_still_projects_for_source_writers():
    new = migrate(
        legacy(
            opinion={
                "summary": "Short summary.",
                "text": "Longer opinion text.",
                "high_level_reasons": ["Reason A", "Reason B"],
            }
        )
    )
    view = legacy_view(new)
    assert (view["opinion"]["summary"], view["opinion"]["text"]) == (
        "Short summary.",
        "Longer opinion text.",
    )

    edited = copy.deepcopy(new)
    edited["opinion"]["summary"] = "Edited: " + edited["opinion"]["summary"]
    view = legacy_view(edited)
    assert (view["opinion"]["summary"], view["opinion"]["text"]) == (
        "Edited: Short summary.",
        "Longer opinion text.",
    )
    edited["opinion"]["summary"] = edited["opinion"]["summary"].replace("Longer", "Shorter")
    view = legacy_view(edited)
    assert view["opinion"]["summary"] == edited["opinion"]["summary"]
    assert "text" not in view["opinion"]

    removed = new["opinion"]["supported_by"][0]
    edited["opinion"]["supported_by"].remove(removed)
    edited["findings"]["comments"] = [
        f for f in edited["findings"]["comments"] if f["id"] != removed
    ]
    validate_canonical(edited)
    assert legacy_view(edited)["opinion"]["high_level_reasons"] == ["Reason B"]


def test_schema_versions_are_compared_rather_than_matched_as_text(tmp_path):
    from ocrs.schema import is_hierarchical

    base = "https://valency-oss.github.io/open-canonical-review-schema/v{}/x.json"
    assert [is_hierarchical(base.format(v)) for v in ("0.8.0", "0.9.0", "0.9.1", "1.0.0")] == [
        False,
        True,
        True,
        True,
    ]
    later = record(findings={"comments": [{"id": "c1", "text": "A comment."}]})
    later["$schema"] = base.format("0.9.1")
    assert migrate(later) == later


def test_a_schema_path_applies_to_one_validation_only():
    old = legacy(opinion={"summary": "A summary."})
    validate_canonical(
        old, schema_path=Path(__file__).parents[1] / "versions/v0.8.0/canonical-review.schema.json"
    )
    validate_canonical(record(opinion={"summary": "A summary."}))


def test_caller_scale_bounds_are_not_presented_as_the_original_form():
    folder = FIXTURES / "openreview_v2"
    bounds = json.loads((folder / "scale_bounds.json").read_text())
    review = map_from(
        "openreview", json.loads((folder / "review.json").read_text()), scale_bounds=bounds
    )
    forms = review["review_context"]["metric_schemas"].values()
    assert all("snapshot" not in form.get("source", {}) for form in forms)
    assert review["extensions"]["openreview"]["caller_scale_bounds"] == bounds


def test_going_down_leaves_no_category_that_only_migration_filled():
    old = legacy(
        opinion={"summary": "A summary."},
        findings={"strengths": [{"text": "Clear."}]},
        ethics_and_risk={"ethical_concerns": True, "notes": "Consent is not described."},
    )
    down = legacy_view(migrate(old))
    assert set(down["findings"]) == {"strengths"}
    assert down["ethics_and_risk"] == old["ethics_and_risk"]
