# Changelog

## 0.9.0

A breaking release that organizes review content as a hierarchy. Opinion and metrics
summarize the review; findings give its points; claims and check results give derived
material; shared evidence pointers identify source passages. Links are review-local IDs,
stored in one direction. Published earlier schemas remain unchanged.

### Schema and migration

- `review_context.metric_schemas` stores source forms and metric definitions once.
  A metric has an `id`, `definition_ref: {schema_id, key}` and original `value`, with
  optional normalization, uncertainty, source answer and `supported_by` finding IDs.
  Move the old `key`, `label`, `aspect` and `scale` into a definition; `aspect` becomes
  `dimension`. The old catalog reference belongs to the source form. Do not invent
  missing rubric metadata or normalize without recording the method.
  `dimension` keeps the closed 0.8 aspect enum and adds `review_confidence`; retain an
  unlisted source criterion's label and prompt with `dimension: "other"`.
- `target.artifacts[]` identifies associated materials with IDs, types and optional
  locations, versions, hashes and reported availability. Examinations belong in checks;
  evaluations belong in findings. An unavailable artifact needs no invented URL.
  `reported_availability` keeps 0.8's vocabulary (`public`, `restricted`,
  `available_on_request`, `not_available`, `unknown`). The 0.8 artifact types `models`
  and `appendix` are now `model` and `supplement`.
- `opinion` holds `summary`, `stance`, optional `decision`, `metric_refs` and optional
  `supported_by`. Move top-level `decision` here and rename `summary_rationale` to
  `rationale`. Direct opinion support is independent of each metric's support.
- `findings` retains five separate arrays: strengths, weaknesses, questions, comments
  and changes. Addressable records require IDs. Weaknesses and changes share severity;
  classify topics, including ethics, with `tags` instead of `scope`. Changes may
  `addresses` other points; OR alternatives that are sufficient individually stay in
  one change. Findings use typed `about` references to claims, contributions, checks or
  individual results. There are no finding-to-finding reasoning links or inverse lists.
- `work_summary` holds a neutral `summary`, descriptive `contributions` and extracted
  `claims`. Move opinion contributions here. Claim assessments become extracted claims
  and source-stated findings; extraction alone does not endorse a claim. Claim-truth
  probabilities must not become probabilities of an unsupportedness judgment.
- Checks separate execution from outcome. `results[]` holds source statuses, notes,
  raw `data` and evidence pointers. Move old items and measurements here; reverse
  `finding_ids` become finding `about` references. Checks have no metric references or
  second evidence list. Raw measurements remain separate from assessment metrics.
- Shared `uncertainty` has finding `probability` or metric `interval`, never both,
  with optional `credence` and `rationale`. Finding credence requires its probability.
  Bounds and intervals are checked on the original metric scale. Reviewer confidence
  is distinct from converter confidence.
- Shared evidence links use `resource`, optional `version`, `location` and `quote`.
  Resource kinds are work, review, artifact and external. Locations include named
  pages, page ranges, sections, figures, tables, equations, line ranges and text anchors.
  Positional `span: {text_ref, start, end}` uses zero-based Unicode code points with an
  exclusive end, relative to one exact stored text representation. Page and section
  never reset the origin. Pass `text_sources` to validation to check bounds and quotes.
- Dedicated `claim_assessments`, `artifact_assessments` and `ethics_and_risk` sections
  are replaced by the common records above. No ethics finding is not a declaration
  that the reviewer found no concerns.

`ocrs.migrate.migrate(review)` converts 0.7 and 0.8 records without changing its input,
assigns the current `$schema` and is idempotent. Fields without a faithful new home stay
in `extensions.ocrs_0_8`, with compact source-conversion metadata. In particular,
claim-local ratings do not silently become work-wide metrics, and numeric scores do
not cause invented supporting findings. Ambiguous old overview text is retained
verbatim; migration does not semantically rewrite a review. Retained fields are keyed by
the ID of the record they belong to, so they stay with it when a migrated review is
edited. A 0.8 `summarizes` list, a finding-to-finding link, is among them. A 0.8
normalized score without a method gets `method: "unspecified"`. Only overall scores
join `opinion.metric_refs`.

### Python package

- Public imports and exports use 0.9 records. Existing source-specific codecs use a
  private compatibility projection; mapping records point into the current hierarchy.
  `map_from` returns 0.9; the per-format functions such as `from_cmt` still return
  the intermediate 0.8 shape, with a 0.8 `$schema`. Any valid 0.9 record, including
  an edited migrated one, can be written by `map_to`.
- OpenReview `scale_bounds` supplied by the caller are kept in
  `extensions.openreview.caller_scale_bounds`, not as the source form's snapshot.
- `validate_canonical(..., schema_path=...)` applies that schema to one call only.
  Records naming 0.9 or any later schema version get the hierarchy's reference checks.
  Evidence ranges are checked using the selected schema, including legacy locations.
- Validation checks global IDs, reference types, definition resolution, original scale
  values and bounds, intervals, source ranges and optional text-span resolution.
  Allowed link directions make the semantic graph acyclic without reciprocal edges.
- Tests cover the discussed adversarial cases, current-record round trips through the
  real-review corpus, migration, Unicode spans, original source fields and examples.
  Historical 0.8 field-contract tests remain against its immutable published schema.
  Fixed OpenReview and DeepReview golden records also check the public 0.9 output directly.
