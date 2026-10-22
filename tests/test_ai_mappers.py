# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the OpenAIReview mapper, its mapping records and gaps."""

import copy
import json
from pathlib import Path

import pytest

from ocrs import (
    map_from,
    map_with_record,
    render_mapping_markdown,
    supported_sources,
    validate_canonical,
)
from ocrs.anchors import Block, BlockKind, find_quote
from ocrs.mappers.ai import Recorder
from ocrs.mapping import MappingStatus, Rule

FIXTURES = Path(__file__).parent / "fixtures" / "ai"
OPENAIREVIEW = json.loads((FIXTURES / "openaireview_paper.json").read_text())
BLOCKS = json.loads((FIXTURES / "paper_blocks.json").read_text())
RUN = {
    "review_id": "3152f8d9-a9e9-4d97-80be-e6b0d7290d42",
    "source_system": "example-platform",
    "requested_by": "example-platform",
    "work_id": "paper-1",
    "work_type": "preprint",
    "work_version": "4b1c7e53-ef3c-4309-99ac-f0c599cbf194",
    "reviewer_commit": "27740f8434cfc0ffee0000000000000000000000",
    "model_id": "us.anthropic.claude-opus-5-5",
    "started_at": "2026-10-03T01:00:00Z",
    "ended_at": "2026-10-03T01:08:00Z",
    "cost_usd": 3.04,
}
COMMENTS = "methods.progressive__us.anthropic.claude-opus-5-5.comments"


def _payload(output):
    """map_with_record's arguments, as map_from's payload."""
    return {"output": copy.deepcopy(output), **RUN, "blocks": BLOCKS}


def _weaknesses(review):
    return review["findings"]["weaknesses"]


class TestOpenAIReview:
    def test_maps_merged_comments(self):
        result = map_with_record("openaireview", **_payload(OPENAIREVIEW))
        validate_canonical(result.review)
        assert result.record.status == MappingStatus.OK
        [method] = [m for k, m in OPENAIREVIEW["methods"].items() if k.startswith("progressive__")]
        weaknesses = _weaknesses(result.review)
        assert [w["title"] for w in weaknesses] == [c["title"] for c in method["comments"]]
        assert weaknesses[0]["text"] == method["comments"][0]["explanation"]
        assert weaknesses[0]["tags"] == [method["comments"][0]["comment_type"]]
        assert result.review["opinion"]["summary"] == method["overall_feedback"]

    def test_records_where_each_quote_was_found(self):
        result = map_with_record("openaireview", **_payload(OPENAIREVIEW))
        links = [w["evidence_links"][0] for w in _weaknesses(result.review)]
        assert {link["resource"]["type"] for link in links} == {"work"}
        anchored = (Rule.ANCHORED_EXACT, Rule.ANCHORED_FUZZY)
        anchors = [step for step in result.record.steps if step.rule in anchored]
        assert [(step.source, step.rule) for step in anchors] == [
            (f"{COMMENTS}[0].quote", Rule.ANCHORED_EXACT),
            (f"{COMMENTS}[2].quote", Rule.ANCHORED_FUZZY),
        ]
        assert anchors[0].result == {"part": "body", "block_id": "ecrossimz2"}

    def test_gaps(self):
        gaps = map_with_record("openaireview", **_payload(OPENAIREVIEW)).record.gaps
        assert [quote.source for quote in gaps.unanchored] == [f"{COMMENTS}[1].quote"]
        unmapped = {field.path for field in gaps.unmapped}
        assert "methods.progressive__*.comments[].paragraph_index" in unmapped
        assert not any(path.startswith("paragraphs") for path in unmapped)
        assert not any("progressive_original" in path for path in unmapped)
        assert "findings.weaknesses[].severity" in gaps.unfilled

    def test_unmapped_fields_kept_in_extensions(self):
        result = map_with_record("openaireview", **_payload(OPENAIREVIEW))
        kept = result.review["extensions"]["openaireview"]
        assert set(kept) == {"slug", "title", "methods"}
        assert "paragraphs" not in kept

    def test_run_details(self):
        review = map_from("openaireview", _payload(OPENAIREVIEW))
        framework = review["referees"][0]["ai_referee"]["system"]["critic_framework"]
        assert framework == {
            "name": "openaireview",
            "version": "27740f8434cf",
            "commit": RUN["reviewer_commit"],
        }
        assert review["provenance"]["source_system"] == "example-platform"
        assert review["provenance"]["mapping"] == {
            "mapping_spec_id": "canonical-review.mapping.v1",
            "mapping_spec_version": "1.2.0",
            "mapper_version": "1.1.0",
        }
        assert review["target"]["version"] == RUN["work_version"]
        assert review["review_context"] == {"requested_by": "example-platform"}

    def test_comment_without_explanation_is_skipped(self):
        output = copy.deepcopy(OPENAIREVIEW)
        [key] = [k for k in output["methods"] if k.startswith("progressive__")]
        output["methods"][key]["comments"][1]["explanation"] = ""
        result = map_with_record("openaireview", **_payload(output))
        assert result.record.status == MappingStatus.PARTIAL
        assert [item.source for item in result.record.skipped] == [f"{COMMENTS}[1]"]
        assert len(_weaknesses(result.review)) == 2


