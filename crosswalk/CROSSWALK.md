# OCRS crosswalk

**This file is generated. Do not edit it.** Run `uv run scripts/build_crosswalk.py` to rebuild it.

The crosswalk shows what each mapper does on the test fixtures. A blank cell means no fixture for that system filled the field. It does not always mean the system cannot fill it.

## How it is made

The generator runs each mapper over every fixture in `tests/fixtures/` and `tests/fixtures/real/` for its system. It then reads back where each OCRS value came from.

- The AI reviewers (DeepReview, OpenAIReview, Reviewer3) keep a mapping record. Each step names the reviewer's field and how its value was taken.
- The saved-page OpenReview mapper (`openreview_page`) lists the page field behind each value.
- The other mappers keep no record. Their columns say only which OCRS fields their reviews fill: **fields observed, sources not recorded**.

## How to read it

Each cell is `method:source_field`. Several are separated by `|`.

| Method | Meaning |
|---|---|
| `copied` | The value was copied as it was. |
| `lookup` | The value was looked up in a table (a label to a recommendation, say). |
| `parsed` | The value was read from the text by a pattern (a page number, say). |
| `anchored_exact` | A quote was found word for word in the paper. |
| `anchored_fuzzy` | A quote was found approximately in the paper. |
| `observed` | The field was filled, but the mapper does not say from what. |

Paths use `[]` for any list position. The files beside this one hold the same data:

- `crosswalk.long.csv`: one row per OCRS field, system and source field, with the number of fixtures that showed it.
- `crosswalk.csv`: one row per OCRS field, including all 851 leaf fields, one column per system.
- `gaps.csv`: source fields with no OCRS field, fields lost on a round trip, and values coerced to an allowed one.
- `coverage.csv`: the table below.

Schema: `https://valency-oss.github.io/open-canonical-review-schema/v0.9.1/canonical-review.schema.json`.

## Coverage

Out of 851 OCRS leaf fields.

| System | Leaf fields filled | % | Required filled | Unmapped source fields | Fixtures | Column |
|---|---|---|---|---|---|---|
| `cmt` | 35 | 4.1 | 8 of 8 |  | 2 | fields observed, sources not recorded |
| `deepreview` | 44 | 5.2 | 8 of 8 | 0 | 1 | fields and sources recorded |
| `editorialmanager` | 40 | 4.7 | 8 of 8 |  | 4 | fields observed, sources not recorded |
| `hotcrp` | 42 | 4.9 | 8 of 8 |  | 3 | fields observed, sources not recorded |
| `jats` | 31 | 3.6 | 8 of 8 |  | 7 | fields observed, sources not recorded |
| `journal_narrative` | 21 | 2.5 | 8 of 8 |  | 8 | fields observed, sources not recorded |
| `openaireview` | 33 | 3.9 | 8 of 8 | 14 | 5 | fields and sources recorded |
| `openreview` | 56 | 6.6 | 8 of 8 |  | 37 | fields observed, sources not recorded |
| `openreview_page` | 52 | 6.1 | 8 of 8 | 1 | 2 | fields and sources recorded |
| `reviewer3` | 50 | 5.9 | 8 of 8 | 0 | 1 | fields and sources recorded |
| `scholarone` | 41 | 4.8 | 8 of 8 |  | 3 | fields observed, sources not recorded |

## Fields by section

Only fields at least one system fills are shown. `crosswalk.csv` lists every field.

### top level

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `$schema` |  | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `created_at` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `review_id` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `updated_at` |  |  |  |  | observed |  |  |  | observed | observed |  |  |
| `version` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |

### `opinion`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `opinion.decision.rationale` |  |  |  |  |  |  |  |  |  | copied:Final Justification |  |  |
| `opinion.decision.recommendation` |  | observed |  | observed | observed | observed |  |  | observed | lookup:Rating |  |  |
| `opinion.decision.revision_requirement` |  |  |  | observed |  |  |  |  |  |  |  | observed |
| `opinion.decision.source_label` |  |  |  | observed |  | observed |  |  | observed |  |  | observed |
| `opinion.metric_refs` |  | observed |  |  | observed |  |  |  | observed | observed |  | observed |
| `opinion.summary` |  | observed | copied:summary | observed | observed | observed | observed | copied:methods.progressive__*.overall_feedback | observed | copied:Summary |  | observed |

