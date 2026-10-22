# OCRS 0.9.0 candidate

This directory stages the 0.9.0 schema while its changes are reviewed in a stack:
metric schemas in review context, artifact identities in target, then the review-content
hierarchy. The final PR activates the complete candidate in the package and publishes a
new versioned copy. Published 0.8.0 files remain unchanged.

## Metric schemas

`review_context.metric_schemas` stores each source form once, keyed by a review-local
schema ID. Its `source` identifies the form and can retain the original rubric snapshot;
`definitions` contains its named metrics, instructions and complete original scales.
Locally authored metrics use the same definition shape.

Each metric observation has an `id`, `definition_ref: {schema_id, key}` and original
`value`. Its optional normalization records the method; rescaling does not make two
rubrics equivalent or turn a confidence rating into a probability. No observed value
is used to guess missing scale bounds.

Definition references must resolve within this review. Scale values, bounds and intervals
are checked against the referenced definition when the candidate is activated.
