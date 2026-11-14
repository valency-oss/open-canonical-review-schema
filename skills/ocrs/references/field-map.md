# Where things go: a field map of OCRS 0.9.3

**Snapshot, dated 2026-11.** Written against OCRS 0.9.3. If the current release (SKILL.md, step 1) is newer, read the CHANGELOG entries after 0.9.3 first; the fetched schema wins every disagreement with this file.

Paths are JSON paths in one record. `[]` means a list. "id" means a review-local id, unique across every addressable item in the record (findings, metrics, claims, contributions, checks, results).

## The record

| Concept | Field | Notes |
|---|---|---|
| Which OCRS version | `$schema` | The version's schema URL. |
| This review's id, its revision, when written | `review_id`, `version`, `created_at` (`updated_at`) | All required except `updated_at`. |
| Where the review came from | `provenance.source_system` (required), `source_review_id`, `source_url`, `review_doi`, `license` | `raw_payload` keeps the source exactly as received, only if asked. |
| The work reviewed | `target.work_id` (`<type>:<value>`, e.g. `doi:10.1/x`, `arxiv_id:2401.00001`, `pubmed_id:123`, `valency_id:W_…`, or `internal_id:<field>:<value>`), `target.work_type`, `title`, `version` | `work_type` is an enum (article, preprint, …). |
| Kind of review | `review_context.review_type` | Enum; includes `initial`, `revision`, `meta_review`, `author_comment`, `screening` (a check against criteria, often from part of the work). |
| Who asked for it | `review_context.requested_by` | Free text. |
| Other reviews it relates to | `related_reviews[]: {type, review_id}` | `type`: `responds_to`, `supersedes`, `summarizes`. |

## Referees

`referees[]` is required, at least one.

| Concept | Field |
|---|---|
| Person, AI or both | `referee_type`: `human`, `ai`, `hybrid` |
| What is disclosed | `identity_mode`: `open`, `single_blind`, `double_blind`, `triple_blind`, `pseudonymous`, `confidential` |
| Id in the source system | `referee_id` |
| A person | `human_referee: {name, orcid, affiliation, …}` (all optional) |
| An AI system | `ai_referee.system.critic_framework: {name, version}`, `ai_referee.system.provider: {organization, platform}`, `ai_referee.system.models[]: {role, model_id, model_version?, parameters?}` |
| Model roles | `reviewer`, `critic`, `verifier`, `retriever`, `ranker`, `planner`, `summarizer`, `classifier`, `other` |
| The run | `ai_referee.execution: {started_at, ended_at, wall_time_seconds, run_id, cost, …}` |
| What it read | `ai_referee.inputs.materials_reviewed[]: {type, ref, content_hash, extent, parts}`; `type` includes `pdf`, `html`, `tex`, `metadata`; `extent`: `full`, `partial`, `unknown` (absent means unknown); `parts[]` are locations such as `{"section": "Abstract"}` |
| Its prompt | `ai_referee.inputs.prompts[]: {role, prompt_hash, prompt_ref}` |
| People in a hybrid review | `hybrid_workflow.human_contributions[]` |

## Scores and categories

Defined once, used by reference.

```json
"review_context": {
  "metric_schemas": {
    "<schema_id>": {
      "source": {"name": "…", "version": "…", "url": "…", "snapshot": "<the original form or prompt, unchanged>"},
      "definitions": {
        "<key>": {
          "label": "…", "dimension": "overall | correctness | … | other", "direction": "higher_is_better | lower_is_better | none",
          "prompt": "<the question asked>",
          "scale": {"type": "ordinal | interval | ratio | binary | categorical | textual",
                    "min": 1, "max": 5, "values": [...], "anchors": [{"value": …, "label": "…"}]}
        }
      }
    }
  }
},
"metrics": [
  {"id": "m1", "definition_ref": {"schema_id": "<schema_id>", "key": "<key>"}, "value": …,
   "justification": "<the reviewer's reason, verbatim>", "supported_by": ["<finding ids>"],
   "source_value": "<the answer as the source wrote it, if it differs>"}
]
```

- `value` must be one of the scale's values or within its bounds; validation checks this.
- `dimension` is a closed enum; an unlisted criterion uses `other` and keeps its own label and prompt.
- `direction: none` for values where higher is not better (an article-type label, a reviewer's confidence, a list of topics).
- Normalizing (`normalized`) needs a stated method; usually leave it out.
- Uncertainty: `uncertainty.interval` on the original scale, or `credence`, with `rationale`.

## The opinion

`opinion` is required (it may be nearly empty).

| Concept | Field |
|---|---|
| The verdict in words | `opinion.summary` |
| Overall sentiment | `opinion.stance`: `positive`, `mixed`, `negative`, `unclear` |
| Accept/reject recommendation | `opinion.decision: {recommendation, revision_requirement, source_label, rationale}` |
| Overall score(s) | `opinion.metric_refs[]`: metric ids; overall ones only |
| Points behind the verdict | `opinion.supported_by[]`: finding ids |

## Points (findings)

`findings` has five lists: `strengths`, `weaknesses`, `questions`, `comments`, `changes`. Each item needs `id` and `text` (verbatim).

| Concept | Field |
|---|---|
| Headline as the reviewer wrote it | `title` |
| Headings it sat under | `group[]`, outermost first |
| Topic or problem kind | `tags[]` (e.g. `ethics`) |
| How serious | `severity` on weaknesses and changes: `info`, `trivial`, `minor`, `major`, `critical` |
| A change fixes a point | `changes[].addresses[]`: finding ids |
| What it is about | `about[]`: typed references to claims, contributions, checks or results |
| How likely it holds | `uncertainty: {probability, credence?, rationale?}` |
| An author's reply to a point | on a comment: `responds_to` (the answered review's finding id) and `status`; needs a `related_reviews` entry of type `responds_to` |

Neutral observations, a classifier's evidence notes and a screener's remarks are `comments`.

## Evidence

On any finding, claim or contribution: `evidence_links[]`.

```json
{"resource": {"type": "work"},
 "version": "v2",
 "quote": "<exact text, character for character>",
 "location": {"section": "3.2", "page": 4, "figure": "Fig. 2",
              "span": {"text_ref": "sha256:<hash of the exact text>", "start": 120, "end": 168}}}
```

- `resource.type`: `work` (the reviewed work), `review`, `artifact` (needs `id`), `external` (needs `ref`).
- `location` fields combine: `section`, `page`/`page_end`, `figure`, `table`, `equation`, `line_start`/`line_end`, `label`, `prefix`/`suffix` (to disambiguate a repeated quote), `span`, `node` (an element id in a structured document).
- `span` offsets are zero-based Unicode code points, end exclusive, counted from the start of the whole text that `text_ref` pins, never from a page or section. Validation with `text_sources={text_ref: text}` checks the quote equals the span.

## Other parts

| Concept | Field |
|---|---|
| Neutral summary of the work, its contributions, its claims | `work_summary: {summary, contributions[], claims[]}` |
| The review's text as written, in parts | `narrative[]: {title, role, audience, content}` |
| Checks the reviewer ran (references, statistics, code) | `checks[]: {id, kind, outcome, results[]}` |
| Associated data, code, supplements | `target.artifacts[]` |
| Source fields with no OCRS home | `extensions.<source_system>` |
