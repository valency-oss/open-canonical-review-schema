# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for roundtrip conversion between source formats and canonical schema."""

import importlib
import json
from pathlib import Path

import pytest

from ocrs import generate_canonical_work_id, map_from, map_to, validate_canonical


def test_openreview_to_canonical_and_back():
    openreview_note = {
        "id": "or_review_1",
        "forum": "or_forum_123",
        "cdate": 1735689600000,  # 2025-01-01T00:00:00Z
        "signatures": ["~Reviewer_One1"],
        "content": {
            "rating": "6: Weak Accept",
            "confidence": "4: confident",
            "summary": "Interesting paper with some gaps.",
            "review": (
                "The main idea is promising. However, the proof is missing key assumptions."
                "\n\nMore detail here."
            ),
            "soundness": 3,
            "clarity": 2,
            "strengths": ["Good motivation", "Solid empirical results"],
            "weaknesses": ["Proof incomplete"],
        },
    }
    canon = map_from("openreview", openreview_note, keep_raw=True)
    validate_canonical(canon)
    assert canon["provenance"]["source_system"] == "openreview"
    assert canon["opinion"]["summary"]
    note2 = map_to("openreview", canon)
    assert "content" in note2 and isinstance(note2["content"], dict)


def test_cmt_to_canonical_and_back():
    cmt = {
        "reviewId": "cmt_r1",
        "paperId": 42,
        "conferenceName": "NeurIPS 2026",
        "trackName": "Main",
        "reviewerId": "rev_77",
        "overallEvaluation": "7: Accept",
        "confidence": 0.8,
        "summary": "Strong contribution.",
        "commentsToAuthors": "Well-written and significant. Missing ablation.",
    }
    canon = map_from("cmt", cmt)
    validate_canonical(canon)
    back = map_to("cmt", canon)
    assert back["reviewId"] == "cmt_r1"
    assert "commentsToAuthors" in back


def test_journal_narrative_minimal():
    j = {
        "doi": "10.5555/12345678",
        "journal": "Journal of Tests",
        "full_text": (
            "This manuscript addresses an important problem. The methods are plausible but unclear."
            "\n\nPlease clarify the assumptions."
        ),
    }
    canon = map_from("journal_narrative", j)
    validate_canonical(canon)
    assert canon["opinion"]["summary"]
    back = map_to("journal_narrative", canon)
    assert back["full_text"]


def test_openreview_note_without_id_or_signature():
    canon = map_from("openreview", {"forum": "or_forum_123", "content": {"summary": "Fine."}})
    assert "referee_id" not in canon["referees"][0]
    assert "source_review_id" not in canon["provenance"]


FIXTURES = Path(__file__).parent / "fixtures"
# Each source's field for the paper ID, as map_to writes it back
SOURCE_ID_FIELD = {
    "openreview": "forum",
    "cmt": "paperId",
    "hotcrp": "pid",
    "scholarone": "documentId",
    "editorialmanager": "manuscriptId",
}


