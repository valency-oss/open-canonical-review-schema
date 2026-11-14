---
name: ocrs
description: Write, read and convert Open Canonical Review Schema (OCRS) records, the open JSON format for peer reviews, screenings and other assessments of scholarly work. Use to write a review as OCRS, to reshape an existing review (free text, a review form, an AI reviewer's output, a classifier's JSON) into one, to summarize, compare or query OCRS records, or to write an OCRS record out to another review system's format. Use whenever a task mentions OCRS or canonical-review JSON, asks to store, exchange, validate or convert a review, referee report, meta-review, author response or screening decision in a standard format, or asks to record what an AI reviewer or classifier concluded about a paper together with its evidence and provenance.
---

# OCRS: reviews as records

OCRS is an open JSON schema for reviews of scholarly work: human, AI or both, full reviews or quick screenings. One record holds one review of one work: who reviewed, what they read, what they concluded, the points behind it, and the exact places in the work those points rest on.

OCRS is open source and still changes (it is pre-1.0; a minor release may break records). **This skill tells you how OCRS thinks; the current schema tells you its field names.** Never write a record from memory: fetch the schema first, then validate what you wrote against it.

## Choose the task

When converting an existing review, preserve its words and stated judgments as described below. When asked to **write a new review**, assess the supplied work within the user's requested scope, write your own findings and conclusions, and cite exact supporting passages. Identify AI authorship and the material actually read; do not attribute your conclusions to a human reviewer. Do not fabricate missing paper content, scores, identities, model versions, or run metadata. When editing, preserve the user's intended meaning and distinguish new assessment from format conversion.

Resolve `scripts/` and `references/` relative to this installed skill's directory, not the user's working directory. Save generated reviews where the user requests.

## Step 1: find the current version

```bash
TAG=$(curl -fsSL https://api.github.com/repos/valency-oss/open-canonical-review-schema/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')   # e.g. v0.9.3
V=${TAG#v}
```

(`gh api repos/valency-oss/open-canonical-review-schema/releases/latest --jq .tag_name` does the same.)

Then read, for that version:

| What | Where |
|---|---|
| The schema (source of truth for every field name, enum and rule) | `https://valency-oss.github.io/open-canonical-review-schema/v$V/canonical-review.schema.json` |
| What changed, with migration notes | `https://raw.githubusercontent.com/valency-oss/open-canonical-review-schema/$TAG/CHANGELOG.md` |
| Complete example records (human, AI, hybrid, author response) | `https://github.com/valency-oss/open-canonical-review-schema/tree/$TAG/examples` |
| The Python package (mappers and validation) | `https://github.com/valency-oss/open-canonical-review-schema/releases/download/$TAG/ocrs-$V-py3-none-any.whl` |

