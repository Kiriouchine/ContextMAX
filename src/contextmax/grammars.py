# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Grammar provisioning state.

The tree-sitter language pack downloads a grammar the first time it is used. Indexing must
never touch the network, so ContextMAX keeps its own ledger of grammars that were provisioned
explicitly (`contextmax grammars fetch`) and treats anything else as unavailable, dropping the
file to tier C with a recorded reason.
"""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path

GRAMMAR_DIR_ENV = "CONTEXTMAX_GRAMMAR_DIR"
PACK_CACHE_ENV = "TREE_SITTER_LANGUAGE_PACK_CACHE_DIR"
PACK_DIST = "tree-sitter-language-pack"


def grammar_dir() -> Path:
    override = os.environ.get(GRAMMAR_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".contextmax" / "grammars").resolve()


def ledger_path() -> Path:
    return grammar_dir() / "provisioned.json"


def configure_pack_environment() -> None:
    """Point the language pack's cache at ContextMAX's grammar folder (before importing it)."""
    os.environ.setdefault(PACK_CACHE_ENV, str(grammar_dir() / "pack"))


def pack_version() -> str | None:
    try:
        return metadata.version(PACK_DIST)
    except metadata.PackageNotFoundError:
        return None


def pack_installed() -> bool:
    return pack_version() is not None


def provisioned() -> dict[str, str]:
    """Grammar name -> pack version that provisioned it."""
    path = ledger_path()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.get("grammars", {}).items()}


def is_provisioned(name: str | None) -> bool:
    if not name:
        return False
    return pack_installed() and name in provisioned()
