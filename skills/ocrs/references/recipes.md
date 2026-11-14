# Recipes

Worked shapes for common cases, as of OCRS 0.9.3. Each shows only the parts that make the case; fill the required fields (SKILL.md, step 3) and validate.

## A classifier or screening run

A model (or a person) sorts a paper into categories against criteria, usually from part of the paper. Typical inputs: a prompt with a rubric, and model output like `{"id": "…", "label": "OUT_OF_SCOPE", "reason": "…", "evidence": [{"quote": "…"}]}`.

- `review_context.review_type`: `screening`.
- The rubric becomes one `metric_schemas` entry. Put the prompt in `source.snapshot` unchanged, and each output field you score (a label, a study design, a topic) becomes a definition with an `ordinal`, `categorical` or `binary` scale whose `values` are exactly the labels the prompt allows. `direction: none`.
- The model's label is a metric; its `reason` is that metric's `justification`, verbatim.
- Each evidence quote becomes a `comments[]` item: its text is the model's note on the quote (or the reason, if it gave none), with one evidence link carrying the quote. The metric and `opinion` are `supported_by` those comments.
- `opinion.metric_refs`: the headline label only.
- Say what was read: `materials_reviewed[]` with `type: metadata` (or `pdf`), `extent: partial`, `parts: [{"section": "Title"}, {"section": "Abstract"}]`, and a `content_hash` of the exact text sent to the model. Give each quote a `span` against that same text (`text_ref` = that hash) so validation can prove the quote is real.
- The model: `models[]: [{"role": "classifier", "model_id": "…"}]`; the prompt: `prompts[]: [{"role": "system", "prompt_hash": "sha256:…"}]`.
- A label that needs no evidence (e.g. "not relevant") still gets a record, with only the metric. Do not invent a reason.
- If the label carries a detail the scale does not list (e.g. `"Category: sub-item"`), store the scale's value in `value` and the original string in `source_value`.

Skeleton:

```json
{
  "$schema": "<schema URL>",
  "review_id": "screen-<work>-<run>", "version": "1.0.0", "created_at": "<run end>",
  "provenance": {"source_system": "<your pipeline>"},
  "referees": [{"referee_type": "ai", "identity_mode": "open", "ai_referee": {
    "system": {"critic_framework": {"name": "<pipeline>", "version": "<prompt hash or release>"},
               "models": [{"role": "classifier", "model_id": "<model>"}]},
    "execution": {"started_at": "…", "ended_at": "…", "run_id": "<batch id>"},
    "inputs": {"materials_reviewed": [{"type": "metadata", "ref": "<url>", "content_hash": "sha256:…",
                                       "extent": "partial", "parts": [{"section": "Title"}, {"section": "Abstract"}]}],
               "prompts": [{"role": "system", "prompt_hash": "sha256:…"}]}}}],
  "target": {"work_id": "arxiv_id:…", "work_type": "preprint", "title": "…"},
  "review_context": {"review_type": "screening", "metric_schemas": {"scope": {
    "source": {"name": "<rubric name>", "snapshot": "<prompt, unchanged>"},
    "definitions": {"label": {"label": "In scope", "dimension": "other", "direction": "none",
      "scale": {"type": "categorical", "values": ["IN_SCOPE", "OUT_OF_SCOPE"]}}}}}},
  "opinion": {"metric_refs": ["m-label"], "supported_by": ["c1"]},
  "metrics": [{"id": "m-label", "definition_ref": {"schema_id": "scope", "key": "label"},
               "value": "OUT_OF_SCOPE", "justification": "<reason, verbatim>", "supported_by": ["c1"]}],
  "findings": {"comments": [{"id": "c1", "text": "<note on the quote>", "evidence_links": [
    {"resource": {"type": "work"}, "quote": "<exact>",
     "location": {"section": "Abstract", "span": {"text_ref": "sha256:…", "start": 0, "end": 0}}}]}]}
}
```

## A free-text referee report

- `review_type`: `initial` (or `revision` for a later round).
- Keep the whole text in `narrative[]`, one part per heading, verbatim, with `role` where the heading says it (summary, review, questions).
- Lift points into `findings` only where the report makes them as separate points (a list item, a numbered concern, a paragraph that is one point). Keep each point's wording; put the heading it sat under in `group`. Severity only if the report says it (a "Minor comments" heading means `minor`).
- A recommendation ("Major revision", "Accept") goes in `opinion.decision`, with the words in `source_label`. "Major revision" is a `revision_requirement`, not a `recommendation`.
- The reviewer's summary of the paper goes in `work_summary.summary`; their overall judgment in `opinion.summary`.
- Scores only if the report gives them; define their scale from the form, not a guess.

## A person signs off on an AI result

- A new record, never an edit of the AI's: same `target`, the person as referee (`identity_mode: confidential` if the name is withheld on purpose, with an internal `referee_id`), same `metric_schemas` copied over so the scales match.
- `related_reviews: [{"type": "supersedes", "review_id": "<the AI record>"}]`.
- Their value as a metric; their note as its `justification` and as `opinion.summary`. `opinion.metric_refs` names the headline value only (the main label or overall score), not secondary categories. Do not copy the AI's evidence over as the person's: if they cited none, the sign-off has none. `opinion.stance` describes the assessment of the reviewed work, not agreement with the previous reviewer. Keep agreement or disagreement in the person’s note.
- The record that stands for a work is then the one no other record supersedes.

## An author response

- `review_type`: `author_comment`; referees are the authors.
- `related_reviews: [{"type": "responds_to", "review_id": "<the review>"}]` (exactly one).
- Each answer is a `comments[]` item with `responds_to: "<finding id in that review>"` and, if stated, `status`.

## A batch

- One record per work per review. Do not pack several works into one record.
- Use one `run_id` (in `execution`) for everything a batch run produced, and the same rubric (`metric_schemas`) in each record, so the batch can be compared later. Before comparing records, check that their rubric definitions are identical.
- Store records as JSON Lines or one file per record; both are fine.
