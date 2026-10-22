# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the canonical review schema itself."""

import json
from importlib.metadata import version
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

from ocrs import load_schema, map_from, map_with_record, schema_id, validate_canonical
from ocrs.migrate import migrate
from ocrs.schema import has_content


def test_schema_id_names_the_package_version():
    expected = (
        "https://valency-oss.github.io/open-canonical-review-schema"
        f"/v{version('ocrs')}/canonical-review.schema.json"
    )
    assert load_schema()["$id"] == expected


MINIMAL_REVIEW = {
    "review_id": "review-1",
    "version": "1.0.0",
    "created_at": "2026-10-06T12:00:00Z",
    "provenance": {"source_system": "example-journal"},
    "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
    "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
    "opinion": {"summary": "A sound paper."},
}
FIXTURES = Path(__file__).parent / "fixtures"


def test_a_review_may_name_its_schema():
    validate_canonical(MINIMAL_REVIEW)
    validate_canonical({"$schema": schema_id(), **MINIMAL_REVIEW})
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical({"$schema": 63, **MINIMAL_REVIEW})


@pytest.mark.parametrize(
    ("source", "fixture"),
    [
        ("cmt", "cmt"),
        ("editorialmanager", "editorialmanager"),
        ("hotcrp", "hotcrp"),
        ("journal_narrative", "journal"),
        ("openreview", "openreview"),
        ("scholarone", "scholarone"),
    ],
)
def test_mappers_name_the_packaged_schema(source, fixture):
    payload = json.loads((FIXTURES / fixture / "minimal_review.json").read_text())
    review = map_from(source, payload)
    assert review["$schema"] == schema_id() == load_schema()["$id"]
    assert next(iter(review)) == "$schema"


def test_ai_mappers_name_the_packaged_schema():
    review = map_with_record(
        "openaireview",
        json.loads((FIXTURES / "ai" / "openaireview_paper.json").read_text()),
        review_id="review-1",
        source_system="example-platform",
        work_id="paper-1",
        work_type="preprint",
        started_at="2026-10-03T01:00:00Z",
        ended_at="2026-10-03T01:08:00Z",
    ).review
    assert review["$schema"] == schema_id()


def test_an_anonymous_human_review_needs_no_human_referee():
    validate_canonical(
        {
            "review_id": "review-1",
            "version": "1.0.0",
            "created_at": "2026-10-06T12:00:00Z",
            "provenance": {"source_system": "example-journal"},
            "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
            "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
            "opinion": {"summary": "A sound paper."},
        }
    )


def test_the_published_copy_of_this_version_matches_the_package():
    schemas = Path(__file__).parent.parent / "src" / "ocrs" / "schemas"
    published = Path(__file__).parent.parent / "versions" / f"v{version('ocrs')}"
    assert sorted(path.name for path in published.iterdir()) == sorted(
        path.name for path in schemas.glob("*.json")
    )
    for path in published.iterdir():
        assert path.read_bytes() == (schemas / path.name).read_bytes(), path.name


def test_schema_is_valid_json_schema():
    Draft202012Validator.check_schema(load_schema())


def _review_of(identifiers: dict) -> dict:
    return {
        "review_id": "review-1",
        "version": "1.0.0",
        "created_at": "2026-10-15T12:00:00Z",
        "provenance": {"source_system": "example-journal"},
        "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
        "target": {
            "work_id": "internal_id:manuscript_id:paper-1",
            "work_type": "article",
            "identifiers": identifiers,
        },
        "opinion": {"summary": "A sound paper."},
    }


def test_target_takes_crossref_identifier_types():
    validate_canonical(
        _review_of(
            {
                "handle": {
                    "value": "1721.1/12345",
                    "hyperlink": "https://hdl.handle.net/1721.1/12345",
                },
                "ark": {"value": "ark:/13030/tf5p30086k"},
                "isbn": {"value": "9780262035613"},
                "issn": {"value": "2050-084X"},
                "ecli": {"value": "ECLI:EU:C:2014:317"},
                "accession": {"value": "MN908947", "database": "GenBank"},
                "purl": "https://purl.org/example/1",
                "uuid": {"value": "123e4567-e89b-12d3-a456-426614174000"},
            }
        )
    )