No fixture fills 2 of the 8 fields in this section.

### `findings`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `findings.changes[].id` |  |  |  |  |  |  |  |  | observed |  |  |  |
| `findings.changes[].text` |  |  |  |  |  |  |  |  | observed |  |  |  |
| `findings.comments[].evidence_links[].location.figure` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `findings.comments[].evidence_links[].location.label` |  |  |  |  |  |  |  |  |  |  | copied:comments[].excerpt \| parsed:comments[].page |  |
| `findings.comments[].evidence_links[].location.page` |  |  |  |  |  |  |  |  |  |  | parsed:comments[].page |  |
| `findings.comments[].evidence_links[].quote` |  |  |  |  |  |  |  |  |  |  | copied:comments[].excerpt |  |
| `findings.comments[].evidence_links[].resource.type` |  |  |  |  |  |  |  |  |  |  | observed \| parsed:comments[].excerpt |  |
| `findings.comments[].group` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `findings.comments[].id` |  |  |  |  |  |  |  |  | observed | observed | parsed:comments[].number |  |
| `findings.comments[].tags` |  |  |  |  |  |  |  |  | observed | observed |  |  |
| `findings.comments[].text` |  |  |  |  |  |  |  |  | observed | copied:Ethical Concerns | copied:comments[].text |  |
| `findings.comments[].title` |  |  |  |  |  |  |  |  |  |  | copied:comments[].title |  |
| `findings.questions[]` |  |  |  |  |  |  |  |  |  | copied:Questions |  |  |
| `findings.questions[].id` |  |  |  |  | observed |  |  |  | observed | observed |  |  |
| `findings.questions[].text` |  |  |  |  | observed |  |  |  | observed | observed |  |  |
| `findings.strengths[]` |  |  |  |  |  |  |  |  |  | copied:Strengths And Weaknesses |  |  |
| `findings.strengths[].group` |  |  |  |  |  |  |  |  | observed | observed |  |  |
| `findings.strengths[].id` |  |  | observed |  | observed |  |  |  | observed | observed |  |  |
| `findings.strengths[].text` |  |  | copied:strengths[].text |  | observed |  |  |  | observed | observed |  |  |
| `findings.strengths[].title` |  |  |  |  |  |  |  |  |  | observed |  |  |
| `findings.weaknesses[]` |  |  |  |  |  |  |  |  |  | copied:Strengths And Weaknesses \| lookup:Strengths And Weaknesses |  |  |
| `findings.weaknesses[].evidence_links[]` |  |  |  |  |  |  |  | anchored_exact:methods.progressive__*.comments[].quote \| anchored_fuzzy:methods.progressive__*.comments[].quote |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.equation` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.figure` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.label` |  |  | observed \| parsed:issues[].tiers[].items[].location |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.page` |  |  | parsed:issues[].tiers[].items[].location |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.page_end` |  |  | parsed:issues[].tiers[].items[].location |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.section` |  |  | parsed:issues[].tiers[].items[].location |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.table` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].location.text_anchor.exact` |  |  |  |  |  |  |  | copied:methods.progressive__*.comments[].quote |  |  |  |  |
| `findings.weaknesses[].evidence_links[].quote` |  |  | parsed:issues[].tiers[].items[].text |  |  |  |  | copied:methods.progressive__*.comments[].quote |  |  |  |  |
| `findings.weaknesses[].evidence_links[].resource.ref` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].resource.type` |  |  | observed \| parsed:issues[].tiers[].items[].location |  |  |  |  | observed |  |  |  |  |
| `findings.weaknesses[].evidence_links[].resource.work` |  |  | parsed:weaknesses[].text |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].resource.work.authors` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].resource.work.title` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].evidence_links[].resource.work.year` |  |  | observed |  |  |  |  |  |  |  |  |  |
| `findings.weaknesses[].group` |  |  | copied:issues[].heading \| copied:issues[].tiers[].heading |  |  |  |  |  | observed | observed |  |  |
| `findings.weaknesses[].id` |  |  | observed |  | observed |  |  | observed | observed | observed |  |  |
| `findings.weaknesses[].severity` |  |  | lookup:issues[].tiers[].heading |  |  |  |  |  |  | observed |  |  |
| `findings.weaknesses[].tags` |  |  |  |  |  |  |  | copied:methods.progressive__*.comments[].comment_type | observed |  |  |  |
| `findings.weaknesses[].text` |  |  | copied:issues[].tiers[].items[].text \| copied:weaknesses[].text |  | observed |  |  | copied:methods.progressive__*.comments[].explanation | observed | observed |  |  |
| `findings.weaknesses[].title` |  |  | copied:issues[].tiers[].items[].title |  |  |  |  | copied:methods.progressive__*.comments[].title |  |  |  |  |

