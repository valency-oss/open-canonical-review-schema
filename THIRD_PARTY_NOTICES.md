# Third-party notices

OCRS's code, schemas, original examples, and original documentation are covered by
[Apache-2.0](LICENSE). That license does not replace the licenses of the materials below.
Keep these notices and the referenced attribution records when redistributing those files.

## Published OpenAIReview outputs

`tests/fixtures/real/openaireview/apep-0001-pdf.json` and
`tests/fixtures/real/openaireview/smoothing-shifts-pdf.json` are adapted from
[ChicagoHAI/OpenAIReview at commit 436a42f](https://github.com/ChicagoHAI/OpenAIReview/tree/436a42f0a7222ae87b5008729f0cc5b521d7e160).
Copyright (c) 2026 ChicagoHAI. The complete MIT permission and warranty notice is in
[licenses/OpenAIReview-MIT.txt](licenses/OpenAIReview-MIT.txt).

OCRS removes the papers' paragraph arrays and obscures quoted paper passages because their
licenses have not been established. The exact source files and modifications are documented
in [the real-fixture README](tests/fixtures/real/README.md#openaireview) and
[sources.json](tests/fixtures/real/sources.json). The MIT notice covers the upstream outputs;
it does not grant rights in the papers they discuss.

## Published peer reviews and paper excerpts

The published OpenReview, eLife, and F1000Research material under
`tests/fixtures/real/openreview/`, `tests/fixtures/real/journal/`, and
`tests/fixtures/real/jats/` is licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
Credit belongs to the original reviewers and authors identified by each source, including
anonymous reviewers where the publisher withholds their names. The source URLs, review DOIs,
license records, and retrieval dates are in [sources.json](tests/fixtures/real/sources.json).
The [fixture README](tests/fixtures/real/README.md) records the transformations: extracting
notes and form bounds, joining narrative paragraphs, and serializing JATS sub-articles.

Paper passages in `tests/fixtures/ai/paper_blocks.json` and
`tests/fixtures/ai/openaireview_paper.json` are from Makan Farhoodimoghadam, Avery Louis,
Joshua S. Bloom, and Karthik Ram, *Beyond Document Relevance: Evaluating Citation-Set Structure
in Citation Recommendation*, under the same CC BY 4.0 license. OCRS includes selected
excerpts as plain text, as described in [the AI-fixture README](tests/fixtures/ai/README.md).

Synthetic fixtures, including the DeepReview and Reviewer3 reports and the documented vendor
API samples, are original OCRS examples under Apache-2.0. A sample's format or product name
does not imply that the vendor supplied or endorsed its contents.

## Brand assets

OCRS shows another organization's logo only when that organization has said it may be used.
None has yet, so the documentation site and the `site/review-flow.png` diagram show each
supported system by its name and its initials in a color from its site. The names identify
the formats OCRS reads and writes and remain their owners' trademarks.

Valency's marks follow the organization's
[trademark policy](https://github.com/valency-oss/.github/blob/main/TRADEMARK.md). No permission
to use another organization's marks as your own branding is granted by this repository.

## Generated documentation

The generated Pages site includes JavaScript, CSS, and fonts supplied by
`json-schema-for-humans` and its dependencies. Preserve their embedded copyright and license
notices when redistributing that generated output. Generated HTML and those dependencies are
not bundled in the OCRS wheel or source archive.
