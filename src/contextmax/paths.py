# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Where things live: project root discovery and the layout of the generated index."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

INDEX_DIR_NAME = ".contextmax"
CONFIG_NAME = "config.json"
SKIP_MARKER = ".contextmax-skip"
INDEX_POINTER = "index-path.txt"
ROOT_ENV = "CONTEXTMAX_ROOT"


class NoIndexError(RuntimeError):
    """Raised when no ContextMAX project can be found."""


def find_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default cwd) to the nearest folder holding .contextmax/config.json."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / INDEX_DIR_NAME / CONFIG_NAME).is_file():
            return candidate
    return None


def resolve_root(explicit: str | os.PathLike | None = None) -> Path:
    """Resolve the project root from --root, CONTEXTMAX_ROOT or the current directory."""
    if explicit:
        root = Path(explicit).resolve()
        if not (root / INDEX_DIR_NAME / CONFIG_NAME).is_file():
            raise NoIndexError(f"no {INDEX_DIR_NAME}/{CONFIG_NAME} under {root}")
        return root
    env = os.environ.get(ROOT_ENV)
    if env:
        return resolve_root(env)
    found = find_root()
    if found is None:
        raise NoIndexError(
            "no ContextMAX project found here or in any parent folder; run `contextmax init` first"
        )
    return found


@dataclass(frozen=True)
class Layout:
    """Every artifact path, derived once from the root and the configured output dir."""

    root: Path
    index: Path

    @property
    def config(self) -> Path:
        return self.root / INDEX_DIR_NAME / CONFIG_NAME

    @property
    def skip_marker(self) -> Path:
        return self.index / SKIP_MARKER

    @property
    def manifest(self) -> Path:
        return self.index / "manifest.json"

    @property
    def build_state(self) -> Path:
        return self.index / "build-state.json"

    @property
    def coverage(self) -> Path:
        return self.index / "coverage.json"

    @property
    def skipped(self) -> Path:
        return self.index / "skipped.jsonl"

    @property
    def nodes(self) -> Path:
        return self.index / "nodes"

    @property
    def edges(self) -> Path:
        return self.index / "edges"

    @property
    def files_jsonl(self) -> Path:
        return self.nodes / "files.jsonl"

    @property
    def graph_dir(self) -> Path:
        return self.index / "graph"

    @property
    def text_dir(self) -> Path:
        return self.index / "text"

    @property
    def cache_dir(self) -> Path:
        return self.index / "cache"

    @property
    def query_db(self) -> Path:
        return self.index / "query.sqlite"

    @property
    def viz_dir(self) -> Path:
        return self.index / "viz"

    @property
    def skill_dir(self) -> Path:
        return self.index / "skill"

    @property
    def logs_dir(self) -> Path:
        return self.index / "logs"

    @property
    def index_md(self) -> Path:
        return self.index / "INDEX.md"

    @property
    def readme(self) -> Path:
        return self.index / "README.md"


def layout_for(root: Path, output_dir: str | None) -> Layout:
    """Compute the layout. `output_dir` may be absolute, root-relative or contain env vars."""
    root = Path(root).resolve()
    default = root / INDEX_DIR_NAME
    if output_dir:
        expanded = Path(os.path.expandvars(os.path.expanduser(output_dir)))
        index = expanded if expanded.is_absolute() else (root / expanded)
        return Layout(root=root, index=index.resolve())
    pointer = default / INDEX_POINTER
    if pointer.is_file():
        target = pointer.read_text(encoding="utf-8-sig").strip()
        if target:
            return Layout(root=root, index=Path(target).resolve())
    return Layout(root=root, index=default)
