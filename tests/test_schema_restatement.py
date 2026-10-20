# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Schema 0.7.2 restates 0.7.1: it defines repeated shapes once, in `$defs`, and accepts
and rejects exactly the reviews 0.7.1 does.

Both published copies are compared, so the test holds after later versions change the
schema. The reviews checked are the examples, the README and CONTRIBUTING blocks, each
mapper's output for its fixtures, and every review one edit away from small reviews that
use the restated parts: the content rule, a work's content hash, the AI referee,
probability and credence, and expertise. The work identifiers are among them, unchanged.
"""

import copy
import itertools
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ocrs import map_from
from ocrs.gaps import iter_schema_paths
from ocrs.mappers.openreview_page import reviews_from_forum_page
from ocrs.schema import _evidence_links

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PREVIOUS = json.loads((ROOT / "versions/v0.7.1/canonical-review.schema.json").read_text())
RESTATED = json.loads((ROOT / "versions/v0.7.2/canonical-review.schema.json").read_text())
CODE_BLOCK = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)

MINIMAL_REVIEW = {
    "review_id": "review-1",
    "version": "1.0.0",
    "created_at": "2026-10-06T12:00:00Z",
    "provenance": {"source_system": "example-journal"},
    "referee": {"referee_type": "human", "identity_mode": "double_blind"},
    "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
    "opinion": {"summary": "A sound paper."},
}
POINT = {"id": "p1", "title": "A title", "text": "A point."}
# Points whose only text is their text, or their title, so that one edit can blank them
POINTS = (POINT, {"text": "A point."}, {"title": "A title", "text": ""})
METRIC = {
    "key": "overall",
    "label": "Overall",
    "scale": {"type": "ordinal", "min": 1, "max": 5},
    "value": 4,
    "uncertainty": {"credence": 0.6, "interval": {"low": 3, "high": 5}, "rationale": "Why."},
}
CLAIM = {
    "claim_id": "c1",
    "claim_text": "The method is faster.",
    "status": "supported",
    "probability": 0.8,
    "credence": 0.5,
    "metrics": [METRIC],
}
AI_SYSTEM = {
    "critic_framework": {"name": "ReviewCritic", "version": "2.1.0"},
    "models": [{"role": "reviewer", "model_id": "model-1"}],
}
AI_EXECUTION = {"started_at": "2026-01-01T00:00:00Z", "ended_at": "2026-01-01T00:01:00Z"}
AI_FORMS = {
    "system": AI_SYSTEM,
    "execution": AI_EXECUTION,
    "inputs": {"prompts": [{"role": "system", "prompt_hash": "abc"}]},
    "outputs": {"token_usage": {"input_tokens": 10}},
    "safety": {"pii_handling": "redacted"},
    "reference": {"third_party_id": "newco-ai-ref-2sd4f6a", "version": "v2"},
}
IDENTIFIERS = {
    "doi": {"value": "10.1234/abc", "hyperlink": "https://doi.org/10.1234/abc"},
    "arxiv_id": {"value": "2401.12345v2"},
    "s2cid": {"value": "12345"},
    "pubmed_id": {"value": "12345"},
    "pmcid": {"value": "PMC5555555"},
    "openalex_id": {"value": "W2741809807"},
    "valency_id": {"value": "W_6r533gdt_v1"},
    "handle": {"value": "20.500.12345/abc"},
    "ark": {"value": "ark:/13030/tf5p30086k"},
    "isbn": {"value": "9780262035613"},
    "issn": {"value": "2050-084X"},
    "ecli": {"value": "ECLI:EU:C:2014:317"},
    "accession": {"value": "MN908947", "database": "GenBank"},
    "purl": "https://purl.org/x",
    "permalink": "https://example.org/x",
    "uuid": {"value": "123e4567-e89b-12d3-a456-426614174000"},
    "internal_id": {"field_name": "hotcrp_pid", "value": "42"},
    "content_hash": {"algorithm": "sha256", "value": "a1b2"},
}
EXPERTISE = {"self_reported_level": "expert", "domain_tags": ["nlp"]}

# Each holds one kind of review content, and nothing else: the content rule's branches.
CONTENT = [
    {"opinion": {"summary": "S"}},
    {"opinion": {"text": "T"}},
    {"opinion": {"stance": "mixed"}},
    {"opinion": {"high_level_reasons": ["R"]}},
    {"opinion": {"contributions": [{"title": "T", "text": "C", "claim_id": "c1"}]}},
    {"opinion": {"contributions": [{"text": "C"}]}},
    *(
        {"findings": {kind: [point]}}
        for kind in ("strengths", "weaknesses", "questions", "comments", "changes")
        for point in POINTS
    ),
    {"findings": {"changes": [{**POINT, "priority": "minor", "applies_to": {"section": "2"}}]}},
    {"decision": {"recommendation": "accept"}},
    {"decision": {"revision_requirement": "minor"}},
    {"decision": {"summary_rationale": "Why.", "confidence": 0.5}},
    {"metrics": [METRIC]},
    {"claim_assessments": [CLAIM]},
    {
        "artifact_assessments": [
            {"artifact_type": "code", "availability": "public", "assessment": "good"}
        ]
    },
    {"checks": [{"kind": "similarity", "outcome": "no_issues"}]},
    {"ethics_and_risk": {"ethical_concerns": True}},
    {"ethics_and_risk": {"notes": "N", "concern_categories": ["privacy"]}},
    *({"ethics_and_risk": {"required_mitigations": [point]}} for point in POINTS),
    {"narrative": {"summary": "S", "detailed_review": "D"}},
    {"narrative": {"author_questions": "Q", "confidential_to_editors": "C"}},
    {"narrative": {"sections": [{"title": "T", "content": "C"}]}},
    {"written_report": {"content_type": "pdf"}},
]
# Small reviews that use the restated parts, with the keys under which to edit them.
BASES = [
    *(({**MINIMAL_REVIEW, "opinion": {}, **content}, [*content]) for content in CONTENT),
    (
        {**MINIMAL_REVIEW, "target": {**MINIMAL_REVIEW["target"], "identifiers": IDENTIFIERS}},
        ["target"],
    ),
    (
        {
            **MINIMAL_REVIEW,
            "findings": {"weaknesses": [{"text": "W", "probability": 0.9, "credence": 0.3}]},
            "claim_assessments": [CLAIM],
        },
        ["findings", "claim_assessments"],
    ),
    (
        {
            **MINIMAL_REVIEW,
            "review_context": {"expertise": EXPERTISE},
            "referee": {**MINIMAL_REVIEW["referee"], "human_referee": {"expertise": EXPERTISE}},
        },
        ["review_context", "referee"],
    ),
    *(
        (
            {
                **MINIMAL_REVIEW,
                "referee": {"referee_type": "ai", "identity_mode": "open", "ai_referee": form},
            },
            ["referee"],
        )
        for form in (
            {k: v for k, v in AI_FORMS.items() if k != "reference"},
            {"reference": AI_FORMS["reference"]},
        )
    ),
]
REPLACEMENTS = (None, "", " \n", "x", 0, 0.5, 2, -1, True, [], {}, ["x"], [{}])
REMOVE = object()


def _paths(node, path):
    yield path
    if isinstance(node, dict):
        children = node.items()
    elif isinstance(node, list):
        children = enumerate(node)
    else:
        children = ()
    for key, child in children:
        yield from _paths(child, (*path, key))


def _edit(review, path, value):
    edited = copy.deepcopy(review)
    parent = edited
    for key in path[:-1]:
        parent = parent[key]
    if value is REMOVE:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    return edited


def _node(review, path):
    for key in path:
        review = review[key]
    return review


def one_edit_away(review, roots):
    """Every review one edit from `review` under the keys `roots`: each value removed,
    replaced by a blank or a value of another type, and each object given a key it does
    not define."""
    for path in itertools.chain.from_iterable(_paths(review[root], (root,)) for root in roots):
        yield _edit(review, path, REMOVE)
        for value in REPLACEMENTS:
            yield _edit(review, path, value)
        if isinstance(node := _node(review, path), dict):
            yield _edit(review, path, {**node, "unexpected": 1})


def ai_referee_key_sets():
    """An AI referee with every combination of its six keys."""
    for size in range(len(AI_FORMS) + 1):
        for keys in itertools.combinations(AI_FORMS, size):
            form = {key: AI_FORMS[key] for key in keys}
            yield {
                **MINIMAL_REVIEW,
                "referee": {"referee_type": "ai", "identity_mode": "open", "ai_referee": form},
            }


def documented_reviews():
    for path in sorted((ROOT / "examples").glob("*.json")):
        yield json.loads(path.read_text())
    for doc in ("README.md", "CONTRIBUTING.md"):
        for block in CODE_BLOCK.findall((ROOT / doc).read_text()):
            example = json.loads(block)
            yield example if "review_id" in example else {**MINIMAL_REVIEW, **example}


def mapped_reviews():
    for source, folder in [
        ("cmt", "cmt"),
        ("editorialmanager", "editorialmanager"),
        ("hotcrp", "hotcrp"),
        ("journal_narrative", "journal"),
        ("openreview", "openreview"),
        ("scholarone", "scholarone"),
    ]:
        for path in sorted((FIXTURES / folder).glob("*.json")):
            yield map_from(source, json.loads(path.read_text()), keep_raw=True)
    v2 = FIXTURES / "openreview_v2"
    for name in ("review", "meta_review", "decision"):
        yield map_from(
            "openreview",
            json.loads((v2 / f"{name}.json").read_text()),
            scale_bounds=json.loads((v2 / "scale_bounds.json").read_text()),
            submission=json.loads((v2 / "submission.json").read_text()),
        )
    yield from reviews_from_forum_page((FIXTURES / "openreview" / "forum_page.html").read_text())
    for source, name in [
        ("openaireview", "openaireview_paper.json"),
        ("deepreview", "deepreview_report.md"),
        ("reviewer3", "reviewer3_report.md"),
    ]:
        text = (FIXTURES / "ai" / name).read_text()
        yield map_from(
            source,
            {
                "output": json.loads(text) if name.endswith(".json") else text,
                "review_id": f"{source}-1",
                "source_system": source,
                "work_id": "doi:10.1234/abc",
                "work_type": "preprint",
                "started_at": "2026-10-15T17:00:00Z",
                "ended_at": "2026-10-15T17:30:00Z",
            },
        )


def reviews():
    yield from documented_reviews()
    yield from mapped_reviews()
    yield from ai_referee_key_sets()
    for review, roots in BASES:
        yield review
        yield from one_edit_away(review, roots)


@pytest.fixture(scope="module")
def corpus():
    return list(reviews())


def test_the_restated_schema_is_a_valid_schema():
    Draft202012Validator.check_schema(RESTATED)


def test_both_versions_accept_and_reject_the_same_reviews(corpus):
    previous, restated = Draft202012Validator(PREVIOUS), Draft202012Validator(RESTATED)
    verdicts = [(previous.is_valid(review), restated.is_valid(review)) for review in corpus]
    assert [i for i, (before, after) in enumerate(verdicts) if before != after] == []
    # The corpus reaches both verdicts, many times over.
    assert sum(before for before, _ in verdicts) > 100
    assert sum(not before for before, _ in verdicts) > 1000


def test_the_content_rule_follows_the_previous_one(corpus):
    """0.7.2's content rule, checked alone with the definitions it refers to, as `has_content`
    checked it, takes the same reviews as 0.7.1's."""
    [rule] = [r for r in PREVIOUS["allOf"] if r.get("$anchor") == "reviewContent"]
    previous = Draft202012Validator(rule)
    [rule] = [r for r in RESTATED["allOf"] if r.get("$anchor") == "reviewContent"]
    restated = Draft202012Validator({**rule, "$defs": RESTATED["$defs"]})
    assert [i for i, r in enumerate(corpus) if restated.is_valid(r) != previous.is_valid(r)] == []


def test_both_versions_allow_the_same_property_paths():
    assert set(iter_schema_paths(PREVIOUS, PREVIOUS)) == set(iter_schema_paths(RESTATED, RESTATED))


def test_both_versions_find_the_same_evidence_links(corpus):
    for review in corpus:
        before = {id(link) for link in _evidence_links(review, PREVIOUS, PREVIOUS)}
        after = {id(link) for link in _evidence_links(review, RESTATED, RESTATED)}
        assert before == after
