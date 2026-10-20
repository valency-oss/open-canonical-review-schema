# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Points can be named, grouped, linked to each other and carry proposed rewrites."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from ocrs import load_schema, validate_canonical

MINIMAL_REVIEW = {
    "review_id": "review-1",
    "version": "1.0.0",
    "created_at": "2026-10-16T12:00:00Z",
    "provenance": {"source_system": "example-journal"},
    "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
    "target": {"work_id": "unknown", "work_type": "article"},
    "opinion": {"summary": "A sound paper."},
}
FINDINGS = {
    "weaknesses": [
        {
            "id": "overview-1",
            "text": "The split may leak weather between training and test days.",
            "summarizes": ["split-1"],
        },
        {
            "id": "split-1",
            "title": "Alternating day split",
            "text": "Test days sit between training days.",
            "severity": "major",
            "group": ["[Datasets] (Pages: 7-13)", "Potential Mistakes and Improvements"],
            "evidence_links": [
                {
                    "type": "paper_section",
                    "ref": "Section 2.3, Pages 10–12",
                    "location": {"section": "2.3", "page": 10, "page_end": 12},
                }
            ],
        },
        {
            "id": "typo-1",
            "text": "Superscript citation used as a noun.",
            "severity": "minor",
            "suggested_edits": [
                {"original": "described in,$^{21}$", "replacement": "described in Ref. 21,"},
                {"replacement": "described by Marchetti,$^{21}$"},
            ],
        },
        {
            "id": "citation-1",
            "text": "The floor-plan graph layers need their source cited.",
            "evidence_links": [
                {
                    "type": "external",
                    "ref": "Reference Paper: Floor-Plan Graphs, Halvorsen et al., 2018",
                    "work": {
                        "title": "Floor-Plan Graphs",
                        "authors": ["Halvorsen et al."],
                        "year": 2018,
                        "identifiers": {"arxiv_id": {"value": "1813.00042"}},
                    },
                },
                {"type": "bibliography", "ref": "Reference 21 (Page 40)"},
            ],
        },
    ],
    "changes": [
        {
            "id": "fix-1",
            "title": "Name the citation",
            "text": "Write the reference as a noun.",
            "scope": "typo",
            "addresses": ["typo-1"],
            "evidence_links": [{"type": "paper_section", "ref": "p.5", "location": {"page": 5}}],
            "suggested_edits": [{"replacement": "described in Ref. 21,"}],
            "group": ["Minor Corrections and Typos"],
        }
    ],
}


def review(findings=None, **context):
    out = {**copy.deepcopy(MINIMAL_REVIEW), "findings": copy.deepcopy(findings or FINDINGS)}
    if context:
        out["review_context"] = context
    return out


def test_new_point_fields_validate():
    validate_canonical(review())


def test_pre_submission_review_type():
    validate_canonical(review(review_type="pre_submission", requested_by="authors"))


def test_an_overview_may_not_say_what_it_covers():
    findings = copy.deepcopy(FINDINGS)
    findings["weaknesses"][0]["summarizes"] = []
    validate_canonical(review(findings))


@pytest.mark.parametrize(
    "path, value",
    [
        (("weaknesses", 2, "suggested_edits", 0), {"original": "x"}),
        (("weaknesses", 2, "suggested_edits", 0), {"replacement": "y", "note": "z"}),
        (("weaknesses", 1, "group"), []),
        (("weaknesses", 1, "id"), ""),
        (("weaknesses", 1, "evidence_links", 0, "location"), {"page_end": 3}),
        (("weaknesses", 3, "evidence_links", 0, "work"), {}),
        (("weaknesses", 0, "summarizes"), ["split-1", "split-1"]),
    ],
)
def test_schema_rejects(path, value):
    findings = copy.deepcopy(FINDINGS)
    node = findings
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(review(findings))


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda f: f["weaknesses"][1].update(id="overview-1"), "not unique"),
        (lambda f: f["changes"][0].update(id="typo-1"), "not unique"),
        (lambda f: f["weaknesses"][0].update(summarizes=["missing"]), "not a finding id"),
        (lambda f: f["changes"][0].update(addresses=["missing"]), "not a finding id"),
        (lambda f: f["weaknesses"][0].update(claim_ids=["missing"]), "not a claim_id"),
        (
            lambda f: f["weaknesses"][1]["evidence_links"][0]["location"].update(page_end=9),
            "before page",
        ),
    ],
)
def test_references_must_resolve(change, message):
    findings = copy.deepcopy(FINDINGS)
    change(findings)
    with pytest.raises(jsonschema.ValidationError, match=message):
        validate_canonical(review(findings))


