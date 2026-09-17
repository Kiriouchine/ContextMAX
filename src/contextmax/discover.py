# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Stage 1: discovery. One catalogue row per file, every exclusion recorded with a reason.

Walk order is sorted by name at every level so the result is independent of filesystem order.
Nothing is read from a cloud placeholder. The index folder and any folder holding a
`.contextmax-skip` marker are never entered.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contextmax import grammars
from contextmax.config import Config
from contextmax.fs import decode_text, is_cloud_placeholder, looks_binary, os_path
from contextmax.gitignore import IgnoreStack, compile_rules
from contextmax.io.canon import join_key, rel_key
from contextmax.model.ids import file_id
from contextmax.model.nodes import file_row, skipped_row
from contextmax.paths import INDEX_DIR_NAME, SKIP_MARKER, Layout
from contextmax.registry import Detection, detect

# Folders no project ever wants indexed. Everything else is the config's decision.
BUILTIN_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        "CVS",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        ".direnv",
        "node_modules",
        ".idea",
        ".vs",
        ".DS_Store",
        "$RECYCLE.BIN",
        "System Volume Information",
    }
)

SNIFF_BYTES = 8192
HASH_CHUNK = 1 << 20


@dataclass
class DiscoveryResult:
    files: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Root:
    path: Path
    prefix: str  # "" for the project root, "ext:<id>" for external roots


def _available_plugins() -> set[str]:
    """Tier-A plugin ids that are importable in this installation."""
    try:
        from contextmax.code import plugins
    except ImportError:
        return set()
    return set(getattr(plugins, "AVAILABLE", ()))


