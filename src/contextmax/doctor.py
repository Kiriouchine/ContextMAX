# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`contextmax doctor`: a read-only readiness report. Warnings degrade, failures block."""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from contextmax import grammars, version
from contextmax.buildstate import BuildState
from contextmax.config import ConfigError, load_config
from contextmax.io.jsonl import read_json
from contextmax.paths import NoIndexError, layout_for, resolve_root

OPTIONAL_PACKAGES: tuple[tuple[str, str, str], ...] = (
    ("pypdf", "PDF text, outlines and links", "BSD"),
    ("openpyxl", "Excel .xlsx workbooks", "MIT"),
    ("xlrd", "legacy Excel .xls workbooks", "BSD"),
    ("tree-sitter", "syntax trees for tier A/B code analysis", "MIT"),
    ("tree-sitter-language-pack", "prebuilt grammars for ~370 languages", "MIT"),
    ("mcp", "the local MCP server", "MIT"),
    ("Pillow", "image dimensions and metadata", "MIT-CMU"),
    ("pdfplumber", "PDF tables", "MIT"),
    ("PyMuPDF", "alternative PDF reader (opt-in)", "AGPL-3.0"),
)

SYNC_MARKERS = ("onedrive", "sharepoint", "dropbox", "google drive", "googledrive", "icloud")


