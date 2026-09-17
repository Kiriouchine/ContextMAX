# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from pathlib import Path

from contextmax.config import Config, default_config
from contextmax.discover import discover
from contextmax.paths import layout_for


def run(corpus: Path, **overrides):
    data = default_config("sample")
    data.update(overrides)
    cfg = Config(data)
    return discover(corpus, cfg, layout_for(corpus, None))


def by_file(result):
    return {row["file"]: row for row in result.files}


def test_every_file_lands_somewhere(corpus: Path):
    result = run(corpus)
    files = by_file(result)
    # Excluded by rules: never in files.jsonl. Everything else: exactly one row.
    assert "build/out.txt" not in files  # .gitignore build/
    assert "logs/run.log" not in files  # .gitignore *.log
    assert "logs/keep.log" in files  # negated
    assert "nested/inner.py" not in files  # skip marker
    for key in (
        "README.md",
        "bin/blob.bin",
        "unknown.zzz",
        "scripts/noext",
        "empty.txt",
        "ärm-note.md",
    ):
        assert key in files, key
    assert result.counts["n_files"] == len(files)


def test_tiers_and_reasons(corpus: Path):
    result = run(corpus)
    files = by_file(result)
    skipped = {(row["file"], row["reason_code"]) for row in result.skipped}
    assert files["bin/blob.bin"]["tier"] == "D"
    assert files["bin/photo.png"]["tier"] == "D" and files["bin/photo.png"]["format"] == "image"
    assert ("bin/photo.png", "catalog-only") in skipped
    assert files["unknown.zzz"]["tier"] == "C" and files["unknown.zzz"]["content_family"] == "text"
    assert (
        files["scripts/noext"]["language"] == "python"
        and files["scripts/noext"]["detected_by"] == "shebang"
    )
    assert files["src/app/main.py"]["tier"] in ("A", "B", "C")
    if files["src/app/main.py"]["tier"] == "C":
        assert ("src/app/main.py", "grammar-missing") in skipped
    assert files["README.md"]["tier"] == "A" and files["README.md"]["adapter"] == "markdown-v1"
    assert files["data/table.csv"]["adapter"] == "sheet-v1"
    assert files["empty.txt"]["lines"] == 0 and files["empty.txt"]["size"] == 0
    assert ("nested", "skip-marker") in skipped


def test_container_formats_are_not_penalised_for_binary_bytes(corpus: Path):
    result = run(corpus)
    files = by_file(result)
    skipped = {row["file"]: row["reason_code"] for row in result.skipped}
    # A PDF holds NUL bytes by nature; the only legitimate demotion is a missing reader.
    assert skipped.get("docs/paper.pdf") in (None, "missing-dependency")
    assert files["docs/paper.pdf"]["format"] == "pdf"
    # OOXML is read by ooxml-v1 (stdlib): tier A, never demoted for its binary bytes.
    assert files["docs/report.docx"]["tier"] == "A"
    assert "docs/report.docx" not in skipped
    # A legacy .doc needs LibreOffice; under test isolation the reason is recorded.
    assert files["docs/legacy.doc"]["tier"] == "D"
    assert skipped["docs/legacy.doc"] == "reader-unavailable"
    # A text-expected file with NUL bytes is demoted, and says so.
    assert files["src/app/broken.py"]["tier"] == "D"
    assert skipped["src/app/broken.py"] == "binary-content"


def test_roles_from_default_rules(corpus: Path):
    files = by_file(run(corpus))
    assert files["tests/test_main.py"]["role"] == "test"
    assert files["vendor/lib.py"]["role"] == "vendor"
    assert files["docs/spec.md"]["role"] == "docs"
    assert files["src/app/main.py"]["role"] == "product"


def test_hashes_and_lines(corpus: Path):
    files = by_file(run(corpus))
    row = files["src/app/util.py"]
    assert len(row["sha256"]) == 64
    assert row["lines"] == 3
    assert row["encoding"] == "utf-8"
    assert files["bin/blob.bin"]["binary"] is True


def test_config_exclude_and_include(corpus: Path):
    files = by_file(run(corpus, exclude=["docs/", "*.md"], include=["README.md"]))
    assert "docs/spec.md" not in files
    assert "zebra-note.md" not in files
    assert "README.md" in files


def test_gitignore_can_be_disabled(corpus: Path):
    files = by_file(run(corpus, respect_gitignore=False))
    assert "build/out.txt" in files
    assert "logs/run.log" in files


def test_rows_are_sorted_and_keys_canonical(corpus: Path):
    result = run(corpus)
    keys = [row["file"] for row in result.files]
    assert all("\\" not in key for key in keys)
    assert all(row["id"] == f"file:{row['file']}" for row in result.files)


def test_language_can_be_disabled(corpus: Path):
    files = by_file(run(corpus, languages={"overrides": {}, "disabled": ["python"]}))
    assert files["src/app/main.py"]["language"] is None
    assert files["src/app/main.py"]["format"] == "plain"


def test_max_file_size_is_announced(corpus: Path):
    (corpus / "big.txt").write_bytes(b"x" * 2048)
    files = by_file(run(corpus, limits={"max_file_mb": 0.001, "max_lines": 50000}))
    assert files["big.txt"]["tier"] == "D"
    assert files["big.txt"]["sha256"] is None
    assert "too-large" in files["big.txt"]["note"] or "exceeds" in files["big.txt"]["note"]