- Export tolerates deleted summaries and status-free raw observations, preserves IDs
  that new changes reference, and does not restore deleted claim, artifact or ethics
  evaluations from migration metadata. Later normalization and interval edits take
  precedence over retained legacy fields. Repeated reasons share one support link;
  empty legacy check notes round-trip without inventing text or a check verdict.
- The package, versioned schema, examples, README and citation are updated together.

## 0.8.0

A breaking release that makes the schema simpler. One shape of point replaces three, the
review's text is a list of parts instead of fixed fields, every review has a list of
referees, and the recommendation's certainty is `credence`, as everywhere else.
`ocrs.migrate.migrate(review)` turns a 0.7 review into a 0.8 one with the same meaning. It
does not change the review it is given, and migrating a migrated review changes nothing.
Every 0.7.2 review that the tests build (the examples, the README blocks, and about 600
reviews one edit away from them) migrates to a valid 0.8 review.

### Schema: breaking changes

- `referee` is gone, and `referees` is required: a list of one referee or more.
  Migration: `"referee": {...}` becomes `"referees": [{...}]`.
- Expertise belongs to the referee, as `referees[].expertise`, and is no longer in
  `review_context.expertise` or `human_referee.expertise`. Migration: move either one onto
  each referee. Drop a `review_context` that is left empty.
- `decision.confidence` is `decision.credence`, with the same meaning: how firmly the
  reviewer holds the recommendation. Findings, claims and metrics already call this
  `credence`. Migration: rename the key.
- Findings, requested changes and contributions are all `$defs/point`. It replaces
  `finding`, `actionItem` and `contribution`, which overlapped. A point has `text`
  (required), `id`, `title`, `severity`, `scope`, `tags`, `group`, `evidence_links`,
  `suggested_edits`, `probability`, `credence`, `summarizes`, `addresses` and `claim_ids`.
  So a weakness can have a scope, and a change can have a probability. Migration for a
  change in `findings.changes`:
  - `priority` becomes `severity`, which now also takes `trivial`, so every priority
    keeps its value.
  - `applies_to.section`, `.figure` and `.table` become `evidence_links` of type
    `paper_section`, `figure` and `table`, with the value as `ref`.
  - `applies_to.finding_id` becomes `addresses: [id]`, and `applies_to.claim_id`
    becomes `claim_ids: [id]`.
  - For a contribution, `claim_id` becomes `claim_ids: [id]`.
- `ethics_and_risk.required_mitigations` is gone. A change that ethics calls for is a
  requested change like any other. Migration: move each mitigation to `findings.changes`
  with `scope: "ethics"`, or, when it has another scope, keep that scope and tag it
  `ethics`. Drop an `ethics_and_risk` that is left empty.
- `narrative` is a list of parts in the order the source gives them, each a `$defs/section`:
  `content` (required), `title`, `role` and `audience`. It replaces the fixed `summary`,
  `detailed_review`, `author_questions` and `confidential_to_editors` fields and the
  `sections` list. A part's `role` says what it is (`summary`, `review`, `questions`,
  `other`), and its `audience` says who the source shows it to (`public`, `authors`,
  `reviewers`, `editors`). A review form's text fields, a report's headed sections and one
  undivided text all fit the same list, and a writer can put each part back under the
  field it came from. Migration:
  - `summary` becomes a part with role `summary`, and `detailed_review` one with role
    `review`.
  - `author_questions` becomes a part with role `questions`, and
    `confidential_to_editors` one with role `review` and audience `editors`.
  - Each of `sections` becomes a part as it is, without a title when the title was empty.
- HotCRP's reviewer expertise, which 0.7 scored as a `confidence` metric labelled "Reviewer
  Expertise", is an `expertise` metric. Migration: change that metric's `key` and `aspect`
  to `expertise`, and a `metric_catalog_ref` of `metric-catalog.core.v1` to
  `metric-catalog.core.v1.1`.
- A narrative part's `title`, when given, may not be empty.
- A review read from JATS has its license in `provenance.license`, where 0.7 kept it only in
  `extensions.jats.permissions`. Migration: set `provenance.license` to the first license's
  `url`, else its text as `name`.
- `validate_canonical` checks the new references as it checked the old ones. A point's
  `summarizes` and `addresses` must name findings in the review, and its `claim_ids` must
  name claim assessments. Ids must be unique across the findings, the contributions (which
  can now have ids) and the checks.

### Schema: additions

- `provenance.license` is the license the review itself is published under, as the source
  states it: `name` (e.g. `CC BY 4.0`), `url`, or both.
