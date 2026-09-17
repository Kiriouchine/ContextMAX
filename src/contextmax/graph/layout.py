# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Deterministic graph layout with no random source anywhere.

Layered layout: back edges found by a sorted iterative depth-first search are removed, ranks
are longest paths from the sources, nodes inside a rank are ordered by four fixed barycentre
passes with a stable sort and the id as tie-break. Cluster layout: nodes grouped by a key are
packed on a grid inside cluster boxes, boxes are ranked like a layered graph of clusters.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

X_SPACING = 210
Y_SPACING = 58
MARGIN = 40
CELL_W = 150
CELL_H = 22
CLUSTER_GAP_X = 120
CLUSTER_GAP_Y = 40
BARYCENTRE_PASSES = 4


@dataclass
class Layout:
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    ranks: dict[str, int] = field(default_factory=dict)
    width: float = 0
    height: float = 0
    back_edges: list[tuple[str, str]] = field(default_factory=list)


def build_adjacency(
    edges: list[tuple[str, str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    out: dict[str, set[str]] = defaultdict(set)
    inc: dict[str, set[str]] = defaultdict(set)
    for src, dst in edges:
        if src == dst:
            continue
        out[src].add(dst)
        inc[dst].add(src)
    return ({k: sorted(v) for k, v in out.items()}, {k: sorted(v) for k, v in inc.items()})


def find_back_edges(nodes: list[str], out: dict[str, list[str]]) -> set[tuple[str, str]]:
    """Iterative DFS in sorted order; an edge to a grey node is a back edge."""
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(nodes, white)
    back: set[tuple[str, str]] = set()
    for start in sorted(nodes):
        if colour[start] != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        colour[start] = grey
        while stack:
            node, idx = stack[-1]
            nbrs = out.get(node, [])
            if idx < len(nbrs):
                stack[-1] = (node, idx + 1)
                nxt = nbrs[idx]
                if nxt not in colour:
                    continue
                if colour[nxt] == white:
                    colour[nxt] = grey
                    stack.append((nxt, 0))
                elif colour[nxt] == grey:
                    back.add((node, nxt))
            else:
                colour[node] = black
                stack.pop()
    return back


def rank_nodes(
    nodes: list[str], edges: list[tuple[str, str]]
) -> tuple[dict[str, int], set[tuple[str, str]]]:
    out, _ = build_adjacency(edges)
    back = find_back_edges(nodes, out)
    forward = [(s, d) for s, d in edges if (s, d) not in back and s != d]
    out_f, inc_f = build_adjacency(forward)
    indeg = {n: len(inc_f.get(n, [])) for n in nodes}
    rank = dict.fromkeys(nodes, 0)
    queue = sorted(n for n in nodes if indeg[n] == 0)
    seen = 0
    while queue:
        node = queue.pop(0)
        seen += 1
        for nxt in out_f.get(node, []):
            if nxt not in indeg:
                continue
            rank[nxt] = max(rank[nxt], rank[node] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
                queue.sort()
    if seen < len(nodes):  # residual cycles (should not happen after back-edge removal)
        top = max(rank.values(), default=0) + 1
        for node in sorted(nodes):
            if indeg[node] > 0:
                rank[node] = top
    return rank, back


def layered_layout(nodes: list[str], edges: list[tuple[str, str]]) -> Layout:
    nodes = sorted(set(nodes))
    if not nodes:
        return Layout()
    rank, back = rank_nodes(nodes, edges)
    out, inc = build_adjacency([(s, d) for s, d in edges if (s, d) not in back])
    layers: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        layers[rank[node]].append(node)
    order = {r: sorted(members) for r, members in layers.items()}
    max_rank = max(order)
    for _ in range(BARYCENTRE_PASSES):
        for r in range(1, max_rank + 1):
            pos = {n: i for i, n in enumerate(order[r - 1])}
            order[r] = sorted(order[r], key=lambda n: (_bary(inc.get(n, []), pos), n))
        for r in range(max_rank - 1, -1, -1):
            pos = {n: i for i, n in enumerate(order[r + 1])}
            order[r] = sorted(order[r], key=lambda n: (_bary(out.get(n, []), pos), n))
    layout = Layout(ranks=rank, back_edges=sorted(back))
    tallest = max(len(m) for m in order.values())
    height = MARGIN * 2 + max(tallest - 1, 0) * Y_SPACING
    for r in range(max_rank + 1):
        members = order[r]
        offset = (tallest - len(members)) * Y_SPACING / 2
        for i, node in enumerate(members):
            layout.positions[node] = (MARGIN + r * X_SPACING, MARGIN + offset + i * Y_SPACING)
    layout.width = MARGIN * 2 + max_rank * X_SPACING
    layout.height = height
    return layout


def _bary(nbrs: list[str], pos: dict[str, int]) -> float:
    vals = [pos[n] for n in nbrs if n in pos]
    return sum(vals) / len(vals) if vals else 1e9


def subdivide_clusters(
    members_by_cluster: dict[str, list[str]], keys_of, max_cluster: int, max_splits: int = 6
) -> dict[str, list[str]]:
    """Split any cluster larger than `max_cluster` along the next finer key of its members."""
    result: dict[str, list[str]] = {}
    for cluster, members in sorted(members_by_cluster.items()):
        if len(members) <= max_cluster:
            result[cluster] = sorted(members)
            continue
        splits = 0
        depth = 1
        groups = {cluster: sorted(members)}
        while splits < max_splits:
            changed = False
            new_groups: dict[str, list[str]] = {}
            for gname, gmembers in sorted(groups.items()):
                if len(gmembers) <= max_cluster:
                    new_groups[gname] = gmembers
                    continue
                buckets: dict[str, list[str]] = defaultdict(list)
                for m in gmembers:
                    keys = keys_of(m)
                    sub = keys[depth] if depth < len(keys) else "…"
                    buckets[f"{gname} / {sub}"].append(m)
                if len(buckets) <= 1:
                    new_groups[gname] = gmembers
                else:
                    new_groups.update({k: sorted(v) for k, v in buckets.items()})
                    changed = True
            groups = new_groups
            depth += 1
            if changed:
                splits += 1
            if not changed and depth > 12:
                break
            if not changed and depth > max(len(keys_of(m)) for m in members):
                break
        result.update(groups)
    return dict(sorted(result.items()))


def clustered_layout(
    nodes: list[str],
    edges: list[tuple[str, str]],
    cluster_of: dict[str, str],
    max_cluster: int = 60,
) -> dict[str, Any]:
    """Grid-pack members inside cluster boxes; rank the boxes as a layered graph of clusters."""
    nodes = sorted(set(nodes))
    members: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        members[cluster_of.get(node, "(root)")].append(node)
    members = subdivide_clusters(
        dict(members), lambda n: cluster_of.get(n, "(root)").split(" / "), max_cluster
    )
    node_cluster = {n: c for c, ms in members.items() for n in ms}
    cluster_edges: dict[tuple[str, str], int] = defaultdict(int)
    for s, d in edges:
        cs, cd = node_cluster.get(s), node_cluster.get(d)
        if cs and cd and cs != cd:
            cluster_edges[(cs, cd)] += 1
    cl_layout = layered_layout(sorted(members), sorted(cluster_edges))
    _, inc = build_adjacency(edges)
    boxes: dict[str, dict[str, Any]] = {}
    positions: dict[str, tuple[float, float]] = {}
    # Place cluster boxes on the layered grid with per-column widths.
    col_width: dict[int, float] = defaultdict(float)
    row_height: dict[str, float] = {}
    dims: dict[str, tuple[int, int]] = {}
    for cluster, ms in members.items():
        cols = max(1, int(len(ms) ** 0.5 + 0.999))
        rows = (len(ms) + cols - 1) // cols
        dims[cluster] = (cols, rows)
        rank = cl_layout.ranks.get(cluster, 0)
        col_width[rank] = max(col_width[rank], cols * CELL_W)
    col_x: dict[int, float] = {}
    x = MARGIN
    for rank in sorted(col_width):
        col_x[rank] = x
        x += col_width[rank] + CLUSTER_GAP_X
    y_cursor: dict[int, float] = defaultdict(lambda: MARGIN)
    ordered = sorted(
        members, key=lambda c: (cl_layout.ranks.get(c, 0), cl_layout.positions.get(c, (0, 0))[1], c)
    )
    for cluster in ordered:
        cols, rows = dims[cluster]
        rank = cl_layout.ranks.get(cluster, 0)
        bx, by = col_x[rank], y_cursor[rank]
        w, h = cols * CELL_W, rows * CELL_H + CELL_H
        boxes[cluster] = {
            "id": cluster,
            "x": bx,
            "y": by,
            "w": w,
            "h": h,
            "size": len(members[cluster]),
        }
        # Members with incoming edges sit in the left column so cross-cluster lines are short.
        ordered_members = sorted(members[cluster], key=lambda n: (0 if inc.get(n) else 1, n))
        for i, node in enumerate(ordered_members):
            c, r = i // rows, i % rows
            positions[node] = (bx + c * CELL_W + CELL_W / 2, by + CELL_H + r * CELL_H)
        y_cursor[rank] = by + h + CLUSTER_GAP_Y
        row_height[cluster] = h
    width = x
    height = max(y_cursor.values(), default=MARGIN) + MARGIN
    return {
        "positions": positions,
        "clusters": [boxes[c] for c in sorted(boxes)],
        "cluster_edges": [
            {"source": s, "target": d, "weight": w} for (s, d), w in sorted(cluster_edges.items())
        ],
        "width": width,
        "height": height,
        "cell": {"w": CELL_W, "h": CELL_H},
    }