@pytest.mark.parametrize(
    "fixture",
    sorted(p for source in SOURCE_ID_FIELD for p in (FIXTURES / source).glob("*.json")),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_work_id_is_canonical_and_maps_back_to_the_source_id(fixture: Path) -> None:
    source = fixture.parent.name
    canon = map_from(source, json.loads(fixture.read_text()))
    target = canon["target"]
    assert target["work_id"] == generate_canonical_work_id(target["identifiers"])
    source_id = target["identifiers"]["internal_id"]["value"]
    # A system that numbers its papers gets the number back
    assert str(map_to(source, canon)[SOURCE_ID_FIELD[source]]) == source_id


def test_journal_narrative_maps_the_doi_back() -> None:
    canon = map_from(
        "journal_narrative",
        {
            "review_id": "r1",
            "doi": "10.1234/abc",
            "manuscript_id": "MS-1",
            "journal": "Example Journal",
            "full_text": "Fine.",
        },
    )
    assert canon["target"]["work_id"] == "doi:10.1234/abc"
    assert map_to("journal_narrative", canon)["doi"] == "10.1234/abc"


# Round trips through each source's own format. No mapper can be a bijection: OCRS holds
# more than any one format, and some formats hold what OCRS has no place for. What a round
# trip can do is give back what it took, and both directions are tested:
#
# - OCRS → source → OCRS: every review a mapper reads comes back the same when it is written
#   in its source's format and read again. Each writer is a left inverse of its reader.
# - Source → OCRS → source: a source review comes back with what OCRS holds of it. LOSSES
#   lists, for each fixture, exactly what it does not give back: `-` a value lost, `+` a
#   value gained, `~` a value changed, with list positions written `[]`. A fixture not
#   listed comes back whole. The test fails when a review loses something new, and when a
#   fix stops a listed loss, so that the table stays true.

OPENREVIEW_V2 = FIXTURES / "openreview_v2"
# What reading an OpenReview API v2 note needs besides the note
OPENREVIEW_V2_FORM = {
    "scale_bounds": json.loads((OPENREVIEW_V2 / "scale_bounds.json").read_text()),
    "submission": json.loads((OPENREVIEW_V2 / "submission.json").read_text()),
}
# What reading an AI reviewer's output needs besides the output
AI_RUN = {
    "review_id": "review-1",
    "source_system": "example-platform",
    "work_id": "doi:10.1234/abc",
    "work_type": "preprint",
    "started_at": "2026-10-15T17:00:00Z",
    "ended_at": "2026-10-15T17:30:00Z",
}
AI_SOURCES = {"openaireview", "deepreview", "reviewer3"}
SOURCE_REVIEWS = [
    *(
        pytest.param(source, path, {}, id=f"{folder}/{path.name}")
        for source, folder in [
            ("cmt", "cmt"),
            ("editorialmanager", "editorialmanager"),
            ("hotcrp", "hotcrp"),
            ("journal_narrative", "journal"),
            ("openreview", "openreview"),
            ("scholarone", "scholarone"),
        ]
        for path in sorted((FIXTURES / folder).glob("*.json"))
    ),
    *(
        pytest.param("openreview", path, OPENREVIEW_V2_FORM, id=f"openreview_v2/{path.name}")
        for path in (
            OPENREVIEW_V2 / f"{name}.json" for name in ("review", "meta_review", "decision")
        )
    ),
]
AI_REVIEWS = [
    pytest.param(source, FIXTURES / "ai" / name, {}, id=f"ai/{name}")
    for source, name in [
        ("openaireview", "openaireview_paper.json"),
        ("deepreview", "deepreview_report.md"),
        ("reviewer3", "reviewer3_report.md"),
    ]
]

# Source → OCRS → source. The AI reviewers' formats are checked in test_ai_writers.py,
# which compares the reports as their readers parse them.
LOSSES = {
    # A review that states no time gets the time of its import, which is written back
    "cmt/minimal_review.json": {"+ reviewDate"},
    "editorialmanager/minimal_review.json": {
        "+ dateReceived",
        # The recommendation is written with its code, as Editorial Manager gives it
        "+ recommendationCode",
    },
    "scholarone/minimal_review.json": {"+ dateReviewReceived"},
    # A review without an ID gets one on import, and it is written back
    "journal/minimal_review.json": {"+ created_at", "+ review_id"},
    # Fields OCRS has no place for
    "cmt/realistic_review.json": {
        "- bestPaperNomination",
        "- confidentialToPC",
        "- ethicsReview",
        "- reviewerEmail",
        "- submissionDate",
    },
    "editorialmanager/realistic_review.json": {
        "- articleType",
        "- dateDue",
        "- dateRequested",
        "- journalId",
        "- keywords",
        "- ratings[].questionId",
    },
    "editorialmanager/realistic_revision.json": {
        "- articleType",
        "- previousReviewId",
        "- ratings[].questionId",
    },
    # HotCRP's bookkeeping, and the reviewer's name in two parts, which the reader does not take
    "hotcrp/realistic_review.json": {
        "- ordinal",
        "- reviewer.first",
        "- reviewer.last",
        "- rtype",
        "- rtype_name",
        "- submitted",
    },
    # The note's bookkeeping, and form fields that are not part of the review. The time of
    # its last change comes back as `mdate`, beside `cdate`
    "openreview/realistic_review.json": {
        "+ mdate",
        "- content.code_of_conduct",
        "- content.title",
        "- invitation",
        "- readers",
        "- replyto",
        "- tcdate",
        "- tmdate",
        "- writers",
    },
    # The fixture's ORCID fails its checksum, so the reader does not keep it
    "scholarone/realistic_review.json": {
        "- articleType",
        "- criteriaResponses[].criterionId",
        "- dateReviewRequested",
        "- fundingStatement",
        "- journalCode",
        "- reviewerOrcid",
        "- specialIssue",
        "- submissionId",
    },
    # The writer writes API v1 notes, so a v2 note's `{"value": …}` fields come back
    # unwrapped, and its invitations as one invitation that names the kind of note. A
    # recommendation is one of OCRS's values: "Accept (Poster)" comes back "Accept"
    "openreview_v2/review.json": {
        "- content.code_of_conduct",
        "- invitations",
        "- number",
        "- readers",
        "- replyto",
        "~ content.clarity",
        "~ content.confidence",
        "~ content.quality",
        "~ content.questions",
        "~ content.rating",
        "~ content.strengths",
        "~ content.summary",
        "~ content.weaknesses",
    },
    "openreview_v2/meta_review.json": {
        "+ invitation",
        "- invitations",
        "- replyto",
        "~ content.confidence",
        "~ content.metareview",
        "~ content.recommendation",
    },
    "openreview_v2/decision.json": {
        "+ invitation",
        "- invitations",
        "- replyto",
        "~ content.comment",
        "~ content.decision",
    },
}


@pytest.fixture
def frozen_clock(monkeypatch):
    """A review that states no time takes the time of its import, so two imports of it
    agree only when the clock stands still."""
    for name in ("cmt", "editorialmanager", "hotcrp", "journal", "openreview", "scholarone"):
        monkeypatch.setattr(
            importlib.import_module(f"ocrs.mappers.{name}"),
            "now_iso",
            lambda: "2026-01-01T00:00:00Z",
        )


def load(path: Path):
    return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()


def read(source: str, payload, form: dict):
    if source in AI_SOURCES:
        return map_from(source, {"output": payload, **AI_RUN})
    return map_from(source, payload, **form)


def differences(before, after, path: str = "") -> set[str]:
    """What changed from `before` to `after`: `-` lost, `+` gained, `~` changed."""
    if isinstance(before, dict) and isinstance(after, dict):
        found = set()
        for key in before.keys() | after.keys():
            child = f"{path}.{key}" if path else key
            if key not in after:
                found.add(f"- {child}")
            elif key not in before:
                found.add(f"+ {child}")
            else:
                found |= differences(before[key], after[key], child)
        return found
    if isinstance(before, list) and isinstance(after, list):
        found = {f"- {path}[]"} if len(after) < len(before) else set()
        found |= {f"+ {path}[]"} if len(after) > len(before) else set()
        for item_before, item_after in zip(before, after, strict=False):
            found |= differences(item_before, item_after, f"{path}[]")
        return found
    return set() if before == after and type(before) is type(after) else {f"~ {path}"}


def without_import_time(review: dict) -> dict:
    """The review without the time of its import, which no two imports share."""
    provenance = {k: v for k, v in review["provenance"].items() if k != "imported_at"}
    return {**review, "provenance": provenance}


def fixture_key(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.mark.parametrize(("source", "path", "form"), SOURCE_REVIEWS + AI_REVIEWS)
@pytest.mark.usefixtures("frozen_clock")
def test_a_review_written_in_its_source_format_reads_back_the_same(source, path, form):
    review = read(source, load(path), form)
    again = read(source, map_to(source, review), form)
    assert differences(without_import_time(review), without_import_time(again)) == set()


@pytest.mark.parametrize(("source", "path", "form"), SOURCE_REVIEWS)
@pytest.mark.usefixtures("frozen_clock")
def test_a_source_review_read_and_written_back_is_given_back_as_listed(source, path, form):
    payload = load(path)
    written = map_to(source, read(source, payload, form))
    assert differences(payload, written) == LOSSES.get(fixture_key(path), set())


def test_the_loss_table_names_only_fixtures_that_are_tested():
    assert set(LOSSES) <= {fixture_key(param.values[1]) for param in SOURCE_REVIEWS}


WRITERS = ["cmt", "editorialmanager", "hotcrp", "openreview", "scholarone"]


def written_review(source_system: str, **fields) -> dict:
    """A small review, as if read from `source_system`."""
    return {
        "review_id": "review-1",
        "version": "1.0.0",
        "created_at": "2025-01-01T00:00:00Z",
        "provenance": {"source_system": source_system},
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "internal_id:paperId:7", "work_type": "article"},
        "opinion": {"summary": "A sound paper."},
        **fields,
    }


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("read_from", ["same", "elsewhere"])
@pytest.mark.parametrize(
    "decision", [{"revision_requirement": "major"}, {"recommendation": "weak_accept"}]
)
def test_a_score_label_that_does_not_say_the_decision_does_not_replace_it(
    writer, read_from, decision
):
    """A score's label is written back only when it reads back as the review's decision."""
    scale = {"type": "ordinal", "min": 1, "max": 5}
    overall = {"key": "overall", "label": "Overall", "scale": scale, "value": 4}
    review = written_review(
        writer if read_from == "same" else "elsewhere",
        decision=decision,
        metrics=[{**overall, "justification": "Excellent"}],
    )
    again = map_from(writer, map_to(writer, review))
    assert {k: again["decision"].get(k) for k in decision} == decision


@pytest.mark.parametrize("writer", WRITERS)
def test_a_list_valued_score_with_a_label_is_written(writer):
    """A score may be a list of values; it is written as it is, without its label."""
    tags = {
        "key": "other",
        "label": "topics",
        "scale": {"type": "categorical"},
        "value": ["theory", "systems"],
        "justification": "Two topics",
    }
    review = written_review(writer, decision={"recommendation": "accept"}, metrics=[tags])
    again = map_from(writer, map_to(writer, review))
    validate_canonical(again)
    assert again["decision"]["recommendation"] == "accept"


@pytest.mark.parametrize(
    ("label", "kept"),
    [("Minor Revision", True), ("Publish as is", True), ("Excellent", True), ("Reject", False)],
)
def test_scholarone_keeps_a_recommendation_label_unless_it_says_another(label, kept):
    """With a code, the code says the recommendation and the source's label is kept, unless
    it says a different recommendation."""
    scale = {"type": "ordinal", "min": 1, "max": 5}
    overall = {"key": "overall", "label": "Overall", "scale": scale, "value": 2}
    review = written_review(
        "elsewhere",
        decision={"revision_requirement": "minor"},
        metrics=[{**overall, "justification": label}],
    )
    written = map_to("scholarone", review)
    assert written["overallRecommendation"] == 2
    assert ("overallRecommendationLabel" in written) is kept
    assert map_from("scholarone", written)["decision"] == {"revision_requirement": "minor"}


@pytest.mark.parametrize("writer", ["cmt", "hotcrp"])
def test_a_score_labelled_by_its_form_keeps_the_label_in_another_system(writer):
    """OpenReview's form names its scores' values ("Accept: Technically solid paper"), so a
    note gives the number alone; another system needs the label written to read the same
    recommendation from the score."""
    review = read("openreview", load(OPENREVIEW_V2 / "review.json"), OPENREVIEW_V2_FORM)
    again = map_from(writer, map_to(writer, review))
    assert again["decision"]["recommendation"] == review["decision"]["recommendation"]


def test_a_decision_note_keeps_its_revision_beside_a_score():
    """The reader takes the recommendation from the score before a Decision note's own
    `decision` field, so a decision the score does not say goes in the score's label."""
    scale = {"type": "ordinal", "min": 1, "max": 10}
    review = written_review(
        "openreview",
        review_context={"review_type": "recommendation"},
        decision={"revision_requirement": "major"},
        metrics=[{"key": "overall", "label": "rating", "scale": scale, "value": 4}],
    )
    again = map_from("openreview", map_to("openreview", review))
    assert again["decision"] == {"revision_requirement": "major"}
    assert again["review_context"] == {"review_type": "recommendation"}


def test_an_openreview_score_goes_back_to_its_own_field():
    """A score keeps its field, so the form's bounds for it apply when it is read again."""
    bounds = {"overall_rating": {"min": 1, "max": 10}}
    note = {"id": "n1", "forum": "f1", "content": {"summary": "S.", "overall_rating": 4}}
    review = map_from("openreview", note, scale_bounds=bounds)
    written = map_to("openreview", review)
    assert written["content"]["overall_rating"] == 4
    again = map_from("openreview", written, scale_bounds=bounds)
    assert again["decision"] == review["decision"] == {"recommendation": "weak_reject"}


@pytest.mark.parametrize("writer", ["cmt", "hotcrp", "openreview"])
def test_an_overall_score_that_is_a_list_leaves_the_recommendation_to_its_field(writer):
    scale = {"type": "categorical"}
    overall = {"key": "overall", "label": "rating", "scale": scale, "value": ["a", "b"]}
    review = written_review(
        writer,
        decision={"recommendation": "accept"},
        metrics=[{**overall, "justification": "Accept"}],
    )
    assert map_from(writer, map_to(writer, review))["decision"]["recommendation"] == "accept"


@pytest.mark.parametrize("writer", ["cmt", "hotcrp", "openreview"])
def test_an_overall_score_that_is_not_a_number_makes_up_no_recommendation(writer):
    """The readers take a recommendation from the overall score's field and read only a number
    there, so a score of another kind is left out rather than read back as a verdict."""
    overall = {"key": "overall", "label": "rating", "scale": {"type": "textual"}, "value": "Strong"}
    again = map_from(writer, map_to(writer, written_review(writer, metrics=[overall])))
    assert "recommendation" not in again.get("decision", {})


@pytest.mark.parametrize(
    ("writer", "payload"),
    [
        ("editorialmanager", {"reviewId": "r", "manuscriptId": "m"}),
        ("scholarone", {"documentId": "d", "reviewerNumber": 1}),
    ],
)
@pytest.mark.usefixtures("frozen_clock")
def test_a_summary_beside_the_comments_is_given_back(writer, payload):
    payload = {**payload, "summary": "Short summary.", "commentsToAuthor": "Long review."}
    review = map_from(writer, payload)
    written = map_to(writer, review)
    assert written["summary"] == "Short summary."
    assert without_import_time(map_from(writer, written)) == without_import_time(review)


@pytest.mark.parametrize("writer", ["cmt", "hotcrp", "openreview"])
@pytest.mark.parametrize("value", [True, "Strong", ["theory", "systems"]])
def test_a_score_that_is_not_a_number_is_written_as_it_is(writer, value):
    """The readers take a label only after a number, so another value is written alone."""
    metric = {"key": "other", "label": "topics", "scale": {"type": "categorical"}}
    review = written_review(writer, metrics=[{**metric, "value": value, "justification": "Why"}])
    written = map_to(writer, review)
    assert (written.get("content") or written)["topics"] == value


@pytest.mark.parametrize(
    ("writer", "name"),
    [("cmt", "overallEvaluation"), ("hotcrp", "overall merit"), ("openreview", "rating")],
)
def test_another_score_does_not_take_the_recommendations_field(writer, name):
    """A score that is not the overall one, named after the field the reader takes the
    recommendation from, is not written there ahead of the overall score."""
    scale = {"type": "ordinal", "min": 1, "max": 5}
    review = written_review(
        writer,
        decision={"recommendation": "reject"},
        metrics=[
            {"key": "other", "label": name, "scale": scale, "value": 5},
            {
                "key": "overall",
                "label": "Overall",
                "scale": scale,
                "value": 1,
                "justification": "Reject",
            },
        ],
    )
    assert map_from(writer, map_to(writer, review))["decision"]["recommendation"] == "reject"


@pytest.mark.parametrize("content", [{"recommendation": "Weak Reject"}, {}])
def test_an_overall_score_on_a_field_without_a_recommendation_stays_there(content):
    """`overall_score` is no recommendation field: the score goes back to it, with the form's
    bounds, and a review without a recommendation gets none."""
    bounds = {"overall_score": {"min": 1, "max": 10}}
    note = {"id": "n1", "forum": "f1", "content": {"summary": "S.", "overall_score": 6, **content}}
    review = map_from("openreview", note, scale_bounds=bounds)
    written = map_to("openreview", review)
    assert written["content"]["overall_score"] == 6
    assert "rating" not in written["content"]
    again = map_from("openreview", written, scale_bounds=bounds)
    assert again.get("decision") == review.get("decision")
    assert again["metrics"] == review["metrics"]


@pytest.mark.parametrize("writer", ["cmt", "hotcrp", "openreview"])
@pytest.mark.parametrize(
    ("value", "label"), [(1e-06, "Tiny"), (6, "Weak accept,\nwith reservations")]
)
def test_a_labelled_score_reads_back_the_same(writer, value, label):
    """A score is written without an exponent, and a label may run over several lines."""
    metric = {"key": "other", "label": "novelty", "scale": {"type": "interval"}, "value": value}
    review = written_review(writer, metrics=[{**metric, "justification": label}])
    [again] = map_from(writer, map_to(writer, review))["metrics"]
    assert (again["value"], again["justification"]) == (value, label)


@pytest.mark.parametrize(
    "source, payload",
    [
        (
            "openreview",
            {"id": "r1", "forum": "f1", "content": {"summary": "S.", "recommendation": "Not sure"}},
        ),
        (
            "cmt",
            {
                "reviewId": "r1",
                "paperId": 1,
                "recommendation": "Not sure",
                "commentsToAuthors": "T.",
            },
        ),
        ("hotcrp", {"pid": 1, "rid": 2, "overall_merit": "Not sure", "comments": "T."}),
    ],
)
def test_a_recommendation_in_words_that_name_none_keeps_them(source, payload):
    """The readers take words that name no recommendation as borderline, and the writers give
    the words back rather than "Borderline"."""
    review = map_from(source, payload)
    assert review["decision"] == {"recommendation": "borderline", "source_label": "Not sure"}
    assert map_from(source, map_to(source, review))["decision"] == review["decision"]


def test_words_beside_a_score_that_would_read_as_another_recommendation_keep_their_field():
    """'Not sure' beside an 8 would read back as the 8's accept, so it stays in its own field,
    which the reader takes the recommendation from first."""
    note = {"id": "r1", "forum": "f1", "content": {"summary": "S.", "recommendation": "Not sure"}}
    note["content"]["rating"] = 8
    review = map_from("openreview", note)
    written = map_to("openreview", review)
    assert written["content"] == note["content"]
    assert map_from("openreview", written)["decision"] == review["decision"]


@pytest.mark.parametrize("source", ["cmt", "hotcrp"])
def test_a_score_carries_a_recommendation_its_number_would_not_read_as(source):
    review = {
        "review_id": "r1",
        "version": "1.0.0",
        "created_at": "2026-10-06T12:00:00Z",
        "provenance": {"source_system": "example-journal"},
        "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
        "target": {"work_id": "internal_id:manuscript_id:p1", "work_type": "article"},
        "opinion": {"summary": "S."},
        "decision": {"recommendation": "borderline", "source_label": "Not sure"},
        "metrics": [
            {
                "key": "overall",
                "label": "Overall",
                "value": 4,
                "scale": {"type": "ordinal", "min": 1, "max": 5},
            }
        ],
    }
    again = map_from(source, map_to(source, review))
    assert again["decision"]["recommendation"] == "borderline"


@pytest.mark.parametrize(
    "target", ["openreview", "cmt", "hotcrp", "editorialmanager", "scholarone"]
)
def test_a_recommendation_ocrs_cannot_name_keeps_its_words_in_every_form(target):
    """A JATS term OCRS cannot name is written in its words. Readers that take such words as
    borderline add that, and keep the words."""
    review = map_from(
        "jats",
        {
            "sub_article": (
                '<sub-article id="r1"><front-stub><custom-meta-group><custom-meta><meta-name>'
                "recommendation</meta-name><meta-value>approve-in-part</meta-value></custom-meta>"
                "</custom-meta-group></front-stub><body><p>Fine.</p></body></sub-article>"
            )
        },
    )
    assert review["decision"] == {"source_label": "approve-in-part"}
    again = map_from(target, map_to(target, review))
    assert again["decision"]["source_label"] == "approve-in-part"
    assert again["decision"].get("recommendation") in (None, "borderline")


def test_scholarone_writes_the_words_beside_the_code_it_makes():
    note = {"id": "r1", "forum": "f1", "content": {"summary": "S.", "decision": "Accept (Oral)"}}
    review = map_from("openreview", note)
    written = map_to("scholarone", review)
    assert (written["overallRecommendation"], written["overallRecommendationLabel"]) == (
        1,
        "Accept (Oral)",
    )
    again = map_from("scholarone", written)
    assert again["decision"] == {"recommendation": "accept"}
    assert [m.get("justification") for m in again["metrics"] if m["key"] == "overall"] == [
        "Accept (Oral)"
    ]
