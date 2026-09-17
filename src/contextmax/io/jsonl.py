# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Deterministic JSON and JSONL readers and writers.

Every artifact ContextMAX generates goes through these functions:
- keys are sorted, rows are sorted by an explicit key, output is UTF-8 without BOM with LF;
- writers return the SHA-256 of the bytes written so the manifest can record it;
- readers accept a BOM (utf-8-sig) because other tools on Windows still write one.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from contextmax.io.atomic import atomic_write_text
from contextmax.io.canon import canonical_json
from contextmax.io.hash import sha256_bytes


def dumps_row(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)


def default_row_key(row: dict[str, Any]) -> tuple:
    """Rows sort by id when present, else by (src, dst, rel) for edges, else canonically."""
    if "id" in row:
        return (0, str(row["id"]), canonical_json(row))
    if "src" in row and "dst" in row:
        return (
            1,
            str(row["src"]),
            str(row.get("dst")),
            str(row.get("rel", "")),
            canonical_json(row),
        )
    return (2, canonical_json(row))


def write_json(path: Path, obj: Any) -> str:
    text = json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    return sha256_bytes(atomic_write_text(Path(path), text))


def write_jsonl(
    path: Path,
    rows: Iterable[dict[str, Any]],
    key: Callable[[dict[str, Any]], Any] | None = None,
) -> str:
    ordered = sorted(rows, key=key or default_row_key)
    text = "".join(dumps_row(row) + "\n" for row in ordered)
    return sha256_bytes(atomic_write_text(Path(path), text))


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))
