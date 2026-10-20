# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Round trips on real reviews.

tests/fixtures/real/ holds published reviews: OpenReview notes from ICLR, NeurIPS, COLM and
TMLR, eLife and F1000Research reports, and OpenAIReview's own outputs, each listed in
`sources.json` with where it came from, its license and when it was fetched
(`scripts/fetch_real_reviews.py` fetches them again). No real HotCRP, CMT, Editorial Manager or
ScholarOne export is public; HotCRP's, ScholarOne's and Editorial Manager's are samples in the
structure their APIs document.

The tests are those of test_roundtrip.py, run on these reviews: OCRS → source → OCRS gives
back the same review, and source → OCRS → source loses exactly what LOSSES lists.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_roundtrip import AI_RUN, differences, frozen_clock, without_import_time  # noqa: F401

from ocrs import map_from, map_to, validate_canonical
from ocrs.mappers import jats
from ocrs.util import narrative_text

REAL = Path(__file__).parent / "fixtures" / "real"
SOURCES = json.loads((REAL / "sources.json").read_text())


def note_kind(note: dict) -> str:
    """`Official_Review`, `Review`, `Meta_Review` or `Decision`, from the note's invitation."""
    return note["invitations"][0].rsplit("/-/", 1)[-1]


def form(source: dict, payload) -> dict:
    """What reading the review needs besides it: for an OpenReview note, the scales of the
    venue's form for its kind of note, and the submission it reviews."""
    if source["system"] != "openreview":
        return {}
    folder = (REAL / source["file"]).parent
    bounds = json.loads((folder / "scale_bounds.json").read_text())
    return {
        "scale_bounds": bounds.get(note_kind(payload)),
        "submission": json.loads((folder / "submission.json").read_text()),
    }


def openaireview_models(paper: dict) -> list[str]:
    """The models whose merged comments a paper.json holds, one review each."""
    return [m["model"] for key, m in paper["methods"].items() if key.startswith("progressive__")]


# Each real review, with what reading it needs. A paper.json is read once for each model
REVIEWS = [
    pytest.param(
        source["system"],
        source["file"],
        {"output_run": {**AI_RUN, "model_id": model}},
        id=f"{source['file']}[{model}]",
    )
    for source in SOURCES
    if source["system"] == "openaireview"
    for model in openaireview_models(json.loads((REAL / source["file"]).read_text()))
] + [
    pytest.param(
        source["system"],
        source["file"],
        form(source, json.loads((REAL / source["file"]).read_text())),
        id=source["file"],
    )
    for source in SOURCES
    if source["system"] != "openaireview"
]


@pytest.fixture
def clock(frozen_clock, monkeypatch):  # noqa: F811
    """frozen_clock, and the JATS mapper's clock: eLife's sub-articles state no date."""
    monkeypatch.setattr(jats, "now_iso", lambda: "2026-01-01T00:00:00Z")


def xml_tree(element: ET.Element) -> dict:
    """An XML element as a dict, to compare: its attributes as `@name`, its text and the text
    after its children as `#text` and `#tail`, and its children as lists by tag."""
    tree: dict = {f"@{k.split('}')[-1]}": v for k, v in element.attrib.items()}
    text = " ".join((element.text or "").split())
    tails = " ".join(" ".join((child.tail or "").split()) for child in element).strip()
    tree |= {"#text": text} if text else {}
    tree |= {"#tail": tails} if tails else {}
    for child in element:
        tree.setdefault(child.tag, []).append(xml_tree(child))
    return tree


def comparable(system: str, payload):
    """A source review as the loss table compares it: a JATS sub-article as its XML tree."""
    if system == "jats":
        return {**payload, "sub_article": xml_tree(ET.fromstring(payload["sub_article"]))}
    return payload


def read(system: str, payload, how: dict) -> dict:
    if "output_run" in how:
        return map_from(system, {"output": payload, **how["output_run"]})
    return map_from(system, payload, **how)


@pytest.mark.parametrize(("system", "file", "how"), REVIEWS)
@pytest.mark.usefixtures("clock")
def test_a_real_review_written_in_its_source_format_reads_back_the_same(system, file, how):
    review = read(system, json.loads((REAL / file).read_text()), how)
    validate_canonical(review)
    again = read(system, map_to(system, review), how)
    assert differences(without_import_time(review), without_import_time(again)) == set()


# Source → OCRS → source, for each real review: `-` a value lost, `+` a value gained, `~` a
# value changed, as in test_roundtrip.LOSSES. A review not listed comes back whole.


def unwrapped(*fields: str) -> set[str]:
    """API v2 fields, which come back unwrapped: the writer writes API v1 notes."""
    return {f"~ content.{field}" for field in fields}


def renamed(**names: str) -> set[str]:
    """Fields that come back under the name the writer gives what the reader took from them."""
    return {
        change for old, new in names.items() for change in (f"- content.{old}", f"+ content.{new}")
    }