The schema's field `description`s are written to be read: when unsure where something goes, search the schema for the concept (`grep -o '"description": "[^"]*evidence[^"]*"'`) rather than guessing.

**Version rules.**
- If you are extending or editing existing records, keep their version (their `$schema` URL) unless asked to upgrade; mixing versions in one store makes them harder to compare. To upgrade, use `from ocrs.migrate import migrate; upgraded = migrate(record)` and read the CHANGELOG entries in between. In 0.9.3 the helper supports 0.7/0.8 inputs and leaves records already naming 0.9 unchanged; it is not a universal migration engine. Follow release-specific migration notes for other versions and validate the result.
- Otherwise use the latest release, and set `$schema` to that version's schema URL.
- `references/field-map.md` in this skill is a snapshot of where things go **as of OCRS 0.9.3**. If the current version is newer, read the CHANGELOG entries after 0.9.3 before trusting it, and let the fetched schema win any disagreement.

## Step 2: the parts that stay true

These ideas are the design of OCRS, not its current spelling. They hold across versions.

1. **The reviewer's words are data, not material.** Copy text verbatim from the source review. Never summarize, polish, translate or "complete" it. If the review does not say something, leave the field out; do not infer a score, a recommendation, a severity or a confidence it did not give. An empty field is honest; an invented one is a defect.
2. **Evidence points at the work exactly, where the reviewer pointed.** A point's evidence is what the reviewer cited: the passages they quoted and the places they named (a section, a table, a figure). Record each exactly: a quote copied character for character, plus where it is (section, page, figure, or a character span in a pinned text). Do not add passages the reviewer did not cite, however relevant they look; finding support for a reviewer's point is a different task, done only when asked. A quote you cannot find in the source is not evidence. Paraphrase belongs in the point's own text, never inside a quote.
3. **Say exactly what was read.** Record whether the reviewer read the full text or only part of it (title and abstract, one section, the metadata), which version, and a content hash when you have the bytes. A judgement from an abstract is a different thing from a judgement from the paper, and readers must be able to tell.
4. **Define a rubric once, then point at it.** A score is a value on a scale someone defined. Store the scale (its values, their labels, the question asked, and the original form or prompt) once in the record, and have each score refer to its definition. Do not rescale or normalize a score unless you record how.
5. **Link conclusions down to reasons.** The overall verdict and each score link to the points that support them; each point links to its evidence. Links go one way (from the conclusion to its support); never store the inverse too.
6. **AI and people are both referees.** For an AI reviewer, record the system, the model(s) and their roles, the prompt (by hash, with a reference to where it lives), when it ran and what it read. For a person, record what can be disclosed and say what is withheld (identity modes such as anonymous or confidential exist for this).
7. **A record is never edited in place to change its conclusion.** A later review (a second pass, a person's sign-off, a revision) is a new record that says which record it supersedes or responds to. A correction or addition to the same review (a point the reviewer sent later) may edit the record, but bump its `version` and set `updated_at`, and say where the addition came from.
8. **Unknown fields go in extensions, sparingly.** If the source has information OCRS has no place for, keep it under `extensions.<source_system>`, and only if someone needs it. Do not copy into extensions what the record already says elsewhere.

## Step 3: build the record

**Check for a mapper first.** OCRS ships readers for several review systems and AI reviewers (OpenReview, CMT, HotCRP, Editorial Manager, ScholarOne, JATS, journal narratives, OpenAIReview, DeepReview, Reviewer3 at the time of writing). `ocrs.supported_sources()` lists them. If the input is one of these, use `ocrs.map_from(source, payload)` or `ocrs.map_with_record(...)` instead of mapping by hand: it is tested, keeps the text verbatim, and reports what it could not place. Then check its output as you would your own (step 4): a mapper may fill in values the review never gave, such as a recommendation derived from a score or a credence derived from a confidence rating. Remove those and say so in your report.

**Otherwise map by hand:**

1. Pick the review type (a full referee review, a meta-review, an author response, a screening against criteria, and so on) from the schema's enum. A quick check of a submission against criteria (scope, ethics, a reporting checklist) is a screening, not a full review.
2. Identify the work (`target`): its primary identifier in the schema's `<type>:<value>` form, its type and version.
3. Record the referee(s) and, for AI, the run (principle 6) and what was read (principle 3).
4. If there are scores or categories, define their rubric once (principle 4), then add one score per value.
5. Split the review's text into points: strengths, weaknesses, questions, requested changes, neutral comments. A classifier's evidence or a screener's notes are comments. Keep each point's text verbatim; give each an id.
6. Attach evidence to points (principle 2).
7. Fill the overall opinion: the verdict in the reviewer's words, the overall score(s), and the points behind it (principle 5). The opinion names only the headline score (an overall rating, a screening's main label); aspect scores, categories and confidence stay as plain metrics. Map a verdict to a fixed recommendation value only when the reviewer's words state it, and keep their words beside it.
8. Set required top-level fields (`$schema`, id, version, created time, provenance) as the schema requires.

**When the schema requires something the source doesn't say** (the reviewer's identity mode, when the review was written, the work's identifier): use the value that claims least (`unknown` where the schema allows it; for a work with no identifier, `target.work_id: "unknown"`), or one the source system's own conventions settle, and list it in your report as your choice, not the reviewer's. A record's `created_at` is when the review was written; if you don't know it, use the conversion time and say so.

**A quote you cannot find in the source** is not evidence. Leave it out of the evidence links, keep the point (with the reviewer's words unchanged in its text), and report it: a reviewer or classifier that paraphrases inside quotes is worth knowing about. If one passage of the work is unmistakably the one they meant, you may link that passage with its exact text instead, and say in your report that you did.

**A recommendation is stated, not derived.** Don't turn a score into an accept/reject recommendation, even where the form labels the score ("6: marginally above the threshold" is a score with its label, not a `weak_accept`). Record the recommendation only when the reviewer wrote one.

`references/field-map.md` maps each of these steps to fields (as of 0.9.3). `references/recipes.md` has worked shapes for common cases: a classifier or screening run, a free-text referee report, a person signing off on an AI result, and a batch of records.

## Step 4: validate until clean

```bash
uv run --no-project --with "https://github.com/valency-oss/open-canonical-review-schema/releases/download/$TAG/ocrs-$V-py3-none-any.whl" \
  python /path/to/installed/ocrs/scripts/check.py record.json --text source.txt
```

`scripts/check.py` (in this skill) runs `ocrs.validate_canonical`, which checks the schema and OCRS's own rules: ids are unique, every reference resolves, links run the allowed way, score values are on their scale. A record is checked against the schema its own `$schema` names, so an older record is validated as that version, using the latest package. Replace the script path with this installed skill’s path. Omit `--text` when source text is unavailable, or repeat it for multiple UTF-8 texts. Text bytes and line endings must match the pinned source exactly. With `--text`, every evidence span must name a supplied text hash, and its quote must equal the selected text. Without it, spans are explicitly reported as unchecked. Quotes without spans need manual location verification; their messages are advisory and do not change the exit status. A successful exit is not proof that every quotation is grounded. Without `uv`: `pip install` the wheel URL above, or `uvx check-jsonschema --schemafile <the record's $schema URL> record.json` for the schema alone.

Fix every error and run it again. Then check by eye what no validator can:

- Is every quote really in the source? Search for each one.
- Did anything the review said get lost? Did anything get added that it did not say?
- Is every score's value exactly as the reviewer gave it, on the scale they used?
- Does the record say what was read (full text or part)?

## Reshaping an existing review: what to tell the user

When you convert someone's review, end with a short report: what went where, what the review contained that has no OCRS field (and where you kept it, if anywhere), what OCRS asks for that the review did not give (left empty, not invented), and any quote you could not find in the work.

## Reading records

When asked to summarize, compare or answer questions about OCRS records:

1. **Validate first** (step 4). A record that fails is still readable, but say so, and don't trust its links. Note each record's version (`$schema`); before comparing records of different versions, use a common version only where a supported, loss-aware migration exists (step 1); otherwise explain the version differences. Keep the original records.
2. **Find the record that stands.** A record named in another's `related_reviews` as `supersedes` has been replaced: report the newer one, and mention the older only to say what changed. `responds_to` marks an author's reply to a review, not a new verdict.
3. **Read every score against its definition.** Look up each metric's `definition_ref` in `review_context.metric_schemas`: the question asked, the scale, its labels, and its `direction`. A 3 on a 1 to 4 scale is not a 3 on a 1 to 10 scale, and on a `direction: none` scale a higher value is not better. Compare scores across records only when their definitions are identical; otherwise say they can't be compared. Where a metric has `source_value`, that is what the reviewer actually wrote.
4. **Give reasons with their support.** Follow `opinion.supported_by` and each metric's `supported_by` to the points behind them, and each point's `evidence_links` to the work. Quote the record's text as written and name the point (its `id`) you draw on. Don't attribute to a reviewer anything the record doesn't say.
5. **Say who reviewed and what they read.** Distinguish AI from human referees, and say when a judgement rests on part of the work (`extent: partial`, such as title and abstract only).

## Writing a record out to another system

`ocrs.supported_targets()` lists the systems OCRS can write (at the time of writing, the same ones it reads). `ocrs.map_to(target, record)` returns the review in that system's format: a dict, or Markdown text for the AI reviewers that write Markdown. It validates the record against the installed package's schema, so migrate an older record first. Some targets give a part rather than a whole document (JATS gives one `<sub-article>` referee report, to place inside the article's XML); say so when you hand it over.

No other format holds everything OCRS does. Before handing the result over, compare it with the record and report what did not carry over: typically evidence spans, AI provenance (models, prompts, what was read), scores the target's form has no field for, and links between points. If the target isn't supported, write it by hand from the record, keeping the text verbatim, and report the same way.
