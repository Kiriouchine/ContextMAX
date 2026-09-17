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
from contextmax.docs import bibliography as bibliography_module
from contextmax.docs import params as params_module
from contextmax.docs import refs as refs_module
from contextmax.docs import structure as structure_module
from contextmax.docs import terms as terms_module
from contextmax.docs.base import DocumentTree, ExtractionError
from contextmax.fs import os_path
from contextmax.io.atomic import atomic_write_text
from contextmax.io.hash import sha256_bytes
from contextmax.io.jsonl import write_jsonl
from contextmax.model.ids import doc_id, ref_id
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
    doc_cfg = ctx.config.data.get("documents", {})
    units_extra = list(doc_cfg.get("units_extra", []))
    sheet = adapter_registry.get("sheet-v1")
    if sheet is not None:  # bounds and units come from the project's config
        sheet.max_rows = int(doc_cfg.get("sheet_max_rows", 400))
        sheet.max_cols = int(doc_cfg.get("sheet_max_cols", 64))
        sheet.units_extra = units_extra
    candidates = [row for row in files if _wants_document(row)]
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
    bibentries: dict[str, list[str]] = defaultdict(list)
    for row, tree, _structure in trees:
        for bib_key, ids in refs_module.collect_bibentries(tree, row["file"]).items():
            bibentries[bib_key].extend(ids)
    # Titles, file stems and BibTeX DOIs/titles: what parsed bibliographies can resolve to.
    doc_titles: dict[str, list[str]] = defaultdict(list)
    doc_stems: dict[str, str] = {}
    bib_dois: dict[str, str] = {}
    bib_titles: dict[str, str] = {}
    for row, tree, _structure in trees:
        title_key = bibliography_module.norm_title(tree.title or "")
        if title_key and len(title_key.split()) >= 2:
            doc_titles[title_key].append(row["file"])
        doc_stems[row["file"]] = bibliography_module.norm_stem(row["file"])
        for idx, ref_key in refs_module.bibentry_ids(tree, row["file"]):
            block = tree.blocks[idx]
            rid = ref_id(row["file"], ref_key)
            doi = (block.extra.get("doi") or "").lower().rstrip(".")
            if doi:
                bib_dois.setdefault(doi, rid)
            entry_title = bibliography_module.norm_title(block.extra.get("title") or "")
            if entry_title:
                bib_titles.setdefault(entry_title, rid)
    catalog = refs_module.Catalog(
        files=all_keys,
        documents={row["file"] for row, _, _ in trees},
        labels=dict(labels),
        bibentries={k: sorted(v) for k, v in bibentries.items()},
        titles={k: sorted(v) for k, v in doc_titles.items()},
    )
    # Terms need the whole corpus (document frequencies) before any document row is written.
    section_cites: dict[str, str] = {}
    for row, tree, structure in trees:
        for s in structure.sections:
            section_cites[s.id] = section_cite(
                row["file"], s, tree.metadata.get("page_unit", "page"), tree.metadata.get("line_unit", "line")
            )
    term_rows, terms_per_doc, terms_top = terms_module.build_terms(
        [(row["file"], tree, structure) for row, tree, structure in trees],
        section_cites,
        list(doc_cfg.get("stopwords_extra", [])),
        int(doc_cfg.get("terms_cap", 40)),
    )
    term_notes = {n["doc"]: n["notes"] for n in terms_top.pop("__notes__", [])}

    layout = ctx.layout
    doc_rows: list[dict[str, Any]] = []
    section_rows: list[dict[str, Any]] = []
    ref_rows: list[dict[str, Any]] = []
    param_rows: list[dict[str, Any]] = []
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
        refs += bibliography_module.parse_bibliography(
            tree, key, structure, dict(doc_titles), doc_stems, bib_dois, bib_titles
        )
        ref_rows.extend(refs)
        own = doc_id(key)
        doc_params = params_module.cell_parameters(tree, key, structure)
        doc_params += params_module.prose_quantities(tree, key, structure, units_extra)
        param_rows.extend(doc_params)
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
                "n_parameters": len(doc_params),
                "n_terms": terms_per_doc.get(own, 0),
                "toc": structure.toc,
                "toc_source": tree.metadata.get("toc_source", "derived"),
                "scan_detected": bool(tree.metadata.get("scan_detected")),
                "metadata": {k: v for k, v in sorted(tree.metadata.items()) if k not in ("toc_source", "scan_detected")},
                "pages": tree.pages,
                "language_hint": None,
                "text_file": f"text/{cache_name}",
                "text_sha256": text_sha,
                "notes": tree.notes + tree.errors + term_notes.get(own, []),
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
                    "page": s.page,
                    "end_page": s.end_page,
                    "cite": section_cite(
                        key,
                        s,
                        tree.metadata.get("page_unit", "page"),
                        tree.metadata.get("line_unit", "line"),
                    ),
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
    ctx.artifacts["nodes/parameters.jsonl"] = write_jsonl(
        layout.nodes / "parameters.jsonl", param_rows
    )
    ctx.artifacts["nodes/terms.jsonl"] = write_jsonl(layout.nodes / "terms.jsonl", term_rows)
    ctx.artifacts["text/index.jsonl"] = write_jsonl(layout.text_dir / "index.jsonl", text_index)
    docmap = render_docmap(doc_rows, section_rows, ref_rows, param_rows, terms_top)
    ctx.artifacts["DOCMAP.md"] = sha256_bytes(atomic_write_text(layout.index / "DOCMAP.md", docmap))
    ctx.extra_skipped.extend(extra_skipped)
    for problem in problems:
        ctx.problems.append(f"documents: {problem}")
    n_ext = sum(1 for r in ref_rows if r["external"])
    n_unres = sum(1 for r in ref_rows if not r["external"] and r["resolved"] is None)
    by_source: dict[str, int] = defaultdict(int)
    for p in param_rows:
        by_source[p["source_kind"]] += 1
    ctx.log(
        f"  {len(doc_rows)} documents, {len(section_rows)} sections, {n_words} words; {len(ref_rows)} references: "
        f"{len(ref_rows) - n_ext - n_unres} resolved, {n_ext} external, {n_unres} unresolved; "
        f"{len(param_rows)} parameters ({', '.join(f'{k} {v}' for k, v in sorted(by_source.items())) or 'none'}); "
        f"{len(term_rows)} terms ({sum(1 for t in term_rows if t['method'] != 'keyphrase')} defined or headings); "
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
        "n_parameters": len(param_rows),
        "n_parameters_by_source": dict(sorted(by_source.items())),
        "n_terms": len(term_rows),
        "n_terms_defined": sum(1 for t in term_rows if t["method"] in ("acronym", "defined", "glossary", "macro")),
        "n_words": n_words,
        "n_extraction_failures": len(extra_skipped),
        "by_adapter": dict(sorted(by_adapter.items())),
        "by_determinism": dict(sorted(by_determinism.items())),
        "adapters": adapters_used,
    }