# The note's bookkeeping, which OCRS has no place for. Its license comes back, from
# provenance.license
NOTE = {
    "- domain",
    "- invitations",
    "- nonreaders",
    "- number",
    "- readers",
    "- replyto",
    "- tcdate",
    "- tmdate",
    "- version",
    "- writers",
}
# ICLR 2026 notes also name the invitations theirs came from
ICLR_2026 = NOTE | {"- parentInvitations"}
# A meta-review or a decision comes back with one invitation that names its kind of note
KIND = {"+ invitation"}
# The ICLR and NeurIPS review form: its scores, text and ethics-review flag, and the
# reviewer's assent to the code of conduct, which is not part of the review
ICLR_REVIEW = {"- content.code_of_conduct"} | unwrapped(
    "confidence",
    "contribution",
    "flag_for_ethics_review",
    "presentation",
    "questions",
    "rating",
    "soundness",
    "strengths",
    "summary",
    "weaknesses",
)
# A decision's title ("Paper Decision") is the form's, not the decider's
DECISION = KIND | {"- content.title"} | unwrapped("decision")
# COLM's review: its reasons to accept and reject, which are strengths and weaknesses, and its
# questions to the authors come back as written
COLM_REVIEW = NOTE | unwrapped(
    "confidence", "ethics_flag", "rating", "reasons_to_accept", "reasons_to_reject", "summary"
)
# TMLR's review: its summary of contributions is the summary, its strengths and weaknesses the
# review's text, each written back to its own field; its notes give no `nonreaders`
TMLR_REVIEW = (NOTE - {"- nonreaders"}) | unwrapped(
    "summary_of_contributions", "strengths_and_weaknesses"
)
TMLR_REVIEW |= unwrapped("audience", "broader_impact_concerns", "claims_and_evidence")
TMLR_REVIEW |= unwrapped("requested_changes")
# The NeurIPS 2024 Datasets and Benchmarks track's review
DATASETS_REVIEW = NOTE | {"- content.title"} | unwrapped("summary_and_contributions")
DATASETS_REVIEW |= unwrapped(
    "additional_feedback",
    "clarity",
    "confidence",
    "correctness",
    "documentation",
    "ethics",
    "flag_for_ethics_review",
    "limitations",
    "opportunities_for_improvement",
    "rating",
    "relation_to_prior_work",
    "review",
    "strengths",
)


def renamed_top(**names: str) -> set[str]:
    """Top-level fields that come back under the name the writer gives them."""
    return {change for old, new in names.items() for change in (f"- {old}", f"+ {new}")}


# What the writers of ScholarOne and Editorial Manager give back of the record their web
# services (getReviewerInfoFull) return. The reviewer comes back as the reader takes them: an
# ID, a name, an affiliation (the first department's) and an ORCID; the recommendation as
# text, without the journal's numeric value for it; the score sheet's numbers as criteria or
# ratings, and only its text answers as score-sheet questions, without their IDs. The record's
# bookkeeping and the dates of the reviewer's invitation, assignment and deadline, which OCRS
# has no place for, are lost
SERVICE_RECORD = {
    "+ reviewerAffiliation",
    "+ reviewerId",
    "+ reviewerName",
    "+ reviewerOrcid",
    "- departments",
    "- reviewerFullName",
    "- reviewerORCIDId",
    "- reviewerRecommendation",
    "- scoreSheetCompletedDate",
    "- reviewerRecommendationNumericValue",
    "- inputIndex",
    "- reviewerAssignmentStatus",
    "- reviewerDateAssigned",
    "- reviewerDateInvited",
    "- scoreSheetDueDate",
    "- reviewerFirstName",
    "- reviewerLastName",
    "- reviewerSalutation",
    "- reviewerPrimaryEmailAddress",
    "- reviewerORCIDIdValidation",
    "- scoreSheetName",
    "- scoreSheetCustomQuestions[]",
    "- scoreSheetCustomQuestions[].answerType",
    "- scoreSheetCustomQuestions[].customQuestionId",
    "- scoreSheetCustomQuestions[].questionName",
    "- scoreSheetCustomQuestions[].questionStatus",
    "- scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerId",
    "- scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerName",
    "- scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerStatus",
    "- scoreSheetCustomQuestions[].scoreSheetCustomAnswer.numericValue",
    # The text answers come first, so the questions do not line up
    "~ scoreSheetCustomQuestions[].questionText",
    "~ scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerText",
}

# A JATS affiliation in parts (institution, city, country) comes back as one text
AFFILIATION_PARTS = {
    "+ sub_article.front-stub[].contrib-group[].contrib[].aff[].#text",
    "- sub_article.front-stub[].contrib-group[].contrib[].aff[].country",
    "- sub_article.front-stub[].contrib-group[].contrib[].aff[].institution",
}