def test_a_change_for_an_ethical_concern_is_a_change_with_scope_ethics():
    out = review()
    out["ethics_and_risk"] = {"ethical_concerns": True}
    mitigation = {"id": "mitigation-1", "text": "Redact.", "scope": "ethics", "addresses": ["x"]}
    out["findings"]["changes"].append(mitigation)
    with pytest.raises(jsonschema.ValidationError, match="not a finding id"):
        validate_canonical(out)
    mitigation["addresses"] = ["typo-1"]
    validate_canonical(out)
    # Ethics has no list of its own changes any more
    out["ethics_and_risk"]["required_mitigations"] = [{"text": "Redact."}]
    with pytest.raises(jsonschema.ValidationError, match="required_mitigations"):
        validate_canonical(out)


def test_a_change_says_how_serious_and_answers_points():
    out = review()
    change = out["findings"]["changes"][0]
    change["severity"] = "trivial"
    validate_canonical(out)
    # Severity runs from info to critical; priority is gone
    change["severity"] = "blocking"
    with pytest.raises(jsonschema.ValidationError, match="severity"):
        validate_canonical(out)
    change["severity"] = "minor"
    change["priority"] = "minor"
    with pytest.raises(jsonschema.ValidationError, match="priority"):
        validate_canonical(out)


def test_source_data_is_not_checked_as_evidence():
    out = review()
    lookalike = {"type": "custom", "ref": "x", "location": {"page": 9, "page_end": 3}}
    out["extensions"] = {"some-reviewer": {"evidence_links": [lookalike]}}
    out["provenance"]["raw_payload"] = {"evidence_links": [lookalike]}
    out["referees"][0] = {
        "referee_type": "ai",
        "identity_mode": "open",
        "ai_referee": {
            "system": {
                "critic_framework": {"name": "some-reviewer", "version": "1"},
                "models": [
                    {
                        "role": "reviewer",
                        "model_id": "m",
                        "parameters": {"evidence_links": [lookalike]},
                    }
                ],
            },
            "execution": {
                "started_at": "2026-10-16T12:00:00Z",
                "ended_at": "2026-10-16T12:05:00Z",
            },
        },
    }
    validate_canonical(out)


def test_page_end_is_checked_wherever_the_link_is():
    out = review()
    out["claim_assessments"] = [
        {
            "claim_id": "c1",
            "claim_text": "A claim.",
            "status": "unclear",
            "evidence_links": [
                {"type": "table", "ref": "Table 4", "location": {"page": 30, "page_end": 29}}
            ],
        }
    ]
    with pytest.raises(jsonschema.ValidationError, match="before page"):
        validate_canonical(out)


@pytest.mark.parametrize(
    "wrap",
    [
        lambda s: {**s, "properties": {**s["properties"], "extensions": True}},
        lambda s: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "definitions": {"review": s},
            "$ref": "#/definitions/review",
        },
    ],
    ids=["boolean-node", "wrapper"],
)
def test_custom_schemas_still_get_page_checks(tmp_path, wrap):
    canonical = json.loads(
        (Path(__file__).parent.parent / "src/ocrs/schemas/canonical-review.schema.json").read_text()
    )
    path = tmp_path / "custom.schema.json"
    path.write_text(json.dumps(wrap(canonical)))
    out = review()
    out["extensions"] = {"x": {"evidence_links": [{"location": {"page": 9, "page_end": 3}}]}}
    try:
        validate_canonical(out, schema_path=path)
        bad = review()
        bad["findings"]["weaknesses"][1]["evidence_links"][0]["location"]["page_end"] = 9
        with pytest.raises(jsonschema.ValidationError, match="before page"):
            validate_canonical(bad, schema_path=path)
    finally:
        load_schema()


def _change_with_scope(scope: str) -> dict:
    out = review()
    out["findings"]["changes"][0]["scope"] = scope
    return out


@pytest.mark.parametrize(
    "scope",
    [
        "typo",
        "clarification",
        "analysis",
        "experiment",
        "theory",
        "writing",
        "figure",
        "references",
        "artifact",
        "ethics",
        "other",
    ],
)
def test_a_change_takes_each_kind_of_scope(scope: str) -> None:
    validate_canonical(_change_with_scope(scope))


def test_a_change_rejects_an_unknown_scope() -> None:
    with pytest.raises(jsonschema.ValidationError, match="scope"):
        validate_canonical(_change_with_scope("plot"))
