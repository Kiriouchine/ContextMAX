# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Shared fixtures: a synthetic corpus and an initialised project."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from contextmax.cli import main
from fixtures.corpus import build_corpus


@pytest.fixture(autouse=True)
def isolated_grammars(tmp_path_factory, monkeypatch):
    """Tier B depends on what a machine has downloaded; tests see an empty grammar folder
    unless they opt in (see tests/unit/test_treesitter.py)."""
    from contextmax import grammars

    monkeypatch.setenv(grammars.GRAMMAR_DIR_ENV, str(tmp_path_factory.mktemp("grammars-empty")))
    grammars.has_tags.cache_clear()
    yield
    grammars.has_tags.cache_clear()


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return build_corpus(tmp_path / "corpus")


@pytest.fixture
def project(corpus: Path) -> Path:
    assert (
        main(["init", str(corpus), "--slug", "sample", "--name", "Sample", "--no-gitignore"]) == 0
    )
    return corpus


@pytest.fixture
def built(project: Path) -> Path:
    assert main(["index", "--root", str(project), "--quiet"]) == 0
    return project