No fixture fills 340 of the 383 fields in this section.

### `metrics`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `metrics[]` |  |  |  |  |  |  |  |  |  | parsed:Clarity \| parsed:Confidence \| parsed:Originality \| lookup:Quality \| lookup:Rating |  |  |
| `metrics[].definition_ref.key` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |
| `metrics[].definition_ref.schema_id` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |
| `metrics[].id` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |
| `metrics[].justification` |  | observed |  | observed | observed |  |  |  | observed |  |  | observed |
| `metrics[].normalized.method` |  | observed |  | observed | observed |  |  |  | observed |  |  | observed |
| `metrics[].normalized.value_0_1` |  | observed |  | observed | observed |  |  |  | observed |  |  | observed |
| `metrics[].value` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |

No fixture fills 8 of the 16 fields in this section.

### `referees`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `referees[].ai_referee.execution.ended_at` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].ai_referee.execution.started_at` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].ai_referee.execution.wall_time_seconds` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].ai_referee.outputs.token_usage.input_tokens` |  |  |  |  |  |  |  | copied:methods.progressive__*.prompt_tokens |  |  |  |  |
| `referees[].ai_referee.outputs.token_usage.output_tokens` |  |  |  |  |  |  |  | copied:methods.progressive__*.completion_tokens |  |  |  |  |
| `referees[].ai_referee.system.critic_framework.name` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].ai_referee.system.critic_framework.version` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].ai_referee.system.models[].model_id` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].ai_referee.system.models[].role` |  |  | observed |  |  |  |  | observed |  |  | observed |  |
| `referees[].competing_interests_declared` |  |  |  |  |  | observed |  |  |  |  |  | observed |
| `referees[].competing_interests_statement` |  |  |  |  |  | observed |  |  |  |  |  |  |
| `referees[].expertise.self_reported_level` |  |  |  |  | observed |  |  |  |  |  |  |  |
| `referees[].human_referee.affiliation` |  |  |  | observed |  | observed |  |  |  |  |  | observed |
| `referees[].human_referee.name` |  |  |  | observed | observed | observed |  |  |  |  |  | observed |
| `referees[].human_referee.orcid` |  |  |  | observed |  |  |  |  |  |  |  | observed |
| `referees[].human_referee.scopus_id` |  |  |  | observed |  |  |  |  |  |  |  |  |
| `referees[].human_referee.third_party_id.key` |  |  |  |  |  |  |  |  |  |  |  | observed |
| `referees[].human_referee.third_party_id.value` |  |  |  |  |  |  |  |  |  |  |  | observed |
| `referees[].identity_mode` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `referees[].referee_id` |  | observed |  | observed | observed |  | observed |  | observed | observed |  | observed |
| `referees[].referee_type` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |

No fixture fills 77 of the 98 fields in this section.

### `target`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `target.identifiers.arxiv_id.hyperlink` |  |  |  |  |  |  |  |  | observed |  |  |  |
| `target.identifiers.arxiv_id.value` |  |  |  |  |  |  |  |  | observed |  |  |  |
| `target.identifiers.doi.hyperlink` |  |  | observed |  |  | observed | observed | observed | observed |  | observed |  |
| `target.identifiers.doi.value` |  |  | observed |  |  | observed | observed | observed | observed |  | observed |  |
| `target.identifiers.internal_id.field_name` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |
| `target.identifiers.internal_id.hyperlink` |  |  |  |  |  |  |  |  | observed | observed |  |  |
| `target.identifiers.internal_id.value` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |
| `target.title` |  | observed |  | observed |  | observed |  |  | observed | observed | copied:title | observed |
| `target.track` |  | observed |  |  |  |  |  |  |  |  |  |  |
| `target.venue` |  | observed |  | observed |  | observed | observed |  | observed | observed |  | observed |
| `target.work_id` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `target.work_type` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |

No fixture fills 77 of the 89 fields in this section.

### `calibration`

No fixture fills 3 of the 3 fields in this section.

### `checks`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `checks[].id` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `checks[].kind` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `checks[].outcome` |  |  |  |  |  |  |  |  |  |  | parsed:fatal_flaws.text |  |
| `checks[].performed_by.name` |  |  |  |  |  |  |  |  |  |  | parsed:ai_text_detection |  |
| `checks[].results[].data` |  |  |  |  |  |  |  |  |  |  | parsed:ai_text_detection \| parsed:reference_check.entries[].status \| parsed:reference_check.summary |  |
| `checks[].results[].evidence_links[].location.label` |  |  |  |  |  |  |  |  |  |  | copied:reference_check.entries[].number |  |
| `checks[].results[].evidence_links[].resource.ref` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `checks[].results[].evidence_links[].resource.type` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `checks[].results[].evidence_links[].resource.work.citation` |  |  |  |  |  |  |  |  |  |  | copied:reference_check.entries[].citation |  |
| `checks[].results[].id` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `checks[].results[].status` |  |  |  |  |  |  |  |  |  |  | parsed:reference_check.entries[].status |  |
| `checks[].summary` |  |  |  |  |  |  |  |  |  |  | copied:ai_text_detection \| copied:fatal_flaws.text \| parsed:reference_check.summary |  |

No fixture fills 70 of the 82 fields in this section.

### `narrative`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `narrative[]` |  |  |  |  |  |  |  |  |  | copied:Limitations \| copied:Questions \| copied:Strengths And Weaknesses \| copied:Summary |  |  |
| `narrative[].audience` |  | observed |  | observed | observed |  |  |  |  |  |  | observed |
| `narrative[].content` |  | observed |  | observed | observed | observed | observed |  | observed | observed |  | observed |
| `narrative[].role` |  | observed |  | observed | observed | observed | observed |  | observed | observed |  | observed |
| `narrative[].title` |  | observed |  | observed | observed | observed | observed |  | observed | observed |  | observed |

No fixture fills 1 of the 6 fields in this section.

### `provenance`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `provenance.imported_at` |  | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `provenance.license.name` |  |  |  |  |  |  |  |  | observed |  |  |  |
| `provenance.license.url` |  |  |  |  |  | observed |  |  |  |  |  |  |
| `provenance.mapping.lossiness_notes` |  |  |  |  |  |  |  |  |  | observed |  |  |
| `provenance.mapping.mapper_version` |  | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `provenance.mapping.mapping_spec_id` |  | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `provenance.mapping.mapping_spec_version` |  | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `provenance.review_doi` |  |  |  |  |  | observed |  |  |  |  |  |  |
| `provenance.source_review_id` |  | observed | observed | observed | observed | observed |  | observed | observed | observed | observed | observed |
| `provenance.source_system` | yes | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed | observed |
| `provenance.source_url` |  |  |  |  |  |  |  |  |  | observed |  |  |

### `related_reviews`

No fixture fills 4 of the 4 fields in this section.

### `review_context`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `review_context.metric_schemas` |  | observed |  | observed | observed |  |  |  | observed | observed |  | observed |
| `review_context.review_type` |  |  |  |  |  | observed |  |  | observed | observed |  |  |
| `review_context.round` |  |  |  | observed | observed |  |  |  |  |  |  |  |
| `review_context.stage` |  |  |  |  |  |  |  |  |  | observed |  |  |

No fixture fills 2 of the 6 fields in this section.

### `signatures`

No fixture fills 2 of the 2 fields in this section.

### `text_format`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `text_format.markup` |  |  |  |  |  |  |  |  |  | observed | observed |  |
| `text_format.math` |  |  |  |  |  |  |  |  |  | observed | observed |  |

### `work_summary`

| OCRS field | Required | `cmt` | `deepreview` | `editorialmanager` | `hotcrp` | `jats` | `journal_narrative` | `openaireview` | `openreview` | `openreview_page` | `reviewer3` | `scholarone` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `work_summary.contributions[].id` |  |  |  |  |  |  |  |  |  |  | observed |  |
| `work_summary.contributions[].text` |  |  |  |  |  |  |  |  |  |  | copied:overview[].text |  |
| `work_summary.contributions[].title` |  |  |  |  |  |  |  |  |  |  | copied:overview[].title |  |

No fixture fills 132 of the 135 fields in this section.

### `written_report`

No fixture fills 8 of the 8 fields in this section.

## Gaps

- **unmapped**: a source field with no OCRS field. Its value is kept in `extensions.<system>`. The count is how many times it was seen. An OpenAIReview paper.json is mapped once per model, and each run counts the other models' entries as unmapped, so its counts add up over all the models. Only systems whose mappers record their mapping report it.
- **kept_in_extensions**: a source field a mapper that records nothing kept in `extensions.<system>`, to write it back. It may have no OCRS field, or be a copy of one it also maps (JATS keeps the article's title, which it maps to `target.title`). The count is how many times it was seen.
- **lost_on_roundtrip**: a source field that does not come back when an OCRS review is written in the source's format again. Taken from `tests/test_roundtrip.py` and `tests/test_real_reviews.py`. The count is how many fixtures lose it.
- **coerced**: a source value OCRS does not allow, replaced by the nearest allowed one.

### `cmt`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| lost_on_roundtrip | `bestPaperNomination` |  | 1 |
| lost_on_roundtrip | `confidentialToPC` |  | 1 |
| lost_on_roundtrip | `ethicsReview` |  | 1 |
| lost_on_roundtrip | `reviewerEmail` |  | 1 |
| lost_on_roundtrip | `submissionDate` |  | 1 |

### `deepreview`

No gaps seen.

### `editorialmanager`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| lost_on_roundtrip | `articleType` |  | 2 |
| lost_on_roundtrip | `dateDue` |  | 1 |
| lost_on_roundtrip | `dateRequested` |  | 1 |
| lost_on_roundtrip | `departments` |  | 1 |
| lost_on_roundtrip | `documentId` |  | 1 |
| lost_on_roundtrip | `inputIndex` |  | 1 |
| lost_on_roundtrip | `journalId` |  | 1 |
| lost_on_roundtrip | `keywords` |  | 1 |
| lost_on_roundtrip | `previousReviewId` |  | 1 |
| lost_on_roundtrip | `ratings[].questionId` |  | 2 |
| lost_on_roundtrip | `reviewerAssignmentStatus` |  | 1 |
| lost_on_roundtrip | `reviewerAverageMScore` |  | 1 |
| lost_on_roundtrip | `reviewerDateAssigned` |  | 1 |
| lost_on_roundtrip | `reviewerDateInvited` |  | 1 |
| lost_on_roundtrip | `reviewerFirstName` |  | 1 |
| lost_on_roundtrip | `reviewerFullName` |  | 1 |
| lost_on_roundtrip | `reviewerLastName` |  | 1 |
| lost_on_roundtrip | `reviewerORCIDId` |  | 1 |
| lost_on_roundtrip | `reviewerORCIDIdValidation` |  | 1 |
| lost_on_roundtrip | `reviewerPersonId` |  | 1 |
| lost_on_roundtrip | `reviewerPrimaryEmailAddress` |  | 1 |
| lost_on_roundtrip | `reviewerRank` |  | 1 |
| lost_on_roundtrip | `reviewerRecommendation` |  | 1 |
| lost_on_roundtrip | `reviewerRecommendationNumericValue` |  | 1 |
| lost_on_roundtrip | `reviewerSalutation` |  | 1 |
| lost_on_roundtrip | `revision` |  | 1 |
| lost_on_roundtrip | `scoreSheetCompletedDate` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[]` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].answerType` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].customQuestionId` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].questionName` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].questionStatus` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerId` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerName` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerStatus` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.numericValue` |  | 1 |
| lost_on_roundtrip | `scoreSheetDueDate` |  | 1 |
| lost_on_roundtrip | `scoreSheetName` |  | 1 |