def _wants_document(row: dict[str, Any]) -> bool:
    """Readable documents and data files, plus images (catalogued with their dimensions)."""
    adapter = row.get("adapter")
    if not adapter_registry.implemented(adapter):
        return False
    if row["content_family"] in DOC_FAMILIES and row["tier"] in ("A", "C"):
        return True
    return adapter == "image-v1" and row["tier"] == "D"


def page_span(page: int, end_page: int | None, unit: str) -> str:
    """`p.12`, `p.12-15`, `slide 3`, `chapter 2-4` depending on the document's page unit."""
    prefix = "p." if unit == "page" else f"{unit} "
    if end_page and end_page != page:
        return f"{prefix}{page}-{end_page}"
    return f"{prefix}{page}"


def section_cite(
    key: str, s: structure_module.Section, page_unit: str = "page", line_unit: str = "line"
) -> str:
    where = s.number or s.path
    if s.page:
        return f"{key} {page_span(s.page, s.end_page, page_unit)} §{where}"
    if line_unit == "paragraph":
        span = f"¶{s.line}" if s.end_line == s.line else f"¶{s.line}-{s.end_line}"
        return f"{key} {span} §{where}"
    return f"{key}:{s.line}-{s.end_line} §{where}"


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
    params: list[dict[str, Any]] | None = None,
    terms_top: dict[str, list[dict[str, Any]]] | None = None,
    cap_sections: int = 200,
) -> str:
    by_doc_sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in sections:
        by_doc_sections[s["doc"]].append(s)
    by_doc_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in refs:
        by_doc_refs[r["doc"]].append(r)
    by_doc_params: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in params or []:
        by_doc_params[p["doc"]].append(p)
    lines = [
        "# Document map",
        "",
        "Generated by ContextMAX. Outlines are derived from headings; references are resolved against the",
        "project where possible and listed as external or unresolved otherwise. Verify at the cited lines.",
        "",
    ]
    images = [d for d in docs if d["adapter"] == "image-v1"]
    if images:
        lines += [
            f"{len(images)} images catalogued with their dimensions (no text, no OCR); see "
            "`nodes/documents.jsonl` rows with adapter `image-v1`.",
            "",
        ]
    for doc in sorted(docs, key=lambda d: d["file"]):
        if doc["adapter"] == "image-v1":
            continue
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
                f"{indent}- {number}{s['title']} (`{s['cite']}`, {s['n_words']} words)"
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
        params_here = by_doc_params.get(doc["id"], [])
        if params_here:
            labels = sorted({p["label"] for p in params_here})
            shown = ", ".join(f"`{x}`" for x in labels[:12]) + (" …" if len(labels) > 12 else "")
            lines += ["", f"Parameters: {len(params_here)} ({shown}); values in `nodes/parameters.jsonl`, `cmx q param <label>`"]
        terms_here = (terms_top or {}).get(doc["id"], [])
        if terms_here:
            defined = [t for t in terms_here if t["method"] in ("acronym", "defined", "glossary", "macro")]
            keyphrases = [t for t in terms_here if t["method"] == "keyphrase"]
            bits = []
            if defined:
                bits.append("defined: " + ", ".join(f"`{t['name']}`" + (f" ({t['acronym']})" if t["acronym"] and t["acronym"] != t["name"] else "") for t in defined[:10]) + (" …" if len(defined) > 10 else ""))
            if keyphrases:
                bits.append("keyphrases: " + ", ".join(f"`{t['name']}`" for t in keyphrases[:8]) + (" …" if len(keyphrases) > 8 else ""))
            lines += ["", f"Terms: {doc.get('n_terms', len(terms_here))} (" + "; ".join(bits) + "); `cmx q term <name>`"]
        lines.append("")
    return "\n".join(lines)