LOSSES = {
    # JATS: eLife's assessment and its authors' response name affiliations in parts; the
    # response's quotes of the reports lose their `content-type`
    "jats/elife_100443_sa0.json": AFFILIATION_PARTS,
    "jats/elife_100443_sa3.json": AFFILIATION_PARTS
    | {
        "- sub_article.body[].disp-quote[].@content-type",
        "- sub_article.front-stub[].contrib-group[].contrib[].aff[].addr-line",
    },
    # An empty paragraph is not kept
    "jats/f1000_154672_report367849.json": {
        "+ sub_article.body[].p[].#text",
        "- sub_article.body[].p[]",
        "~ sub_article.body[].p[].#text",
    },
    # ICLR 2024 (a withdrawn submission's reviews)
    **{
        f"openreview/SJTSvRtGsN/official_review_{note}.json": NOTE | ICLR_REVIEW
        for note in ("0OAL4CMJcy", "W0VehSkHDz", "xZzCQESypD")
    },
    # ICLR 2025
    **{
        f"openreview/45rvZkJbuX/official_review_{note}.json": NOTE | ICLR_REVIEW
        for note in ("7qTIapO7GL", "G8RSJfLah2", "Gi0Y2ziQdN", "XHSZRUSJje")
    },
    "openreview/45rvZkJbuX/meta_review_8y3LUsPgFN.json": NOTE
    | KIND
    | unwrapped("metareview", "additional_comments_on_reviewer_discussion"),
    # An empty comment is not kept
    "openreview/45rvZkJbuX/decision_D7B4Alrbcx.json": NOTE | DECISION | {"- content.comment"},
    # ICLR 2026
    **{
        f"openreview/y3oHMcoItR/official_review_{note}.json": ICLR_2026 | ICLR_REVIEW
        for note in ("F57t6Rab9l", "MJSr1mbZan", "PZwCwlLtxZ")
    },
    "openreview/y3oHMcoItR/official_review_8245mXvN5V.json": ICLR_2026
    | ICLR_REVIEW
    | unwrapped("details_of_ethics_concerns"),
    "openreview/y3oHMcoItR/meta_review_cqnYimoTWt.json": ICLR_2026
    | KIND
    | unwrapped("summary", "reviewer_concerns", "reviewer_scores"),
    "openreview/y3oHMcoItR/decision_7G51pxEliY.json": ICLR_2026 | DECISION | {"- content.comment"},
    # NeurIPS 2024
    **{
        f"openreview/y8Rm4VNRPH/official_review_{note}.json": NOTE
        | ICLR_REVIEW
        | unwrapped("limitations")
        for note in ("hQNYHP50sF", "jq3aXcAGvg", "o2xPg2Q6RX")
    },
    "openreview/y8Rm4VNRPH/decision_8rnWnEtQSY.json": NOTE | DECISION | unwrapped("comment"),
    # NeurIPS 2024 Datasets and Benchmarks
    **{
        f"openreview/u7m2CG84BQ/official_review_{note}.json": DATASETS_REVIEW
        for note in ("1Tdm2PIzC6", "ZfMFUByqxu", "gNTgwR1yjh")
    },
    "openreview/u7m2CG84BQ/decision_uEYwZQkxHQ.json": NOTE | DECISION | unwrapped("comment"),
    # COLM 2024; two of its reviewers asked the authors no questions
    **{
        f"openreview/Ti67584b98/official_review_{note}.json": COLM_REVIEW
        for note in ("4hyzSpPXWL", "wAkraRm611")
    },
    **{
        f"openreview/Ti67584b98/official_review_{note}.json": COLM_REVIEW
        | unwrapped("questions_to_authors")
        for note in ("7vPwN4jhBp", "H0VXzifN1H")
    },
    "openreview/Ti67584b98/decision_YmItSNepAk.json": NOTE | DECISION | unwrapped("comment"),
    # TMLR. Its decision's recommendation ("Reject") is written as a decision's is
    **{
        f"openreview/rNsAQisgOo/review_{note}.json": TMLR_REVIEW
        for note in ("OXdnDIV02l", "iXvnhYWkLI", "yD4cisomcG")
    },
    "openreview/rNsAQisgOo/decision_8Y0iuEelW9.json": NOTE
    | KIND
    | renamed(recommendation="decision")
    | unwrapped("audience", "claims_and_evidence", "comment"),
    # HotCRP's API review object comes back in the fields the writer writes: the review's ID
    # as `id`, the time it was imported as `submitted_at` (it says no time of submission), the
    # reviewer under `reviewer`, and the default
    # form's fields under the names the reader takes them as. HotCRP's bookkeeping (`object`,
    # `ordinal`, `rtype`, `status`, `version`) and whether the review is `blind` are lost
    "hotcrp/documented_api_review.json": {
        "+ comments",
        "+ confidential_comments",
        "+ id",
        "+ overall_merit",
        "+ paper_summary",
        "+ reviewer_expertise",
        "+ submitted_at",
        "- ComAut",
        "- ComPC",
        "- OveMer",
        "- PapSum",
        "- RevExp",
        "- blind",
        "- object",
        "- ordinal",
        "- reviewer_email",
        "- rid",
        "- rtype",
        "- status",
        "- version",
        "~ reviewer",
    },
    # ScholarOne's and Editorial Manager's web-service record comes back in the fields their
    # writers write, so each field it shares with them comes back renamed
    "scholarone/documented_api_reviewer.json": SERVICE_RECORD
    | {
        "+ criteriaResponses",
        "+ dateReviewReceived",
        "+ overallRecommendationLabel",
        # The manuscript's ID beside the revision's document ID, which is the work's
        "- submissionId",
        "- numberOfDaysFromReviewAssignmentToCompletion",
        # Sums of the score sheet's values, and the editor's rating of the reviewer
        "- reviewAverageMScore",
        "- reviewSumMScore",
        "- reviewRScore",
        "- reviewerRatingCustomQuestions",
        "- reviewerRatingFormName",
    },
    "editorialmanager/documented_api_reviewer.json": SERVICE_RECORD
    | renamed_top(
        documentId="manuscriptId",
        revision="revisionNumber",
        reviewerRecommendation="recommendation",
        scoreSheetCompletedDate="dateReceived",
    )
    | {
        # The review's ID, made of the document's and the reviewer's, is written as such
        "+ reviewId",
        "- reviewerPersonId",
        "+ ratings",
        "+ recommendationCode",
        "- reviewerAverageMScore",
        "- reviewerRank",
    },
}


@pytest.mark.parametrize(("system", "file", "how"), REVIEWS)
@pytest.mark.usefixtures("clock")
def test_a_real_review_read_and_written_back_is_given_back_as_listed(system, file, how):
    payload = json.loads((REAL / file).read_text())
    written = map_to(system, read(system, payload, how))
    assert differences(comparable(system, payload), comparable(system, written)) == LOSSES.get(
        file, set()
    )


def test_the_loss_table_names_only_real_reviews():
    assert set(LOSSES) <= {source["file"] for source in SOURCES}


def test_every_real_review_says_where_it_came_from():
    listed = {source["file"] for source in SOURCES}
    on_disk = {
        str(path.relative_to(REAL))
        for path in REAL.rglob("*.json")
        if path.name not in ("sources.json", "scale_bounds.json", "submission.json")
    }
    assert listed == on_disk
    for source in SOURCES:
        assert source["kind"] in ("real", "documented")
        assert source["url"].startswith("https://")
        assert source["license"] and source["retrieved"]


