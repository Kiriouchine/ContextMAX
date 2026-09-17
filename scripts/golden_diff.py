# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Report exactly how a freshly built corpus index differs from the committed goldens.

Job logs need repository admin rights to download, so this prints a compact, greppable summary
that CI can put into an artifact name: which artifact, which row, which field, which values.

    python scripts/golden_diff.py            # human summary
    python scripts/golden_diff.py --first    # one sanitised token naming the first difference
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
KEY_FIELD = {"nodes": "id", "edges": "src", "skipped.jsonl": "file"}


def build_index() -> Path:
    os.environ["CONTEXTMAX_NO_OPTIONAL_READERS"] = "1"
    os.environ["CONTEXTMAX_GRAMMAR_DIR"] = tempfile.mkdtemp(prefix="cmx-empty-grammars-")
    from contextmax.cli import main
    from fixtures.corpus import build_corpus

    root = Path(tempfile.mkdtemp(prefix="cmx-golden-diff-")) / "corpus"
    build_corpus(root)
    assert main(["init", str(root), "--slug", "sample", "--name", "Sample", "--no-gitignore"]) == 0
    assert main(["index", "--root", str(root), "--quiet"]) == 0
    return root / ".contextmax"


def rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def key_of(relative: str, row: dict) -> str:
    field = KEY_FIELD.get(relative.split("/")[0], KEY_FIELD.get(relative, "id"))
    return str(row.get(field) or row.get("file") or row.get("id") or "?")


def differences(built: Path) -> list[str]:
    out: list[str] = []
    for golden in sorted(GOLDEN.rglob("*")):
        if not golden.is_file():
            continue
        relative = golden.relative_to(GOLDEN).as_posix()
        actual = built / relative
        if golden.read_bytes() == (actual.read_bytes() if actual.is_file() else b""):
            continue
        if not actual.is_file():
            out.append(f"{relative}: MISSING from the build")
            continue
        if relative.endswith(".json"):
            want, got = json.loads(golden.read_text("utf-8")), json.loads(actual.read_text("utf-8"))
            for field in sorted(set(want) | set(got)):
                if want.get(field) != got.get(field):
                    out.append(f"{relative}: {field}: golden {want.get(field)!r} != built {got.get(field)!r}")
            continue
        want_rows = {key_of(relative, r): r for r in rows(golden)}
        got_rows = {key_of(relative, r): r for r in rows(actual)}
        for key in sorted(set(want_rows) | set(got_rows)):
            a, b = want_rows.get(key), got_rows.get(key)
            if a == b:
                continue
            if a is None:
                out.append(f"{relative}: {key}: only in the build")
            elif b is None:
                out.append(f"{relative}: {key}: only in the golden")
            else:
                for field in sorted(set(a) | set(b)):
                    if a.get(field) != b.get(field):
                        out.append(f"{relative}: {key}: {field}: golden {a.get(field)!r} != built {b.get(field)!r}")
    return out


def main() -> int:
    built = build_index()
    diffs = differences(built)
    if not diffs:
        print("goldens match the build")
        if "--first" in sys.argv:
            print("TOKEN=match")
        return 0
    for line in diffs[:200]:
        print(line)
    if len(diffs) > 200:
        print(f"... {len(diffs) - 200} more differences")
    if "--first" in sys.argv:
        token = re.sub(r"[^A-Za-z0-9._-]+", "-", diffs[0])[:180]
        print(f"TOKEN={token}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
