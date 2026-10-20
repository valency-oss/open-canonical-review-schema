# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Reviews can record the checks run on a work, the work's contributions, points they
do not classify, and how their text is written."""

import copy

import jsonschema
import pytest

from ocrs import validate_canonical

REVIEW = {
    "review_id": "review-1",
    "version": "1.0.0",
    "created_at": "2026-10-16T12:00:00Z",
    "provenance": {"source_system": "some-ai-reviewer"},
    "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
    "target": {
        "work_id": "unknown",
        "work_type": "preprint",
        "title": "Forecasting bay temperatures from two sensor feeds",
    },
    "text_format": {"markup": "markdown", "math": "tex"},
    "opinion": {
        "contributions": [
            {
                "title": "Multi-source forecasting",
                "text": "The authors combine a ceiling thermal array with truck-yard snapshots.",
            },
            {"text": "The model cuts temperature error by 21% at 20 minutes.", "claim_ids": ["c1"]},
        ]
    },
    "claim_assessments": [
        {
            "claim_id": "c1",
            "claim_text": "Error falls by 21% at a 20-minute horizon.",
            "status": "not_evaluated",
        }
    ],
    "findings": {
        "comments": [
            {
                "id": "symbol-1",
                "title": "Symbol collision for $\\kappa$",
                "text": "$\\kappa$ is the time constant in Eq. (6) and a threshold in Eq. (9).",
                "group": ["Reviewer Comments"],
                "evidence_links": [
                    {
                        "type": "paper_section",
                        "ref": "Page 12",
                        "quote": "dry bulb is normalized as ( ◦ C − 16) / 8",
                        "location": {"page": 12},
                    },
                    {"type": "figure", "ref": "Fig 3"},
                ],
            }
        ]
    },
    "checks": [
        {
            "id": "ai-text",
            "kind": "ai_text_detection",
            "label": "AI Text Detection",
            "performed_by": {"name": "Pangram", "url": "https://www.pangram.com"},
            "summary": "33% AI-generated and 0% AI-assisted text detected.",
            "measurements": [
                {"key": "ai_generated", "label": "AI-generated", "value": 0.33, "unit": "fraction"},
                {"key": "ai_assisted", "value": 0, "unit": "fraction"},
            ],
        },
        {
            "kind": "fatal_flaw_screen",
            "label": "Fatal Flaws",
            "outcome": "no_issues",
            "summary": "No fatal methodological flaws were identified.",
        },
        {
            "id": "references",
            "kind": "reference_verification",
            "summary": "Checked 57 references: 55 verified, 2 not found.",
            "measurements": [
                {"key": "checked", "value": 57},
                {"key": "verified", "value": 55},
                {"key": "not_found", "value": 2},
            ],
            "items": [
                {
                    "target": {
                        "type": "bibliography",
                        "ref": "9",
                        "location": {"page": 40},
                        "work": {"citation": "R. Vantongeren, Depot plant specifications (2021)."},
                    },
                    "status": "Not Found",
                    "flagged": True,
                }
            ],
            "finding_ids": ["symbol-1"],
        },
    ],
}


def review():
    return copy.deepcopy(REVIEW)


def test_new_fields_validate():
    validate_canonical(review())


def test_a_review_of_unclassified_comments_says_something():
    out = review()
    del out["opinion"]["contributions"]
    validate_canonical(out)
    out["findings"]["comments"] = []
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(out)


def test_a_source_unit_keeps_its_value():
    out = review()
    out["checks"][0]["measurements"][0] = {"key": "ai_generated", "value": 33, "unit": "%"}
    validate_canonical(out)


@pytest.mark.parametrize(
    "path, value",
    [
        (("checks", 1), {"kind": "fatal_flaw_screen"}),
        (("checks", 1), {"outcome": "no_issues"}),
        (("checks", 1, "kind"), "spelling"),
        (("checks", 1, "outcome"), "passed"),
        (("checks", 0, "performed_by"), {"version": "2"}),
        (("checks", 0, "measurements", 0, "value"), 33),
        (("checks", 0, "measurements", 0, "value"), "0.33"),
        (("checks", 0, "measurements", 1), {"value": 0}),
        (("checks", 2, "items", 0), {"target": {"type": "bibliography", "ref": "12"}}),
        (("checks", 2, "items", 0, "target", "work", "citation"), ""),
        (("checks", 2, "finding_ids"), ["symbol-1", "symbol-1"]),
        (("text_format",), {}),
        (("text_format", "markup"), "rst"),
        (("text_format", "math"), "mathml"),
        (("opinion", "contributions", 0), {"title": "No text"}),
        (("target", "title"), ""),
    ],
)
def test_schema_rejects(path, value):
    out = review()
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(out)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda r: r["checks"][0].update(id="symbol-1"), "not unique"),
        (lambda r: r["checks"][2].update(id="ai-text"), "not unique"),
        (lambda r: r["checks"][2].update(finding_ids=["missing"]), "not a finding id"),
        (lambda r: r["checks"][2].update(finding_ids=["ai-text"]), "not a finding id"),
        (
            lambda r: r["opinion"]["contributions"][1].update(claim_ids=["missing"]),
            "not a claim_id",
        ),
        (
            lambda r: r["checks"][2]["items"][0]["target"]["location"].update(page_end=39),
            "before page",
        ),
    ],
)
def test_references_must_resolve(change, message):
    out = review()
    change(out)
    with pytest.raises(jsonschema.ValidationError, match=message):
        validate_canonical(out)


def test_comments_can_be_summarized_and_acted_on():
    out = review()
    out["findings"]["weaknesses"] = [
        {"id": "overview-1", "text": "Notation is inconsistent.", "summarizes": ["symbol-1"]}
    ]
    out["findings"]["changes"] = [{"text": "Rename the threshold.", "addresses": ["symbol-1"]}]
    validate_canonical(out)