# Bugs the real reviews found


def real(file: str):
    return json.loads((REAL / file).read_text())


def read_real(file: str) -> dict:
    source = next(source for source in SOURCES if source["file"] == file)
    payload = real(file)
    return map_from(source["system"], payload, **form(source, payload))


def test_a_tmlr_review_is_read():
    """TMLR's form names its fields differently: the review had no content OCRS read, and
    map_from refused it."""
    review = read_real("openreview/rNsAQisgOo/review_yD4cisomcG.json")
    content = {
        k: v["value"]
        for k, v in real("openreview/rNsAQisgOo/review_yD4cisomcG.json")["content"].items()
    }
    assert review["opinion"]["summary"] == content["summary_of_contributions"]
    assert narrative_text(review, "review") == content["strengths_and_weaknesses"]
    # The requested changes are the list's three items; the reference after the list, which
    # the first cites, is no change, and the field's text is kept whole
    assert [c["text"][:30] for c in review["findings"]["changes"]] == [
        "Please consider demonstrating ",
        "The reviewer will be intereste",
        "Please improve the design of F",
    ]
    sections = {
        s["title"]: s["content"] for s in [p for p in review["narrative"] if "role" not in p]
    }
    assert sections == {
        "requested_changes": content["requested_changes"].strip(),
        "broader_impact_concerns": "No.",
        "claims_and_evidence": "No",
        "audience": "Yes",
    }


def test_colm_reasons_to_accept_and_reject_are_strengths_and_weaknesses():
    review = read_real("openreview/Ti67584b98/official_review_7vPwN4jhBp.json")
    content = {
        k: v["value"]
        for k, v in real("openreview/Ti67584b98/official_review_7vPwN4jhBp.json")["content"].items()
    }
    findings = review["findings"]
    assert findings["strengths"][0]["text"] == content["reasons_to_accept"].splitlines()[0]
    assert findings["weaknesses"][0]["text"] == content["reasons_to_reject"].splitlines()[0]
    assert findings["questions"][0]["text"] == content["questions_to_authors"].splitlines()[0]


def test_an_iclr_2026_meta_review_keeps_all_its_parts():
    """ICLR 2026's meta-review form has no `metareview`: its account of the reviewers'
    concerns and scores were lost."""
    review = read_real("openreview/y3oHMcoItR/meta_review_cqnYimoTWt.json")
    assert review["review_context"]["review_type"] == "meta_review"
    assert [s["title"] for s in [p for p in review["narrative"] if "role" not in p]] == [
        "reviewer_concerns",
        "reviewer_scores",
    ]


def test_a_score_given_with_its_label_reads_as_one_given_alone():
    """ICLR 2024's notes give "3 good", ICLR 2025's give 3 on a form where 3 is "good". Both
    read with the label; before, the second lost it on a round trip, as the writer leaves out
    a label the form gives."""
    labelled = read_real("openreview/SJTSvRtGsN/official_review_W0VehSkHDz.json")
    soundness = next(m for m in labelled["metrics"] if m["label"] == "soundness")
    assert (soundness["value"], soundness["justification"]) == (3, "good")
    alone = read_real("openreview/45rvZkJbuX/official_review_Gi0Y2ziQdN.json")
    soundness = next(m for m in alone["metrics"] if m["label"] == "soundness")
    assert (soundness["value"], soundness["justification"]) == (3, "good")


def test_a_journal_reviewers_number_is_written_back():
    """The journal narrative writer dropped `reviewer_id`, so a review lost its referee."""
    review = read_real("journal/elife_100443_sa1.json")
    assert review["referees"][0]["referee_id"] == "Reviewer #1"
    assert map_to("journal_narrative", review)["reviewer_id"] == "Reviewer #1"


def test_a_heading_is_not_the_summary():
    """eLife's reviews start with the heading "Summary:", which was the review's summary."""
    review = read_real("journal/elife_100443_sa1.json")
    assert review["opinion"]["summary"].startswith("This is an important contribution")
    one_line = map_from("journal_narrative", {"full_text": "Summary:"})
    assert one_line["opinion"]["summary"] == "Summary:"


def test_openaireview_reads_the_comments_of_the_runs_model():
    """A paper.json holds the merged comments of each model OpenAIReview ran. The mapper read
    the first model's, whatever `model_id` said, so a review said it was Gemini's and held
    Claude's comments."""
    paper = real("openaireview/smoothing-shifts-pdf.json")
    merged = {k: m for k, m in paper["methods"].items() if k.startswith("progressive__")}
    assert len(merged) == 2
    # A run names its model as the method's key does, or as its `model` does
    for model, method in [
        *((key.removeprefix("progressive__"), m) for key, m in merged.items()),
        *((m["model"], m) for m in merged.values()),
    ]:
        review = map_from("openaireview", {"output": paper, **AI_RUN, "model_id": model})
        titles = [w["title"] for w in review["findings"]["weaknesses"]]
        assert titles == [c["title"] for c in method["comments"]]
        # Written back, the comments go back to the model they came from
        assert map_to("openaireview", review) == paper
    with pytest.raises(ValueError, match="No OpenAIReview method ran with model"):
        map_from("openaireview", {"output": paper, **AI_RUN, "model_id": "another-model"})


