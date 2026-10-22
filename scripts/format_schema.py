#!/usr/bin/env python3
# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Write the current schema in its house layout, so a re-serialization never shows up
as a diff: two-space indentation, `required` and `type` lists on one line, and objects
without a description that fit in 120 columns on one line. Enums and anything with a
description stay one item per line.

    python scripts/format_schema.py           # rewrite the schema files
    python scripts/format_schema.py --check   # exit 1 if a file would change
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src/ocrs/schemas/canonical-review.schema.json"
INLINE_LISTS = {"required", "type"}
WIDTH = 120


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def scalar(value) -> bool:
    return not isinstance(value, (dict, list))


def has_description(value) -> bool:
    if isinstance(value, dict):
        return "description" in value or any(map(has_description, value.values()))
    if isinstance(value, list):
        return any(map(has_description, value))
    return False


def one_line(key, value, width) -> bool:
    if scalar(value):
        return True
    if isinstance(value, list) and all(map(scalar, value)):
        return key in INLINE_LISTS
    return width <= WIDTH and not has_description(value)


def layout(value, depth=0, key=None, lead=0) -> str:
    text = compact(value)
    if key is not None and one_line(key, value, lead + len(text)):
        return text
    pad = "  " * depth
    if isinstance(value, dict) and value:
        lines = []
        for k, v in value.items():
            prefix = f"{pad}  {compact(k)}: "
            lines.append(prefix + layout(v, depth + 1, k, len(prefix)))
        return "{\n" + ",\n".join(lines) + f"\n{pad}}}"
    if isinstance(value, list) and value:
        lines = [f"{pad}  " + layout(v, depth + 1, "[]", len(pad) + 2) for v in value]
        return "[\n" + ",\n".join(lines) + f"\n{pad}]"
    return text


def formatted(path: Path) -> str:
    return layout(json.loads(path.read_text(encoding="utf-8"))) + "\n"


def schema_files() -> list[Path]:
    """The packaged schema and its published copy for the same version."""
    version = json.loads(SCHEMA.read_text(encoding="utf-8"))["$id"].split("/")[-2]
    return [SCHEMA, ROOT / "versions" / version / SCHEMA.name]


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for path in schema_files():
        text = formatted(path)
        if path.read_text(encoding="utf-8") != text:
            stale.append(path)
            if not check:
                path.write_text(text, encoding="utf-8")
    for path in stale:
        print(f"{'would reformat' if check else 'reformatted'} {path.relative_to(ROOT)}")
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
