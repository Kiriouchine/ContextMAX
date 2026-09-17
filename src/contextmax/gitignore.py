# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
r"""A gitignore-compatible matcher using only the standard library.

Semantics implemented (see `git help gitignore`):
- blank lines and lines starting with '#' are ignored; '\#' and '\!' escape those characters;
- trailing spaces are ignored unless escaped with a backslash;
- '!' negates a pattern; the last matching pattern decides;
- a pattern without a slash (other than a trailing one) matches at any depth;
- a pattern with a slash elsewhere is anchored to the directory holding the ignore file;
- a trailing slash restricts the pattern to directories;
- '*' matches anything but '/', '?' one character but '/', '[...]' a class, and '**' spans
  directories in the leading, middle and trailing positions;
- a directory that is ignored hides everything below it (the walker must not descend).

Patterns are always matched against canonical keys (forward slashes, relative to the project
root), which is the one path form ContextMAX uses everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    regex: re.Pattern[str]
    negated: bool
    dir_only: bool
    source: str


def _translate(pattern: str) -> str:
    """Translate one gitignore glob (already anchored/normalized) into a regex fragment."""
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern.startswith("**", i):
                after = pattern[i + 2 : i + 3]
                before = pattern[i - 1 : i] if i > 0 else ""
                if (before == "" or before == "/") and after == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                if (before == "" or before == "/") and after == "":
                    out.append(".*")
                    i += 2
                    continue
                out.append("[^/]*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(ch))
                i += 1
            else:
                body = pattern[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                body = body.replace("\\", "\\\\")
                out.append(f"[{body}]")
                i = j + 1
        elif ch == "\\" and i + 1 < n:
            out.append(re.escape(pattern[i + 1]))
            i += 2
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def compile_rule(line: str, base: str = "") -> Rule | None:
    """Compile one ignore line. `base` is the canonical key of the ignore file's directory."""
    raw = line.rstrip("\n")
    if not raw.strip() or raw.lstrip().startswith("#"):
        return None
    # Trailing spaces are ignored unless escaped.
    stripped = raw
    while stripped.endswith(" ") and not stripped.endswith("\\ "):
        stripped = stripped[:-1]
    text = stripped
    negated = False
    if text.startswith("!"):
        negated = True
        text = text[1:]
    elif text.startswith("\\!") or text.startswith("\\#"):
        text = text[1:]
    if not text:
        return None
    dir_only = text.endswith("/")
    if dir_only:
        text = text.rstrip("/")
    if not text:
        return None
    anchored = "/" in text
    if text.startswith("/"):
        text = text.lstrip("/")
    fragment = _translate(text)
    if anchored:
        prefix = re.escape(base + "/") if base else ""
        regex = f"^{prefix}{fragment}(?:/.*)?$"
    else:
        prefix = re.escape(base + "/") if base else ""
        regex = f"^{prefix}(?:.*/)?{fragment}(?:/.*)?$"
    return Rule(regex=re.compile(regex), negated=negated, dir_only=dir_only, source=raw)


def compile_rules(lines: list[str], base: str = "") -> list[Rule]:
    rules: list[Rule] = []
    for line in lines:
        rule = compile_rule(line, base)
        if rule is not None:
            rules.append(rule)
    return rules


class IgnoreStack:
    """Ordered ignore rules from the root down; the deepest file's rules are consulted last."""

    def __init__(self) -> None:
        self._frames: list[tuple[str, list[Rule]]] = []

    def push(self, base: str, rules: list[Rule]) -> None:
        self._frames.append((base, rules))

    def pop(self) -> None:
        self._frames.pop()

    def is_ignored(self, key: str, is_dir: bool) -> str | None:
        """Return the source line of the deciding rule when `key` is ignored, else None."""
        decision: str | None = None
        for _base, rules in self._frames:
            for rule in rules:
                if rule.dir_only and not is_dir:
                    # A dir-only rule still hides files whose ancestor directory matches;
                    # that case is handled by the walker refusing to descend into the dir.
                    continue
                if rule.regex.match(key):
                    decision = None if rule.negated else rule.source
        return decision
