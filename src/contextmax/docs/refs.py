# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""References: links, includes, cross-references, citations, figures and path mentions,
each resolved against the project when possible and kept visible when not."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from contextmax.docs.adapters.common import paths_in, urls_in
from contextmax.docs.base import DocumentTree
from contextmax.docs.structure import Structure
from contextmax.io.canon import parent_key, rel_key
from contextmax.model.ids import doc_id, file_id, ref_id, slug

URL_SCHEMES = ("http://", "https://", "ftp://", "mailto:", "file://", "www.")
INCLUDE_EXTS = {
    "input": (".tex",),
    "include": (".tex",),
    "subfile": (".tex",),
    "bibliography": (".bib",),
    "addbibresource": ("",),
    "includegraphics": (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"),
    "lstinputlisting": ("",),
}


@dataclass
class Catalog:
    """What exists in the project: file keys, which of them are documents, and labels."""

    files: set[str]
    documents: set[str]
    labels: dict[str, list[tuple[str, str | None]]] = field(
        default_factory=dict
    )  # label -> [(doc key, section id)]
    by_basename: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in self.files:
            self.by_basename.setdefault(key.rsplit("/", 1)[-1].lower(), []).append(key)


def _split_target(target: str) -> tuple[str, str | None]:
    target = target.strip().strip("<>")
    anchor = None
    if "#" in target:
        target, anchor = target.split("#", 1)
    if "?" in target:
        target = target.split("?", 1)[0]
    return target, anchor


def _resolve_path(
    catalog: Catalog, doc_key: str, target: str, exts: tuple[str, ...] = ("",)
) -> tuple[str | None, list[str], str]:
    """Return (resolved key, candidates, evidence) for a relative or bare path target."""
    if not target:
        return None, [], "empty"
    cleaned = target.replace("\\", "/")
    if cleaned.startswith("/"):
        cleaned = cleaned.lstrip("/")
        bases = [""]
    else:
        base = parent_key(doc_key)
        bases = [base]
        parts = base.split("/") if base else []
        for depth in range(len(parts) - 1, -1, -1):
            bases.append("/".join(parts[:depth]))
    for base in bases:
        for ext in (*exts, ""):
            candidate = rel_key(f"{base}/{cleaned}{ext}") if base else rel_key(f"{cleaned}{ext}")
            if candidate in catalog.files:
                return candidate, [], "path" if base == bases[0] else "path-parent"
    leaf = cleaned.rsplit("/", 1)[-1].lower()
    matches = sorted(catalog.by_basename.get(leaf, []))
    if not matches:
        for ext in exts:
            matches = sorted(catalog.by_basename.get(leaf + ext, []))
            if matches:
                break
    if len(matches) == 1:
        return matches[0], [], "basename"
    return None, matches, "unresolved"


def _node_for(catalog: Catalog, key: str) -> str:
    return doc_id(key) if key in catalog.documents else file_id(key)


def build_references(
    tree: DocumentTree, key: str, structure: Structure, catalog: Catalog
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    own_doc = doc_id(key)
    section_by_slug = {slug(s.title): s.id for s in structure.sections}
    section_of_block = structure.block_section
    seen_paths: set[tuple[str, str | None]] = set()
    ordinal = 0

    def add(
        ref_kind: str,
        raw: str,
        text: str,
        line: int,
        section: str | None,
        resolved: str | None,
        candidates: list[str],
        external: bool,
        confidence: str | None,
        evidence: str,
    ) -> None:
        nonlocal ordinal
        ordinal += 1
        rows.append(
            {
                "id": ref_id(key, f"r{ordinal}"),
                "kind": "reference",
                "family": "doc",
                "ref_kind": ref_kind,
                "name": text or raw,
                "raw": raw,
                "doc": own_doc,
                "section": section,
                "file": key,
                "line": line,
                "resolved": resolved,
                "candidates": sorted(candidates),
                "external": external,
                "confidence": confidence,
                "evidence": evidence,
                "cite": f"{key}:{line}" if line else key,
            }
        )

    for idx, block in enumerate(tree.blocks):
        section = section_of_block[idx] if idx < len(section_of_block) else None
        target = (block.target or "").strip()
        if block.kind in ("link", "figure") and target:
            if target.lower().startswith(URL_SCHEMES):
                add(
                    "url" if block.kind == "link" else "figure",
                    target,
                    block.text,
                    block.line,
                    section,
                    None,
                    [],
                    True,
                    None,
                    "url",
                )
                continue
            path, anchor = _split_target(target)
            if not path and anchor:
                resolved = section_by_slug.get(slug(anchor)) or section_by_slug.get(anchor.lower())
                add(
                    "crossref",
                    target,
                    block.text,
                    block.line,
                    section,
                    resolved,
                    [],
                    False,
                    "high" if resolved else None,
                    "anchor" if resolved else "anchor-unresolved",
                )
                continue
            resolved_key, cands, evidence = _resolve_path(
                catalog, key, path, (".md", ".html", ".htm", ".txt", ".tex")
            )
            resolved = _node_for(catalog, resolved_key) if resolved_key else None
            if resolved and anchor and resolved_key in catalog.documents:
                resolved = f"{doc_id(resolved_key)}#{slug(anchor)}"
            confidence = {"path": "high", "path-parent": "high", "basename": "medium"}.get(evidence)
            add(
                "link" if block.kind == "link" else "figure",
                target,
                block.text,
                block.line,
                section,
                resolved,
                [_node_for(catalog, c) for c in cands],
                False,
                confidence,
                evidence,
            )
        elif block.kind == "include" and target:
            exts = INCLUDE_EXTS.get(block.extra.get("command", ""), ("",))
            resolved_key, cands, evidence = _resolve_path(catalog, key, target, exts)
            add(
                "include",
                target,
                target,
                block.line,
                section,
                _node_for(catalog, resolved_key) if resolved_key else None,
                [_node_for(catalog, c) for c in cands],
                False,
                "high" if resolved_key else None,
                evidence,
            )
        elif block.kind == "ref" and target:
            if block.extra.get("ref_kind") == "footnote":
                add(
                    "footnote",
                    target,
                    block.text,
                    block.line,
                    section,
                    own_doc,
                    [],
                    False,
                    "high",
                    "footnote",
                )
                continue
            owners = catalog.labels.get(target, [])
            same = [o for o in owners if o[0] == key]
            chosen = same[0] if len(same) == 1 else (owners[0] if len(owners) == 1 else None)
            if chosen:
                resolved = chosen[1] or doc_id(chosen[0])
                add(
                    "crossref",
                    target,
                    block.text,
                    block.line,
                    section,
                    resolved,
                    [],
                    False,
                    "high",
                    "label",
                )
            else:
                cands = [o[1] or doc_id(o[0]) for o in owners]
                add(
                    "crossref",
                    target,
                    block.text,
                    block.line,
                    section,
                    None,
                    cands,
                    False,
                    None,
                    "label-ambiguous" if cands else "label-unresolved",
                )
        elif block.kind == "citation" and target:
            add(
                "citation",
                target,
                block.text,
                block.line,
                section,
                None,
                [],
                True,
                None,
                "no-bibliography",
            )
        elif block.kind in ("paragraph", "list_item", "table"):
            for url in urls_in(block.text):
                add("url", url, url, block.line, section, None, [], True, None, "url-in-text")
            for path in paths_in(block.text):
                if (path, section) in seen_paths:
                    continue
                seen_paths.add((path, section))
                resolved_key, cands, evidence = _resolve_path(catalog, key, path)
                if resolved_key or cands:
                    add(
                        "path",
                        path,
                        path,
                        block.line,
                        section,
                        _node_for(catalog, resolved_key) if resolved_key else None,
                        [_node_for(catalog, c) for c in cands],
                        False,
                        "medium"
                        if evidence in ("path", "path-parent")
                        else ("low" if resolved_key else None),
                        evidence,
                    )
    return rows


LABEL_RE = re.compile(r"^\s*$")


def collect_labels(
    tree: DocumentTree, key: str, structure: Structure
) -> dict[str, list[tuple[str, str | None]]]:
    labels: dict[str, list[tuple[str, str | None]]] = {}
    for idx, block in enumerate(tree.blocks):
        if block.kind == "label" and block.target:
            section = structure.block_section[idx] if idx < len(structure.block_section) else None
            labels.setdefault(block.target, []).append((key, section))
    return labels
