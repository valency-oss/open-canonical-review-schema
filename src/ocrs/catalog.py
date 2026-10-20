# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Metric catalog loading and alias resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "schemas" / "metric-catalog.core.v1.1.json"


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CATALOG_PATH
    return json.loads(p.read_text())


def alias_map(catalog: dict[str, Any]) -> dict[str, str]:
    amap: dict[str, str] = {}
    for m in catalog.get("metrics", []):
        key = m["key"]
        for a in m.get("aliases", []):
            amap[a.casefold()] = key
    return amap
