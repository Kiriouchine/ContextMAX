# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`config-v1`: JSON, JSON Lines, YAML (a line-based subset), TOML, XML, INI and dependency
manifests. Keys become sections and searchable `path = value` lines; string values that look like
paths or URLs become references. Never executes or resolves anything; caps are announced."""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from typing import Any
from xml.etree import ElementTree as ET

from contextmax.docs.adapters.common import decode, squash
from contextmax.docs.base import Block, DocumentTree, ExtractionError

MAX_SECTIONS = 100
MAX_ENTRIES = 2000
MAX_RECORDS = 200
VALUE_PREVIEW = 200
URL = re.compile(r"^(https?|ftp|git|ssh)://\S+$")
PATHLIKE = re.compile(r"^(?:\.{0,2}[/\\]|[A-Za-z]:[/\\]|[\w.-]+[/\\])?[\w./\\-]+\.[A-Za-z0-9]{1,5}$")
YAML_ENTRY = re.compile(r"^(\s*)(?:- )?(?:([^:#\"']+?)\s*:\s*(.*))?$")
YAML_LIST = re.compile(r"^(\s*)-\s+(.*)$")
REQ_LINE = re.compile(r"^([A-Za-z0-9][\w.\-\[\]]*)\s*([=<>!~]=?.*)?$")


def _preview(value: Any) -> str:
    if isinstance(value, str):
        text = squash(value)
    elif isinstance(value, bool) or value is None:
        text = json.dumps(value)
    elif isinstance(value, (int, float)):
        text = repr(value)
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:VALUE_PREVIEW] + ("…" if len(text) > VALUE_PREVIEW else "")


def flatten(value: Any, prefix: str = "", out: list[tuple[str, Any]] | None = None) -> list[tuple[str, Any]]:
    """Depth-first (key order preserved) `path -> scalar` pairs."""
    if out is None:
        out = []
    if len(out) > MAX_ENTRIES * 2:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            out.append((prefix, value))
        else:
            for idx, v in enumerate(value):
                flatten(v, f"{prefix}[{idx}]", out)
    else:
        out.append((prefix, value))
    return out


class ConfigAdapter:
    id = "config-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        name = key.rsplit("/", 1)[-1]
        lower = name.lower()
        tree.title = name
        text = decode(data)
        try:
            if lower.endswith((".jsonl", ".ndjson")):
                self._records(tree, text)
            elif lower.endswith((".json", ".geojson", ".json5")) or lower in ("package.json", "package-lock.json", "pipfile.lock"):
                self._mapping(tree, text, json.loads(text), "json")
            elif lower.endswith((".toml",)) or lower in ("pipfile", "cargo.lock", "poetry.lock", "uv.lock"):
                self._mapping(tree, text, tomllib.loads(text), "toml")
            elif lower.endswith((".yml", ".yaml")):
                self._yaml(tree, text)
            elif lower.endswith((".xml", ".xsd", ".xsl", ".xslt", ".svg", ".plist", ".csproj", ".vcxproj", ".props",
                                 ".targets", ".resx", ".nuspec", ".pom", ".xaml")):
                self._xml(tree, data)
            elif lower.startswith("requirements") or lower in ("go.mod", "go.sum") or lower.endswith(".lock"):
                self._lines(tree, text, dependencies=True)
            elif lower.startswith(".") or lower.endswith((".ini", ".cfg", ".conf", ".properties", ".editorconfig")):
                self._ini(tree, text)
            else:
                self._lines(tree, text, dependencies=False)
        except ExtractionError:
            raise
        except (ValueError, tomllib.TOMLDecodeError, configparser.Error, ET.ParseError) as exc:
            tree.notes.append(f"parse failed ({exc.__class__.__name__}); indexed as lines")
            tree.blocks = []
            self._lines(tree, text, dependencies=False)
        return tree

    # ----- shapes -----------------------------------------------------------------------------
    def _mapping(self, tree: DocumentTree, text: str, value: Any, flavour: str) -> None:
        tree.metadata["shape"] = flavour
        if isinstance(value, dict):
            keys = list(value.keys())
            if len(keys) > MAX_SECTIONS:
                tree.notes.append(f"TRUNCATED: {MAX_SECTIONS} of {len(keys)} top-level keys shown as sections")
            lines = text.split("\n")
            line = 1
            entries_total = 0
            for idx, top in enumerate(keys):
                needle = json.dumps(str(top)) if flavour == "json" else str(top)
                line = self._find_line(lines, needle, line)
                if idx < MAX_SECTIONS:
                    tree.blocks.append(Block(kind="heading", text=str(top), level=1, line=line, end_line=line))
                entries = flatten(value[top], str(top))
                entries_total += len(entries)
                if entries_total > MAX_ENTRIES:
                    tree.notes.append(f"TRUNCATED: entries beyond {MAX_ENTRIES} not listed")
                    break
                self._entries(tree, entries, line)
        else:
            self._entries(tree, flatten(value, "$"), 1)

    def _records(self, tree: DocumentTree, text: str) -> None:
        tree.metadata["shape"] = "jsonl"
        lines = text.split("\n")
        n = 0
        for number, raw in enumerate(lines, start=1):
            if not raw.strip():
                continue
            n += 1
            if n > MAX_RECORDS:
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                tree.blocks.append(Block(kind="paragraph", text=squash(raw)[:VALUE_PREVIEW], line=number, end_line=number))
                continue
            self._entries(tree, flatten(record, f"[{n}]"), number)
        tree.metadata["n_records"] = n
        if n > MAX_RECORDS:
            tree.notes.append(f"TRUNCATED: first {MAX_RECORDS} of {n} records listed")

    def _entries(self, tree: DocumentTree, entries: list[tuple[str, Any]], line: int) -> None:
        for path, value in entries:
            preview = _preview(value)
            tree.blocks.append(Block(kind="list_item", text=f"{path} = {preview}", line=line, end_line=line))
            if isinstance(value, str):
                self._reference(tree, value, line)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        self._reference(tree, item, line)

    def _yaml(self, tree: DocumentTree, text: str) -> None:
        tree.metadata["shape"] = "yaml-lite"
        stack: list[tuple[int, str]] = []
        for number, raw in enumerate(text.split("\n"), start=1):
            line = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
            if not line.strip() or line.strip() in ("---", "..."):
                continue
            indent = len(line) - len(line.lstrip(" "))
            m = YAML_LIST.match(line)
            if m and ":" not in m.group(2).split(" ")[0]:
                while stack and stack[-1][0] >= indent + 2:
                    stack.pop()
                path = ".".join(p for _, p in stack) or "$"
                tree.blocks.append(Block(kind="list_item", text=f"{path}[] = {squash(m.group(2))[:VALUE_PREVIEW]}", line=number, end_line=number))
                self._reference(tree, m.group(2).strip().strip("'\""), number)
                continue
            body = line[indent + 2:] if m else line
            if m:
                indent += 2
            if ":" not in body:
                continue
            k, _, v = body.partition(":")
            k = k.strip().strip("'\"")
            v = v.strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if indent == 0:
                tree.blocks.append(Block(kind="heading", text=k, level=1, line=number, end_line=number))
            stack.append((indent, k))
            if v and v not in ("|", ">", "|-", ">-"):
                path = ".".join(p for _, p in stack)
                tree.blocks.append(Block(kind="list_item", text=f"{path} = {squash(v)[:VALUE_PREVIEW]}", line=number, end_line=number))
                self._reference(tree, v.strip("'\""), number)

    def _xml(self, tree: DocumentTree, data: bytes) -> None:
        tree.metadata["shape"] = "xml"
        if b"<!ENTITY" in data[:20000]:
            raise ExtractionError("XML with entity declarations is not parsed (safety)")
        root = ET.fromstring(data)
        count = 0
        cursor = 1
        lines = decode(data).split("\n")

        def visit(node: ET.Element, path: str, depth: int) -> None:
            nonlocal count, cursor
            if count >= MAX_ENTRIES:
                return
            tag = node.tag.split("}")[-1]
            here = f"{path}/{tag}" if path else tag
            line = cursor = self._find_line(lines, f"<{tag}", cursor)
            if depth <= 1:
                tree.blocks.append(Block(kind="heading", text=tag, level=depth + 1, line=line, end_line=line))
            for attr, value in sorted(node.attrib.items()):
                count += 1
                tree.blocks.append(Block(kind="list_item", text=f"{here}@{attr.split('}')[-1]} = {squash(value)[:VALUE_PREVIEW]}", line=line, end_line=line))
                self._reference(tree, value, line)
            content = squash(node.text or "")
            if content:
                count += 1
                tree.blocks.append(Block(kind="list_item", text=f"{here} = {content[:VALUE_PREVIEW]}", line=line, end_line=line))
                self._reference(tree, content, line)
            for child in node:
                visit(child, here, depth + 1)

        visit(root, "", 0)
        if count >= MAX_ENTRIES:
            tree.notes.append(f"TRUNCATED: first {MAX_ENTRIES} XML entries listed")

    def _ini(self, tree: DocumentTree, text: str) -> None:
        tree.metadata["shape"] = "ini"
        parser = configparser.ConfigParser(interpolation=None, allow_no_value=True, strict=False, delimiters=("=", ":"))
        parser.optionxform = str  # keep key case
        try:
            parser.read_string(text)
        except configparser.MissingSectionHeaderError:
            self._lines(tree, text, dependencies=False)
            return
        lines = text.split("\n")
        line = 1
        for section in parser.sections():
            line = self._find_line(lines, f"[{section}]", line)
            tree.blocks.append(Block(kind="heading", text=section, level=1, line=line, end_line=line))
            at = line
            for k, v in parser.items(section):
                at = self._find_line(lines, k, at)
                tree.blocks.append(Block(kind="list_item", text=f"{section}.{k} = {squash(v or '')[:VALUE_PREVIEW]}", line=at, end_line=at))
                if v:
                    self._reference(tree, v, at)
        for k, v in parser.defaults().items():
            tree.blocks.append(Block(kind="list_item", text=f"{k} = {squash(v or '')[:VALUE_PREVIEW]}", line=1, end_line=1))

    def _lines(self, tree: DocumentTree, text: str, dependencies: bool) -> None:
        tree.metadata["shape"] = "dependencies" if dependencies else "lines"
        n = 0
        for number, raw in enumerate(text.split("\n"), start=1):
            line = raw.strip()
            if not line or line.startswith(("#", ";", "//")):
                continue
            n += 1
            if n > MAX_ENTRIES:
                tree.notes.append(f"TRUNCATED: first {MAX_ENTRIES} lines listed")
                break
            if dependencies:
                m = REQ_LINE.match(line.split(" #")[0].split(" ;")[0].strip())
                if m:
                    tree.blocks.append(Block(kind="list_item", text=f"{m.group(1)} {squash(m.group(2) or '')}".strip(), line=number, end_line=number,
                                             extra={"dependency": m.group(1)}))
                    continue
            tree.blocks.append(Block(kind="list_item", text=squash(line)[:VALUE_PREVIEW], line=number, end_line=number))
            self._reference(tree, line, number)

    # ----- helpers ----------------------------------------------------------------------------
    @staticmethod
    def _reference(tree: DocumentTree, value: str, line: int) -> None:
        value = value.strip()
        if not value or len(value) > 500 or " " in value:
            return
        if URL.match(value):
            tree.blocks.append(Block(kind="link", text=value, target=value, line=line, end_line=line))
        elif (
            PATHLIKE.match(value)
            and ("/" in value or "\\" in value or "." in value[1:])
            and not value.replace(".", "").replace("-", "").isdigit()
        ):
            tree.blocks.append(
                Block(kind="link", text=value, target=value, line=line, end_line=line, extra={"config_value": True})
            )

    @staticmethod
    def _find_line(lines: list[str], needle: str, start_line: int) -> int:
        """First line at or after `start_line` containing `needle`; `start_line` when absent."""
        for idx in range(max(start_line - 1, 0), len(lines)):
            if needle in lines[idx]:
                return idx + 1
        return start_line