class TestRecord:
    def test_steps_name_rules(self):
        steps = map_with_record("openaireview", **_payload(OPENAIREVIEW)).record.steps
        rules = {(step.source, step.rule) for step in steps}
        assert (f"{COMMENTS}[0].title", Rule.COPIED) in rules
        assert (f"{COMMENTS}[2].quote", Rule.ANCHORED_FUZZY) in rules

    def test_markdown(self):
        result = map_with_record("openaireview", **_payload(OPENAIREVIEW))
        markdown = render_mapping_markdown(result)
        assert markdown.startswith("# openaireview review mapped to OCRS")
        assert "| Unanchored | 1 of 3 quotes |" in markdown
        assert "`methods.progressive__*.comments[].paragraph_index`" in markdown
        assert f"### `{COMMENTS}[0]` → `findings.weaknesses[0]`" in markdown


class TestFindQuote:
    blocks = [
        Block(id="b1", text="We train on **ten** datasets [ref-3](#ref-ref-3)."),
        Block(kind=BlockKind.ABSTRACT, text="A short abstract about citation sets."),
    ]

    def test_exact_after_normalising(self):
        match, _ = find_quote("we train on ten datasets.", self.blocks)
        assert match is not None and match.exact and match.block.id == "b1"

    def test_fuzzy(self):
        match, score = find_quote("A short abstract about the citation sets.", self.blocks)
        assert match is not None and not match.exact and score >= 0.9
        assert match.block.kind == BlockKind.ABSTRACT

    @pytest.mark.parametrize("quote", ["Something the paper never says at all.", ""])
    def test_not_found(self, quote):
        match, score = find_quote(quote, self.blocks)
        assert match is None and score < 0.9


def test_run_times_need_a_timezone():
    run = {**RUN, "started_at": "2026-10-03T01:00:00"}
    with pytest.raises(ValueError):
        map_with_record("openaireview", OPENAIREVIEW, **run, blocks=BLOCKS)


def test_without_a_paper_quotes_are_copied_but_not_checked():
    result = map_with_record("openaireview", OPENAIREVIEW, **RUN)
    assert result.record.gaps.unanchored is None
    anchored = (Rule.ANCHORED_EXACT, Rule.ANCHORED_FUZZY)
    assert not [step for step in result.record.steps if step.rule in anchored]
    [key] = [k for k in OPENAIREVIEW["methods"] if k.startswith("progressive__")]
    link = _weaknesses(result.review)[0]["evidence_links"][0]
    quote = OPENAIREVIEW["methods"][key]["comments"][0]["quote"]
    assert (link["resource"]["type"], link["quote"]) == ("work", quote)
    assert "| Unanchored | not checked (no paper given) |" in render_mapping_markdown(result)


def test_map_from_keeps_the_raw_output_when_asked():
    assert "raw_payload" not in map_from("openaireview", _payload(OPENAIREVIEW))["provenance"]
    review = map_from("openaireview", _payload(OPENAIREVIEW), keep_raw=True)
    assert review["provenance"]["raw_payload"] == OPENAIREVIEW


def test_ai_reviewers_are_sources():
    assert "openaireview" in supported_sources()


class TestRecorder:
    def test_lookup_maps_a_known_value(self):
        recorder = Recorder(checks_quotes=False)
        table = {"high": "major"}
        assert recorder.lookup("x.level", "y.severity", "high", table) == "major"
        assert [(step.source, step.rule) for step in recorder.steps] == [("x.level", Rule.LOOKUP)]

    def test_lookup_records_an_unknown_value_as_coerced(self):
        recorder = Recorder(checks_quotes=False)
        assert recorder.lookup("x.level", "y.severity", "cosmetic", {"high": "major"}) is None
        [coercion] = recorder.coerced
        assert (coercion.source, coercion.original, coercion.result) == (
            "x.level",
            "cosmetic",
            None,
        )


class TestPickMethod:
    def test_the_only_method(self):
        output = {"methods": {"zero_shot__m": {"overall_feedback": "Fine.", "comments": []}}}
        review = map_with_record("openaireview", output, **RUN).review
        assert review["opinion"]["summary"] == "Fine."
        assert "findings" not in review

    def test_unmerged_alone_is_not_mapped(self):
        output = {"methods": {"progressive_original__m": {}, "a__m": {}, "b__m": {}}}
        with pytest.raises(ValueError, match="Cannot tell which OpenAIReview method"):
            map_with_record("openaireview", output, **RUN)

    def test_no_feedback_and_no_tokens(self):
        output = {"methods": {"progressive__m": {"comments": [{"explanation": "A gap."}]}}}
        review = map_with_record("openaireview", output, **RUN).review
        assert review["opinion"] == {}
        assert "outputs" not in review["referees"][0]["ai_referee"]
        assert _weaknesses(review) == [{"id": "comment-1", "text": "A gap."}]


def test_ocrs_version_when_the_package_is_not_installed(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    from ocrs.mappers import ai

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(ai, "version", missing)
    assert ai.ocrs_version() == "unknown"
