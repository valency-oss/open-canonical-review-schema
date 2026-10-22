# Security policy

OCRS follows the [Valency security policy](https://github.com/valency-oss/.github/blob/main/SECURITY.md).

## Supported versions

Security fixes are provided for the latest OCRS release. Upgrade older installations to the
latest release. Historical schema files remain immutable; a correction is published under a
new version as described in [CONTRIBUTING.md](CONTRIBUTING.md#versioning).

## Reporting a vulnerability

Email **security@valency.io** with a description, reproduction steps, affected OCRS version,
potential impact, and any suggested fix. Do not post security reports, credentials, private
manuscripts, or confidential reviews in public issues. Once enabled for the public repository,
GitHub's **Security → Report a vulnerability** form is another private reporting route.

We aim to acknowledge reports within five business days. For critical issues, we aim to
provide a fix or mitigation within 30 days; actively exploited issues take priority, and we
will communicate timing after assessing the report. We follow coordinated disclosure and
credit reporters in release notes unless they prefer anonymity.

## Handling review data

OCRS validation checks data structure and references. It does not sanitize HTML or Markdown,
verify that linked resources are safe, or decide which review content may be published.
Treat imported text and URLs as untrusted when rendering them. Confidential narrative parts,
reviewer identities, `extensions`, and retained raw source data can contain information that
must not be exposed to readers; apply your own access controls and publication policy.
