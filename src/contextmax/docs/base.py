# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The document adapter contract.

Every format adapter turns a file into a `DocumentTree`: metadata plus an ordered list of
blocks. Structure, references, the text cache and the query layer work only on that tree, so
they never know which format produced it. Line numbers are 1-based lines of the source file
where the format has lines; page-based formats set `page` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

BLOCK_KINDS = (
    "heading",
    "paragraph",
    "list_item",
    "table",
    "code",
    "figure",
    "footnote",
    "link",
    "citation",
    "label",
    "ref",
    "include",
    "math",
    "page",
    "cell",
    "title",
    "bibentry",
)


@dataclass
class Block:
    kind: str
    text: str = ""
    line: int = 0
    end_line: int = 0
    level: int = 0  # heading depth (1 = top) or list nesting
    number: str | None = None  # explicit heading number such as "3.1.2"
    lang: str | None = None  # code block language
    target: str | None = None  # link, include, figure or ref target
    rows: list[list[str]] | None = None  # table rows
    page: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentTree:
    key: str
    adapter: str
    adapter_version: str
    determinism: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)
    pages: int | None = None
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ExtractionError(Exception):
    """Raised by an adapter when a file cannot be read; the reason lands in skipped.jsonl."""


class FormatAdapter(Protocol):
    id: str
    version: str
    determinism: str

    def available(self) -> tuple[bool, str]: ...

    def extract(self, key: str, data: bytes) -> DocumentTree: ...
