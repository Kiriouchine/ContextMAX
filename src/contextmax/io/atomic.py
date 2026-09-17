# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Atomic file writes so a crash never leaves a half-written artifact behind."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` via a temporary sibling and an atomic replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()


def atomic_write_text(path: Path, text: str) -> bytes:
    """Write UTF-8 text without BOM and with LF newlines; returns the bytes written."""
    data = text.encode("utf-8")
    atomic_write_bytes(path, data)
    return data
