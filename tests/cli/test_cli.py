# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

import json
from pathlib import Path

from contextmax.cli import main


def test_init_creates_config_and_gitignore_block(corpus: Path, capsys):
    (corpus / ".git").mkdir()  # only a git repository gets the ignore block
    assert main(["init", str(corpus), "--slug", "sample"]) == 0
    config = corpus / ".contextmax" / "config.json"
    assert config.is_file()
    assert (corpus / ".contextmax" / ".contextmax-skip").is_file()
    gitignore = (corpus / ".gitignore").read_text(encoding="utf-8")
    assert ".contextmax/*" in gitignore and "!.contextmax/config.json" in gitignore
    assert "build/" in gitignore  # the user's rules survive
    # Second init is a no-op without --force.
    assert main(["init", str(corpus)]) == 0
    assert "already initialised" in capsys.readouterr().out


def test_init_in_plain_folder_leaves_gitignore_alone(tmp_path: Path):
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "a.txt").write_text("x", encoding="utf-8")
    assert main(["init", str(folder), "--slug", "archive"]) == 0
    assert (folder / ".contextmax" / "config.json").is_file()
    assert not (folder / ".gitignore").exists()


def test_status_before_and_after_build(project: Path, capsys):
    assert main(["status", "--root", str(project), "--json"]) == 0
    before = json.loads(capsys.readouterr().out)
    assert before["found"] is True and before["built"] is False
    assert main(["index", "--root", str(project), "--quiet"]) == 0
    assert main(["status", "--root", str(project), "--json"]) == 0
    after = json.loads(capsys.readouterr().out)
    assert after["built"] is True
    assert after["manifest"]["completeness"]["verdict"] == "full"
    assert after["coverage"]["n_files"] > 20
    assert after["coverage"]["by_tier"]["D"] >= 2


def test_status_without_project_returns_3(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CONTEXTMAX_ROOT", raising=False)
    assert main(["status", "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["found"] is False


def test_root_is_found_from_a_subfolder(built: Path, capsys, monkeypatch):
    monkeypatch.chdir(built / "src" / "app")
    monkeypatch.delenv("CONTEXTMAX_ROOT", raising=False)
    assert main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["project"]["slug"] == "sample"


def test_invalid_config_is_reported_with_path(project: Path, capsys):
    config = project / ".contextmax" / "config.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["limits"] = {"max_file_mb": "big"}
    config.write_text(json.dumps(data), encoding="utf-8")
    assert main(["index", "--root", str(project), "--quiet"]) == 2
    assert "$.limits.max_file_mb" in capsys.readouterr().err


def test_doctor_json(built: Path, capsys):
    code = main(["doctor", "--root", str(built), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    names = {c["name"] for c in payload["checks"]}
    assert {"python", "sqlite-fts5", "root", "config", "manifest"} <= names
    assert payload["failures"] == 0


def test_index_writes_ledger_and_marker(built: Path):
    index = built / ".contextmax"
    state = json.loads((index / "build-state.json").read_text(encoding="utf-8"))
    assert state["stages"]["discover"]["ok"] is True
    assert state["stages"]["manifest"]["ok"] is True
    assert state["stages"]["code"]["implemented"] is True
    assert state["stages"]["documents"]["implemented"] is False
    assert (index / ".contextmax-skip").is_file()
    assert (index / "INDEX.md").read_text(encoding="utf-8").startswith("# Sample")