@pytest.mark.parametrize(
    "identifiers",
    [
        {"handle": {"value": "hdl:1721.1/12345"}},
        {"ark": {"value": "13030/tf5p30086k"}},
        {"isbn": {"value": "978-0-262-03561-3"}},
        {"issn": {"value": "2050084X"}},
        {"ecli": {"value": "EU:C:2014:317"}},
        {"accession": {"database": "GenBank"}},
        {"purl": {"value": "https://purl.org/example/1"}},
        {"uuid": {"value": "123e4567e89b12d3a456426614174000"}},
    ],
)
def test_crossref_identifier_types_reject_malformed_values(identifiers: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_of(identifiers))


def _review_with(finding: dict, claim: dict) -> dict:
    finding = dict(finding)
    claim = dict(claim)
    uncertainty = {k: finding.pop(k) for k in ("probability", "credence") if k in finding}
    if uncertainty:
        finding["uncertainty"] = uncertainty
    belief = {
        "id": "f2",
        "text": claim["claim_text"],
        "about": [{"type": "claim", "id": claim["claim_id"]}],
    }
    if any(k in claim for k in ("probability", "credence")):
        belief["uncertainty"] = {k: claim[k] for k in ("probability", "credence") if k in claim}
    return {
        **MINIMAL_REVIEW,
        "findings": {"weaknesses": [{"id": "f1", **finding}], "comments": [belief]},
        "work_summary": {"claims": [{"id": claim["claim_id"], "text": claim["claim_text"]}]},
    }


CLAIM = {"claim_id": "c1", "claim_text": "The method doubles accuracy.", "status": "unclear"}
FINDING = {"text": "The baseline is missing."}


def test_findings_and_claims_take_probability_and_credence() -> None:
    validate_canonical(
        _review_with(
            {**FINDING, "probability": 0.8, "credence": 0.6},
            {**CLAIM, "probability": 0.3, "credence": 0.9},
        )
    )
    validate_canonical(_review_with(FINDING, CLAIM))


@pytest.mark.parametrize(
    "estimate", [{"probability": 1.2}, {"probability": -0.1}, {"probability": 0.5, "credence": 2}]
)
def test_probability_and_credence_are_between_0_and_1(estimate: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_with({**FINDING, **estimate}, CLAIM))
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_with(FINDING, {**CLAIM, **estimate}))


def test_credence_needs_a_probability() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_with({**FINDING, "credence": 0.5}, CLAIM))
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_with(FINDING, {**CLAIM, "credence": 0.5}))


def _review_of_target(target: dict) -> dict:
    return {**_review_of({}), "target": {"work_type": "article", **target}}


@pytest.mark.parametrize(
    "work_id", ["doi:10.7554/eLife.112155.1", "internal_id:openreview_forum:2dnO3LLiJ1", "unknown"]
)
def test_work_id_is_type_and_value(work_id: str) -> None:
    validate_canonical(_review_of_target({"work_id": work_id}))


@pytest.mark.parametrize("work_id", ["paper-1", "internal_id:42", "issn:2050-084X", "doi:"])
def test_work_id_rejects_free_form_values(work_id: str) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_of_target({"work_id": work_id}))


def test_target_relations_name_other_versions_and_forms():
    validate_canonical(
        _review_of_target(
            {
                "work_id": "doi:10.7554/eLife.112155.1",
                "identifiers": {"doi": {"value": "10.7554/eLife.112155.1"}},
                "version": "1",
                "relations": [
                    {
                        "type": "is_version_of",
                        "identifiers": {"doi": {"value": "10.64898/2026.06.08.730955"}},
                    },
                    {
                        "type": "is_same_as",
                        "identifiers": {"doi": {"value": "10.7554/eLife.112155"}},
                    },
                    {
                        "type": "is_new_version_of",
                        "identifiers": {"internal_id": {"field_name": "ms", "value": "MS-1"}},
                        "version": "v1",
                    },
                ],
            }
        )
    )


