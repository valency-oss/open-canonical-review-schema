# Contributing to OCRS

Thank you for helping with the Open Canonical Review Schema (OCRS). OCRS is two things: a
specification, the JSON Schema for one peer review of one scholarly work, and a Python package
that maps reviews from other systems to it. This guide covers both: how the specification
changes and is versioned, and how to work on the code.

You can contribute by:

- [telling us how you use OCRS](https://github.com/valency-oss/open-canonical-review-schema/issues/new?template=adoption-story.yml), so we know what to keep stable;
- [proposing a schema change](https://github.com/valency-oss/open-canonical-review-schema/issues/new?template=schema-change.yml): a field, a value or a rule OCRS lacks or gets wrong;
- fixing descriptions, examples and documentation;
- adding or improving a mapper for a review system or AI reviewer.

## Contributor License Agreement

Before your contribution can be accepted, you must consent to our
[Contributor License Agreement (CLA)](CLA.md). This ensures that Valency Systems Inc. can use
and distribute your contributions under the project's Apache License 2.0.

You sign on your first pull request: the CLA check comments on it, and you reply with
`I have read the CLA Document and I hereby sign the CLA`. The check records your signature and
passes, and it doesn't ask again on later pull requests.

## The specification

### What is normative

The files in `src/ocrs/schemas/` are the specification. Each release publishes them, unchanged,
at `https://valency-oss.github.io/open-canonical-review-schema/v<version>/`, the folder named in
the review schema's `$id`:

| File | What it defines |
|---|---|
| `canonical-review.schema.json` | A review: its fields, their types, allowed values and descriptions |
| `metric-catalog.core.v1.1.json` | The metric keys reviews use in `metrics` |
| `mapping-spec.v1.2.0.json` | The defaults mappers apply, the metric catalog they use, and the signals that mark a review as written by an AI referee |

A field's `description` is part of the specification: it says what the value means. The rules
that JSON Schema cannot express, such as ids that must be unique and references that must name
a finding, are part of it too, and `validate_canonical` checks them; [CHANGELOG.md](CHANGELOG.md)
lists each with the version that added it. The README, the generated HTML
documentation and the examples are informative. Where they disagree with the schema, the schema
is right and the rest is a bug.

The mapping record that `map_with_record` returns (how each field was mapped, and the gaps) is
part of the Python package, not of the specification: `Rule`, `Step` and `MappingRecord` in
`src/ocrs/mapping.py` define it.

### Proposing a change

Open a [schema change issue](https://github.com/valency-oss/open-canonical-review-schema/issues/new?template=schema-change.yml)
before writing a pull request for anything beyond a fix to a description. A proposal is easiest
to accept when it shows:

- **the data**: a real review, or the export format of a real system, that OCRS cannot express
  or expresses wrongly;
- **who produces it**: the review systems, venues or AI reviewers that would fill the field;
- **prior art**: how established standards name and define the same thing, such as Crossref's
  peer review metadata, JATS or the NISO/STM standard terminology for peer review. OCRS follows them where it
  can, and says so in the description (for example, `review_context.stage` follows Crossref);
- **compatibility**: whether reviews valid today stay valid (see below).

Small fixes, such as a clearer description or a typo, can go straight to a pull request.

### Compatibility

A change is **compatible** when every review valid under the previous version is still valid
under the new one and still means the same thing. These changes are compatible:

- adding an optional field;
- adding a value to an enum;
- relaxing a rule, for example removing a `required` entry or widening a pattern;
- adding a metric to the catalog;
- clarifying a description without changing what a value means.

These changes are **breaking**:

- removing or renaming a field, or a value of an enum;
- making a field required, or adding a rule that some valid reviews break;
- changing a field's type, or what an existing value means.

A breaking change needs a migration: the CHANGELOG says what an existing review must change to
become valid, as the entry for 0.5.0 does for `review_context.stage`.

Consumers should expect enums to grow. A program that reads OCRS should handle a value it does
not know, for example by treating it as unspecified, rather than reject the review.

### Versioning

The schema and the Python package share one version, `MAJOR.MINOR.PATCH`, set in
`pyproject.toml` and in the schema's `$id`. A published version never changes: a fix, however
small, is a new version.

While OCRS is a draft (`0.x`):

- a **patch** version (`0.6.0` → `0.6.1`) makes only compatible changes;
- a **minor** version (`0.5.0` → `0.6.0`) may make breaking changes, each listed in the
  CHANGELOG with its migration.

From 1.0.0, OCRS follows [Semantic Versioning](https://semver.org/): a **major** version for
breaking changes, a **minor** version for compatible additions, and a **patch** version for
changes to descriptions, documentation and the package that leave the schema's rules as they
are.

The metric catalog and the mapping spec carry their own versions in their file names, because
they change on their own schedule. A new version of either is a new file; the old one stays.

### Schema style

New fields should read like the fields already there:

- **Names** are `snake_case` for properties and enum values, and `camelCase` for `$defs`.
  Name a field for what it means, not for the system it came from: `provenance.review_doi`,
  not `crossref_doi`.
- **Every property has a `description`** that says what the value is, in plain words. Say
  where a value comes from when that matters ("as the review gives it", "as the source states
  it"), and name the standard it follows.
- **Objects are closed** (`"additionalProperties": false`). Data with no OCRS field goes in
  `extensions.<source>`, so a new field is added to the schema rather than slipped into an
  object.
- **New fields are optional.** A review from a system that has no such data is still a
  complete review.
- **Record, don't infer.** A field holds what the review says. If a source can leave a value
  out, the field can be absent; do not add a default that the source never stated.
- **Rules JSON Schema cannot express**, such as cross-references between ids, go in
  `check_references` in `src/ocrs/schema.py`, with a test.

### A schema change, step by step

A pull request that changes the schema:

1. Changes `src/ocrs/schemas/canonical-review.schema.json` (or the catalog or mapping spec).
2. Sets the new version in `pyproject.toml`, in the schema's `$id`, in `CITATION.cff`, in
   the README's version badge, status line and schema URLs. The `sync-example-schema`
   pre-commit hook then sets each example's `$schema` to the new `$id` (or run
   `python scripts/sync_examples.py`).
3. Copies the files in `src/ocrs/schemas/` to `versions/v<version>/`, which GitHub Pages
   publishes at the `$id` URL. It never changes a version that is already published.
4. Adds a CHANGELOG entry that says whether every review valid under the previous version is
   still valid, and gives the migration for each breaking change.
5. Adds tests that exercise the new fields, and updates an example in `examples/` when that
   shows the field in use.
6. Updates the mappers whose sources have the new data.

The tests check that the published copy matches the package, that the `$id` names the
package's version, that the versions in the README and `CITATION.cff` match it, and that every
example and every JSON and Python block in the README and this guide still works.

### Releases

A version's pull request updates `main` and the versioned schema files. Once public hosting
is enabled, GitHub Pages publishes every version in `versions/` at its permanent URL, along
with the current HTML documentation. CI builds the site on every pull request.

Maintainers then run **Prepare release**, which tests the built distributions and creates a
draft GitHub release with the matching version tag, wheel, source archive, checksums, and
changelog entry. Publishing that draft makes the version available for pinned installation.
See [RELEASING.md](RELEASING.md) for initial hosting configuration and the release procedure.

## The Python package

### Getting started

1. Fork the repository
2. Clone your fork locally
3. [Install uv](https://docs.astral.sh/uv/getting-started/installation/), if you don't have it.
4. Set up the development environment and install the git hooks:

```bash
uv sync               # the package, plus pytest, Ruff and prek from the dev group
uv run prek install   # the git hooks; once per clone
```

[Prek](https://github.com/j178/prek), the pre-commit-compatible runner that reads
`.pre-commit-config.yaml`, is a `dev` dependency of this repository, pinned in `uv.lock`, so
`uv sync` installs it into `.venv`. Run it with `uv run prek`; don't install prek or
pre-commit globally.

The hooks are required, not optional. Besides running Ruff, the `sync-example-schema` hook
sets the `$schema` of each review in `examples/` to the schema's `$id` whenever the schema or
an example changes. A version bump committed without it leaves the examples on the old
version, and `test_example_names_the_current_schema` fails in CI. If that happens, run
`uv run prek run --all-files` (or `python scripts/sync_examples.py`) and commit the result.

A hook that fixes a file stops the commit. Review the change, `git add` it, and commit again.

### Running tests

```bash
uv run pytest -q
```

### Linting and formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
uv run ruff check .      # Check for issues
uv run ruff check --fix . # Auto-fix issues
uv run ruff format .     # Format code
```

Run the pre-commit hooks on all files with:

```bash
uv run prek run --all-files
```

### Checking distributions

Package checks install the built wheel into a temporary environment and run the full tests
from the extracted source archive, so missing fixtures or editable-install assumptions fail:

```bash
uv build
uv run python scripts/check_distribution.py dist
```

Use a clean `dist/` directory containing only the current version's wheel and source archive.
CI runs this check independently of the tests in the working checkout.

### Code style

- Follow PEP 8 conventions
- Use type hints for function signatures
- Keep functions focused and well-documented
- Add tests for new functionality

### Adding a new mapper

To add support for a new source format:

1. Create a new file in `src/ocrs/mappers/` (e.g., `newformat.py`)
2. Implement `from_newformat(payload, keep_raw=False)` and `to_newformat(canonical)`
3. Register the mapper in `src/ocrs/registry.py`
4. Add tests in `tests/test_roundtrip.py`

### AI reviewer mappers

An AI reviewer mapper belongs in OCRS only if the reviewer's output format is public, as
OpenAIReview's is, or is what the reviewer gives its users, as DeepReview's Markdown report is.

A mapper takes the reviewer's output (its JSON as a dict, or its text if it writes Markdown), the review envelope that `map_with_record` built from its
keyword arguments, and the paper's blocks (or `None`). It fills the envelope through a
`Recorder` and returns `finish(...)`, both from `ocrs.mappers.ai`. Add it and its version to
`_FROM_WITH_RECORD` and `_MAPPER_VERSIONS` in `src/ocrs/registry.py`, and its tests to
`tests/test_ai_mappers.py`. See `src/ocrs/mappers/openaireview.py` for a complete mapper, and
`src/ocrs/mappers/deepreview.py` for one that parses Markdown first.

The mapper copies the reviewer's text and never rewrites or invents it. `Recorder.copy` copies
a value, `Recorder.lookup` maps it through a table and records a coercion when the value is
not in it, `Recorder.parse` records a value read out of the reviewer's text by a pattern, and
`Recorder.evidence_link` copies a quote and, given the paper, records where it was found. `finish` keeps whatever the mapper did not read in `extensions.<name>`, validates
the review, and records the gaps.

## Submitting changes

1. Create a feature branch from `main`
2. Make your changes with clear commit messages
3. Ensure all tests pass and linting is clean
4. Push to your fork and open a pull request

In the pull request:

- Describe the change, and link the issue it settles
- For a schema change, say whether it is compatible
- Make sure CI passes
- Respond to review feedback

Valency Systems Inc. maintains OCRS. A maintainer reviews each pull request, and a schema change
is merged once its issue has settled what the field means and who will fill it.

## Reporting issues

For vulnerabilities, follow [SECURITY.md](SECURITY.md) and contact `security@valency.io`
privately. Do not include confidential reviews, private manuscript text, or credentials in
public bug reports.

When reporting bugs:

- Include Python version and OS
- Provide a minimal reproducible example
- Include the full error traceback

For feature requests:

- Explain the use case
- Describe the expected behavior
- Consider how it fits with existing functionality

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## Questions?

Open an issue for questions about contributing or the project architecture.
