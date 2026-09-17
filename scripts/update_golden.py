# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Rebuild the fixture corpus and copy its artifacts into tests/fixtures/golden/."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from contextmax.cli import main  # noqa: E402
from fixtures.corpus import build_corpus  # noqa: E402

ARTIFACTS = (
    "nodes/files.jsonl",
    "nodes/symbols.jsonl",
    "edges/calls.jsonl",
    "edges/imports.jsonl",
    "edges/contains.jsonl",
    "nodes/documents.jsonl",
    "nodes/sections.jsonl",
    "nodes/references.jsonl",
    "skipped.jsonl",
    "coverage.json",
)


def run() -> int:
    golden = ROOT / "tests" / "fixtures" / "golden"
    with tempfile.TemporaryDirectory(prefix="contextmax-golden-") as tmp:
        # Golden files never depend on which grammars this machine has provisioned.
        os.environ["CONTEXTMAX_NO_OPTIONAL_READERS"] = "1"
        os.environ["CONTEXTMAX_GRAMMAR_DIR"] = str(Path(tmp) / "grammars-empty")
        root = build_corpus(Path(tmp) / "corpus")
        if main(["init", str(root), "--slug", "sample", "--name", "Sample", "--no-gitignore"]) != 0:
            return 1
        if main(["index", "--root", str(root), "--quiet"]) != 0:
            return 1
        for artifact in ARTIFACTS:
            source = root / ".contextmax" / artifact
            target = golden / artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            print(f"updated {target.relative_to(ROOT)} ({source.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
