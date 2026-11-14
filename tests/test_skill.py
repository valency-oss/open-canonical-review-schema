"""Exercise the installed skill helper independently of the caller's directory."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("skill_check", ROOT / "skills/ocrs/scripts/check.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


@pytest.fixture
def review():
    return {
        "$schema": check.ocrs.schema_id(),
        "review_id": "skill-test",
        "version": "1.0.0",
        "created_at": "2026-11-13T00:00:00Z",
        "provenance": {"source_system": "skill-test"},
        "referees": [{"referee_type": "human", "identity_mode": "confidential"}],
        "target": {"work_id": "unknown", "work_type": "preprint"},
        "opinion": {"summary": "Promising work."},
    }


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["check.py", *map(str, args)])
    return check.main()


@pytest.mark.parametrize("kind", ["single", "array", "jsonl"])
def test_input_formats(tmp_path, monkeypatch, review, capsys, kind):
    data = json.dumps(review)
    if kind == "array":
        data = f"[{data}, {data}]"
    elif kind == "jsonl":
        data = f"{data}\n{data}\n"
    path = tmp_path / "reviews.json"
    path.write_text(data)
    monkeypatch.chdir(tmp_path)
    assert run(monkeypatch, path) == 0
    assert capsys.readouterr().out.count("ok    ") == (1 if kind == "single" else 2)


@pytest.mark.parametrize("data", ["", "[]", "null", "[3]", '{"broken":', "{}\nnot-json"])
def test_bad_input_does_not_stop_next_file(tmp_path, monkeypatch, review, capsys, data):
    bad, good = tmp_path / "bad.json", tmp_path / "good.json"
    bad.write_text(data)
    good.write_text(json.dumps(review))
    assert run(monkeypatch, bad, good) == 1
    output = capsys.readouterr().out
    assert "FAIL" in output and "ok    " in output
    assert "Traceback" not in output


def test_spans_preserve_bytes_and_require_matching_text(tmp_path, monkeypatch, review, capsys):
    text = "α\r\nExact evidence.\r\n"
    source = tmp_path / "source.txt"
    source.write_bytes(text.encode("utf-8"))
    ref = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    link = {
        "resource": {"type": "work"},
        "quote": "Exact evidence.",
        "location": {"span": {"text_ref": ref, "start": 3, "end": 18}},
    }
    review["findings"] = {"comments": [{"id": "c1", "text": "Evidence.", "evidence_links": [link]}]}
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path, "--text", source) == 0
    assert run(monkeypatch, path) == 0
    assert "UNCHECKED span" in capsys.readouterr().out
    source.write_bytes(text.replace("\r\n", "\n").encode())
    assert run(monkeypatch, path, "--text", source) == 1
    assert "No --text file matches" in capsys.readouterr().out
    source.write_bytes(text.encode())
    link["quote"] = "Not what the paper says."
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path, "--text", source) == 1
    assert "quote does not equal" in capsys.readouterr().out


@pytest.mark.parametrize(
    "schema", [None, 3, "https://example.org/schema", check.SCHEMA_HOST + "../x"]
)
def test_untrusted_schema_fails_cleanly(tmp_path, monkeypatch, review, capsys, schema):
    review["$schema"] = schema
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path) == 1
    assert "Not a versioned OCRS schema URL" in capsys.readouterr().out


def test_older_schema_uses_published_version(tmp_path, monkeypatch, review, capsys):
    url = check.SCHEMA_HOST + "v0.9.2/canonical-review.schema.json"
    review["$schema"] = url
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache = tmp_path / "ocrs-skill/v0.9.2_canonical-review.schema.json"
    cache.parent.mkdir()
    cache.write_bytes((ROOT / "versions/v0.9.2/canonical-review.schema.json").read_bytes())
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path) == 0
    assert url in capsys.readouterr().out


def test_extensions_are_not_treated_as_evidence(review):
    review["extensions"] = {"source": {"evidence_links": [{"quote": None, "location": 3}]}}
    assert check.check_evidence(review, {}) == []


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_jsonl_preserves_unicode_separators(
    tmp_path, monkeypatch, review, capsys, separator, newline
):
    review["opinion"]["summary"] = f"First paragraph{separator}Second paragraph"
    row = json.dumps(review, ensure_ascii=False)
    path = tmp_path / "unicode.jsonl"
    path.write_bytes((row + newline + row + newline).encode("utf-8"))
    assert check.records(path) == [review, review]
    assert run(monkeypatch, path) == 0
    assert capsys.readouterr().out.count("ok    ") == 2


def test_result_data_is_ignored_but_result_evidence_is_checked(
    tmp_path, monkeypatch, review, capsys
):
    result = {
        "id": "result-1",
        "data": {"evidence_links": [{"location": 3}]},
    }
    review["checks"] = [{"id": "check-1", "kind": "source-output", "results": [result]}]
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path) == 0
    assert "FAIL" not in capsys.readouterr().out

    source = tmp_path / "source.txt"
    source.write_bytes(b"Actual text.")
    result["evidence_links"] = [
        {
            "resource": {"type": "work"},
            "quote": "Actual text.",
            "location": {"span": {"text_ref": "sha256:" + "0" * 64, "start": 0, "end": 12}},
        }
    ]
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path, "--text", source) == 1
    output = capsys.readouterr().out
    assert "No --text file matches" in output
    assert "$.checks[0].results[0].evidence_links[0]" in output


def test_material_part_span_text_coverage_and_bounds(tmp_path, monkeypatch, capsys):
    review = json.loads((ROOT / "examples/ai-review.json").read_text())
    source = tmp_path / "source.txt"
    source.write_bytes("α\r\nAbstract text.".encode())
    span = {
        "text_ref": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "start": 3,
        "end": 17,
    }
    review["referees"][0]["ai_referee"]["inputs"] = {
        "materials_reviewed": [
            {
                "type": "metadata",
                "ref": "paper.txt",
                "extent": "partial",
                "parts": [{"span": span}],
            }
        ]
    }
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path, "--text", source) == 0
    capsys.readouterr()
    assert run(monkeypatch, path) == 0
    output = capsys.readouterr().out
    assert (
        "UNCHECKED span at $.referees[0].ai_referee.inputs.materials_reviewed[0].parts[0]" in output
    )
    source.write_bytes(b"Unrelated text.")
    assert run(monkeypatch, path, "--text", source) == 1
    assert "No --text file matches" in capsys.readouterr().out
    source.write_bytes("α\r\nAbstract text.".encode())
    span["end"] = 999999
    path.write_text(json.dumps(review))
    assert run(monkeypatch, path, "--text", source) == 1
    assert "span.end exceeds" in capsys.readouterr().out