- `decision.source_label` is the recommendation in the source's own words, verbatim
  (`Accept (Oral)`, F1000Research's `approve-with-reservations`). A term that OCRS cannot
  read as a recommendation can be kept in `source_label` alone.
- `related_reviews` lists the other reviews this one `responds_to`, `supersedes` or
  `summarizes`, each by `review_id`, `doi` or `url`.
- `scale.values` lists the values a scale allows when they are not every step from `min`
  to `max`, as for ICLR's overall rating (1, 3, 5, 6, 8, 10).
- `identity_mode` adds `triple_blind`: the reviewer, the authors and the editors do not
  know each other's identities.
- A metric's `aspect` adds `expertise`.

### Specification files

- `metric-catalog.core.v1.1.json` adds an `expertise` key (Reviewer Expertise). A form that
  asks for expertise, such as HotCRP's, now keeps it apart from confidence.
- `mapping-spec.v1.2.0.json` uses that catalog, and every mapper says it follows 1.2.0.
- The package ships only the current files. `metric-catalog.core.v1.json` and
  `mapping-spec.v1.1.0.json` are still published with 0.7.2 and earlier versions.

### Python package

- `ocrs.migrate.migrate` turns a 0.7 review into a 0.8 one.
- The review-flow diagram, on the documentation site and in the README, shows JATS and
  OCRS 0.8.0, with a column for each source.
- A writer puts in a field the authors see only the narrative parts the authors may read:
  those with no `audience`, or `public` or `authors`. The review's text for the editors goes
  in the system's confidential field, when it has one. A part for the other reviewers goes
  nowhere.
  `ocrs.util.for_authors` tells which parts the authors may read.
- New helpers in `ocrs.util`: `referee_of`, `section`, and `narrative_part`,
  `narrative_text`, `narrative_field` and `narrative_parts`, which find narrative parts by
  role and audience. `recommendation_label` gives the label to write for a decision.
- Every mapper reads into and writes from the 0.8 shape:
  - **Narrative:** each reader keeps its source's text fields as narrative parts, titled
    with the field's name, and each writer puts them back under those names. So the
    TMLR and Datasets and Benchmarks reviews that lost their field names on a round trip
    now keep them.
  - **Recommendation wording:** a recommendation given in words keeps its wording in
    `decision.source_label`, and writers give it back verbatim, so `Accept (Poster)` no
    longer comes back as `Accept`. This holds for OpenReview, CMT, HotCRP, Editorial
    Manager, ScholarOne and JATS. Words that name no recommendation (`Not sure`), which
    the OpenReview, CMT and HotCRP readers take as `borderline`, go back as written too.
    Beside a score, whose number a reader takes for words that name none, they go in
    OpenReview's `recommendation` field, which is read first. CMT and HotCRP give the
    score OCRS's words.
  - **OpenReview:** the reader takes the note's `license` as `provenance.license`.
    `replyto`, when it is not the forum, becomes a `responds_to` related review. A form
    bound's `values` becomes `scale.values`. The writer gives the license and the reply
    back to a note read from OpenReview. A review from elsewhere that has no text of its
    own is written with its other parts as the review, so that it can be read again.
  - **JATS:** the reader takes the report's license as `provenance.license`. The writer
    writes the license `provenance.license` holds, even when the review was read from JATS
    and its license was later changed. The report's body is every part that is the review,
    then the questions for the authors and the other parts they may read. Without a part
    that is the review, it is the other parts, with or without a title.
  - **A recommendation OCRS cannot name** ("Needs discussion", JATS's `approve-in-part`)
    is kept as `decision.source_label` alone, and every writer writes it in its words.
    Editorial Manager and ScholarOne read it back as it was; OpenReview, CMT and HotCRP
    read it as `borderline`, as they read any such words, and keep them.
  - **ScholarOne:** beside a recommendation code it writes for a review from elsewhere, it
    writes the source's words for the recommendation (`Accept (Oral)`) as the label.
  - **HotCRP:** reviewer expertise, which was a `confidence` metric, is an `expertise`
    metric and the referee's expertise. A form's separate confidence is still a
    `confidence` metric, and it sets `decision.credence`.

## 0.7.2

The schema says the same thing in fewer words. Every review valid under 0.7.1 is valid under
0.7.2, every invalid one is still invalid, and no value changes meaning.

### Schema

- Shapes the schema spelled out several times are defined once, in `$defs`, and referred to
  where they are used. The file is 2,849 lines, from 3,268.
  - `nonBlank` and `hasTitleOrText` say when text counts as review content. The
    `reviewContent` rule repeated them in each of its branches.
  - `workIdentifiers.content_hash` refers to `contentHash`, which it copied.
  - `probability` and `credence`, which findings, claim assessments and metric uncertainty
    share, and `expertise`, which `review_context` and `human_referee` share.
  - `aiReferee`'s two forms no longer repeat its properties: full provenance has `system` and
    `execution` and no `reference`, and a reference is `reference` alone.
- A program that takes the `reviewContent` rule out of the schema, to check it alone, must
  bring the schema's `$defs` with it, since the rule now refers to them.

### Python package

- `ocrs.schema.has_content` checks the content rule together with the schema's `$defs`.
- A test checks that the published 0.7.1 and 0.7.2 schemas accept and reject the same
  reviews: the examples, the README and CONTRIBUTING blocks, each mapper's output for its
  fixtures, and every review one edit away from small reviews that use the restated parts,
  about 4,500 in all.
- `map_to` gives a review read from OpenReview, CMT, HotCRP, Editorial Manager or ScholarOne
  back as that system holds it, so that reading what it writes gives the same review. Before,
  each writer lost part of what its reader took: OpenReview and CMT wrote scores under their
  catalog keys or dropped them, and OpenReview's came back in another order; the labels the
  reviewer gave scores were cut (`6: Weak Accept` came back `6`); review dates, reviewers,
  meta-review and decision notes, questions for the authors, ScholarOne's competing interests
  and criterion labels, and Editorial Manager's rating labels were lost. Now:
  - Each score is written under its own field name with its label (`"7: Accept, but not among
    top submissions"`; HotCRP's `"4. Accept"`). A label that is the review form's own
    description of the value is left out, so the value alone says it. A review from another
    system gives its scores under their catalog keys, as before.
  - A recommendation the overall score's label already says is not written again as its own
    field, which made OpenReview read the score as a second one. A label that would read back
    as another recommendation gives way to the decision's own (`4: Major Revision`), so the
    decision survives. A form's own label for a value is left out only when writing back to
    that form; another system gets it written.
  - The review's time (`cdate`, `submitted_at`, `reviewDate`, `dateReceived`,
    `dateReviewReceived`), the reviewer, the title, the questions for the authors
    (HotCRP's `questions_for_authors`) and, for OpenReview meta-reviews and decisions, the
    kind of note and its own fields (`metareview`, `comment`, `decision`) are written.
  - HotCRP, CMT and Editorial Manager IDs that are numbers are written as numbers, and a
    value the review does not have is left out rather than written as null.
  - Editorial Manager writes the recommendation's code beside its text, and ScholarOne its
    label only when the review gave one.
- The readers keep a little more, so that their writers can give it back: CMT and OpenReview
  keep the overall score's label, and CMT the confidence's, as the other scores' labels were
  kept; OpenReview labels the overall score and the confidence with their form fields
  (`rating`, `overall rating`, `confidence`), as it labels its other scores, where they were
  `Overall Assessment` and `Reviewer Confidence`, so that each is written back to its own field
  and the form's bounds for it apply again; CMT takes the paper's title from `paperTitle` and
  the review's date from `reviewDate` as well as `createdAt`; Editorial Manager and ScholarOne
  take the title from `manuscriptTitle`; HotCRP keeps both `questions` and
  `questions_for_authors` when a form has both, where the questions for the authors replaced
  the others; and a score's label may run over several lines (`"6: Weak accept,\nwith
  reservations"`), where such a score was not read at all.
- Tests write each fixture back in its source's format and read it again, both ways. Every
  review OCRS reads from a system comes back unchanged through that system's format; going
  the other way, `tests/test_roundtrip.py` lists the system's own fields that OCRS has no
  place for, such as CMT's `bestPaperNomination` or HotCRP's `rtype`, and the tests fail if a
  review loses more.
- `map_from("jats", …)` and `map_to("jats", …)` read and write peer-review reports published
  as JATS `<sub-article>`s, as JATS4R recommends: eLife's, F1000Research's, PeerJ's and
  others'. A payload is the sub-article's XML with what its article says of itself (version
  DOI, title, journal), and `ocrs.mappers.jats.sub_articles` splits an article into them. The
  reader takes the report's type (an editor's report is a meta-review, an author comment an
  author comment), DOI, referees (named, open; `<anonymous/>`, single blind), competing
  interests, date, the version it reviews, its recommendation and its text, with bold and
  italic as Markdown, quotes as `> `, and the parts under headings as narrative sections.
  The report's title, license, assessment terms, recommendation term, the referees' roles
  and the responses nested in it are kept in `extensions.jats` and written back. It is
  tested on 7 real eLife and F1000Research sub-articles, which come back whole but for
  eLife's structured affiliations, and on each written from OCRS's fields alone.
- The same round trips run on real reviews, in `tests/fixtures/real/` and
  `tests/test_real_reviews.py`: 32 OpenReview notes from ICLR 2024 to 2026, NeurIPS 2024 (main
  and Datasets and Benchmarks), COLM 2024 and TMLR, with each venue's own scales; 7 eLife and
  F1000Research reports as journal narratives; and both reviews in each of 2 OpenAIReview
  outputs. HotCRP, ScholarOne and Editorial Manager have samples in the structure their APIs
  document; no real HotCRP, CMT, Editorial Manager or ScholarOne export is public.
  `scripts/fetch_real_reviews.py` fetches them again, and `sources.json` records each one's
  URL, license and retrieval date. They found these bugs, now fixed:
  - OpenReview: a TMLR review had no content the reader knew, and `map_from` refused it. The
    reader now takes the names venues give its fields: TMLR's `summary_of_contributions`,
    `strengths_and_weaknesses` and `requested_changes` (as `findings.changes`), the Datasets
    and Benchmarks track's `summary_and_contributions`, and COLM's `reasons_to_accept`,
    `reasons_to_reject` and `questions_to_authors`, which it dropped. Further named parts of a
    review are kept as `narrative.sections` under their field names and written back under
    them: the meta-review's account of the discussion (ICLR 2025's
    `additional_comments_on_reviewer_discussion`, ICLR 2026's `reviewer_concerns` and
    `reviewer_scores`, which have no `metareview`), `limitations`, TMLR's
    `claims_and_evidence`, `audience` and `broader_impact_concerns`, and the Datasets and
    Benchmarks track's questions.
  - OpenReview: a score given as a number takes the form's label for it, as the overall score
    and confidence did, so ICLR 2024's `"3 good"` and ICLR 2025's `3` (where 3 is "good") read
    the same. Before, a review whose scores came with labels lost them on a round trip, since
    the writer leaves out a label the form gives.
  - A label that places the work against the acceptance threshold says no verdict: ICLR's 6,
    "marginally above the acceptance threshold", was an `accept`, and is now what the score
    says, `weak_accept`, as "below the acceptance threshold" already was.
  - Journal narratives: the writer drops no `reviewer_id`, which lost the review's referee, and
    the summary of a review that starts with a heading ("Summary:", as eLife's do) is the
    paragraph under it, not the heading.
  - OpenAIReview: a paper.json holds one review for each model it ran. The reader took the
    first model's, whatever `model_id` said, so a review said it was Gemini's and held
    Claude's comments. It now reads the method run with `model_id` (named by the method's key
    or its `model`), raises when `model_id` names none of several, and the writer writes back
    to that method.
  - HotCRP: the reader takes the review object HotCRP's API returns: the review's ID as `rid`,
    which it read as a score (193 on a 1–5 scale), its last change, `modified_at`, as
    `updated_at`, the reviewer's name and `reviewer_email`, and the default form's fields under
    their UIDs (`OveMer`, `RevExp`, `PapSum`, `ComAut`, `ComPC`), whose text it dropped.
  - ScholarOne and Editorial Manager: the readers took only the comments and IDs of the record
    each system's web service (`getReviewerInfoFull`) returns. They now take the rest of what
    OCRS has a place for: the recommendation's text (`reviewerRecommendation`), the reviewer
    (`reviewerPersonId`, `reviewerFullName`, `reviewerORCIDId`, ScholarOne's
    `reviewerResearcherId` and Editorial Manager's `scopusId`, and the first of their
    `departments` as the affiliation), when the score sheet was completed, Editorial
    Manager's `revision` as the round, and the score sheet: an answer with a number is a score,
    with its text as the label, and an answer in words a narrative section, written back as a
    score-sheet question. A review's ID is the revision's document ID and the reviewer's, so
    two reviewers of one revision are two reviews. The services document their responses in
    XML only, so the samples are one result each and the JSON shape is unverified. Neither
    reader takes the reviewer rating form, the editor's rating of the reviewer, as part of the
    review.
  - OpenReview: a text field was read a point per line, so a heading ("Major concerns:") was a
    weakness of its own and a reference after a list ("[1] Blundell, Charles, et al.") a
    requested change. Strengths, weaknesses, questions and requested changes written as text
    are now read as a saved forum page's are: a list's items are its points, and a heading is
    the `group` of the points under it, a Minor or Typos heading making them minor. The
    field's text is kept as written, as a narrative section under its field name, and the
    writer gives it back unless the findings no longer match it, when it writes them as a
    list. A list's numbers are not part of its points' text.
  - OpenReview: an ethics flag was a score ("no concerns" was 1.0) or lost (ICLR's list of
    choices). ICLR's and NeurIPS's `flag_for_ethics_review`, the Datasets and Benchmarks
    track's numbered choice and COLM's `ethics_flag` (by the form's labels) now say
    `ethics_and_risk.ethical_concerns`, with ICLR's kinds of concern as `concern_categories`,
    and `details_of_ethics_concerns` is its `notes`. The flag is kept in
    `extensions.openreview.ethics_flags` and written back as the form gave it while the
    review still says what it said; otherwise the review's concerns are written as ICLR's
    choices. A number the form does not label says neither, and stays a score.
  - OpenReview: the note's last change (`tmdate`, else `mdate`) is `updated_at`, written back
    as `mdate`. Every real note was changed after it was written.
  - ScholarOne's writer wrote a recommendation code for a review read from ScholarOne whose
    recommendation came as text, and the reader then took the code for an overall score the
    review did not have; it now writes the text. It writes a `documentId` that is a number as
    a number. Editorial Manager's writer, and ScholarOne's, write the reviewer's affiliation,
    which their readers took and the writers dropped.

## 0.7.1

The addition is optional, so every 0.7.0 review is valid under 0.7.1.

### Schema

- An action item's `scope` takes two new kinds of change. `figure` is a change to a
  figure, plot or table: a missing error bar, an unreadable axis, a panel that does not
  match the text. `references` is a change to the work's references: a missing citation,
  a wrong or retracted one, or a reference that does not say what it is cited for. Before
  0.7.1 such changes had to be `writing`, `typo`, `artifact` or `other`.

### Python package

- `from_openreview` reads API v2 notes, whose form fields are `{"value": …}`. Before, such a
  note gave no opinion, findings or scores, and `map_from` raised "has no review content".
  API v1 notes are read as before.
- `map_from("openreview", note, scale_bounds=…, submission=…)` takes the review form's
  bounds for each score field (`{"rating": {"min": 1, "max": 6, "labels": {"6": "Strong
  Accept"}}}`), so scores are on the form's scale with its descriptions as anchors, and the
  work reviewed (`id`, `title`, `venue`, `venueid`, `doi`, `arxiv_id`), which fills `target`.
  Both are optional, and giving either to another source raises `ValueError`.
- A `Meta_Review` or `Decision` note, known by its invitation, has `review_context.review_type`
  `meta_review` or `recommendation`. Its `metareview` or `comment` becomes the opinion and
  narrative, and its `recommendation` or `decision` the decision.

## 0.7.0

A breaking change: a review that says nothing about the work, which 0.6.3 accepted by
mistake, is invalid. Every other 0.6.3 review is valid under 0.7.0.

### Schema

- A review must have content (the rule's `$anchor` is `reviewContent`), at least one of:
  an opinion `summary`, `text`, `stance`, `high_level_reasons` or `contributions`; a
  finding of any kind, `changes` included; a `decision.recommendation`,
  `revision_requirement` or `summary_rationale`; a metric, claim assessment, artifact
  assessment or check; `ethics_and_risk` with `ethical_concerns: true`, `notes`,
  `concern_categories` or `required_mitigations`; narrative text, or a narrative section
  with content; or a `written_report`. Text counts only when it has a character other
  than whitespace, and a list only when one of its items has such text. Before 0.7.0 the
  schema stated a narrower rule (an opinion summary or text, or a strength, weakness,
  question or comment), but its findings branch passed whenever `findings` was absent, so
  a review with `"opinion": {}` and nothing else was valid. Migration: a review with none
  of these, or only blank text, must gain one, or it is not a review; one whose content is
  something that rule left out (a check, a recommendation, scores, ethics notes, a written
  report and so on) needs no change.
- `review_context.review_type` takes `citation_review`, a review of only the work's
  references, such as whether each exists and says what it is cited for. Crossref has no
  such type. Its findings usually go in a `reference_verification` check, one item per
  reference.

### Python package

- Mappers no longer invent an opinion summary. When the source has no text, CMT, Editorial
  Manager, HotCRP, the journal narrative mapper, OpenReview and ScholarOne leave `opinion`
  empty, where they wrote `No summary provided.` or `No opinion text provided.`; a review
  with scores or a recommendation is still valid.
- `map_from` and `map_with_record` raise `ValueError` ("The <source> review has no review
  content: …") for a source that says nothing, rather than return a review that fails
  validation. `ocrs.schema.has_content` tells whether a review meets the rule.

- `map_to` writes an OCRS review in each AI reviewer's own format: `openaireview` gives
  OpenAIReview's `paper.json` as a dict, `deepreview` and `reviewer3` give the report's
  Markdown. Each writes what its mapper reads and puts back what the mapper kept in
  `extensions.<reviewer>`, so a review mapped from a reviewer and written back maps to the
  same OCRS review. Points a format has no place for become comments or go under headings
  of their own; scores and the decision are left out. `supported_targets()` lists the three.
- So that writing back never has to guess, the AI mappers record a little more:
  OpenAIReview weaknesses get IDs `comment-<n>` (their place in the method's comments),
  and `extensions.openaireview` always names the method that was mapped. A skipped
  OpenAIReview comment, DeepReview point or Reviewer3 reference row keeps its empty
  `explanation`, `text` or `status` in extensions, and a Reviewer3 row whose other
  columns are kept keeps its number with them. DeepReview headings inside fenced code are
  code, not sections. Mapper versions: OpenAIReview, DeepReview and Reviewer3 1.1.0.
- Python 3.12 or later is required (was 3.10), and CI tests on Python 3.12, 3.13 and 3.14.
- `ocrs.mappers.openreview_page` reads a saved OpenReview forum page and maps each Official
  Review on it to an OCRS review (`reviews_from_forum_page`), and `scripts/openreview_page_to_ocrs.py`
  writes them as JSON files. Each review's `provenance.source_url` opens the forum at that
  review, and `extensions.openreview` records the page field behind each OCRS value
  (`source_fields`), the fields with no OCRS field, the replies below the review and a hash of
  the page. Strengths, Weaknesses, Minor and Questions become findings; scores become metrics
  with their labels as anchors, since a page does not state a scale.

### Mapper fixes

- Writing back to DeepReview and Reviewer3 contains code fences: a block of free text
  that leaves a fence open goes last in its report or section, and any other is closed,
  so it no longer swallows the sections, points or comments written after it. A
  reviewer's own report, which can leave a fence open only at its end, comes back as it
  was.
- Thematic breaks (`- - -`, `* * *`) are no longer read as list items when finding code
  fences, so a fenced heading after one stays code.
- Recommendation labels that place the work short of acceptance ("Below the acceptance
  threshold") give no label, so the score decides; before, they read as `accept`.
- OpenReview takes the first confidence field that gives a number for the decision's
  confidence, so `confidence: "High"` beside `reviewer_confidence: 4` sets it.
- Reviewer3 writes a fatal flaw whose ID is not a one-based place (`fatal-flaw-0`) as a
  plain point instead of failing, and DeepReview writes a skipped point of places alone
  so they read back as places.
- Identifiers, links and times are no longer read as scores: a DOI (`10.1234/…` became a
  metric of 10.1234), an ORCID, an arXiv ID, a version, a paper or submission ID, a
  timestamp or a date (`created_at`, `cdate`, `paperId`, `review_date`) in a CMT, OpenReview
  or HotCRP review no longer becomes an `other` metric. Nor does a boolean.
- A recommendation or score field that is present but null or blank no longer hides the
  next one (OpenReview `recommendation: null` with a `rating`, HotCRP `overall_merit: null`
  with `overall`), and a score of 0 is kept (CMT `overallEvaluation: 0`, a ScholarOne
  criterion response of 0, reviewer number 0).
- OpenReview's `overall_rating` and `overall` give one overall metric, not two, and its
  recommendation is read from the reviewer's label before the number, as CMT and HotCRP do
  (`3: Strong Accept` is `strong_accept`, not `borderline`).
- Recommendation labels are read by whole words in every mapper: `Not acceptable` and
  `Unacceptable` are `reject`, and `Marginally acceptable` says nothing, so the score
  decides; before, `acceptable` read as `accept`. A negated qualifier is set aside: `Not a
  strong accept` leaves the score to decide, and `Weak accept (not a strong accept)` is
  `weak_accept`.
- A field name names a catalog metric only by whole words: it contains an alias
  (`Soundness score`), or it is part of aliases of one metric only (`presentation`). An
  empty or short name (`""`, `ab`) or one shared by several metrics (`quality`) is `other`;
  before, an empty ScholarOne criterion became the overall score.
- A ScholarOne recommendation code outside 1–5 gives no recommendation and no metric; it
  was read on a higher-is-better scale, the reverse of ScholarOne's (9 was `accept`).
- HotCRP takes a numeric `contactId` as the referee ID and leaves null items out of
  findings; OpenReview leaves out a bare bullet (`-`). A journal review without a journal
  has no `venue` (it failed validation), and a numeric `reviewer_id` is kept as text.

## 0.6.3

The addition is optional, so every 0.6.2 review is valid under 0.6.3.

### Schema

- `$schema` names the OCRS version a review follows, as the URL of that version's schema
  (its `$id`). Validators and editors can use it to pick the schema to check the review
  against. Before 0.6.3, a review could not carry it, since the top-level object is closed.

### Python package

- Every mapper sets `$schema` to the packaged schema's `$id`, as the first key of the review.
- `schema_id()` returns that URL, for reviews written without a mapper.
- The examples name their schema in `$schema`.

## 0.6.2

All additions are optional, so every 0.6.1 review is valid under 0.6.2.

### Schema

- `target.identifiers.valency_id` gives the work's Valency Hub ID: `W_` and at least 8
  characters from a-z and 2-9 without `i`, `l` and `o` (`W_6r533gdt`), or one version's ID,
  with `_v` and the version number (`W_6r533gdt_v2`). Its page is
  `https://hub.valency.io/works/<id>`. `target.work_id` takes `valency_id:<id>`, which comes
  after OpenAlex in the resolution priority.
- `referee.human_referee.valency_id` gives the reviewer's Valency Hub author ID (`A_7zdytxzb`),
  whose page is `https://hub.valency.io/authors/<id>`.

### Python package

- `validate_valency_work` and `validate_valency_author` check the two ID formats, and
  `build_work_identifiers` takes `valency_id`, adding its Hub link.
- A `work_id` given as a Hub work page (`https://hub.valency.io/works/W_…`) or as a Hub
  citation (`vlnc:W_…`) becomes `identifiers.valency_id`, not a `permalink` or an
  `internal_id`.

- New mapper `reviewer3` for Reviewer3's Markdown report: `map_with_record` takes the
  report's text as `output`. The Overview becomes `opinion.contributions`; AI Text
  Detection, Fatal Flaws and Reference Check become `checks`, with an `outcome` only for
  Fatal Flaws, which states one; Reviewer Comments become `findings.comments`, with no
  severity, and each comment's page and excerpt become an evidence link. The schema is
  unchanged.

## 0.6.1

All additions are optional, so every 0.6.0 review is valid under 0.6.1.

### Schema

- `checks` records systematic checks run on the work, including those that found nothing:
  AI-text detection, reference verification, fatal-flaw screens, similarity, image
  integrity, statistics and retractions. Each check has a `kind`, the tool that ran it
  (`performed_by`; absent means the referee), an `outcome` only when the source states one,
  the source's `summary`, `measurements` (a proportion is a 0–1 `fraction`) and per-item
  results (`items`: what was checked, the source's `status`, and whether it was `flagged`).
  `finding_ids` links a check to the findings that report its problems.
- `opinion.contributions` lists what the work contributes, as the reviewer reads it, with an
  optional `title` and a `claim_id` in `claim_assessments`. Contributions are neither
  strengths nor assessed claims.
- `findings.comments` holds points the source does not classify as strengths, weaknesses or
  questions. A review whose only points are comments is valid.
- `text_format` says how the review's free text is written: `markup` (`plain`, `markdown`
  or `html`) and `math` (`none` or `tex`).
- Evidence links' `work` takes `citation`, the reference as printed.
- `target.title` gives the work's title, as the review gives it.
- `validate_canonical` also checks that check ids are unique among checks, findings and
  action items, that `checks[].finding_ids` name findings, and that
  `opinion.contributions[].claim_id` names a claim in `claim_assessments`.

## 0.6.0

All additions are optional, so every 0.5.0 review is valid under 0.6.0.

### Schema

- Findings take an `id`, unique among the review's findings and action items, a `group`
  (the review's headings the point sits under, outermost first) and `suggested_edits`
  (rewrites the reviewer proposes: a `replacement` and, optionally, the `original` text).
- A finding that restates others in brief lists their ids in `summarizes`, so it can be
  left out when counting points. `summarizes: []` marks an overview whose source does not
  say which points it covers.
- Action items (`findings.changes` and `ethics_and_risk.required_mitigations`) take an
  `id`, `title`, `evidence_links`, `suggested_edits` and `group`, as findings do, and
  `applies_to.finding_id` names the finding they address.
- Evidence locations take `page_end` for a page range. Evidence links take the type
  `bibliography`, for the work's own reference list, and a `work` (title, authors, year,
  identifiers) for another work, such as a citation the reviewer says is missing.
- `review_context.review_type` takes `pre_submission`: feedback the authors asked for
  before submitting.
- `validate_canonical` also checks what JSON Schema cannot: ids are unique, `summarizes`
  and `applies_to.finding_id` name findings that exist, and `page_end` is not before `page`.

### Python package

- New mapper `deepreview` for Google DeepReview's Markdown report: `map_with_record`
  takes the report's text as `output`.
- `map_with_record` no longer requires `reviewer_commit` or `model_id`. It takes
  `reviewer_version` for a reviewer with releases rather than commits; what is not given
  is `unspecified`. `map_from(..., keep_raw=True)` keeps a Markdown report as
  `raw_payload.text`.
- Mapping records have a `parsed` rule for values a mapper reads out of the reviewer's
  text by a pattern, and `Recorder.parse` to record them.

## 0.5.0

- Added `review_context.stage`, `pre_publication` or `post_publication`, after Crossref's
  peer-review `stage`. Removed `post_publication` from `review_context.review_type`, which
  now only says what kind of review it is. Existing records must move that value to
  `stage` and set `review_type` to the kind of review, for example `initial` or
  `community_comment`.
- Added the Crossref peer-review types OCRS could not express to
  `review_context.review_type`: `author_comment`, `community_comment`, `aggregate` and
  `recommendation`. Of Crossref's other types, `referee-report` is `initial`, `revision`
  or `rebuttal_response` depending on the round, `editor-report` is `meta_review`, and
  `manuscript` is the reviewed manuscript itself rather than a review, so it has no value.

- Added optional `provenance.review_doi`, the DOI registered for the review itself
  (e.g., a Crossref peer review DOI). The reviewed work's DOI stays in
  `target.identifiers.doi`.
- Added `proceedings_article` to `target.work_type`, for papers published in
  conference proceedings.

- Renamed metric `uncertainty.confidence` to `uncertainty.credence`, retaining the
  0–1 bounds, interval, and rationale. Existing records must rename this nested key,
  including in metrics within claim assessments. `decision.confidence` and finding and
  claim `probability` and `credence` are unchanged.

- Added shared structured evidence locations with section, one-based page, document
  version, and exact text anchors with surrounding context. Artifact assessments now
  support the same `evidence_links` as claims, findings, and metrics. Existing links
  remain valid.

- Split acceptance recommendations from `decision.revision_requirement`, with `none`,
  `minor`, `major`, and `unspecified` options. Revision-only source decisions no longer
  imply an acceptance judgment. This replaces the revision values in the old enum.
  Existing records must move `minor_revision` and `major_revision` from
  `decision.recommendation` to `decision.revision_requirement` as `minor` and `major`,
  and `revise` to `unspecified`, leaving `recommendation` absent unless the source
  separately states an acceptance judgment. The mappers make this split on import.
  Export to a source with one decision field puts a requested revision ahead of
  acceptance, so it loses the acceptance judgment when both are present.
- Updated decision mappers, examples, and migration guidance. Published v0.4.0 is unchanged.
- Removed duplicate `seed` and `seeds` fields from `ai_referee.execution`.
  Review-run seeds live in `referee.reproducibility`; explicit stage seeds override
  the whole-review seed. Existing records must move `ai_referee.execution.seed` and
  `seeds` to that location; where both locations were populated, resolve conflicts using
  the actual run configuration.
- `target.identifiers` takes every identifier type Crossref uses for related items:
  `handle`, `ark`, `isbn`, `issn`, `ecli`, `accession` (with an optional `database`),
  `purl` and `uuid`. All are optional, so existing records stay valid. `issn` names the
  journal or series, so it never becomes the primary identifier. `ocrs.identifiers`
  adds validators, resolver URLs and `build_work_identifiers` arguments for them.
- `target.work_id` has a format: `<type>:<value>`, where `<type>` is the primary
  identifier's key in `target.identifiers` (`doi:10.7554/eLife.112155.1`). An internal ID
  also names its field (`internal_id:openreview_forum:2dnO3LLiJ1`), and a work with no
  identifier is `unknown`. Existing records must rewrite `work_id`;
  `generate_canonical_work_id(identifiers)` builds it. Mappers now derive it from
  `identifiers`, so a DOI wins over a platform's paper ID, and `map_to` reads the platform
  ID back from `identifiers.internal_id`. `map_with_record`'s `work_id` still takes any
  identifier of the paper.
- `target` names the exact version reviewed. Its other versions and forms go in the new
  `target.relations`: each has a `type`, its `identifiers` and an optional `version`. The
  types are Crossref's intra-work relation types (`is_version_of`, `is_preprint_of`,
  `replaces`, `is_same_as`, …) and DataCite's `is_new_version_of` and
  `is_previous_version_of`, in snake_case. `target.revision_of` is deprecated: use a
  relation of type `is_new_version_of`.
- Replaced `findings.required_changes` and `findings.optional_suggestions` with one
  `findings.changes` list. A change's `priority` is now `critical`, `major`, `minor`, or
  `trivial` (was `low`, `medium`, `high`, or `blocking`) and says how serious the problem
  is, not whether the reviewer requires the change; `decision.revision_requirement` still
  records that. The new values also apply to `ethics_and_risk.required_mitigations`.
  Existing records must move both lists into `changes` and map each priority to a new value.

## 0.4.0

The first public version.

### Schema

- `$id` is `https://valency-oss.github.io/open-canonical-review-schema/v0.4.0/canonical-review.schema.json`, and each version is published at its own URL.
- A human review no longer needs a `human_referee` object.
- Findings and claim assessments take optional `probability` (how likely the statement is true, 0–1) and `credence` (how confident the reviewer is in that probability, 0–1). `credence` needs `probability`.

### Python package

- `map_from` keeps an AI reviewer's raw output in `provenance.raw_payload` when `keep_raw=True`.
- The OpenReview mapper leaves out `referee_id` and `source_review_id` when the note has no signature or `id`, instead of writing `null`.
- Removed the PAT mapper.
- `ocrs.mappers.ai` (was `ocrs.mappers._ai`) holds the helpers the AI reviewer mappers are built on.
