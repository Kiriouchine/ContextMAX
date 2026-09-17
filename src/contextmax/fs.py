# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Filesystem helpers that keep reads safe and platform differences contained."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows attribute bits: FILE_ATTRIBUTE_OFFLINE and FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS.
# A file carrying either is a cloud placeholder; reading it would trigger a download.
_WIN_PLACEHOLDER_BITS = 0x1000 | 0x400000

SNIFF_BYTES = 8192


def is_cloud_placeholder(path: Path, st: os.stat_result | None = None) -> bool:
    """True when the file's bytes are not on this machine (OneDrive, iCloud, ...)."""
    if path.name.endswith(".icloud") and path.name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            st = st or path.stat()
        except OSError:
            return False
        attrs = getattr(st, "st_file_attributes", 0)
        return bool(attrs & _WIN_PLACEHOLDER_BITS)
    return False


def read_head(path: Path, size: int = SNIFF_BYTES) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(size)


def looks_binary(head: bytes) -> bool:
    """A NUL byte in the first chunk is the classic and reliable binary test."""
    if not head:
        return False
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False  # UTF-16 BOM: text
    return b"\x00" in head


def decode_text(data: bytes) -> tuple[str, str]:
    """Decode bytes to text with a deterministic cascade; returns (text, encoding)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        pass
    return data.decode("latin-1"), "latin-1"


def read_text(path: Path) -> tuple[str, str]:
    with open(path, "rb") as handle:
        return decode_text(handle.read())


def count_lines(data: bytes) -> int:
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


def shebang_interpreter(head: bytes) -> str | None:
    """Return the interpreter name from a #! line, e.g. 'python3' or 'bash'."""
    if not head.startswith(b"#!"):
        return None
    line = head.split(b"\n", 1)[0][2:].strip().decode("utf-8", errors="replace")
    parts = line.split()
    if not parts:
        return None
    exe = parts[0].replace("\\", "/").rsplit("/", 1)[-1]
    if exe == "env" and len(parts) > 1:
        candidates = [p for p in parts[1:] if not p.startswith("-")]
        exe = candidates[0] if candidates else ""
    exe = exe.strip()
    return exe or None


def os_path(path: Path) -> str:
    """A path string safe for very long Windows paths."""
    text = str(path)
    if sys.platform == "win32" and len(text) > 240 and not text.startswith("\\?\\"):
        return "\\?\\" + text
    return text
