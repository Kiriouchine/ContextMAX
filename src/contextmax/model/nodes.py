# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Node envelope builders.

Every node row shares the envelope: id, kind, family, name, file, tier, cite. Family-specific
fields are added by the builders below so that every row of a kind has the same key set, which
keeps JSONL diffs meaningful and lets consumers rely on presence rather than `.get()` chains.
"""

from __future__ import annotations

from typing import Any

TIERS = ("A", "B", "C", "D")
FAMILIES = ("file", "code", "doc")
CONFIDENCES = ("high", "medium", "low")


def file_row(
    *,
    id: str,
    key: str,
    name: str,
    ext: str,
    size: int,
    sha256: str | None,
    family: str,
    language: str | None,
    format: str | None,
    grammar: str | None,
    plugin: str | None,
    adapter: str | None,
    determinism: str | None,
    detected_by: str,
    tier: str,
    role: str,
    lines: int | None,
    binary: bool,
    encoding: str | None,
    note: str | None,
) -> dict[str, Any]:
    assert tier in TIERS, tier
    return {
        "id": id,
        "kind": "file",
        "family": "file",
        "name": name,
        "file": key,
        "ext": ext,
        "size": size,
        "sha256": sha256,
        "content_family": family,
        "language": language,
        "format": format,
        "grammar": grammar,
        "plugin": plugin,
        "adapter": adapter,
        "determinism": determinism,
        "detected_by": detected_by,
        "tier": tier,
        "role": role,
        "lines": lines,
        "binary": binary,
        "encoding": encoding,
        "note": note,
        "cite": key,
    }


def skipped_row(
    *, key: str, reason_code: str, reason: str, size: int | None, detected_as: str | None
) -> dict[str, Any]:
    return {
        "file": key,
        "reason_code": reason_code,
        "reason": reason,
        "size": size,
        "detected_as": detected_as,
    }