@pytest.mark.parametrize(
    "relation",
    [
        {"type": "isVersionOf", "identifiers": {"doi": {"value": "10.1234/x"}}},
        {"type": "is_review_of", "identifiers": {"doi": {"value": "10.1234/x"}}},
        {"type": "is_version_of", "identifiers": {}},
        {"type": "is_version_of"},
        {"type": "is_version_of", "identifiers": {"doi": {"value": "not-a-doi"}}},
    ],
)
def test_target_relations_reject_unknown_types_and_missing_identifiers(relation: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_of_target({"work_id": "doi:10.1234/y", "relations": [relation]}))


def test_revision_of_is_deprecated_but_still_valid():
    target = load_schema()["properties"]["target"]["properties"]["revision_of"]
    assert target["deprecated"] is True
    validate_canonical(_review_of_target({"work_id": "doi:10.1234/y", "revision_of": "MS-1"}))


def _review_with_provenance(provenance: dict) -> dict:
    return {
        "review_id": "review-1",
        "version": "1.0.0",
        "created_at": "2026-10-15T12:00:00Z",
        "provenance": {"source_system": "example-journal", **provenance},
        "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
        "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
        "opinion": {"summary": "A sound paper."},
    }


def test_provenance_takes_an_optional_review_doi() -> None:
    validate_canonical(_review_with_provenance({"review_doi": "10.5555/review.2041"}))
    validate_canonical(_review_with_provenance({}))


@pytest.mark.parametrize(
    "review_doi", ["", "https://doi.org/10.5555/review.2041", "doi:10.5555/x", "10.12/x"]
)
def test_review_doi_must_be_a_bare_doi(review_doi: str) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_with_provenance({"review_doi": review_doi}))


def test_a_conference_paper_can_be_a_proceedings_article() -> None:
    review = _review_with_provenance({})
    review["target"]["work_type"] = "proceedings_article"
    validate_canonical(review)


def _review_in_context(review_context: dict) -> dict:
    return {
        "review_id": "review-1",
        "version": "1.0.0",
        "created_at": "2026-10-15T12:00:00Z",
        "provenance": {"source_system": "example-journal"},
        "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
        "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
        "review_context": review_context,
        "opinion": {"summary": "A sound paper."},
    }


@pytest.mark.parametrize(
    "review_type",
    [
        "initial",
        "revision",
        "rebuttal_response",
        "meta_review",
        "shepherding",
        "replication",
        "author_comment",
        "community_comment",
        "aggregate",
        "recommendation",
    ],
)
def test_review_type_covers_the_crossref_peer_review_types(review_type: str) -> None:
    validate_canonical(_review_in_context({"review_type": review_type}))


@pytest.mark.parametrize("stage", ["pre_publication", "post_publication"])
def test_stage_says_whether_the_review_came_before_or_after_publication(stage: str) -> None:
    validate_canonical(_review_in_context({"review_type": "initial", "stage": stage}))
    validate_canonical(_review_in_context({"stage": stage}))


def test_publication_stage_is_no_longer_a_review_type() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_in_context({"review_type": "post_publication"}))


@pytest.mark.parametrize("stage", ["published", "pre-publication", ""])
def test_stage_takes_only_the_two_values(stage: str) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(_review_in_context({"stage": stage}))


def _review_saying(**content) -> dict:
    """A minimal review whose only content is `content`."""
    review = {key: value for key, value in MINIMAL_REVIEW.items() if key != "opinion"}
    return {**review, "opinion": {}, **content}


