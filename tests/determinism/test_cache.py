# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""A cached rebuild must be byte-identical to a full build."""

from __future__ import annotations

from pathlib import Path

from contextmax.cli import main
from contextmax.io.jsonl import read_json


def _manifest(root: Path) -> dict:
    return read_json(root / ".contextmax" / "manifest.json")


def _note(root: Path) -> str:
    return read_json(root / ".contextmax" / "build-state.json")["stages"]["code"]["note"]


def test_cached_rebuild_equals_full_build(built: Path):
    full_hash = _manifest(built)["artifact_identity_hash"]
    cache = built / ".contextmax" / "cache"
    assert cache.is_dir() and any(cache.iterdir())
    assert main(["index", "--root", str(built), "--quiet"]) == 0
    note = _note(built)
    assert note.endswith("misses 0") and not note.startswith("cache hits 0")
    assert _manifest(built)["artifact_identity_hash"] == full_hash
    assert main(["index", "--root", str(built), "--full", "--quiet"]) == 0
    assert _note(built).startswith("cache hits 0")
    assert _manifest(built)["artifact_identity_hash"] == full_hash


def test_edit_invalidates_only_that_file(built: Path):
    analysed = read_json(built / ".contextmax" / "coverage.json")["code"]["n_files_analysed"]
    (built / "src" / "app" / "util.py").write_bytes(b"def helper():\n    return 42\n")
    assert main(["index", "--root", str(built), "--quiet"]) == 0
    assert _note(built) == f"cache hits {analysed - 1}, misses 1"
