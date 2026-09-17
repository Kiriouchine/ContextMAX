# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The tier B worker survives a native crash: the file is recorded, the rest is analysed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from contextmax import grammars
from contextmax.code.run import _tier_b_batch
from contextmax.code.tsworker import CRASH_HOOK_ENV

REAL_DIR = Path.home() / ".contextmax" / "grammars"


@pytest.fixture
def real_grammars(monkeypatch):
    if not grammars.pack_installed():
        pytest.skip("tree-sitter-language-pack not installed")
    monkeypatch.setenv(
        grammars.GRAMMAR_DIR_ENV, str(os.environ.get("CONTEXTMAX_TEST_GRAMMAR_DIR") or REAL_DIR)
    )
    grammars.has_tags.cache_clear()
    if not grammars.is_provisioned("python"):
        pytest.skip("python grammar not provisioned")
    yield
    grammars.has_tags.cache_clear()


def test_worker_reports_crash_and_continues(real_grammars, tmp_path: Path, monkeypatch):
    files = {}
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.py"
        path.write_text(f"def {name}_fn():\n    return {name}_helper()\n", encoding="utf-8")
        files[name] = path
    entries = [
        {"key": f"{n}.py", "path": str(p), "language": "python", "grammar": "python"}
        for n, p in files.items()
    ]
    monkeypatch.setenv(CRASH_HOOK_ENV, "b.py")
    logs: list[str] = []
    analyses, errors, crashed = _tier_b_batch(entries, logs.append)
    assert crashed == ["b.py"]
    assert set(analyses) == {"a.py", "c.py"} and not errors
    assert [s.name for s in analyses["c.py"].symbols if s.kind == "function"] == ["c_fn"]
    assert any("crashed on b.py" in line for line in logs)


def test_worker_clean_run(real_grammars, tmp_path: Path, monkeypatch):
    monkeypatch.delenv(CRASH_HOOK_ENV, raising=False)
    path = tmp_path / "x.py"
    path.write_text("def f():\n    g()\n", encoding="utf-8")
    analyses, errors, crashed = _tier_b_batch(
        [{"key": "x.py", "path": str(path), "language": "python", "grammar": "python"}],
        lambda _m: None,
    )
    assert not crashed and not errors and analyses["x.py"].tier == "B"
