# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Language and format registries plus file-type detection.

Detection order: configured overrides, exact filename, extension (formats before languages),
shebang, content sniff, then the text/binary fallback. Every outcome records how it was reached.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from contextmax.fs import looks_binary, shebang_interpreter


@dataclass(frozen=True)
class Detection:
    family: str  # code | document | data | binary | text
    language: str | None
    format: str | None
    grammar: str | None
    plugin: str | None
    adapter: str | None
    determinism: str | None
    requires: tuple[str, ...]
    how: str  # override | filename | extension | shebang | sniff | fallback
    reason: str | None = None


def _load(name: str) -> dict[str, Any]:
    with (
        resources.files("contextmax.registry").joinpath(name).open("r", encoding="utf-8") as handle
    ):
        return json.load(handle)


@lru_cache(maxsize=1)
def languages() -> dict[str, dict[str, Any]]:
    return _load("languages.json")["languages"]


@lru_cache(maxsize=1)
def formats() -> dict[str, dict[str, Any]]:
    return _load("formats.json")["formats"]


@lru_cache(maxsize=1)
def _tables() -> dict[str, dict[str, tuple[str, str]]]:
    by_ext: dict[str, tuple[str, str]] = {}
    by_name: dict[str, tuple[str, str]] = {}
    by_shebang: dict[str, tuple[str, str]] = {}
    # Formats first so a shared extension resolves to the document reading.
    for fmt_id, fmt in sorted(formats().items()):
        for ext in fmt.get("extensions", []):
            by_ext.setdefault(ext.lower(), ("format", fmt_id))
        for name in fmt.get("filenames", []):
            by_name.setdefault(name.lower(), ("format", fmt_id))
    for lang_id, lang in sorted(languages().items()):
        for ext in lang.get("extensions", []):
            by_ext.setdefault(ext.lower(), ("language", lang_id))
        for name in lang.get("filenames", []):
            by_name.setdefault(name.lower(), ("language", lang_id))
        for exe in lang.get("shebangs", []):
            by_shebang.setdefault(exe.lower(), ("language", lang_id))
    return {"ext": by_ext, "name": by_name, "shebang": by_shebang}


def _language_detection(lang_id: str, how: str) -> Detection:
    lang = languages()[lang_id]
    return Detection(
        family="code",
        language=lang_id,
        format=None,
        grammar=lang.get("grammar"),
        plugin=lang.get("plugin"),
        adapter=None,
        determinism=None,
        requires=(),
        how=how,
    )


def _format_detection(fmt_id: str, how: str) -> Detection:
    fmt = formats()[fmt_id]
    return Detection(
        family=fmt["family"],
        language=None,
        format=fmt_id,
        grammar=None,
        plugin=None,
        adapter=fmt.get("adapter"),
        determinism=fmt.get("determinism"),
        requires=tuple(fmt.get("requires", [])),
        how=how,
        reason=fmt.get("reason"),
    )


TEXT_FALLBACK = Detection(
    family="text",
    language=None,
    format="plain",
    grammar=None,
    plugin=None,
    adapter="plain-v1",
    determinism="intrinsic",
    requires=(),
    how="fallback",
)
BINARY_FALLBACK = Detection(
    family="binary",
    language=None,
    format=None,
    grammar=None,
    plugin=None,
    adapter=None,
    determinism="catalog-only",
    requires=(),
    how="sniff",
    reason="binary content of unknown format",
)


def _split_ext(name: str) -> str:
    index = name.rfind(".")
    if index <= 0:
        return ""
    return name[index:].lower()


def detect(
    name: str, head: bytes | None = None, overrides: dict[str, str] | None = None
) -> Detection:
    """Detect the type of a file from its name and (optionally) its first bytes."""
    tables = _tables()
    ext = _split_ext(name)
    lower = name.lower()

    if overrides and ext and ext in overrides:
        target = overrides[ext]
        if target in languages():
            return _language_detection(target, "override")
        if target in formats():
            return _format_detection(target, "override")

    if lower in tables["name"]:
        kind, ident = tables["name"][lower]
        return (
            _language_detection(ident, "filename")
            if kind == "language"
            else _format_detection(ident, "filename")
        )

    if ext and ext in tables["ext"]:
        kind, ident = tables["ext"][ext]
        return (
            _language_detection(ident, "extension")
            if kind == "language"
            else _format_detection(ident, "extension")
        )

    if head is None:
        return TEXT_FALLBACK

    exe = shebang_interpreter(head)
    if exe:
        base = exe.lower()
        for candidate in (base, base.rstrip("0123456789."), base.split("-")[0]):
            if candidate in tables["shebang"]:
                return _language_detection(tables["shebang"][candidate][1], "shebang")

    if looks_binary(head):
        return BINARY_FALLBACK

    stripped = head.lstrip(b" \t\r\n")
    if stripped.startswith(b"\xef\xbb\xbf"):
        stripped = stripped[3:].lstrip(b" \t\r\n")
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<svg"):
        return _format_detection("xml", "sniff")
    if stripped.startswith(b"<!DOCTYPE html") or stripped.lower().startswith(b"<html"):
        return _format_detection("html", "sniff")
    if stripped[:1] in (b"{", b"["):
        try:
            json.loads(stripped.decode("utf-8", errors="strict"))
            return _format_detection("json", "sniff")
        except (ValueError, UnicodeDecodeError):
            pass
    if stripped.startswith(b"%PDF-"):
        return _format_detection("pdf", "sniff")
    if stripped.startswith(b"PK\x03\x04"):
        return _format_detection("archive", "sniff")
    return TEXT_FALLBACK


def language_name(lang_id: str | None) -> str | None:
    if lang_id is None:
        return None
    return languages().get(lang_id, {}).get("name", lang_id)


def format_name(fmt_id: str | None) -> str | None:
    if fmt_id is None:
        return None
    return formats().get(fmt_id, {}).get("name", fmt_id)