def _read_stats(
    path: Path, size: int, max_bytes: int
) -> tuple[str | None, int | None, bytes, str | None]:
    """Return (sha256, line count, head bytes, error). Large files are only sniffed."""
    head = b""
    digest = hashlib.sha256()
    lines = 0
    ends_with_newline = True
    first = True
    if size > max_bytes:
        with open(os_path(path), "rb") as handle:
            head = handle.read(SNIFF_BYTES)
        return None, None, head, None
    with open(os_path(path), "rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                break
            if first:
                head = chunk[:SNIFF_BYTES]
                first = False
            digest.update(chunk)
            lines += chunk.count(b"\n")
            ends_with_newline = chunk.endswith(b"\n")
    if size > 0 and not ends_with_newline:
        lines += 1
    if size == 0:
        lines = 0
    return digest.hexdigest(), lines, head, None


def _tier_for(
    det: Detection, plugins: set[str], binary: bool
) -> tuple[str, str | None, str | None]:
    """Return (tier, reason_code, reason) for a detected, readable file."""
    text_expected = det.family in ("code", "text") or (
        det.family in ("document", "data") and not det.container
    )
    if binary and text_expected:
        return "D", "binary-content", "file contains binary data despite its name"
    if det.family == "code":
        if det.plugin and det.plugin in plugins:
            return "A", None, None
        if det.grammar and grammars.is_provisioned(det.grammar):
            return "B", None, None
        if det.grammar:
            return (
                "C",
                "grammar-missing",
                f"grammar '{det.grammar}' is not provisioned; lexical analysis only",
            )
        return (
            "C",
            "no-grammar",
            "no tree-sitter grammar is known for this language; lexical analysis only",
        )
    if det.family in ("document", "data"):
        if det.adapter is None:
            return "D", "catalog-only", det.reason or "format is catalogued but not read"
        missing = [pkg for pkg in det.requires if not _package_available(pkg)]
        if missing:
            return "D", "missing-dependency", f"reading {det.format} needs {', '.join(missing)}"
        from contextmax.docs import adapters as doc_adapters

        if not doc_adapters.implemented(det.adapter):
            return (
                "D",
                "adapter-not-implemented",
                f"{det.adapter} is not implemented in this version",
            )
        return "A", None, None
    if det.family == "text":
        return "C", None, None
    return "D", "catalog-only", det.reason or "binary file"


_PKG_CACHE: dict[str, bool] = {}


def _package_available(name: str) -> bool:
    if name not in _PKG_CACHE:
        from importlib import metadata

        try:
            metadata.version(name)
            _PKG_CACHE[name] = True
        except metadata.PackageNotFoundError:
            _PKG_CACHE[name] = False
    return _PKG_CACHE[name]


def resolve_roots(root: Path, config: Config) -> list[Root]:
    roots: list[Root] = []
    seen_ids: set[str] = set()
    for entry in config.roots:
        path = Path(os.path.expandvars(os.path.expanduser(entry)))
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            path.relative_to(root)
            prefix = ""
            if path != root:
                prefix = rel_key(str(path.relative_to(root)))
        except ValueError:
            base = rel_key(path.name) or "root"
            ident = base
            ordinal = 2
            while ident in seen_ids:
                ident = f"{base}~{ordinal}"
                ordinal += 1
            seen_ids.add(ident)
            prefix = f"ext:{ident}"
        roots.append(Root(path=path, prefix=prefix))
    return roots


def discover(root: Path, config: Config, layout: Layout) -> DiscoveryResult:
    result = DiscoveryResult()
    plugins = _available_plugins()
    overrides = config.language_overrides
    max_bytes = config.max_file_bytes
    index_dir = layout.index.resolve()

    counts: dict[str, Any] = {
        "n_files": 0,
        "n_dirs": 0,
        "n_excluded_dirs": 0,
        "n_excluded_files": 0,
        "total_bytes": 0,
        "by_tier": {},
        "by_family": {},
        "by_language": {},
        "by_format": {},
        "by_role": {},
        "by_skip_reason": {},
        "by_excluded_by": {},
    }

    def bump(bucket: str, key: str | None) -> None:
        if key is None:
            return
        counts[bucket][key] = counts[bucket].get(key, 0) + 1

    project_rules = compile_rules([*config.exclude, *[f"!{p}" for p in config.include]], "")

    for source in resolve_roots(root, config):
        if source.path.is_file():
            _visit_file(
                source.path,
                join_key(source.prefix, source.path.name),
                0,
                result,
                counts,
                bump,
                config,
                plugins,
                overrides,
                max_bytes,
            )
            continue
        if not source.path.is_dir():
            result.skipped.append(
                skipped_row(
                    key=source.prefix or ".",
                    reason_code="root-missing",
                    reason=f"configured root does not exist: {source.path}",
                    size=None,
                    detected_as=None,
                )
            )
            bump("by_skip_reason", "root-missing")
            continue
        stack = IgnoreStack()
        stack.push("", project_rules)
        _walk(
            source.path,
            source.prefix,
            stack,
            index_dir,
            result,
            counts,
            bump,
            config,
            plugins,
            overrides,
            max_bytes,
        )

    counts["n_skipped"] = len(result.skipped)
    result.counts = counts
    return result


def _walk(
    top: Path,
    top_key: str,
    stack: IgnoreStack,
    index_dir: Path,
    result: DiscoveryResult,
    counts: dict[str, Any],
    bump,
    config: Config,
    plugins: set[str],
    overrides: dict[str, str],
    max_bytes: int,
) -> None:
    # Iterative, sorted DFS so deep trees cannot overflow the recursion limit.
    pending: list[tuple[Path, str, int]] = [(top, top_key, 0)]
    frames_by_depth: dict[int, bool] = {}
    while pending:
        directory, dir_key, depth = pending.pop()
        # Unwind ignore frames pushed by deeper or sibling directories already finished.
        while frames_by_depth and max(frames_by_depth) >= depth:
            level = max(frames_by_depth)
            if frames_by_depth.pop(level):
                stack.pop()
        counts["n_dirs"] += 1
        pushed = False
        if config.respect_gitignore:
            ignore_file = directory / ".gitignore"
            if ignore_file.is_file():
                try:
                    lines = ignore_file.read_text(
                        encoding="utf-8-sig", errors="replace"
                    ).splitlines()
                except OSError:
                    lines = []
                stack.push(dir_key, compile_rules(lines, dir_key))
                pushed = True
        frames_by_depth[depth] = pushed
        try:
            entries = sorted(os.scandir(os_path(directory)), key=lambda e: e.name)
        except OSError as exc:
            result.skipped.append(
                skipped_row(
                    key=dir_key or ".",
                    reason_code="read-error",
                    reason=f"cannot list directory: {exc.__class__.__name__}",
                    size=None,
                    detected_as=None,
                )
            )
            bump("by_skip_reason", "read-error")
            continue
        subdirs: list[tuple[Path, str, int]] = []
        for entry in entries:
            name = entry.name
            key = join_key(dir_key, name)
            try:
                is_symlink = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_symlink, is_dir = False, False
            if is_symlink:
                result.skipped.append(
                    skipped_row(
                        key=key,
                        reason_code="symlink",
                        reason="symbolic links are not followed",
                        size=None,
                        detected_as=None,
                    )
                )
                bump("by_skip_reason", "symlink")
                continue
            if is_dir:
                path = Path(entry.path)
                if (
                    path.resolve() == index_dir
                    or (path / SKIP_MARKER).is_file()
                    or name == INDEX_DIR_NAME
                ):
                    result.skipped.append(
                        skipped_row(
                            key=key,
                            reason_code="skip-marker",
                            reason="folder holds a .contextmax-skip marker or is the index",
                            size=None,
                            detected_as=None,
                        )
                    )
                    counts["n_excluded_dirs"] += 1
                    bump("by_excluded_by", "skip-marker")
                    continue
                if name in BUILTIN_EXCLUDED_DIRS:
                    counts["n_excluded_dirs"] += 1
                    bump("by_excluded_by", f"builtin:{name}")
                    continue
                decided = stack.is_ignored(key, True)
                if decided is not None:
                    counts["n_excluded_dirs"] += 1
                    bump("by_excluded_by", decided)
                    continue
                subdirs.append((path, key, depth + 1))
                continue
            decided = stack.is_ignored(key, False)
            if decided is not None:
                counts["n_excluded_files"] += 1
                bump("by_excluded_by", decided)
                continue
            _visit_file(
                Path(entry.path),
                key,
                depth,
                result,
                counts,
                bump,
                config,
                plugins,
                overrides,
                max_bytes,
                entry,
            )
        # Push in reverse so the smallest name is processed first (stack order).
        for item in reversed(subdirs):
            pending.append(item)


def _visit_file(
    path: Path,
    key: str,
    depth: int,
    result: DiscoveryResult,
    counts: dict[str, Any],
    bump,
    config: Config,
    plugins: set[str],
    overrides: dict[str, str],
    max_bytes: int,
    entry: os.DirEntry | None = None,
) -> None:
    name = path.name
    ext = os.path.splitext(name)[1].lower()
    try:
        st = entry.stat(follow_symlinks=False) if entry is not None else path.stat()
    except OSError as exc:
        result.skipped.append(
            skipped_row(
                key=key,
                reason_code="read-error",
                reason=f"cannot stat: {exc.__class__.__name__}",
                size=None,
                detected_as=None,
            )
        )
        bump("by_skip_reason", "read-error")
        return
    size = st.st_size
    role = config.role_for(key)
    placeholder = is_cloud_placeholder(path, st)
    sha256: str | None = None
    lines: int | None = None
    head = b""
    encoding: str | None = None
    note: str | None = None
    if placeholder:
        det = detect(name, None, overrides)
        tier, code, reason = (
            "D",
            "cloud-placeholder",
            "cloud-only placeholder; bytes are not on this machine",
        )
    else:
        try:
            sha256, lines, head, _ = _read_stats(path, size, max_bytes)
        except OSError as exc:
            det = detect(name, None, overrides)
            result.files.append(
                _row(
                    key,
                    name,
                    ext,
                    size,
                    None,
                    det,
                    "D",
                    role,
                    None,
                    False,
                    None,
                    f"read error: {exc.__class__.__name__}",
                )
            )
            result.skipped.append(
                skipped_row(
                    key=key,
                    reason_code="read-error",
                    reason=f"cannot read: {exc.__class__.__name__}",
                    size=size,
                    detected_as=None,
                )
            )
            bump("by_skip_reason", "read-error")
            _count(counts, bump, "D", det, role, size)
            return
        det = detect(name, head, overrides)
        binary = looks_binary(head)
        if det.family == "code" and det.language in config.disabled_languages:
            det = detect(name, head, {**overrides, ext: "plain"}) if ext else det
        tier, code, reason = _tier_for(det, plugins, binary)
        if size > max_bytes:
            tier, code, reason = (
                "D",
                "too-large",
                f"{size / (1024 * 1024):.1f} MB exceeds limits.max_file_mb",
            )
        elif (
            lines is not None
            and lines > config.max_lines
            and tier in ("A", "B", "C")
            and det.family != "binary"
        ):
            tier, code, reason = "D", "too-many-lines", f"{lines} lines exceed limits.max_lines"
        if not binary and det.family != "binary" and head:
            _, encoding = decode_text(head)
        if code is None and det.family == "code" and tier == "C":
            note = "lexical analysis"
    row = _row(
        key,
        name,
        ext,
        size,
        sha256,
        det,
        tier,
        role,
        lines,
        looks_binary(head) if head else False,
        encoding,
        note if note else (reason if code else None),
    )
    result.files.append(row)
    if code is not None:
        result.skipped.append(
            skipped_row(
                key=key,
                reason_code=code,
                reason=reason or code,
                size=size,
                detected_as=det.language or det.format,
            )
        )
        bump("by_skip_reason", code)
    _count(counts, bump, tier, det, role, size)


def _row(key, name, ext, size, sha256, det: Detection, tier, role, lines, binary, encoding, note):
    return file_row(
        id=file_id(key),
        key=key,
        name=name,
        ext=ext,
        size=size,
        sha256=sha256,
        family=det.family,
        language=det.language,
        format=det.format,
        grammar=det.grammar,
        plugin=det.plugin,
        adapter=det.adapter,
        determinism=det.determinism,
        detected_by=det.how,
        tier=tier,
        role=role,
        lines=lines,
        binary=binary,
        encoding=encoding,
        note=note,
    )


def _count(counts, bump, tier, det: Detection, role, size) -> None:
    counts["n_files"] += 1
    counts["total_bytes"] += size
    bump("by_tier", tier)
    bump("by_family", det.family)
    bump("by_language", det.language)
    bump("by_format", det.format)
    bump("by_role", role)
