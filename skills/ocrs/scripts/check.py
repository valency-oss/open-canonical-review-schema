"""Validate JSON, JSON arrays, or JSON Lines of OCRS reviews.

Run with the released OCRS package; see SKILL.md. Optional --text files are
UTF-8 texts hashed as exact bytes (without newline normalization). Span offsets
count Unicode code points, not bytes. Missing texts are reported, never silently
presented as verified evidence.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:
    import ocrs
except ImportError:
    sys.exit(
        "The ocrs package is not installed. Run with: "
        "uv run --no-project --with <ocrs wheel URL> python check.py ..."
    )

SCHEMA_HOST = "https://valency-oss.github.io/open-canonical-review-schema/"


def records(path: Path) -> list[Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("no records")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
        for n, line in enumerate(raw.split("\n"), 1):
            if line.strip():
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {n}: {exc.msg}") from exc
    result = data if isinstance(data, list) else [data]
    if not result:
        raise ValueError("no records")
    return result


def schema_file(url: str) -> Path:
    """Cache only versioned schemas from the official publication host."""
    if not isinstance(url, str) or not re.fullmatch(
        re.escape(SCHEMA_HOST) + r"v\d+\.\d+\.\d+/canonical-review\.schema\.json", url
    ):
        raise ValueError(f"Not a versioned OCRS schema URL: {url}")
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache = base / "ocrs-skill" / url[len(SCHEMA_HOST) :].replace("/", "_")
    if not cache.exists():
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        if json.loads(data).get("$id") != url:
            raise ValueError("Downloaded schema does not identify the requested version")
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a complete JSON file, including when two checks run concurrently.
        with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
            try:
                tmp.write(data)
                tmp.close()
                temporary.replace(cache)
            finally:
                temporary.unlink(missing_ok=True)
    return cache


def evidence(
    obj: Any, node: Any, schema: dict, path: str = "$"
) -> Iterator[tuple[str, dict, str | None]]:
    """Yield schema-declared locations and quotes, excluding arbitrary source data.

    An evidence link owns its location and quote; a standalone evidenceLocation
    (such as a material part) has no quote. Follow the selected record schema,
    including older versions, rather than guessing from property names.
    """
    if not isinstance(node, dict):
        return
    ref = node.get("$ref")
    if ref == "#/$defs/evidenceLink":
        if isinstance(obj, dict):
            yield path, obj.get("location", {}), obj.get("quote")
        return
    if ref == "#/$defs/evidenceLocation":
        if isinstance(obj, dict):
            yield path, obj, None
        return
    if ref and ref.startswith("#/$defs/"):
        target = schema.get("$defs", {}).get(ref.removeprefix("#/$defs/"))
        yield from evidence(obj, target, schema, path)
        return
    for alternative in node.get("anyOf", []) + node.get("oneOf", []) + node.get("allOf", []):
        yield from evidence(obj, alternative, schema, path)
    if isinstance(obj, dict):
        for key, child in node.get("properties", {}).items():
            if key in obj:
                yield from evidence(obj[key], child, schema, f"{path}.{key}")
    elif isinstance(obj, list) and isinstance(node.get("items"), dict):
        for i, value in enumerate(obj):
            yield from evidence(value, node["items"], schema, f"{path}[{i}]")


def check_evidence(record: dict, texts: dict[str, str], schema: dict | None = None) -> list[str]:
    schema = ocrs.load_schema() if schema is None else schema
    notes = []
    for path, location, quote in evidence(record, schema, schema):
        span = location.get("span")
        if span:
            ref = span["text_ref"]
            if ref not in texts:
                if texts:
                    raise ValueError(f"No --text file matches {ref} at {path}")
                notes.append(f"UNCHECKED span at {path}: supply its --text file")
        elif quote is not None:
            found = any(quote in text for text in texts.values())
            state = (
                "found in --text (location unverified)"
                if found
                else ("NOT FOUND in --text" if texts else "check by hand")
            )
            notes.append(f"quote without a span at {path}: {state}: {quote[:70]!r}")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument(
        "--text", action="append", type=Path, default=[], help="exact UTF-8 source text"
    )
    args = ap.parse_args()
    texts = {}
    for path in args.text:
        try:
            data = path.read_bytes()
            texts["sha256:" + hashlib.sha256(data).hexdigest()] = data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"FAIL  {path}: {exc}")
            return 1
    package = ocrs.schema_id()
    bad = 0
    for path in args.files:
        try:
            batch = records(path)
        except (OSError, ValueError) as exc:
            print(f"FAIL  {path}: {exc}")
            bad += 1
            continue
        for n, rec in enumerate(batch, 1):
            name = f"{path}#{n}"
            try:
                if not isinstance(rec, dict):
                    raise ValueError("a review must be a JSON object")
                name += f" {rec.get('review_id', '?')}"
                schema_path = None
                if "$schema" not in rec:
                    print(f"note  {name}: no $schema; using {package}")
                elif rec["$schema"] != package:
                    schema_path = schema_file(rec["$schema"])
                    print(f"note  {name}: validating against {rec['$schema']}")
                ocrs.validate_canonical(rec, text_sources=texts or None, schema_path=schema_path)
                notes = check_evidence(rec, texts, ocrs.load_schema(schema_path))
            except Exception as exc:  # Report a failed record and continue the batch.
                bad += 1
                msg = getattr(exc, "message", None) or str(exc).splitlines()[0]
                where = "/".join(str(p) for p in getattr(exc, "absolute_path", []))
                print(f"FAIL  {name}: {msg}" + (f"  (at {where})" if where else ""))
                continue
            print(f"ok    {name} (structure and supplied spans)")
            for note in notes:
                print(f"      {note}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
