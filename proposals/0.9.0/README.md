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

## Artifact identities

`target.artifacts[]` lists code, data, models, protocols and supplementary materials.
Each has an ID and a type; location, exact version, content hash and reported availability
are optional. Missing or unavailable material does not need an invented URL. Merely listing
an artifact does not mean that the reviewer checked it.

The final hierarchy uses shared evidence pointers to refer to these IDs. Examinations
live in checks, and their significance lives in findings. Artifact records need no reverse
lists of checks, findings or metrics.