def test_hotcrp_reads_its_apis_review_object():
    """HotCRP's API gives the review's ID as `rid` and its fields under their UIDs. The
    reader took `rid` for a score, 193 on a 1–5 scale, and dropped the review's text."""
    review = read_real("hotcrp/documented_api_review.json")
    assert review["review_id"] == "hotcrp_193"
    assert review["provenance"]["source_review_id"] == "193"
    assert review["referees"][0]["referee_id"] == "pat@example.org"
    assert review["referees"][0]["human_referee"]["name"] == "Pat Example"
    # Its last change; it says no time of submission, so it was written when it was imported
    assert review["updated_at"] == "2025-01-01T00:00:00Z"
    assert review["created_at"] != review["updated_at"]
    assert [m["label"] for m in review["metrics"]] == ["Overall Merit", "Reviewer Expertise"]
    assert [(p["role"], p.get("audience")) for p in review["narrative"]] == [
        ("summary", None),
        ("review", "authors"),
        ("review", "editors"),
    ]


def test_hotcrp_writes_an_unlabelled_score_as_it_came():
    """The writer gave HotCRP's unlabelled overall merit the recommendation as a label
    (`2. Reject`), which the reader then took as the reviewer's."""
    written = map_to("hotcrp", read_real("hotcrp/documented_api_review.json"))
    assert written["overall_merit"] == 2


def test_marginally_above_the_threshold_is_a_weak_accept():
    """ICLR's 6, "marginally above the acceptance threshold", was read as a plain accept:
    wording that places the work against the threshold says no verdict, so the score does."""
    for file in (
        "openreview/SJTSvRtGsN/official_review_W0VehSkHDz.json",  # "6: marginally above …"
        "openreview/45rvZkJbuX/official_review_Gi0Y2ziQdN.json",  # 6, on the 2025 form
    ):
        review = read_real(file)
        overall = next(m for m in review["metrics"] if m["key"] == "overall")
        assert overall["justification"] == "marginally above the acceptance threshold"
        assert review["decision"]["recommendation"] == "weak_accept"


# ScholarOne and Editorial Manager: no real export is public, so these test a record in the
# structure each web service (getReviewerInfoFull) documents, with values written for OCRS.
# Before, the readers took the record's comments and IDs and none of the rest.


def test_scholarone_reads_its_web_services_record():
    review = read_real("scholarone/documented_api_reviewer.json")
    # A record is one reviewer's review of one revision
    assert review["review_id"] == "s1_51234567_p9876543"
    assert review["created_at"] == "2026-03-20T16:45:10Z"
    assert review["referees"][0]["referee_id"] == "9876543"
    assert review["referees"][0]["human_referee"] == {
        "orcid": "0000-0002-1825-0097",
        "name": "Example, Dr. Riley",
        "affiliation": "Department of Chemistry, Example University",
        "third_party_id": {"key": "researcherid", "value": "A-1234-2020"},
    }
    # "Minor Revision", from the recommendation's text
    assert review["decision"] == {"revision_requirement": "minor", "source_label": "Minor Revision"}
    # The score sheet's answers with numbers are scores, with the answer as their label
    assert [(m["label"], m["value"], m.get("justification")) for m in review["metrics"]] == [
        ("Does the manuscript contain new and significant information?", 4.0, "Yes"),
        ("Are the methods described comprehensively?", 3.0, "Partly"),
    ]
    # and those in words are parts of the text. The editor's rating of the reviewer is
    # neither: it is not part of the review
    assert [p for p in review["narrative"] if "role" not in p] == [
        {
            "title": "Which further references should the authors cite?",
            "content": "The calibration study the method builds on.",
        }
    ]
    assert narrative_text(review, audience="editors") == "A minor revision should suffice."


def test_editorial_manager_reads_its_web_services_record():
    review = read_real("editorialmanager/documented_api_reviewer.json")
    # The record has no review ID: it is made of the revision's document and the reviewer
    assert review["review_id"] == "em_JEXP-D-26-00142R1_p4455667"
    assert review["created_at"] == "2026-04-21T12:05:00Z"
    assert review["referees"][0]["referee_id"] == "4455667"
    human = review["referees"][0]["human_referee"]
    assert (human["scopus_id"], human["affiliation"]) == (
        "57190000001",
        "Example Institute of Technology",
    )
    # Revision 1 is the second round
    assert review["review_context"] == {"round": 2}
    assert review["decision"] == {"revision_requirement": "major", "source_label": "Major Revision"}
    # An integer question's answer is a score; its `numericValue` is always null
    assert [(m["label"], m["value"]) for m in review["metrics"]] == [
        ("Rate the originality of the work (1 = poor, 5 = excellent)", 4)
    ]
    assert [s["title"] for s in [p for p in review["narrative"] if "role" not in p]] == [
        "Is the English acceptable?",
        "Comments on the statistical analysis",
    ]


@pytest.mark.parametrize("system", ["scholarone", "editorialmanager"])
def test_two_reviewers_of_a_revision_are_two_reviews(system):
    record = real(f"{system}/documented_api_reviewer.json")
    other = {**record, "reviewerPersonId": 1234567}
    assert map_from(system, record)["review_id"] != map_from(system, other)["review_id"]


def test_a_scholarone_recommendation_given_as_text_is_written_as_text():
    """The web service gives the recommendation's text alone. The writer wrote ScholarOne's
    code for it as well, which the reader then took for an overall score the review did not
    have."""
    written = map_to("scholarone", read_real("scholarone/documented_api_reviewer.json"))
    assert "overallRecommendation" not in written
    assert written["overallRecommendationLabel"] == "Minor Revision"
    assert written["documentId"] == 51234567


def test_score_sheet_answers():
    from ocrs.util import score_sheet_answers

    def question(text, answer=None, answer_type="TYPE_RADIO"):
        q = {"questionText": text, "answerType": answer_type}
        return q | ({"scoreSheetCustomAnswer": answer} if answer is not None else {})

    scored, written = score_sheet_answers(
        [
            # ScholarOne's own sample lists questions without an answer
            question("Unanswered"),
            question("Scored", {"answerText": "Good", "numericValue": 4.0}),
            question("Number as text", {"answerText": "3", "numericValue": "3"}),
            question("Integer", {"answerText": "5", "numericValue": None}, "Integer"),
            # A text question is not a score, though its answer starts with a number
            question("Notes", {"answerText": "2 errors in Table 1."}, "Notes"),
            question("Several", [{"answerText": "Data"}, {"answerText": "Code"}], "Checkbox"),
            "not a question",
        ]
    )
    assert scored == [("Scored", 4.0, "Good"), ("Number as text", 3, None), ("Integer", 5, None)]
    assert written == [("Notes", "2 errors in Table 1."), ("Several", "Data\nCode")]


