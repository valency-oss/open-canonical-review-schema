#!/usr/bin/env python3
"""Point every example review's `$schema` at the packaged schema's `$id`.

Run after a version bump, or let the `sync-example-schema` pre-commit hook run it. Each example
is rewritten in the repository's JSON format (2-space indent, UTF-8, trailing newline) with
`$schema` as its first key; only the top-level `$schema` changes, never a nested one. Exits 1
when it changed a file, as pre-commit hooks that fix files do, and without changing any when
`examples/` or an example in it is a symbolic link.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "src" / "ocrs" / "schemas" / "canonical-review.schema.json"
EXAMPLES = ROOT / "examples"


def sync(text: str, schema_id: str) -> str:
    """The example with its top-level `$schema` set to `schema_id`, as the first key."""
    review = json.loads(text)
    review.pop("$schema", None)
    return json.dumps({"$schema": schema_id, **review}, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    schema_id = json.loads(SCHEMA.read_text())["$id"]
    paths = sorted(EXAMPLES.glob("*.json"))
    # A link would have the rewrite land wherever it points, perhaps outside the checkout
    links = [path for path in [EXAMPLES, *paths] if path.is_symlink()]
    if links:
        for path in links:
            print(f"{path.relative_to(ROOT)} is a symbolic link; examples must be files")
        return 1
    changed = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        synced = sync(text, schema_id)
        if synced != text:
            path.write_text(synced, encoding="utf-8")
            changed.append(path.relative_to(ROOT))
    for path in changed:
        print(f"Set $schema in {path} to {schema_id}")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
