# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Canonical forms that every stage must use.

Determinism rules encoded here:
- JSON is hashed in one canonical serialization (sorted keys, compact separators, UTF-8),
  so the hash is independent of whitespace, key order and BOM.
- Relative paths have exactly one form: forward slashes, no leading "./", NFC-normalized.
  Every pattern, id and lookup sees this form and nothing else.
- Strings are compared by code point (Python's default), never by locale.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import PurePath
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize `obj` in the one canonical form used for hashing."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_json(obj: Any) -> str:
    """SHA-256 of the canonical JSON form of `obj`."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel_key(path: str | PurePath) -> str:
    """The ONE canonical relative path form.

    Forward slashes, no leading "./" or "/", no trailing "/", NFC-normalized so that a file
    created on macOS (NFD) and the same file on Windows (NFC) produce the same key.
    """
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    return unicodedata.normalize("NFC", text)


def join_key(*parts: str) -> str:
    """Join path parts into a canonical relative key, dropping empty parts."""
    return rel_key("/".join(p for p in (rel_key(x) for x in parts) if p))


def parent_key(key: str) -> str:
    """Parent of a canonical key ("" for a top-level entry)."""
    index = key.rfind("/")
    return key[:index] if index >= 0 else ""


def sorted_unique(values) -> list:
    """Sorted list without duplicates, for every list that lands in an artifact."""
    return sorted(set(values))
