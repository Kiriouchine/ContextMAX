# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Golden files: the corpus must produce exactly the committed artifacts.

Regenerate deliberately with `python scripts/update_golden.py` and review the diff. A golden
change is a behaviour change and belongs in the commit message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden"
ARTIFACTS = (
    "nodes/files.jsonl",
    "nodes/symbols.jsonl",
    "edges/calls.jsonl",
    "edges/imports.jsonl",
    "edges/contains.jsonl",
    "skipped.jsonl",
    "coverage.json",
)


@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_artifact_matches_golden(built: Path, artifact: str):
    expected_path = GOLDEN_DIR / artifact
    actual_path = built / ".contextmax" / artifact
    assert actual_path.is_file(), f"{artifact} was not produced"
    if not expected_path.is_file():
        pytest.fail(f"no golden file for {artifact}; run scripts/update_golden.py")
    expected = expected_path.read_bytes()
    actual = actual_path.read_bytes()
    if expected != actual:
        exp_lines = expected.decode("utf-8").splitlines()
        act_lines = actual.decode("utf-8").splitlines()
        diff = [line for line in act_lines if line not in set(exp_lines)][:5]
        missing = [line for line in exp_lines if line not in set(act_lines)][:5]
        pytest.fail(
            f"{artifact} differs from golden\n  first new lines: {diff}\n  first missing lines: {missing}\n"
            "  regenerate with scripts/update_golden.py if the change is intended"
        )
