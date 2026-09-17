# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Two runs, two machines, two creation orders: the artifacts must be byte-identical."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from contextmax.cli import main
from contextmax.io.jsonl import read_json
from fixtures.corpus import build_corpus

ARTIFACTS = (
    "nodes/files.jsonl",
    "nodes/symbols.jsonl",
    "nodes/documents.jsonl",
    "nodes/sections.jsonl",
    "nodes/references.jsonl",
    "edges/calls.jsonl",
    "skipped.jsonl",
    "coverage.json",
    "INDEX.md",
    "CODEMAP.md",
    "DOCMAP.md",
)


def _build(root: Path, reverse: bool = False) -> dict:
    build_corpus(root, reverse=reverse)
    assert main(["init", str(root), "--slug", "sample", "--name", "Sample", "--no-gitignore"]) == 0
    assert main(["index", "--root", str(root), "--quiet"]) == 0
    return read_json(root / ".contextmax" / "manifest.json")


def _bytes(root: Path) -> dict[str, bytes]:
    return {name: (root / ".contextmax" / name).read_bytes() for name in ARTIFACTS}


def test_two_runs_are_identical(tmp_path: Path):
    root = tmp_path / "p"
    first = _build(root)
    first_bytes = _bytes(root)
    assert main(["index", "--root", str(root), "--quiet"]) == 0
    second = read_json(root / ".contextmax" / "manifest.json")
    assert first["artifact_identity_hash"] == second["artifact_identity_hash"]
    assert first["baseline_identity_hash"] == second["baseline_identity_hash"]
    assert _bytes(root) == first_bytes


def test_creation_order_and_location_do_not_matter(tmp_path: Path):
    a = _build(tmp_path / "alpha")
    b = _build(tmp_path / "zulu" / "deeper", reverse=True)
    assert a["artifact_identity_hash"] == b["artifact_identity_hash"]
    assert a["baseline_identity_hash"] == b["baseline_identity_hash"]
    assert _bytes(tmp_path / "alpha") == _bytes(tmp_path / "zulu" / "deeper")


def test_hash_moves_when_a_source_changes(tmp_path: Path):
    root = tmp_path / "p"
    before = _build(root)
    (root / "src" / "app" / "util.py").write_bytes(b"def helper():\n    return 2\n")
    assert main(["index", "--root", str(root), "--quiet"]) == 0
    after = read_json(root / ".contextmax" / "manifest.json")
    assert before["baseline_identity_hash"] != after["baseline_identity_hash"]
    assert before["artifact_identity_hash"] != after["artifact_identity_hash"]


def test_identity_excludes_timestamps_and_ledger(tmp_path: Path):
    root = tmp_path / "p"
    manifest = _build(root)
    hashed = set(manifest["artifact_hashes"])
    assert "manifest.json" not in hashed
    assert "build-state.json" not in hashed
    assert "README.md" not in hashed
    assert "nodes/files.jsonl" in hashed
    assert "coverage.json" in hashed
    assert manifest["completeness"]["verdict"] == "full"


def test_corpus_bytes_do_not_depend_on_the_zlib_build(tmp_path: Path):
    """Every corpus file must be byte-identical on any machine.

    DEFLATE output differs between zlib and zlib-ng, so a compressed member inside a synthetic
    Office fixture would change the file's hash, and with it every golden artifact, depending
    only on which Python built it. Fixture packages are therefore stored, never deflated.
    """
    import zipfile

    root = build_corpus(tmp_path / "corpus")
    packages = [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix.lower() in (".docx", ".pptx", ".odt", ".odp", ".ods", ".epub")
    ]
    assert packages, "the corpus should contain container documents"
    for path in packages:
        with zipfile.ZipFile(path) as zf:
            compressed = sorted(
                i.filename for i in zf.infolist() if i.compress_type != zipfile.ZIP_STORED
            )
        assert not compressed, f"{path.name} compresses {compressed}; use zipped(..., ZIP_STORED)"
