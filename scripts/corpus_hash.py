# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Index the fixture corpus in a temp folder and print its artifact identity hash.

CI runs this on every OS and fails when the hashes differ. Usage:
    python scripts/corpus_hash.py [--out FILE]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from contextmax.cli import main  # noqa: E402
from contextmax.io.jsonl import read_json  # noqa: E402
from fixtures.corpus import build_corpus  # noqa: E402


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="contextmax-corpus-") as tmp:
        # Tier B output depends on provisioned grammars; the cross-OS comparison uses none.
        os.environ["CONTEXTMAX_NO_OPTIONAL_READERS"] = "1"
        os.environ["CONTEXTMAX_GRAMMAR_DIR"] = str(Path(tmp) / "grammars-empty")
        root = build_corpus(Path(tmp) / "corpus")
        if main(["init", str(root), "--slug", "sample", "--name", "Sample", "--no-gitignore"]) != 0:
            return 1
        if main(["index", "--root", str(root), "--quiet"]) != 0:
            return 1
        manifest = read_json(root / ".contextmax" / "manifest.json")
    digest = manifest["artifact_identity_hash"]
    print(digest)
    if args.out:
        # Explicit LF: on Windows, text mode would write CRLF and the CI comparison
        # would read two "different" hashes that differ only in line endings.
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(digest + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
