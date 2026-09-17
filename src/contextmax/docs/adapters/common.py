# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Helpers shared by the text-based adapters."""

from __future__ import annotations

import re

from contextmax.fs import decode_text

_WS = re.compile(r"[ \t]+")
_NUMBER_PREFIX = re.compile(r"^\s*((?:\d+\.)*\d+|[A-Z](?:\.\d+)*|[IVXLC]+\.)\.?\s+(?=\S)")
_URL = re.compile(r"https?://[^\s<>()\"']+[^\s<>()\"'.,;:]")
_PATH = re.compile(
    r"(?<![\w/\\.])((?:[\w.-]+[/\\])*[\w.-]+\.(?:md|txt|tex|bib|html?|pdf|docx?|xlsx?|pptx?|csv|json|ya?ml|toml|xml|py|m|c|h|cpp|hpp|js|ts|sh|ps1|bat|vhd|v|sv|mat|slx|png|jpg|jpeg|svg))(?![\w/\\])",
    re.IGNORECASE,
)


def decode(data: bytes) -> str:
    text, _ = decode_text(data)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def squash(text: str) -> str:
    return _WS.sub(" ", text).strip()


def split_number(title: str) -> tuple[str | None, str]:
    """Separate an explicit leading number ("3.1.2 Scope" -> ("3.1.2", "Scope"))."""
    m = _NUMBER_PREFIX.match(title)
    if not m:
        return None, title.strip()
    number = m.group(1).rstrip(".")
    rest = title[m.end() :].strip()
    if not rest:
        return None, title.strip()
    return number, rest


def urls_in(text: str) -> list[str]:
    return _URL.findall(text)


def paths_in(text: str) -> list[str]:
    return [m.group(1) for m in _PATH.finditer(text)]