# OpenReview's text fields, ethics flags and edit times, which the reader took line by line,
# as scores, and not at all


def test_a_heading_groups_the_points_under_it():
    """ICLR 2026's reviewer wrote "Major concerns:" above a list. The reader took each line as a
    point, so the heading was a weakness of its own."""
    review = read_real("openreview/y3oHMcoItR/official_review_F57t6Rab9l.json")
    weaknesses = review["findings"]["weaknesses"]
    assert len(weaknesses) == 12
    assert all(w["group"] == ["Major concerns"] for w in weaknesses)
    assert weaknesses[0]["text"].startswith("The documentation about the experiment")


def test_a_minor_heading_makes_its_points_minor():
    from ocrs.mappers.openreview import from_openreview

    text = "**Major**\n\n- No ablation.\n\n**Minor**\n\n- A typo on page 3.\n- Figure 2 is small."
    review = from_openreview({"id": "r", "forum": "f", "content": {"weaknesses": text}})
    assert [
        (w["text"], w["group"], w.get("severity")) for w in review["findings"]["weaknesses"]
    ] == [
        ("No ablation.", ["Major"], None),
        ("A typo on page 3.", ["Minor"], "minor"),
        ("Figure 2 is small.", ["Minor"], "minor"),
    ]


@pytest.mark.parametrize(
    "file", [s["file"] for s in SOURCES if s["system"] == "openreview"], ids=lambda f: f
)
def test_a_finding_field_written_as_text_comes_back_as_written(file):
    """Each strengths, weaknesses, questions or requested-changes field comes back with the
    text the reviewer wrote, headings, numbering and references included, not as the points
    the reader took from it."""
    from ocrs.mappers.openreview import FINDING_KEYS

    note = real(file)
    written = map_to("openreview", read_real(file))["content"]
    for names in FINDING_KEYS.values():
        for name in names:
            value = (note["content"].get(name) or {}).get("value")
            if isinstance(value, str) and value.strip():
                assert written[name] == value.strip()


def test_a_finding_changed_in_ocrs_is_written_as_it_now_is():
    review = read_real("openreview/y3oHMcoItR/official_review_F57t6Rab9l.json")
    review["findings"]["weaknesses"] = review["findings"]["weaknesses"][:1]
    written = map_to("openreview", review)["content"]["weaknesses"]
    assert written == [review["findings"]["weaknesses"][0]["text"]]


def test_an_ethics_flag_is_whether_there_are_ethical_concerns():
    """ICLR's flag (a list of choices) was lost, and COLM's and the Datasets and Benchmarks
    track's became scores, with "no concerns" normalized to 1.0."""
    for file in (
        "openreview/y3oHMcoItR/official_review_F57t6Rab9l.json",  # ["No ethics review needed."]
        "openreview/u7m2CG84BQ/official_review_ZfMFUByqxu.json",  # "2: No, there are no …"
        "openreview/Ti67584b98/official_review_7vPwN4jhBp.json",  # 1, which the form calls No
    ):
        review = read_real(file)
        assert review["ethics_and_risk"] == {"ethical_concerns": False}
        assert not [m for m in review["metrics"] if "ethic" in m["label"]]
    # The reviewer's account of the concerns is theirs, in their words
    details = read_real("openreview/y3oHMcoItR/official_review_8245mXvN5V.json")
    assert details["ethics_and_risk"] == {"ethical_concerns": False, "notes": "None"}


def test_an_ethics_flag_names_the_kinds_of_concern():
    from ocrs.mappers.openreview import from_openreview

    flag = ["Yes, Privacy, security and safety", "Yes, Discrimination / bias / fairness concerns"]
    content = {"summary": "S.", "flag_for_ethics_review": flag, "details_of_ethics_concerns": "D."}
    note = {"id": "r", "forum": "f", "content": content}
    review = from_openreview(note)
    assert review["ethics_and_risk"] == {
        "ethical_concerns": True,
        "concern_categories": ["privacy", "security", "bias_fairness"],
        "notes": "D.",
    }
    # Written back in the form's own words
    written = map_to("openreview", review)["content"]
    assert (written["flag_for_ethics_review"], written["details_of_ethics_concerns"]) == (
        flag,
        "D.",
    )
    # A number the form does not label says neither yes nor no, and stays a score
    unlabelled = from_openreview(
        {"id": "r", "forum": "f", "content": {"summary": "S.", "ethics_flag": 1}}
    )
    assert "ethics_and_risk" not in unlabelled
    assert [m["label"] for m in unlabelled["metrics"]] == ["ethics flag"]


def test_a_notes_last_change_is_when_it_was_updated():
    """Every real note was changed after it was written, most after the rebuttal; the reader
    kept only when it was written."""
    note = real("openreview/y3oHMcoItR/official_review_F57t6Rab9l.json")
    review = read_real("openreview/y3oHMcoItR/official_review_F57t6Rab9l.json")
    assert (review["created_at"], review["updated_at"]) == (
        "2025-11-04T07:33:14.100000Z",
        "2025-11-12T02:56:08.832000Z",
    )
    written = map_to("openreview", review)
    assert (written["cdate"], written["mdate"]) == (note["cdate"], note["mdate"])


