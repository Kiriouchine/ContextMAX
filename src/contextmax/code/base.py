# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""The code analysis contract shared by every tier.

A tier-A plugin, the generic tree-sitter analyzer (tier B) and the lexical analyzer (tier C)
all produce the same `FileAnalysis`, so resolution, output and queries never branch on how a
file was read. Line numbers are 1-based and always refer to the real line in the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

CONTAINER_KINDS = frozenset(
    {
        "class",
        "struct",
        "interface",
        "enum",
        "namespace",
        "module",
        "trait",
        "impl",
        "package",
        "entity",
        "architecture",
        "record",
        "union",
        "protocol",
        "object",
        "type",
    }
)


@dataclass
class Symbol:
    name: str
    qualname: str
    kind: str
    line: int
    end_line: int
    end_exact: bool
    signature: str
    params: list[dict[str, Any]] = field(default_factory=list)
    returns: Any = None
    doc: str | None = None
    parent: str | None = None  # qualname of the enclosing symbol
    visibility: str = "public"
    decorators: list[str] = field(default_factory=list)
    content_hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallSite:
    caller: str | None  # qualname of the enclosing symbol; None means file level
    name: str
    qualifier: str | None
    line: int
    col: int
    kind: str = "call"  # call | bare | instantiate | reference | index
    # A tier A plugin may say where the name comes from: ("module", "name") for an import,
    # ("__self__", "method") for self.method(), ("__class__", "method") for cls.method().
    hint: tuple[str, str] | None = None
    # "syntax" when a grammar or plugin found it, "lexical" when a pattern did (tier B files
    # whose tags query has no reference patterns keep their calls, at low confidence).
    source: str = "syntax"


@dataclass
class Import:
    module: str
    line: int
    kind: str = "import"  # import | include | require | source | run | load | addpath | use
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    relative: bool = False
    raw: str = ""


@dataclass
class FileAnalysis:
    key: str
    language: str | None
    tier: str
    adapter: str
    adapter_version: str
    n_lines: int
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class LanguagePlugin(Protocol):
    id: str
    language: str
    tier: str

    def analyze_file(self, path, key: str, text: str, language: str | None) -> FileAnalysis: ...