### `hotcrp`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| lost_on_roundtrip | `ComAut` |  | 1 |
| lost_on_roundtrip | `ComPC` |  | 1 |
| lost_on_roundtrip | `OveMer` |  | 1 |
| lost_on_roundtrip | `PapSum` |  | 1 |
| lost_on_roundtrip | `RevExp` |  | 1 |
| lost_on_roundtrip | `blind` |  | 1 |
| lost_on_roundtrip | `object` |  | 1 |
| lost_on_roundtrip | `ordinal` |  | 2 |
| lost_on_roundtrip | `reviewer.first` |  | 1 |
| lost_on_roundtrip | `reviewer.last` |  | 1 |
| lost_on_roundtrip | `reviewer_email` |  | 1 |
| lost_on_roundtrip | `rid` |  | 1 |
| lost_on_roundtrip | `rtype` |  | 2 |
| lost_on_roundtrip | `rtype_name` |  | 1 |
| lost_on_roundtrip | `status` |  | 1 |
| lost_on_roundtrip | `submitted` |  | 1 |
| lost_on_roundtrip | `version` |  | 1 |

### `jats`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| kept_in_extensions | `article.doi` |  | 7 |
| kept_in_extensions | `article.journal` |  | 7 |
| kept_in_extensions | `article.title` |  | 7 |
| kept_in_extensions | `article_type` |  | 7 |
| kept_in_extensions | `contributors[].affiliation_ref.id` |  | 3 |
| kept_in_extensions | `contributors[].affiliation_ref.label` |  | 3 |
| kept_in_extensions | `contributors[].given_names` |  | 17 |
| kept_in_extensions | `contributors[].orcid_element` |  | 19 |
| kept_in_extensions | `contributors[].role.specific_use` |  | 16 |
| kept_in_extensions | `contributors[].role.text` |  | 19 |
| kept_in_extensions | `contributors[].surname` |  | 17 |
| kept_in_extensions | `keywords[].terms[]` |  | 2 |
| kept_in_extensions | `keywords[].type` |  | 2 |
| kept_in_extensions | `lists_in_paragraphs` |  | 1 |
| kept_in_extensions | `permissions.copyright_statement` |  | 3 |
| kept_in_extensions | `permissions.copyright_year` |  | 3 |
| kept_in_extensions | `permissions.licenses[].text` |  | 4 |
| kept_in_extensions | `permissions.licenses[].url` |  | 3 |
| kept_in_extensions | `pub_date.pub_type` |  | 3 |
| kept_in_extensions | `recommendation.name` |  | 3 |
| kept_in_extensions | `recommendation.value` |  | 3 |
| kept_in_extensions | `related_article.ext-link-type` |  | 3 |
| kept_in_extensions | `related_article.id` |  | 3 |
| kept_in_extensions | `related_article.related-article-type` |  | 3 |
| kept_in_extensions | `responses[]` |  | 1 |
| kept_in_extensions | `title` |  | 7 |
| lost_on_roundtrip | `sub_article.body[].disp-quote[].@content-type` |  | 1 |
| lost_on_roundtrip | `sub_article.body[].p[]` |  | 1 |
| lost_on_roundtrip | `sub_article.front-stub[].contrib-group[].contrib[].aff[].addr-line` |  | 1 |
| lost_on_roundtrip | `sub_article.front-stub[].contrib-group[].contrib[].aff[].country` |  | 2 |
| lost_on_roundtrip | `sub_article.front-stub[].contrib-group[].contrib[].aff[].institution` |  | 2 |