# JATS sub-articles: the reports, assessments and responses eLife and F1000Research publish


def test_an_f1000_report_is_read_from_its_jats():
    review = read_real("jats/f1000_176295_report477634.json")
    assert (
        review["review_id"]
        == review["provenance"]["review_doi"]
        == ("10.5256/f1000research.194339.r477634")
    )
    assert review["created_at"] == "2026-05-09T00:00:00Z"
    # The version it reviews, from its related article
    assert review["target"]["work_id"] == "doi:10.12688/f1000research.176295.1"
    assert review["referees"][0] == {
        "referee_type": "human",
        "identity_mode": "open",
        "human_referee": {
            "name": "Awiruth Klaisiri",
            "affiliation": "Thammasat University, Pathum Thani, Thailand",
        },
        "competing_interests_statement": "No competing interests were disclosed.",
        "competing_interests_declared": False,
    }
    # "approve-with-reservations", kept as F1000Research wrote it
    # The report's own term is kept beside OCRS's reading of it
    assert review["decision"] == {
        "recommendation": "weak_accept",
        "source_label": "approve-with-reservations",
    }
    kept = review["extensions"]["jats"]
    assert kept["recommendation"] == {
        "name": "recommendation",
        "value": "approve-with-reservations",
    }
    assert (
        kept["permissions"]["licenses"][0]["url"] == "https://creativecommons.org/licenses/by/4.0/"
    )
    assert narrative_text(review, "review").startswith("1. How did you check the defects")
    # The authors' response nested in the report goes back with it
    assert len(kept["responses"]) == 1
    written = ET.fromstring(map_to("jats", review)["sub_article"])
    assert [s.get("article-type") for s in written.findall("sub-article")] == ["response"]


def test_an_elife_public_review_is_anonymous_and_sectioned():
    review = read_real("jats/elife_100443_sa1.json")
    assert review["referees"][0]["identity_mode"] == "single_blind"
    assert review["referees"][0]["human_referee"] == {}
    # The sub-article states no version: the article it is part of does
    assert review["target"]["work_id"] == "doi:10.7554/eLife.100443.2"
    assert review["target"]["venue"] == "eLife"
    assert [s["title"] for s in [p for p in review["narrative"] if "role" not in p]] == [
        "Summary",
        "Strengths",
        "Weaknesses",
    ]
    assert review["opinion"]["summary"].startswith("This is an important contribution")


def test_an_elife_assessment_keeps_its_terms():
    review = read_real("jats/elife_100443_sa0.json")
    assert review["review_context"] == {"review_type": "meta_review"}
    assert review["referees"][0]["human_referee"]["name"] == "Anurag Agrawal"
    # Its significance and strength of evidence have no OCRS field yet
    assert review["extensions"]["jats"]["keywords"] == [
        {"type": "claim-importance", "terms": ["Important"]},
        {"type": "evidence-strength", "terms": ["Solid"]},
    ]
    assert "**important**" in review["opinion"]["summary"]
    written = ET.fromstring(map_to("jats", review)["sub_article"])
    assert [k.text for k in written.iter("kwd")] == ["Important", "Solid"]
    assert written.find("body/p/bold").text == "important"


def test_an_elife_author_response_has_all_its_authors():
    review = read_real("jats/elife_100443_sa3.json")
    assert review["review_context"] == {"review_type": "author_comment"}
    assert len(review["referees"]) == 13
    assert review["referees"][0]["human_referee"] == {
        "name": "Nicole Foxworth",
        "affiliation": "Massachusetts General Hospital, Boston, United States",
    }
    # It quotes the reports it answers
    quotes = [b for b in narrative_text(review, "review").split("\n\n") if b.startswith("> ")]
    assert quotes[0].startswith("> “Claiming a possible therapeutic role")
    assert review["opinion"]["summary"].startswith("We agree that")


@pytest.mark.parametrize(
    "file", [s["file"] for s in SOURCES if s["system"] == "jats"], ids=lambda f: f
)
@pytest.mark.usefixtures("clock")
def test_a_jats_review_without_what_ocrs_has_no_field_for_is_written_from_ocrs(file):
    """Without extensions.jats, the writer writes the sub-article from OCRS's fields alone, and
    reading it gives the same review."""
    review = read_real(file)
    review.pop("extensions")
    again = map_from("jats", map_to("jats", review))
    again.pop("extensions")
    assert differences(without_import_time(review), without_import_time(again)) == set()


def test_a_review_from_elsewhere_is_written_as_a_referee_report():
    review = read_real("openreview/y8Rm4VNRPH/official_review_hQNYHP50sF.json")
    written = map_to("jats", review)
    element = ET.fromstring(written["sub_article"])
    assert element.get("article-type") == "referee-report"
    again = map_from("jats", written)
    # Its summary, then its parts under their headings
    text = narrative_text(again, "review")
    assert text.startswith(review["opinion"]["summary"])
    assert "strengths:" in text and "weaknesses:" in text
    # The recommendation goes as a JATS4R term; JATS has no place for how sure of it
    # Written back with the JATS4R term for the recommendation, which reads back as its label
    assert again["decision"] == {
        "recommendation": review["decision"]["recommendation"],
        "source_label": review["decision"]["recommendation"],
    }


