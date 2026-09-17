# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Stage 3: documents. Extract every readable document, build its outline, write the text
cache, then resolve references across the whole set (labels live in other files)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from contextmax.docs import adapters as adapter_registry
from contextmax.docs import refs as refs_module
from contextmax.docs import structure as structure_module
from contextmax.docs.base import DocumentTree, ExtractionError
from contextmax.fs import os_path
from contextmax.io.atomic import atomic_write_text
from contextmax.io.hash import sha256_bytes
from contextmax.io.jsonl import write_jsonl
from contextmax.model.ids import doc_id
from contextmax.model.nodes import skipped_row

DOC_FAMILIES = ("document", "text", "data")


def text_cache_name(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + ".txt"


def run_documents_stage(ctx) -> dict[str, Any]:
    assert ctx.discovery is not None
    from contextmax.discover import resolve_roots

    roots_of = {
        r.prefix: r.path for r in resolve_roots(ctx.root, ctx.config) if r.prefix.startswith("ext:")
    }
    files = ctx.discovery.files
    all_keys = {row["file"] for row in files}
    candidates = [
        row
        for row in files
        if row["content_family"] in DOC_FAMILIES
        and row["tier"] in ("A", "C")
        and adapter_registry.implemented(row.get("adapter"))
    ]
    trees: list[tuple[dict[str, Any], DocumentTree, structure_module.Structure]] = []
    problems: list[str] = []
    extra_skipped: list[dict[str, Any]] = []
    for row in candidates:
        adapter = adapter_registry.get(row["adapter"])
        assert adapter is not None
        path = _path_for(ctx.root, roots_of, row["file"])
        try:
            data = Path(os_path(path)).read_bytes()
            tree = adapter.extract(row["file"], data)
        except ExtractionError as exc:
            extra_skipped.append(
                skipped_row(
                    key=row["file"],
                    reason_code="extraction-failed",
                    reason=str(exc),
                    size=row["size"],
                    detected_as=row["format"],
                )
            )
            continue
        except Exception as exc:
            problems.append(
                f"{row['file']}: {row['adapter']} failed ({exc.__class__.__name__}: {exc})"
            )
            extra_skipped.append(
                skipped_row(
                    key=row["file"],
                    reason_code="extraction-failed",
                    reason=f"{row['adapter']}: {exc.__class__.__name__}",
                    size=row["size"],
                    detected_as=row["format"],
                )
            )
            continue
        structure = structure_module.build(tree, row["file"])
        trees.append((row, tree, structure))

    # Pass 2: labels across the whole set, then references.
    labels: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for row, tree, structure in trees:
        for label, owners in refs_module.collect_labels(tree, row["file"], structure).items():
            labels[label].extend(owners)
    catalog = refs_module.Catalog(
        files=all_keys, documents={row["file"] for row, _, _ in trees}, labels=dict(labels)
    )

    layout = ctx.layout
    doc_rows: list[dict[str, Any]] = []
    section_rows: list[dict[str, Any]] = []
    ref_rows: list[dict[str, Any]] = []
    text_index: list[dict[str, Any]] = []
    by_adapter: dict[str, int] = defaultdict(int)
    by_determinism: dict[str, int] = defaultdict(int)
    n_words = 0
    for row, tree, structure in trees:
        key = row["file"]
        cache_name = text_cache_name(key)
        text_bytes = atomic_write_text(layout.text_dir / cache_name, structure.text)
        text_sha = sha256_bytes(text_bytes)
        ctx.artifacts[f"text/{cache_name}"] = text_sha
        refs = refs_module.build_references(tree, key, structure, catalog)
        ref_rows.extend(refs)
        own = doc_id(key)
        doc_rows.append(
            {
                "id": own,
                "kind": "document",
                "family": "doc",
                "name": row["name"],
                "title": tree.title or row["name"],
                "file": key,
                "format": row["format"],
                "adapter": tree.adapter,
                "adapter_version": tree.adapter_version,
                "determinism": tree.determinism,
                "tier": row["tier"],
                "role": row["role"],
                "chars": len(structure.text),
                "n_lines": row.get("lines"),
                "n_words": structure.n_words,
                "n_sections": len(structure.sections),
                "n_tables": structure.tables,
                "n_figures": structure.figures,
                "n_footnotes": structure.footnotes,
                "n_code_blocks": structure.code_blocks,
                "n_references": len(refs),
                "toc": structure.toc,
                "toc_source": "derived",
                "pages": tree.pages,
                "language_hint": None,
                "text_file": f"text/{cache_name}",
                "text_sha256": text_sha,
                "notes": tree.notes + tree.errors,
                "cite": key,
            }
        )
        text_index.append(
            {"id": own, "file": key, "text_file": f"text/{cache_name}", "sha256": text_sha}
        )
        for s in structure.sections:
            section_rows.append(
                {
                    "id": s.id,
                    "kind": "section",
                    "family": "doc",
                    "name": s.title,
                    "title": s.title,
                    "doc": own,
                    "file": key,
                    "depth": s.depth,
                    "number": s.number,
                    "path": s.path,
                    "parent": s.parent,
                    "order": s.order,
                    "line": s.line,
                    "end_line": s.end_line,
                    "text_range": [s.text_start, s.text_end],
                    "n_words": s.n_words,
                    "n_blocks": s.n_blocks,
                    "preview": s.preview,
                    "cite": f"{key}:{s.line}-{s.end_line} §{s.number or s.path}",
                }
            )
        by_adapter[tree.adapter] += 1
        by_determinism[tree.determinism] += 1
        n_words += structure.n_words

    ctx.artifacts["nodes/documents.jsonl"] = write_jsonl(layout.nodes / "documents.jsonl", doc_rows)
    ctx.artifacts["nodes/sections.jsonl"] = write_jsonl(
        layout.nodes / "sections.jsonl", section_rows
    )
    ctx.artifacts["nodes/references.jsonl"] = write_jsonl(
        layout.nodes / "references.jsonl", ref_rows
    )
    ctx.artifacts["text/index.jsonl"] = write_jsonl(layout.text_dir / "index.jsonl", text_index)
    docmap = render_docmap(doc_rows, section_rows, ref_rows)
    ctx.artifacts["DOCMAP.md"] = sha256_bytes(atomic_write_text(layout.index / "DOCMAP.md", docmap))
    ctx.extra_skipped.extend(extra_skipped)
    for problem in problems:
        ctx.problems.append(f"documents: {problem}")
    n_ext = sum(1 for r in ref_rows if r["external"])
    n_unres = sum(1 for r in ref_rows if not r["external"] and r["resolved"] is None)
    ctx.log(
        f"  {len(doc_rows)} documents, {len(section_rows)} sections, {n_words} words; {len(ref_rows)} references: "
        f"{len(ref_rows) - n_ext - n_unres} resolved, {n_ext} external, {n_unres} unresolved; "
        f"{len(extra_skipped)} extraction failures"
    )
    adapters_used = {
        aid: {
            "version": adapter_registry.get(aid).version,
            "determinism": adapter_registry.get(aid).determinism,
            "n": count,
        }
        for aid, count in sorted(by_adapter.items())
    }
    return {
        "n_documents": len(doc_rows),
        "n_sections": len(section_rows),
        "n_references": len(ref_rows),
        "n_references_external": n_ext,
        "n_references_unresolved": n_unres,
        "n_words": n_words,
        "n_extraction_failures": len(extra_skipped),
        "by_adapter": dict(sorted(by_adapter.items())),
        "by_determinism": dict(sorted(by_determinism.items())),
        "adapters": adapters_used,
    }


def _path_for(root: Path, roots_of: dict[str, Path], key: str) -> Path:
    if key.startswith("ext:"):
        prefix, _, rest = key.partition("/")
        base = roots_of.get(prefix)
        if base is not None:
            return base / rest
    return root / key


def render_docmap(
    docs: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    cap_sections: int = 200,
) -> str:
    by_doc_sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in sections:
        by_doc_sections[s["doc"]].append(s)
    by_doc_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in refs:
        by_doc_refs[r["doc"]].append(r)
    lines = [
        "# Document map",
        "",
        "Generated by ContextMAX. Outlines are derived from headings; references are resolved against the",
        "project where possible and listed as external or unresolved otherwise. Verify at the cited lines.",
        "",
    ]
    for doc in sorted(docs, key=lambda d: d["file"]):
        lines += [
            f"## {doc['title']}",
            "",
            f"`{doc['file']}` · {doc['format']} · {doc['adapter']} ({doc['determinism']}) · "
            f"{doc['n_words']} words · {doc['n_sections']} sections · {doc['n_references']} references",
            "",
        ]
        secs = sorted(by_doc_sections.get(doc["id"], []), key=lambda s: s["order"])
        for s in secs[:cap_sections]:
            indent = "  " * (s["depth"] - 1)
            number = f"{s['number']} " if s["number"] else ""
            lines.append(
                f"{indent}- {number}{s['title']} (`{doc['file']}:{s['line']}`, {s['n_words']} words)"
            )
        if len(secs) > cap_sections:
            lines.append(f"- … {len(secs) - cap_sections} more sections in `nodes/sections.jsonl`")
        refs_here = by_doc_refs.get(doc["id"], [])
        if refs_here:
            counts: dict[str, int] = defaultdict(int)
            for r in refs_here:
                state = (
                    "resolved" if r["resolved"] else ("external" if r["external"] else "unresolved")
                )
                counts[f"{r['ref_kind']} {state}"] += 1
            lines += [
                "",
                "References: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
            ]
            unresolved = sorted(
                {r["raw"] for r in refs_here if not r["external"] and not r["resolved"]}
            )
            if unresolved:
                lines.append(
                    "Unresolved: "
                    + ", ".join(f"`{u}`" for u in unresolved[:20])
                    + (" …" if len(unresolved) > 20 else "")
                )
        lines.append("")
    return "\n".join(lines)