### `journal_narrative`

No gaps seen.

### `openaireview`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| unmapped | `methods.progressive__*.comments[].comment_type` |  | 36 |
| unmapped | `methods.progressive__*.comments[].explanation` |  | 36 |
| unmapped | `methods.progressive__*.comments[].id` |  | 75 |
| unmapped | `methods.progressive__*.comments[].paragraph_index` |  | 75 |
| unmapped | `methods.progressive__*.comments[].quote` |  | 36 |
| unmapped | `methods.progressive__*.comments[].title` |  | 36 |
| unmapped | `methods.progressive__*.completion_tokens` |  | 4 |
| unmapped | `methods.progressive__*.cost_usd` |  | 9 |
| unmapped | `methods.progressive__*.label` |  | 9 |
| unmapped | `methods.progressive__*.model` |  | 9 |
| unmapped | `methods.progressive__*.overall_feedback` |  | 4 |
| unmapped | `methods.progressive__*.prompt_tokens` |  | 4 |
| unmapped | `slug` |  | 5 |
| unmapped | `title` |  | 5 |

### `openreview`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| kept_in_extensions | `ethics_flags.fields.ethics_flag` |  | 5 |
| kept_in_extensions | `ethics_flags.fields.flag_for_ethics_review` |  | 3 |
| kept_in_extensions | `ethics_flags.fields.flag_for_ethics_review[]` |  | 14 |
| kept_in_extensions | `ethics_flags.say.concern_categories[]` |  | 1 |
| kept_in_extensions | `ethics_flags.say.ethical_concerns` |  | 22 |
| kept_in_extensions | `venueid` |  | 35 |
| lost_on_roundtrip | `content.code_of_conduct` |  | 16 |
| lost_on_roundtrip | `content.comment` |  | 2 |
| lost_on_roundtrip | `content.recommendation` |  | 1 |
| lost_on_roundtrip | `content.title` |  | 9 |
| lost_on_roundtrip | `domain` |  | 32 |
| lost_on_roundtrip | `invitation` |  | 1 |
| lost_on_roundtrip | `invitations` |  | 35 |
| lost_on_roundtrip | `nonreaders` |  | 29 |
| lost_on_roundtrip | `number` |  | 33 |
| lost_on_roundtrip | `parentInvitations` |  | 6 |
| lost_on_roundtrip | `readers` |  | 34 |
| lost_on_roundtrip | `replyto` |  | 36 |
| lost_on_roundtrip | `tcdate` |  | 33 |
| lost_on_roundtrip | `tmdate` |  | 33 |
| lost_on_roundtrip | `version` |  | 32 |
| lost_on_roundtrip | `writers` |  | 33 |