@dataclass
class Check:
    area: str
    name: str
    state: str  # ok | warn | fail
    detail: str


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def run_doctor(root_arg: str | None = None) -> tuple[list[Check], int]:
    checks: list[Check] = []

    # Toolchain ---------------------------------------------------------------------------
    py = sys.version_info
    bits = platform.architecture()[0]
    if py < (3, 11):
        checks.append(
            Check(
                "toolchain",
                "python",
                "fail",
                f"{platform.python_version()} ({bits}); 3.11+ required",
            )
        )
    else:
        checks.append(
            Check(
                "toolchain",
                "python",
                "ok",
                f"{platform.python_version()} ({bits}) at {sys.executable}",
            )
        )
    try:
        con = sqlite3.connect(":memory:")
        has_fts = bool(con.execute("select sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0])
        con.close()
    except sqlite3.Error:
        has_fts = False
    checks.append(
        Check(
            "toolchain",
            "sqlite-fts5",
            "ok" if has_fts else "warn",
            f"SQLite {sqlite3.sqlite_version}; FTS5 {'available' if has_fts else 'missing: full-text search degrades to LIKE'}",
        )
    )
    for pkg, purpose, license_name in OPTIONAL_PACKAGES:
        found = _package_version(pkg)
        if found:
            state = "warn" if license_name.startswith("AGPL") else "ok"
            note = f"{found} ({license_name})" + (
                " — copyleft, opt-in only" if state == "warn" else ""
            )
            checks.append(Check("readers", pkg, state, note))
        else:
            checks.append(
                Check(
                    "readers",
                    pkg,
                    "warn" if not license_name.startswith("AGPL") else "ok",
                    f"not installed; {purpose} unavailable"
                    if not license_name.startswith("AGPL")
                    else "not installed (fine)",
                )
            )
    gst = grammars.status()
    if gst["pack_installed"]:
        state = "ok" if gst["with_tags"] else "warn"
        detail = (
            f"pack {gst['pack_version']}; {gst['n_provisioned']} grammar(s) provisioned in {gst['folder']}; "
            f"tier B ready for {len(gst['with_tags'])} of them"
            if gst["bundle_present"]
            else f"pack {gst['pack_version']} installed but no grammar bundle yet; run `contextmax grammars fetch --for-project`"
        )
        checks.append(Check("grammars", "provisioned", state, detail))
    else:
        checks.append(
            Check(
                "grammars",
                "language-pack",
                "warn",
                "tree-sitter-language-pack not installed; all code falls to tier C",
            )
        )
    # Project -----------------------------------------------------------------------------
    root: Path | None = None
    try:
        root = resolve_root(root_arg)
        checks.append(Check("project", "root", "ok", str(root)))
    except NoIndexError as exc:
        checks.append(Check("project", "root", "warn", str(exc)))
    if root is not None:
        layout0 = layout_for(root, None)
        try:
            config = load_config(layout0.config)
            checks.append(Check("project", "config", "ok", f"{config.slug} ({layout0.config})"))
        except ConfigError as exc:
            config = None
            checks.append(Check("project", "config", "fail", "; ".join(exc.messages)))
        if config is not None:
            layout = layout_for(root, config.output_dir)
            lower = str(layout.index).lower()
            if any(marker in lower for marker in SYNC_MARKERS):
                checks.append(
                    Check(
                        "project",
                        "index-location",
                        "warn",
                        f"{layout.index} looks like a synced folder; set output_dir elsewhere to avoid uploading derived data",
                    )
                )
            else:
                checks.append(Check("project", "index-location", "ok", str(layout.index)))
            if layout.manifest.is_file():
                try:
                    manifest = read_json(layout.manifest)
                    comp = manifest.get("completeness", {})
                    state = "ok" if comp.get("verdict") == "full" else "warn"
                    checks.append(
                        Check(
                            "index",
                            "manifest",
                            state,
                            f"{comp.get('verdict', '?')}; engine {manifest.get('engine_version')}; "
                            f"baseline {str(manifest.get('baseline_identity_hash', ''))[:12]}",
                        )
                    )
                except (OSError, ValueError) as exc:
                    checks.append(Check("index", "manifest", "fail", f"unreadable: {exc}"))
            else:
                checks.append(
                    Check("index", "manifest", "warn", "no index built yet; run `contextmax index`")
                )
            state_data = BuildState.load(layout.build_state)
            if state_data:
                failed = [
                    n for n, s in state_data.get("stages", {}).items() if s.get("ok") is False
                ]
                checks.append(
                    Check(
                        "index",
                        "last-build",
                        "warn" if failed else "ok",
                        f"started {state_data.get('started_utc')}; failed stages: {', '.join(failed) or 'none'}",
                    )
                )
            for name in ("nodes/files.jsonl", "skipped.jsonl", "coverage.json"):
                checks.append(
                    Check(
                        "index",
                        name,
                        "ok" if (layout.index / name).is_file() else "warn",
                        "present" if (layout.index / name).is_file() else "missing",
                    )
                )

        # AI hosts ---------------------------------------------------------------------------
        home = Path.home()
        host_paths = {
            "claude-code-project": root / ".claude",
            "claude-code-user": home / ".claude",
            "copilot-project": root / ".github",
            "copilot-user": home / ".copilot",
            "cursor": root / ".cursor",
            "windsurf": root / ".windsurf",
            "codex": root / ".codex",
            "agents-md": root / "AGENTS.md",
        }
        found = sorted(name for name, path in host_paths.items() if path.exists())
        checks.append(
            Check(
                "hosts",
                "detected",
                "ok",
                ", ".join(found)
                if found
                else "none detected (skills can still be installed explicitly)",
            )
        )
        desktop = _claude_desktop_config()
        checks.append(
            Check(
                "hosts",
                "claude-desktop",
                "ok" if desktop and desktop.exists() else "warn",
                str(desktop) if desktop and desktop.exists() else "config file not found",
            )
        )

    exit_code = 1 if any(c.state == "fail" for c in checks) else 0
    return checks, exit_code


def _claude_desktop_config() -> Path | None:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / "Claude" / "claude_desktop_config.json" if base else None
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def checks_to_dict(checks: list[Check], exit_code: int) -> dict[str, Any]:
    return {
        "engine_version": version.__version__,
        "checks": [asdict(c) for c in checks],
        "failures": sum(1 for c in checks if c.state == "fail"),
        "warnings": sum(1 for c in checks if c.state == "warn"),
        "exit_code": exit_code,
    }
