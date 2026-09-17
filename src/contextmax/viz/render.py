# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Stage 8: offline HTML pages. One self-contained file each, data inlined and escaped so
document text can never close the script tag, no external URL anywhere, no timestamps so the
pages are part of the reproducible artifact set."""

from __future__ import annotations

import json
from collections import defaultdict
from importlib import resources
from typing import Any

from contextmax.io.atomic import atomic_write_text
from contextmax.io.hash import sha256_bytes
from contextmax.io.jsonl import read_json, read_jsonl
from contextmax.manifest import completeness
from contextmax.registry import formats, languages


def json_for_script(obj: Any) -> str:
    """JSON safe to inline inside <script>: no '</', no '<!--', no line separators."""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _asset(name: str) -> str:
    return (
        resources.files("contextmax.viz")
        .joinpath("assets")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _load(layout, name: str) -> list[dict[str, Any]]:
    path = layout.index / name
    return read_jsonl(path) if path.is_file() else []


PAGES = (
    ("index.html", "Overview", "index"),
    ("code.html", "Code map", "code"),
    ("docs.html", "Document map", "docs"),
)


def _shell(page: str, title: str, project: str, verdict: str, body: str, data: Any) -> str:
    nav = " ".join(f'<a href="{href}">{label}</a>' for href, label, _ in PAGES)
    banner = (
        f'<div class="banner {verdict}">Build completeness: <strong>{verdict}</strong>. '
        + (
            "Every implemented stage ran without error."
            if verdict == "full"
            else "A stage failed or was skipped; check build-state.json before trusting gaps."
        )
        + "</div>"
    )
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_esc(project)} · {title}</title>'
        f'<style>{_asset("app.css")}</style></head>\n<body data-page="{page}">'
        f'<header><h1>{_esc(project)}</h1><nav>{nav}</nav><span class="spacer"></span><span class="note">ContextMAX · offline · no model in the build</span></header>'
        f"{banner}{body}"
        f'<script id="data" type="application/json">{json_for_script(data)}</script>'
        f"<script>{_asset('app.js')}</script></body></html>\n"
    )


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def run_viz_stage(ctx) -> dict[str, Any]:
    layout = ctx.layout
    coverage = ctx.coverage or (read_json(layout.coverage) if layout.coverage.is_file() else {})
    verdict = completeness(ctx.state.data, coverage)["verdict"]
    project = ctx.config.name
    max_bytes = int(float(ctx.config.data["viz"]["max_page_mb"]) * 1024 * 1024)
    written: dict[str, int] = {}

    # --- index ---------------------------------------------------------------------------
    names = {
        "languages": {k: v["name"] for k, v in languages().items()},
        "formats": {k: v["name"] for k, v in formats().items()},
    }
    index_data = {"coverage": coverage, "names": names, "project": project}
    written["index.html"] = _write(
        ctx,
        layout.viz_dir / "index.html",
        _shell(
            "index",
            "Overview",
            project,
            verdict,
            '<main class="single"><div id="app"></div></main>',
            index_data,
        ),
    )

    # --- code ----------------------------------------------------------------------------
    graph = (
        read_json(layout.graph_dir / "graph.json")
        if (layout.graph_dir / "graph.json").is_file()
        else {}
    )
    symbols = [s for s in _load(layout, "nodes/symbols.jsonl") if s["kind"] != "region"]
    calls = [
        c for c in _load(layout, "edges/calls.jsonl") if c["status"] == "resolved" and c["dst"]
    ]
    links = _load(layout, "edges/links.jsonl")
    sections = _load(layout, "nodes/sections.jsonl")
    sec_by_id = {s["id"]: s for s in sections}
    mentions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    section_mentions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sym_label = {
        s["id"]: (s["name"] if s["qualname"] == "(file)" else s["qualname"]) for s in symbols
    }
    for e in links:
        if e["rel"] == "mentions_symbol" and e["status"] == "resolved" and e["dst"] in sym_label:
            sec = sec_by_id.get(e["src"])
            if sec:
                mentions[e["dst"]].append(
                    {
                        "section": sec["id"],
                        "title": sec["title"],
                        "cite": sec["cite"],
                        "confidence": e["confidence"],
                    }
                )
                section_mentions[sec["id"]].append(
                    {
                        "symbol": e["dst"],
                        "label": sym_label[e["dst"]],
                        "cite": e["dst"].split("#")[0][4:],
                        "confidence": e["confidence"],
                    }
                )
    code_full = graph.get("code_full", {})
    code_data = {
        "overview": graph.get("overview", {"nodes": [], "edges": [], "width": 0, "height": 0}),
        "symbols": [
            {
                "id": s["id"],
                "label": sym_label[s["id"]],
                "kind": s["kind"],
                "file": s["file"],
                "cite": s["cite"],
                "role": s["role"],
                "tier": s["tier"],
                "signature": s.get("signature"),
                "doc": s.get("doc"),
                "cluster": s["file"].rsplit("/", 1)[0] if "/" in s["file"] else ".",
            }
            for s in sorted(symbols, key=lambda s: s["id"])
        ],
        "calls": [
            {"source": c["src"], "target": c["dst"]}
            for c in sorted(calls, key=lambda c: (c["src"], c["dst"]))
        ],
        "mentions": dict(sorted(mentions.items())),
        "truncated": code_full.get("truncated", 0),
        "selection_rule": code_full.get("selection_rule", ""),
        "project": project,
    }
    code_body = (
        '<div class="toolbar"><input id="search" type="search" placeholder="search symbols or files"> '
        '<button id="overview-btn">Overview</button> <span class="note">hops:</span> '
        '<button data-depth="1" class="active">1</button><button data-depth="2">2</button><button data-depth="3">3</button><button data-depth="all">all</button></div>'
        '<main><div class="canvas" id="canvas"><svg></svg></div><aside class="panel"><div id="panel"></div><h2>Symbols</h2><ul class="list" id="symbol-list"></ul></aside></main>'
    )
    code_data = _trim(code_data, max_bytes, "symbols", "calls")
    written["code.html"] = _write(
        ctx,
        layout.viz_dir / "code.html",
        _shell("code", "Code map", project, verdict, code_body, code_data),
    )

    # --- docs ----------------------------------------------------------------------------
    documents = _load(layout, "nodes/documents.jsonl")
    references = _load(layout, "nodes/references.jsonl")
    parameters = _load(layout, "nodes/parameters.jsonl")
    params_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in parameters:
        params_by_doc[p["doc"]].append(
            {
                "label": p["label"],
                "display": p.get("display"),
                "unit": p.get("unit_norm") or p.get("unit"),
                "formula": p.get("formula"),
                "source_kind": p.get("source_kind"),
                "hidden": p.get("hidden"),
                "cite": p["cite"],
            }
        )
    ref_summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in references:
        state = (
            "resolved" if r.get("resolved") else ("external" if r.get("external") else "unresolved")
        )
        ref_summary[r["doc"]][f"{r['ref_kind']} {state}"] += 1
    doc_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    doc_of_section = {s["id"]: s["doc"] for s in sections}
    for e in links:
        if e["rel"] in ("links", "crossref", "mentions_file", "cites") and e["dst"]:
            doc = doc_of_section.get(e["src"], e["src"])
            target = e["dst"]
            page = None
            label = target
            if target.startswith("doc:"):
                base = target.split("#", 1)[0]
                page = f"docs.html#doc={base}" if "#" not in target else f"docs.html#sec={target}"
                label = target[4:]
            elif target.startswith("file:"):
                label = target[5:]
            doc_links[doc].append(
                {
                    "rel": e["rel"],
                    "label": label,
                    "target_page": page,
                    "confidence": e.get("confidence"),
                    "status": e.get("status"),
                }
            )
    docs_data = {
        "documents": [
            {
                "id": d["id"],
                "title": d["title"],
                "file": d["file"],
                "format": d["format"],
                "adapter": d["adapter"],
                "determinism": d["determinism"],
                "sections": d["n_sections"],
                "words": d["n_words"],
                "parameters": d.get("n_parameters", 0),
                "refs_summary": ", ".join(
                    f"{k} {v}" for k, v in sorted(ref_summary.get(d["id"], {}).items())
                )
                or None,
            }
            for d in sorted(documents, key=lambda d: d["file"])
        ],
        "sections": [
            {
                "id": s["id"],
                "doc": s["doc"],
                "title": s["title"],
                "depth": s["depth"],
                "number": s["number"],
                "cite": s["cite"],
                "preview": s["preview"],
            }
            for s in sorted(sections, key=lambda s: (s["doc"], s["order"]))
        ],
        "doc_links": {
            k: sorted(v, key=lambda r: (r["rel"], r["label"])) for k, v in sorted(doc_links.items())
        },
        "section_mentions": {
            k: sorted(v, key=lambda r: r["label"]) for k, v in sorted(section_mentions.items())
        },
        "parameters": {k: v[:100] for k, v in sorted(params_by_doc.items())},
        "project": project,
    }
    docs_body = (
        '<div class="toolbar"><input id="search" type="search" placeholder="search documents"></div>'
        '<main><div class="canvas" id="canvas"></div><aside class="panel"><div id="panel"></div><h2>Documents</h2><ul class="list" id="doc-list"></ul></aside></main>'
    )
    docs_data = _trim(docs_data, max_bytes, "sections", "section_mentions", "parameters")
    written["docs.html"] = _write(
        ctx,
        layout.viz_dir / "docs.html",
        _shell("docs", "Document map", project, verdict, docs_body, docs_data),
    )
    ctx.log("  " + ", ".join(f"{name} ({size // 1024} KB)" for name, size in written.items()))
    return {"pages": sorted(written), "bytes": written}


def _trim(data: dict[str, Any], max_bytes: int, *bulk_keys: str) -> dict[str, Any]:
    """Keep pages openable: drop the bulkiest lists when the payload exceeds the cap, and say so."""
    size = len(json_for_script(data).encode("utf-8"))
    if size <= max_bytes:
        return data
    trimmed = dict(data)
    for key in bulk_keys:
        trimmed[key] = [] if isinstance(trimmed.get(key), list) else {}
    trimmed["trimmed"] = (
        f"payload of {size // (1024 * 1024)} MB exceeded viz.max_page_mb; lists {', '.join(bulk_keys)} omitted from this page"
    )
    return trimmed


def _write(ctx, path, html: str) -> int:
    data = atomic_write_text(path, html)
    ctx.artifacts[f"viz/{path.name}"] = sha256_bytes(data)
    return len(data)