def test_sub_articles_are_an_articles_reports_not_their_responses():
    from ocrs.mappers.jats import sub_articles

    article = """<article xmlns:xlink="http://www.w3.org/1999/xlink"><front>
      <journal-meta><journal-title-group><journal-title>J</journal-title></journal-title-group>
      </journal-meta><article-meta><article-id pub-id-type="doi">10.1234/j.1</article-id>
      <article-id pub-id-type="doi" specific-use="version">10.1234/j.1.2</article-id>
      <title-group><article-title>A <italic>work</italic></article-title></title-group>
      </article-meta></front>
      <sub-article article-type="referee-report" id="r1"><body><p>Fine.</p></body>
        <sub-article article-type="response" id="c1"><body><p>Thanks.</p></body></sub-article>
      </sub-article></article>"""
    payloads = sub_articles(article)
    assert [ET.fromstring(p["sub_article"]).get("id") for p in payloads] == ["r1"]
    assert payloads[0]["article"] == {"doi": "10.1234/j.1.2", "title": "A work", "journal": "J"}
    review = map_from("jats", payloads[0])
    assert review["review_id"] == "r1"
    assert review["opinion"]["summary"] == "Fine."


def test_an_ethics_flag_changed_in_ocrs_is_written_as_it_now_is():
    """The writer gave back the form's flag even when the review no longer said what it said,
    so a concern added in OCRS came back as "No ethics review needed"."""
    review = read_real("openreview/y3oHMcoItR/official_review_F57t6Rab9l.json")
    review["ethics_and_risk"] = {"ethical_concerns": True, "concern_categories": ["privacy"]}
    written = map_to("openreview", review)["content"]
    assert written["flag_for_ethics_review"] == ["Yes, Privacy, security and safety"]
    again = map_from("openreview", map_to("openreview", review))
    assert again["ethics_and_risk"]["ethical_concerns"] is True
    # A review from elsewhere has its concerns written as ICLR's choices
    del review["extensions"]
    review["ethics_and_risk"] = {"ethical_concerns": False}
    written = map_to("openreview", review)["content"]
    assert written["flag_for_ethics_review"] == ["No ethics review needed."]


def test_a_scholarone_overall_score_question_is_a_criterion():
    """A score-sheet question the reader files as an overall score is no recommendation code:
    the writer wrote the recommendation's code in its place and dropped the question."""
    record = real("scholarone/documented_api_reviewer.json")
    question = {
        "answerType": "TYPE_RADIO",
        "questionText": "Overall score",
        "scoreSheetCustomAnswer": {"answerText": "Good", "numericValue": 4.0},
    }
    record = {**record, "scoreSheetCustomQuestions": [question]}
    review = map_from("scholarone", record)
    written = map_to("scholarone", review)
    assert "overallRecommendation" not in written
    assert written["criteriaResponses"][0]["criterionName"] == "Overall score"
    again = map_from("scholarone", written)
    assert differences(without_import_time(review), without_import_time(again)) == set()


def test_a_scholarone_overall_score_equal_to_a_code_is_still_a_criterion():
    """An "Overall score" of 2 beside "Minor Revision", whose code is 2: by its value alone it
    looked like the code, and the question was dropped."""
    record = real("scholarone/documented_api_reviewer.json")
    question = {
        "answerType": "TYPE_RADIO",
        "questionText": "Overall score",
        "scoreSheetCustomAnswer": {"answerText": "Fair", "numericValue": 2},
    }
    review = map_from("scholarone", {**record, "scoreSheetCustomQuestions": [question]})
    written = map_to("scholarone", review)
    assert "overallRecommendation" not in written
    assert [c["criterionName"] for c in written["criteriaResponses"]] == ["Overall score"]
    again = map_from("scholarone", written)
    assert differences(without_import_time(review), without_import_time(again)) == set()


def test_an_ethics_category_added_in_place_is_written():
    """What the form's flag said was kept as the same list as the review's categories, so an
    edit to one changed the other, and the old flag was written."""
    from ocrs.mappers.openreview import from_openreview

    flag = ["Yes, Discrimination / bias / fairness concerns"]
    note = {"id": "r", "forum": "f", "content": {"summary": "S.", "flag_for_ethics_review": flag}}
    review = from_openreview(note)
    review["ethics_and_risk"]["concern_categories"].append("privacy")
    written = map_to("openreview", review)["content"]["flag_for_ethics_review"]
    assert written == [
        "Yes, Discrimination / bias / fairness concerns",
        "Yes, Privacy, security and safety",
    ]


def test_a_review_of_findings_and_a_summary_taken_from_them_keeps_them_all():
    """An OpenReview note with findings and no text has a summary taken from its first
    finding. The JATS writer wrote that summary alone, and the other findings were lost."""
    from ocrs.mappers.openreview import from_openreview

    note = {"id": "r", "forum": "f", "content": {"weaknesses": ["No ablation.", "One dataset."]}}
    review = from_openreview(note)
    assert review["opinion"]["summary"] == "No ablation."
    again = map_from("jats", map_to("jats", review))
    assert [p for p in again["narrative"] if "role" not in p] == [
        {"title": "Weaknesses", "content": "- No ablation.\n- One dataset."}
    ]


def test_an_ethics_flag_given_as_a_number_in_text_reads_by_the_forms_label():
    from ocrs.mappers.openreview import from_openreview

    note = {"id": "r", "forum": "f", "content": {"summary": "S.", "ethics_flag": "1"}}
    bounds = {"ethics_flag": {"min": 1, "max": 2, "labels": {"1": "No", "2": "Yes"}}}
    review = from_openreview(note, scale_bounds=bounds)
    assert review["ethics_and_risk"] == {"ethical_concerns": False}
    assert not review["metrics"]


@pytest.mark.parametrize("system", ["scholarone", "editorialmanager"])
def test_a_score_sheet_of_one_question_may_come_as_an_object(system):
    """The JSON shape is not documented: a lone question may come unwrapped from its list."""
    record = real(f"{system}/documented_api_reviewer.json")
    first = record["scoreSheetCustomQuestions"][0]
    review = map_from(system, {**record, "scoreSheetCustomQuestions": first})
    assert [m["label"] for m in review["metrics"]] == [first["questionText"]]
