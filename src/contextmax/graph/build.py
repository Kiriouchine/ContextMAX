# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Stage 5: graph/graph.json, the data behind every HTML view, laid out deterministically."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from contextmax.graph.layout import clustered_layout, layered_layout
from contextmax.io.canon import parent_key
from contextmax.io.jsonl import read_jsonl, write_json
from contextmax.model.ids import mod_id


def _load(layout, name: str) -> list[dict[str, Any]]:
    path = layout.index / name
    return read_jsonl(path) if path.is_file() else []


def module_of(file_key: str) -> str:
    folder = parent_key(file_key)
    return folder or "."


def run_graph_stage(ctx) -> dict[str, Any]:
    layout = ctx.layout
    max_full = int(ctx.config.data["graph"]["max_full_nodes"])
    max_cluster = int(ctx.config.data["graph"]["max_cluster"])
    symbols = [s for s in _load(layout, "nodes/symbols.jsonl") if s["kind"] != "region"]
    calls = [
        c for c in _load(layout, "edges/calls.jsonl") if c["status"] == "resolved" and c["dst"]
    ]
    documents = _load(layout, "nodes/documents.jsonl")
    links = _load(layout, "edges/links.jsonl")
    sections = _load(layout, "nodes/sections.jsonl")

    mod_of_sym = {s["id"]: mod_id(module_of(s["file"])) for s in symbols}
    doc_by_id = {d["id"]: d for d in documents}
    doc_of_section = {s["id"]: s["doc"] for s in sections}

    # --- overview: modules and document folders --------------------------------------------
    module_size: dict[str, int] = defaultdict(int)
    for s in symbols:
        module_size[mod_of_sym[s["id"]]] += 1
    module_edges: dict[tuple[str, str], int] = defaultdict(int)
    for c in calls:
        ms, md = mod_of_sym.get(c["src"]), mod_of_sym.get(c["dst"])
        if ms and md and ms != md:
            module_edges[(ms, md)] += c.get("count", 1)
    docgroup_size: dict[str, int] = defaultdict(int)
    for d in documents:
        docgroup_size[f"docs:{module_of(d['file'])}"] += 1
    docgroup_edges: dict[tuple[str, str], int] = defaultdict(int)
    for e in links:
        if e["rel"] == "mentions_symbol" and e["status"] == "resolved" and e["dst"] in mod_of_sym:
            doc = doc_of_section.get(e["src"]) or e["src"]
            if doc in doc_by_id:
                docgroup_edges[
                    (f"docs:{module_of(doc_by_id[doc]['file'])}", mod_of_sym[e["dst"]])
                ] += 1
    overview_nodes = sorted(set(module_size) | set(docgroup_size))
    overview_edges = sorted({**dict(module_edges), **docgroup_edges}.items())
    ov_layout = layered_layout(overview_nodes, [k for k, _ in overview_edges])
    overview = {
        "nodes": [
            {
                "id": n,
                "label": n.split(":", 1)[1] if ":" in n else n,
                "kind": "docs" if n.startswith("docs:") else "module",
                "size": docgroup_size.get(n, module_size.get(n, 0)),
                "x": round(ov_layout.positions[n][0], 1),
                "y": round(ov_layout.positions[n][1], 1),
            }
            for n in overview_nodes
        ],
        "edges": [{"source": s, "target": d, "weight": w} for (s, d), w in overview_edges],
        "width": ov_layout.width,
        "height": ov_layout.height,
    }

    # --- code_full: every symbol, clustered by folder, capped by degree then id ---------------
    degree: dict[str, int] = defaultdict(int)
    for c in calls:
        degree[c["src"]] += 1
        degree[c["dst"]] += 1
    ranked = sorted(symbols, key=lambda s: (-degree.get(s["id"], 0), s["id"]))
    kept = ranked[:max_full]
    kept_ids = {s["id"] for s in kept}
    code_edges = [
        (c["src"], c["dst"]) for c in calls if c["src"] in kept_ids and c["dst"] in kept_ids
    ]
    code_layout = clustered_layout(
        sorted(kept_ids), code_edges, {s["id"]: module_of(s["file"]) for s in kept}, max_cluster
    )
    callers_count: dict[str, int] = defaultdict(int)
    callees_count: dict[str, int] = defaultdict(int)
    for c in calls:
        callers_count[c["dst"]] += 1
        callees_count[c["src"]] += 1
    code_full = {
        "nodes": [
            {
                "id": s["id"],
                "label": s["name"] if s["qualname"] == "(file)" else s["qualname"],
                "kind": s["kind"],
                "cluster": module_of(s["file"]),
                "file": s["file"],
                "line": s["span"]["start"],
                "role": s["role"],
                "tier": s["tier"],
                "callers": callers_count.get(s["id"], 0),
                "callees": callees_count.get(s["id"], 0),
                "x": round(code_layout["positions"][s["id"]][0], 1),
                "y": round(code_layout["positions"][s["id"]][1], 1),
            }
            for s in sorted(kept, key=lambda s: s["id"])
        ],
        "edges": [{"source": s, "target": d} for s, d in sorted(set(code_edges))],
        "clusters": code_layout["clusters"],
        "cluster_edges": code_layout["cluster_edges"],
        "width": code_layout["width"],
        "height": code_layout["height"],
        "cell": code_layout["cell"],
        "truncated": len(symbols) - len(kept),
        "selection_rule": "highest degree first, then id",
    }

    # --- docs_full: documents, edges from links between them ---------------------------------
    doc_edges: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in links:
        if e["rel"] not in ("links", "crossref", "cites", "mentions_file") or not e["dst"]:
            continue
        src_doc = doc_of_section.get(e["src"]) or e["src"]
        dst = e["dst"]
        dst_doc = dst.split("#", 1)[0] if dst.startswith("doc:") else dst
        if dst_doc.startswith("file:"):
            maybe = "doc:" + dst_doc[5:]
            dst_doc = maybe if maybe in doc_by_id else dst_doc
        if src_doc in doc_by_id and dst_doc in doc_by_id and src_doc != dst_doc:
            doc_edges[(src_doc, dst_doc)][e["rel"]] += 1
    doc_nodes = sorted(doc_by_id)
    dl = clustered_layout(
        doc_nodes,
        sorted(doc_edges),
        {d: module_of(doc_by_id[d]["file"]) for d in doc_nodes},
        max_cluster,
    )
    docs_full = {
        "nodes": [
            {
                "id": d,
                "label": doc_by_id[d]["title"][:60],
                "file": doc_by_id[d]["file"],
                "format": doc_by_id[d]["format"],
                "cluster": module_of(doc_by_id[d]["file"]),
                "sections": doc_by_id[d]["n_sections"],
                "words": doc_by_id[d]["n_words"],
                "x": round(dl["positions"][d][0], 1),
                "y": round(dl["positions"][d][1], 1),
            }
            for d in doc_nodes
        ],
        "edges": [
            {"source": s, "target": d, "kinds": dict(sorted(k.items())), "weight": sum(k.values())}
            for (s, d), k in sorted(doc_edges.items())
        ],
        "clusters": dl["clusters"],
        "cluster_edges": dl["cluster_edges"],
        "width": dl["width"],
        "height": dl["height"],
    }

    # --- links: document <-> module bipartite ---------------------------------------------
    bip: dict[tuple[str, str], int] = defaultdict(int)
    for e in links:
        if e["rel"] == "mentions_symbol" and e["status"] == "resolved" and e["dst"] in mod_of_sym:
            doc = doc_of_section.get(e["src"]) or e["src"]
            if doc in doc_by_id:
                bip[(doc, mod_of_sym[e["dst"]])] += e.get("count", 1)
    graph = {
        "schema_version": 1,
        "overview": overview,
        "code_full": code_full,
        "docs_full": docs_full,
        "links": {
            "edges": [{"source": s, "target": d, "weight": w} for (s, d), w in sorted(bip.items())]
        },
        "counts": {
            "symbols": len(symbols),
            "calls": len(calls),
            "documents": len(documents),
            "links": len(links),
        },
    }
    ctx.artifacts["graph/graph.json"] = write_json(layout.graph_dir / "graph.json", graph)
    ctx.log(
        f"  overview {len(overview_nodes)} nodes / {len(overview_edges)} edges; code {len(kept)} of {len(symbols)} symbols drawn; "
        f"docs {len(doc_nodes)} nodes / {len(doc_edges)} edges; {len(bip)} doc-module links"
    )
    return {
        "overview_nodes": len(overview_nodes),
        "code_nodes": len(kept),
        "code_truncated": len(symbols) - len(kept),
        "doc_nodes": len(doc_nodes),
        "doc_edges": len(doc_edges),
        "doc_module_links": len(bip),
    }
