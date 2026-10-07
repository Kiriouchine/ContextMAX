"""Deterministic layered layout: the same graph always gets the same picture.

Cycles are broken by a depth-first search in sorted order, each node goes to the column of its
longest path from a root (so arrows point right), and four barycentre passes order each column
to reduce crossings. No randomness, no physics, ties broken by name.
"""
from __future__ import annotations

from collections import defaultdict, deque

PASSES = 4


def adjacency(nodes, edges):
    out, inc = defaultdict(set), defaultdict(set)
    known = set(nodes)
    for s, t in edges:
        if s in known and t in known and s != t:
            out[s].add(t)
            inc[t].add(s)
    return ({k: sorted(v) for k, v in out.items()}, {k: sorted(v) for k, v in inc.items()})


def back_edges(nodes, out_adj) -> set:
    colour = {n: 0 for n in nodes}
    found = set()
    for root in nodes:
        if colour[root]:
            continue
        stack = [(root, iter(out_adj.get(root, ())))]
        colour[root] = 1
        while stack:
            node, children = stack[-1]
            for child in children:
                if colour[child] == 1:
                    found.add((node, child))
                elif colour[child] == 0:
                    colour[child] = 1
                    stack.append((child, iter(out_adj.get(child, ()))))
                    break
            else:
                colour[node] = 2
                stack.pop()
    return found


def ranks(nodes, edges) -> tuple[dict, dict, dict]:
    """Longest path from a root, computed in topological order."""
    nodes = sorted(nodes)
    out_adj, _ = adjacency(nodes, edges)
    cyc = back_edges(nodes, out_adj)
    fwd = [(s, t) for s, t in edges if (s, t) not in cyc and s != t]
    out_adj, in_adj = adjacency(nodes, fwd)
    indeg = {n: len(in_adj.get(n, ())) for n in nodes}
    queue = deque(n for n in nodes if indeg[n] == 0)
    rank = {n: 0 for n in nodes}
    while queue:
        n = queue.popleft()
        for c in out_adj.get(n, ()):
            rank[c] = max(rank[c], rank[n] + 1)
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    return rank, out_adj, in_adj


def order(rank: dict, out_adj: dict, in_adj: dict) -> dict[int, list]:
    rows = defaultdict(list)
    for n in sorted(rank):
        rows[rank[n]].append(n)
    pos = {n: i for lvl in rows for i, n in enumerate(rows[lvl])}
    for step in range(PASSES):
        levels = sorted(rows) if step % 2 == 0 else sorted(rows, reverse=True)
        nb = in_adj if step % 2 == 0 else out_adj
        for lvl in levels:
            def order_key(n, nb=nb):
                linked = [pos[m] for m in nb.get(n, ()) if m in pos]
                return (round(sum(linked) / len(linked), 6) if linked else float(pos[n]), n)
            rows[lvl].sort(key=order_key)
            for i, n in enumerate(rows[lvl]):
                pos[n] = i
    return rows


def layered(nodes, edges, sizes: dict | None = None, gap_x: int = 120, gap_y: int = 40,
            default: tuple[int, int] = (160, 64)) -> dict:
    """Place nodes in columns by rank. sizes: node -> (w, h). Returns {node: (x, y, w, h)},
    each column's width set by its widest node, nodes centred in their column."""
    nodes = sorted(nodes)
    if not nodes:
        return {"pos": {}, "width": 0, "height": 0}
    sizes = sizes or {}
    rank, out_adj, in_adj = ranks(nodes, edges)
    rows = order(rank, out_adj, in_adj)
    # A column far taller than the picture is wide (many modules that do not call each other)
    # wraps into several narrower columns, in the same order, so the picture stays near square.
    area = sum((sizes.get(n, default)[0] + gap_x) * (sizes.get(n, default)[1] + gap_y) for n in nodes)
    limit = max(400, int(area ** 0.5 * 1.1))
    columns = []
    for lvl in sorted(rows):
        chunk, h_used = [], 0
        for n in rows[lvl]:
            h = sizes.get(n, default)[1]
            if chunk and h_used + h > limit:
                columns.append(chunk)
                chunk, h_used = [], 0
            chunk.append(n)
            h_used += h + gap_y
        if chunk:
            columns.append(chunk)
    col_w = [max(sizes.get(n, default)[0] for n in c) for c in columns]
    col_h = [sum(sizes.get(n, default)[1] for n in c) + gap_y * (len(c) - 1) for c in columns]
    height = max(col_h)
    pos, x = {}, 0
    for c, w_col, h_col in zip(columns, col_w, col_h, strict=True):
        y = (height - h_col) // 2
        for n in c:
            w, h = sizes.get(n, default)
            pos[n] = (x + (w_col - w) // 2, y, w, h)
            y += h + gap_y
        x += w_col + gap_x
    return {"pos": pos, "width": x - gap_x, "height": height, "rank": rank}
