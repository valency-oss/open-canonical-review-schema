# Example reviews

Each file is a complete OCRS review, and the tests validate every one.

| File | What it shows |
|---|---|
| `human-review.json` | A single-blind journal review by a person: scores, a recommendation, and findings that point to sections and figures |
| `ai-review.json` | An AI review: OpenAIReview's output on a preprint, mapped by `map_with_record`, with the reviewer's commit, the model and the run times, and the reviewer's unmapped fields in `extensions.openaireview` |
| `ai-review-deepreview.json` | Feedback on a draft from Google's DeepReview, as its authors would ask for it, mapped by `map_with_record` and trimmed to six of its 42 detailed points: overview weaknesses that `summarize` detailed ones, points grouped by part of the paper and tier, page ranges, quotes, suggested rewrites and works the paper should cite |
| `hybrid-review.json` | A review an AI system drafted and a person checked, edited and approved, with what each contributed. The reviewed preprint is a second version, linked to its first in `target.relations` |
| `author-response.json` | The authors' response to `human-review.json`: an `author_comment` that `responds_to` that review, whose points each name the finding they answer and what the authors did about it |

`human-review.json`, `author-response.json` and `hybrid-review.json` are made up. `ai-review.json` is a real OpenAIReview run on Makan Farhoodimoghadam, Avery Louis, Joshua S. Bloom and Karthik Ram, "Beyond Document Relevance: Evaluating Citation-Set Structure in Citation Recommendation", licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); it quotes short excerpts of the paper. `ai-review-deepreview.json` maps a report written in DeepReview's format on an invented draft about forecasting bay temperatures in a cold-storage warehouse (`tests/fixtures/ai/deepreview_report.md`), so the paper, its numbers and the report's text are all made up; its run times are illustrative, since the report does not state them, and its overview links (`summarizes`) were added by hand, since the report does not make them.
