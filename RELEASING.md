# Releasing OCRS

OCRS publishes immutable versioned schemas on GitHub Pages and Python distributions on
GitHub Releases. It currently has no PyPI publishing workflow or PyPI credentials.
The first release prepared by this procedure is **v0.9.0**.

## One-time repository setup

These are administrator operations, separate from merging a code change. The configuration
is checked in so reviewers can see exactly which protections will be applied. Keep the
repository private until its owner chooses to publish it. Both publication workflows require
the canonical repository, its `main` branch, and public visibility.

After this PR is merged, authenticate `gh` as a repository administrator and work from the
updated `main` checkout:

```bash
repo=valency-oss/open-canonical-review-schema
```

### Require review and passing checks

Import [.github/rulesets/main.json](.github/rulesets/main.json) as an **additional** branch
ruleset. It preserves the existing merge allowlist, PR requirement, and force-push/deletion
protections. It applies only to the default branch, so the CLA bot can still write signatures
to `cla-signatures`.

```bash
gh api "repos/$repo/rulesets" --jq '.[] | {id, name, enforcement}'
gh api --method POST "repos/$repo/rulesets" --input .github/rulesets/main.json
gh api "repos/$repo/rules/branches/main"
```

Create it once. If `OCRS release checks` already exists, use its ID from the first command
with `gh api --method PUT "repos/$repo/rulesets/ID" --input .github/rulesets/main.json`
instead. Do not replace the organization's other rulesets.

The required GitHub Actions checks are `test (3.12)`, `test (3.13)`, `test (3.14)`, `package`,
`docs`, `links`, and `cla`. An approving review from someone other than the last pusher and
resolved review threads are also required. Enable these rules after this PR lands, when the
new check names exist. The `cla` job runs the pinned CLA Assistant on `pull_request_target`
without checking out or executing the contributor's code.

### Publish the site and enable private security reports

When the repository owner has made the repository public, confirm that `isPrivate` is
`false`. Then configure Pages to use GitHub Actions and re-enable its deployment workflow:

```bash
gh repo view "$repo" --json isPrivate --jq .isPrivate
gh api --method POST "repos/$repo/pages" -f build_type=workflow
gh workflow enable docs.yml --repo "$repo"
gh workflow run docs.yml --repo "$repo" --ref main
gh api --method PUT "repos/$repo/private-vulnerability-reporting"
gh api --method PATCH "repos/$repo" \
  -f homepage=https://valency-oss.github.io/open-canonical-review-schema/
```

If Pages already exists, update it with `gh api --method PUT "repos/$repo/pages"
-f build_type=workflow` instead of POST. The deployment uses the `github-pages` environment;
restrict its deployment branches to `main` in repository Settings → Environments. Do not
enable publishing from pull requests or forks.

The email route in [SECURITY.md](SECURITY.md) works independently of GitHub's private
reporting feature and follows the [organization policy](https://github.com/valency-oss/.github/blob/main/SECURITY.md).
Keep secret scanning, push protection, CodeQL, and Dependabot security updates enabled.
Reconcile stale dependency alerts against the current lockfile; do not dismiss an alert
solely because CI is green.

The Pages deployment checks the public homepage and compares **every** hosted versioned
JSON file byte-for-byte with `versions/`. Confirm the run succeeds and check the current
schema without GitHub authentication:

```bash
curl --fail https://valency-oss.github.io/open-canonical-review-schema/v0.9.0/canonical-review.schema.json
uvx check-jsonschema --schemafile https://valency-oss.github.io/open-canonical-review-schema/v0.9.0/canonical-review.schema.json examples/human-review.json
```

## Every release

1. Follow [the schema-change checklist](CONTRIBUTING.md#a-schema-change-step-by-step). Keep
   package metadata, schema IDs, `versions/`, examples, README installation commands, citation,
   and changelog on the same version. Published tags and schemas must not be overwritten.
2. Merge the version's PR only after the required checks and review pass. Wait for Pages to
   deploy successfully before publishing the matching Python release.
3. Run **Prepare release** on `main`:

   ```bash
   gh workflow run release.yml --repo valency-oss/open-canonical-review-schema --ref main
   ```

   It builds a wheel from the source archive, installs it in an isolated environment, runs
   the archive's complete test suite, and creates a **draft** release targeting the exact
   tested commit. Notes come from that version's CHANGELOG entry. The assets include the
   wheel, source archive, and `SHA256SUMS`; an existing version tag makes the workflow fail.
4. Review the draft and publish it in GitHub Releases. Verify that its tag points to the
   tested commit and its version matches `pyproject.toml`. The initial tag is `v0.9.0`.
5. Test installation from outside the checkout using a clean environment:

   ```bash
   uv venv /tmp/ocrs-release-smoke
   uv pip install --python /tmp/ocrs-release-smoke/bin/python \
     "ocrs @ git+https://github.com/valency-oss/open-canonical-review-schema.git@v0.9.0"
   /tmp/ocrs-release-smoke/bin/python -c "from ocrs import schema_id; print(schema_id())"
   ```

   Use the new version in these commands for later releases. The repository's Python
   requirement is 3.12 or newer. Downloaded assets can be verified with
   `sha256sum --check SHA256SUMS` (or `shasum -a 256 --check SHA256SUMS` on macOS).

## Local release checks

```bash
uv sync --locked --extra docs
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest -q
uv build
uv run --no-sync python scripts/check_distribution.py dist
uv run --no-sync python scripts/generate_docs.py
```

Use a clean `dist/` directory before building. The archive check uses `uv.lock` from the
source distribution and verifies that the imported `ocrs` comes from the installed wheel.
Licenses and third-party notices are included in both distribution formats.
