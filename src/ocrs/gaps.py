# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Compute where a mapped review falls short of OCRS: unmapped and unfilled fields."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Collection, Iterator
from typing import Any

from .mapping import FieldCount

_INDEX = re.compile(r"\[\d+\]")


def generic_path(path: str) -> str:
    return _INDEX.sub("[]", path)


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def iter_leaves(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Every non-empty value that is not a dict or a list, with its path."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_leaves(child, _join(path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_leaves(child, f"{path}[{index}]")
    elif not is_empty(value):
        yield path, value


def _covered(path: str, prefixes: Collection[str]) -> bool:
    """Whether `path` is one of `prefixes` or below one: looks up each of its ancestors,
    rather than scanning every prefix, so a check costs the path's length."""
    return path in prefixes or any(
        path[:i] in prefixes for i, char in enumerate(path) if char in ".["
    )


def leftover(
    value: Any,
    read: set[str],
    ignored: set[str],
    generic: Callable[[str], str] = generic_path,
    path: str = "",
) -> Any:
    """`value` without what the mapper read or deliberately ignores.

    `read` holds concrete paths; `ignored` holds generic ones. Lists keep
    their length, so `issues[3]` in the leftover is still `issues[3]` in the
    reviewer's output. Returns None when nothing is left.
    """
    if _covered(path, read) or (path and _covered(generic(path), ignored)):
        return None
    if isinstance(value, dict):
        kept = {k: leftover(v, read, ignored, generic, _join(path, k)) for k, v in value.items()}
        kept = {k: v for k, v in kept.items() if not is_empty(v)}
        return kept or None
    if isinstance(value, list):
        kept = [leftover(v, read, ignored, generic, f"{path}[{i}]") for i, v in enumerate(value)]
        return kept if any(not is_empty(v) for v in kept) else None
    return None if is_empty(value) else value


def count_unmapped(left: Any, generic: Callable[[str], str] = generic_path) -> list[FieldCount]:
    counts = Counter(generic(path) for path, _ in iter_leaves(left))
    return [FieldCount(path=path, count=count) for path, count in sorted(counts.items())]


def iter_schema_paths(
    node: dict[str, Any], schema: dict[str, Any], path: str = "", seen: frozenset[str] = frozenset()
) -> Iterator[str]:
    """Every property path the schema allows, with `[]` for list items."""
    ref = node.get("$ref")
    if ref:
        if ref in seen:
            return
        name = ref.removeprefix("#/$defs/")
        yield from iter_schema_paths(schema["$defs"][name], schema, path, seen | {ref})
        return
    for alternative in node.get("oneOf", []) + node.get("anyOf", []) + node.get("allOf", []):
        yield from iter_schema_paths(alternative, schema, path, seen)
    if "items" in node and isinstance(node["items"], dict):
        yield from iter_schema_paths(node["items"], schema, f"{path}[]", seen)
    for key, child in node.get("properties", {}).items():
        child_path = _join(path, key)
        yield child_path
        yield from iter_schema_paths(child, schema, child_path, seen)


def _parent(path: str) -> str:
    if path.endswith("[]"):
        return path[:-2]
    return path.rpartition(".")[0]


def unfilled_paths(review: dict[str, Any], schema: dict[str, Any], ignored: set[str]) -> list[str]:
    """OCRS fields left empty, listed only where their parent is filled."""
    present = {generic_path(path) for path, _ in iter_leaves(review)}
    present_containers = {""}
    for path in present:
        while path:
            path = _parent(path)
            present_containers.add(path)
    unfilled = set()
    for path in iter_schema_paths(schema, schema):
        if _parent(path) not in present_containers or _covered(path, ignored):
            continue
        if path in present or path in present_containers:
            continue
        unfilled.add(path)
    return sorted(unfilled)
