# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Grammar provisioning for tier B.

`tree-sitter-language-pack` fetches one platform bundle from the network the first time a
grammar is needed and extracts grammars from it afterwards. Indexing must never touch the
network, so ContextMAX only loads a grammar when the bundle for the installed pack version is
already in its cache folder (`~/.contextmax/grammars`, override with CONTEXTMAX_GRAMMAR_DIR)
and the grammar has a tags query. `cmx grammars fetch` is the one command that downloads.
"""

from __future__ import annotations

import json
import os
from functools import cache
from importlib import metadata
from pathlib import Path
from typing import Any

GRAMMAR_DIR_ENV = "CONTEXTMAX_GRAMMAR_DIR"
PACK_DIST = "tree-sitter-language-pack"


def grammar_dir() -> Path:
    override = os.environ.get(GRAMMAR_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".contextmax" / "grammars").resolve()


def ledger_path() -> Path:
    return grammar_dir() / "provisioned.json"


def pack_version() -> str | None:
    try:
        return metadata.version(PACK_DIST)
    except metadata.PackageNotFoundError:
        return None


def pack_installed() -> bool:
    return pack_version() is not None


_configured_for: Path | None = None


def _pack():
    """Import and configure the pack for the current grammar folder (no download)."""
    global _configured_for
    import tree_sitter_language_pack as pack

    folder = grammar_dir() / "pack"
    if _configured_for != folder:
        pack.configure(pack.PackConfig(cache_dir=str(folder)))
        _configured_for = folder
    return pack


def bundle_present() -> bool:
    """True when the platform bundle for the installed pack version is in the cache."""
    version = pack_version()
    if version is None:
        return False
    base = grammar_dir() / "pack" / "tree-sitter-language-pack" / f"v{version}"
    bundles = base / "bundles"
    if bundles.is_dir() and any(bundles.iterdir()):
        return True
    libs = base / "libs"
    return libs.is_dir() and any(libs.iterdir())


def read_ledger() -> dict[str, Any]:
    path = ledger_path()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_ledger(data: dict[str, Any]) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def provisioned() -> dict[str, str]:
    """Grammar name -> pack version, from the ledger, only while the bundle is still present."""
    if not bundle_present():
        return {}
    ledger = read_ledger()
    if ledger.get("pack_version") != pack_version():
        return {}
    return {str(k): str(v) for k, v in ledger.get("grammars", {}).items()}


def is_provisioned(name: str | None) -> bool:
    if not name or not pack_installed():
        return False
    return name in provisioned()


@cache
def has_tags(name: str) -> bool:
    if not is_provisioned(name):
        return False
    try:
        return bool(_pack().get_tags_query(name))
    except Exception:
        return False


def tags_query(name: str) -> str | None:
    if not has_tags(name):
        return None
    return _pack().get_tags_query(name)


_loaded: dict[str, tuple[Any, Any]] = {}


def load(name: str):
    """Return (Language, Parser) for a provisioned grammar; raises when not provisioned.

    Objects are kept for the life of the process: a Language collected while a Parser or a
    Query still points at it is a native crash waiting to happen.
    """
    if name in _loaded:
        return _loaded[name]
    if not is_provisioned(name):
        raise LookupError(f"grammar '{name}' is not provisioned; run `contextmax grammars fetch`")
    pack = _pack()
    lang = pack.get_language(name)
    parser = pack.get_parser(name)
    _loaded[name] = (lang, parser)
    return _loaded[name]


def manifest_languages() -> list[str]:
    if not pack_installed():
        return []
    try:
        return sorted(_pack().manifest_languages())
    except Exception:
        return []


def fetch(names: list[str] | None = None, all_languages: bool = False) -> dict[str, Any]:
    """Download the platform bundle (network) and record every requested grammar as provisioned.

    With `all_languages` every manifest language is recorded; otherwise only `names`. Loading
    a grammar once after the download proves it can be extracted offline.
    """
    if not pack_installed():
        raise RuntimeError(
            "tree-sitter-language-pack is not installed; `pip install contextmax[code]`"
        )
    pack = _pack()
    wanted = sorted(set(pack.manifest_languages())) if all_languages else sorted(set(names or []))
    unknown = [n for n in wanted if not pack.has_language(n)]
    wanted = [n for n in wanted if pack.has_language(n)]
    if wanted:
        pack.download(wanted)
    loaded: dict[str, str] = {}
    failed: dict[str, str] = {}
    for name in wanted:
        try:
            pack.get_language(name)
            loaded[name] = pack_version() or ""
        except Exception as exc:
            failed[name] = f"{exc.__class__.__name__}: {exc}"
    ledger = read_ledger()
    if ledger.get("pack_version") != pack_version():
        ledger = {"pack_version": pack_version(), "grammars": {}}
    ledger.setdefault("grammars", {}).update(loaded)
    write_ledger(ledger)
    has_tags.cache_clear()
    return {
        "provisioned": sorted(loaded),
        "failed": failed,
        "unknown": unknown,
        "pack_version": pack_version(),
        "folder": str(grammar_dir()),
    }


def status() -> dict[str, Any]:
    ledger = provisioned()
    return {
        "pack_installed": pack_installed(),
        "pack_version": pack_version(),
        "folder": str(grammar_dir()),
        "bundle_present": bundle_present(),
        "n_provisioned": len(ledger),
        "provisioned": sorted(ledger),
        "with_tags": sorted(n for n in ledger if has_tags(n)),
        "without_tags": sorted(n for n in ledger if not has_tags(n)),
    }
