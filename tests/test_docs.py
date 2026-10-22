# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""The examples in the README and CONTRIBUTING.md work as written.

Each Python block runs on its own. Blocks may use the inputs a reader brings
(`openreview_note`, `openreview_forum_page`, `openaireview_paper_json`, `deepreview_report`,
`reviewer3_report`), which come from test fixtures.
Each JSON block is a whole review, or part of one that must validate when
added to a minimal review.
"""

import importlib.util
import json
import re
from importlib.metadata import version
from pathlib import Path

import pytest

from ocrs import schema_id, validate_canonical
from ocrs.catalog import load_catalog
from ocrs.hierarchy import resolve_definition

ROOT = Path(__file__).parent.parent
DOCS = ["README.md", "CONTRIBUTING.md"]
FIXTURES = ROOT / "tests" / "fixtures"
CODE_BLOCK = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)
MINIMAL_REVIEW = {
    "review_id": "review-1",
    "version": "1.0.0",
    "created_at": "2026-10-06T12:00:00Z",
    "provenance": {"source_system": "example-journal"},
    "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
    "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
    "opinion": {"summary": "A sound paper."},
}


def code_blocks(language):
    blocks = []
    for doc in DOCS:
        text = (ROOT / doc).read_text()
        for match in CODE_BLOCK.finditer(text):
            if match.group(1) == language:
                line = text[: match.start()].count("\n") + 1
                blocks.append(pytest.param(match.group(2), id=f"{doc}:{line}"))
    return blocks


def reader_inputs():
    return {
        "openreview_note": json.loads(
            (FIXTURES / "openreview" / "realistic_review.json").read_text()
        ),
        "openreview_forum_page": (FIXTURES / "openreview" / "forum_page.html").read_text(
            encoding="utf-8"
        ),
        "openaireview_paper_json": json.loads(
            (FIXTURES / "ai" / "openaireview_paper.json").read_text()
        ),
        "deepreview_report": (FIXTURES / "ai" / "deepreview_report.md").read_text(),
        "reviewer3_report": (FIXTURES / "ai" / "reviewer3_report.md").read_text(),
    }


@pytest.mark.parametrize("code", code_blocks("python"))
def test_python_example_runs(code):
    exec(compile(code, "<doc example>", "exec"), reader_inputs())


@pytest.mark.parametrize("text", code_blocks("json"))
def test_json_example_validates(text):
    example = json.loads(text)
    validate_canonical(example if "review_id" in example else {**MINIMAL_REVIEW, **example})


@pytest.mark.parametrize(
    "path", sorted((ROOT / "examples").glob("*.json")), ids=lambda path: path.name
)
def test_example_review_validates(path):
    validate_canonical(json.loads(path.read_text()))


@pytest.mark.parametrize(
    "path", sorted((ROOT / "examples").glob("*.json")), ids=lambda path: path.name
)
def test_example_metrics_use_catalog_keys(path):
    keys = {metric["key"] for metric in load_catalog()["metrics"]}
    review = json.loads(path.read_text())
    for metric in review.get("metrics", []):
        definition = resolve_definition(review, metric)
        assert definition["catalog_key"] in keys


@pytest.mark.parametrize(
    "path", sorted((ROOT / "examples").glob("*.json")), ids=lambda path: path.name
)
def test_example_names_the_current_schema(path):
    """Also that the example is as `scripts/sync_examples.py` writes it."""
    text = path.read_text(encoding="utf-8")
    assert json.loads(text)["$schema"] == schema_id()
    assert _sync_examples().sync(text, schema_id()) == text


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sync_examples():
    return _script("sync_examples")


def test_schema_files_are_in_the_house_layout():
    """As `scripts/format_schema.py` writes them, so re-serializing makes no diff."""
    format_schema = _script("format_schema")
    for path in format_schema.schema_files():
        assert path.read_text(encoding="utf-8") == format_schema.formatted(path), path


@pytest.mark.parametrize(
    "text",
    [
        '{\n  "$schema": "https://example.org/v0.0.1/s.json",\n  "review_id": "r"\n}\n',
        '{\n    "$schema": "https://example.org/v0.0.1/s.json",\n    "review_id": "r"\n}\n',
        '{"review_id": "r", "$schema": "https://example.org/v0.0.1/s.json"}',
        '{"review_id": "r", "extensions": {"x": {"$schema": "keep"}}}',
    ],
    ids=["two-space", "four-space", "single-line, not first", "missing, nested kept"],
)
def test_sync_examples_sets_the_top_level_schema(text):
    sync = _sync_examples().sync
    synced = sync(text, schema_id())
    review = json.loads(text)
    review.pop("$schema", None)
    assert json.loads(synced) == {"$schema": schema_id(), **review}
    assert next(iter(json.loads(synced))) == "$schema"
    assert sync(synced, schema_id()) == synced


def test_readme_and_citation_name_the_package_version():
    current = version("ocrs")
    readme = (ROOT / "README.md").read_text()
    assert f"badge/schema-v{current}-" in readme
    assert f"**Status: v{current}," in readme
    assert set(re.findall(r"open-canonical-review-schema/v(\d+\.\d+\.\d+)/", readme)) == {current}
    assert f"\nversion: {current}\n" in (ROOT / "CITATION.cff").read_text()
