# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Entity id builders (see ADR-0003). Ids never contain line numbers."""

from __future__ import annotations

import re
import unicodedata

from contextmax.io.canon import rel_key

_TERM_STRIP = re.compile(r"[^a-z0-9]+")


def file_id(key: str) -> str:
    return f"file:{rel_key(key)}"


def sym_id(key: str, qualname: str, ordinal: int = 1) -> str:
    suffix = "" if ordinal <= 1 else f"~{ordinal}"
    return f"sym:{rel_key(key)}#{qualname}{suffix}"


def doc_id(key: str) -> str:
    return f"doc:{rel_key(key)}"


def section_id(key: str, section_path: str) -> str:
    return f"doc:{rel_key(key)}#{section_path}"


def ref_id(key: str, ref_key: str) -> str:
    return f"ref:{rel_key(key)}#{ref_key}"


def param_id(key: str, locator: str) -> str:
    return f"param:{rel_key(key)}#{locator}"


def mod_id(folder_key: str) -> str:
    return f"mod:{rel_key(folder_key) or '.'}"


def normalize_term(text: str) -> str:
    """Lowercase, accent-folded, hyphen-joined token form used in term ids."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    return _TERM_STRIP.sub("-", folded).strip("-")


def term_id(text: str) -> str:
    return f"term:{normalize_term(text)}"


def slug(text: str, max_len: int = 60) -> str:
    """A stable slug for section paths; keeps it short and lowercase."""
    value = normalize_term(text)
    return value[:max_len].rstrip("-") or "section"