@pytest.mark.parametrize(
    "content",
    [
        {"opinion": {"summary": "A sound paper."}},
        {"opinion": {"text": "The paper is sound."}},
        {"opinion": {"contributions": [{"text": "A new method."}]}},
        {"findings": {"strengths": [{"text": "Clear."}]}},
        {"findings": {"weaknesses": [{"text": "Small sample."}]}},
        {"findings": {"questions": [{"text": "Why this baseline?"}]}},
        {"findings": {"comments": [{"text": "Typo on page 2."}]}},
        {"findings": {"changes": [{"text": "Add an ablation."}]}},
        {"decision": {"recommendation": "accept"}},
        {"decision": {"revision_requirement": "minor"}},
        {
            "metrics": [
                {
                    "key": "overall",
                    "label": "Overall",
                    "scale": {"type": "ordinal", "min": 1, "max": 5},
                    "value": 4,
                }
            ]
        },
        {
            "claim_assessments": [
                {"claim_id": "c1", "claim_text": "It works.", "status": "supported"}
            ]
        },
        {
            "artifact_assessments": [
                {"artifact_type": "code", "availability": "public", "assessment": "good"}
            ]
        },
        {"checks": [{"kind": "reference_verification", "summary": "All references found."}]},
        {"narrative": [{"role": "review", "content": "The paper is sound."}]},
        {"narrative": [{"title": "Methods", "content": "Sound."}]},
        {"narrative": [{"content": ""}, {"content": "Sound."}]},
        {"opinion": {"stance": "positive"}},
        {"opinion": {"high_level_reasons": ["The method is new."]}},
        {"findings": {"weaknesses": [{"title": "No ablation", "text": ""}]}},
        {"decision": {"summary_rationale": "The results hold up."}},
        {"ethics_and_risk": {"ethical_concerns": True}},
        {"ethics_and_risk": {"notes": "The dataset exposes participant identities."}},
        {"ethics_and_risk": {"concern_categories": ["privacy"]}},
        {"findings": {"changes": [{"text": "Anonymize the dataset.", "scope": "ethics"}]}},
        {"decision": {"source_label": "Accept (Oral)"}},
        {"written_report": {"content_type": "pdf", "filename": "review.pdf"}},
    ],
)
def test_a_migrated_review_with_any_assessment_has_content(content: dict) -> None:
    review = migrate(_review_saying(**content))
    validate_canonical(review)
    assert has_content(review)


@pytest.mark.parametrize("flagged", [True, False])
def test_a_review_of_only_the_citations_is_a_review(flagged: bool) -> None:
    """A citation review checks the references and says nothing else, not even a summary."""
    reference = {
        "target": {"type": "bibliography", "ref": "12"},
        "status": "Not found" if flagged else "Verified",
        "flagged": flagged,
    }
    review = _review_saying(
        review_context={"review_type": "citation_review"},
        checks=[{"kind": "reference_verification", "items": [reference]}],
    )
    review = migrate(review)
    validate_canonical(review)
    assert has_content(review)


@pytest.mark.parametrize(
    "content",
    [
        {},
        {"findings": {}},
        {"findings": {"strengths": [], "changes": []}},
        {"decision": {"credence": 0.8}},
        {"metrics": [], "checks": [], "claim_assessments": [], "artifact_assessments": []},
        {"narrative": [{"role": "review", "content": ""}]},
        {"narrative": [{"title": "Methods", "content": ""}]},
        {"narrative": [{"role": "summary", "content": "  \n"}]},
        {"opinion": {"summary": " ", "high_level_reasons": ["", " "], "contributions": []}},
        {"findings": {"strengths": [{"text": ""}], "comments": [{"title": " ", "text": " "}]}},
        {"decision": {"credence": 0.8, "summary_rationale": ""}},
        {"ethics_and_risk": {"ethical_concerns": False, "notes": "", "concern_categories": []}},
        {"decision": {"source_label": " "}},
    ],
)
def test_a_review_that_says_nothing_is_invalid(content: dict) -> None:
    review = _review_saying(**content)
    assert not has_content(review)
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(review)