### `openreview_page`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| unmapped | `Code Of Conduct Acknowledgement` |  | 1 |

### `reviewer3`

No gaps seen.

### `scholarone`

| Kind | Source field | OCRS field | Count |
|---|---|---|---|
| lost_on_roundtrip | `articleType` |  | 1 |
| lost_on_roundtrip | `criteriaResponses[].criterionId` |  | 1 |
| lost_on_roundtrip | `dateReviewRequested` |  | 1 |
| lost_on_roundtrip | `departments` |  | 1 |
| lost_on_roundtrip | `fundingStatement` |  | 1 |
| lost_on_roundtrip | `inputIndex` |  | 1 |
| lost_on_roundtrip | `journalCode` |  | 1 |
| lost_on_roundtrip | `numberOfDaysFromReviewAssignmentToCompletion` |  | 1 |
| lost_on_roundtrip | `reviewAverageMScore` |  | 1 |
| lost_on_roundtrip | `reviewRScore` |  | 1 |
| lost_on_roundtrip | `reviewSumMScore` |  | 1 |
| lost_on_roundtrip | `reviewerAssignmentStatus` |  | 1 |
| lost_on_roundtrip | `reviewerDateAssigned` |  | 1 |
| lost_on_roundtrip | `reviewerDateInvited` |  | 1 |
| lost_on_roundtrip | `reviewerFirstName` |  | 1 |
| lost_on_roundtrip | `reviewerFullName` |  | 1 |
| lost_on_roundtrip | `reviewerLastName` |  | 1 |
| lost_on_roundtrip | `reviewerORCIDId` |  | 1 |
| lost_on_roundtrip | `reviewerORCIDIdValidation` |  | 1 |
| lost_on_roundtrip | `reviewerOrcid` |  | 1 |
| lost_on_roundtrip | `reviewerPrimaryEmailAddress` |  | 1 |
| lost_on_roundtrip | `reviewerRatingCustomQuestions` |  | 1 |
| lost_on_roundtrip | `reviewerRatingFormName` |  | 1 |
| lost_on_roundtrip | `reviewerRecommendation` |  | 1 |
| lost_on_roundtrip | `reviewerRecommendationNumericValue` |  | 1 |
| lost_on_roundtrip | `reviewerSalutation` |  | 1 |
| lost_on_roundtrip | `scoreSheetCompletedDate` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[]` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].answerType` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].customQuestionId` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].questionName` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].questionStatus` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerId` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerName` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.answerStatus` |  | 1 |
| lost_on_roundtrip | `scoreSheetCustomQuestions[].scoreSheetCustomAnswer.numericValue` |  | 1 |
| lost_on_roundtrip | `scoreSheetDueDate` |  | 1 |
| lost_on_roundtrip | `scoreSheetName` |  | 1 |
| lost_on_roundtrip | `specialIssue` |  | 1 |
| lost_on_roundtrip | `submissionId` |  | 2 |
