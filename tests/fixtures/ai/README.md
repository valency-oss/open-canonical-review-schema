# AI reviewer fixtures

See [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md) for the distinction between
original OCRS fixtures and the CC BY 4.0 paper excerpts included here.

Outputs of AI reviewers, used by `tests/test_ai_mappers.py`, `tests/test_deepreview.py` and `tests/test_reviewer3.py`. The OpenAIReview output is real; the DeepReview and Reviewer3 reports are written in each reviewer's format about an invented paper.

| File | What it is |
|---|---|
| `openaireview_paper.json` | OpenAIReview's `paper.json`, with 3 of its 24 merged comments, 1 unmerged comment and 2 paragraphs |
| `paper_blocks.json` | Paragraphs, abstract and references of the paper, as plain text, for matching quotes |
| `deepreview_report.md` | A whole Google DeepReview report, as its "Copy Report" gives it, on an invented draft about forecasting bay temperatures in a cold-storage warehouse; used by `tests/test_deepreview.py` |
| `reviewer3_report.md` | A whole Reviewer3 report, as its Markdown export gives it, on the same invented draft; used by `tests/test_reviewer3.py` |

Both reports are made up: the paper, its depot, sensors, methods, people, references, DOIs and numbers are invented, and so is every sentence. What the reports keep from their reviewers is the structure the mappers read: the headings and their order, the number of points in each part and tier, page ranges, places, quotes, proposed rewrites, cited works and tables. The Reviewer3 report keeps that reviewer's quirks: a title typo ("Symbolcollision"), excerpts copied from a PDF's text layer (`σ = 2 . 5`, `sec- ond`) and a figure label (`Fig 3`) given as an excerpt.

The OpenAIReview review ran on 2026-10-03 with Claude Opus 5.5 (`us.anthropic.claude-opus-5-5`), OpenAIReview at commit `27740f8434cf` (v0.3.0).

The quotes and paragraphs come from Makan Farhoodimoghadam, Avery Louis, Joshua S. Bloom and Karthik Ram, "Beyond Document Relevance: Evaluating Citation-Set Structure in Citation Recommendation", licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Only short excerpts are included.
