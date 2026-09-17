# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

import random

from contextmax.graph.layout import (
    clustered_layout,
    find_back_edges,
    layered_layout,
    rank_nodes,
    subdivide_clusters,
)


def test_back_edges_break_cycles_and_ranks_are_longest_paths():
    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("a", "d"), ("d", "c")]
    out = {"a": ["b", "d"], "b": ["c"], "c": ["a"], "d": ["c"]}
    assert find_back_edges(nodes, out) == {("c", "a")}
    rank, back = rank_nodes(nodes, edges)
    assert back == {("c", "a")}
    assert rank == {"a": 0, "b": 1, "d": 1, "c": 2}


def test_layered_layout_is_order_independent():
    nodes = [f"n{i}" for i in range(40)]
    edges = [(f"n{i}", f"n{(i * 7 + 3) % 40}") for i in range(40)] + [
        (f"n{i}", f"n{i + 1}") for i in range(0, 39, 3)
    ]
    base = layered_layout(nodes, edges)
    for seed in range(5):
        rng = random.Random(seed)
        shuffled_nodes = nodes[:]
        rng.shuffle(shuffled_nodes)
        shuffled_edges = edges[:]
        rng.shuffle(shuffled_edges)
        other = layered_layout(shuffled_nodes, shuffled_edges)
        assert other.positions == base.positions
        assert other.ranks == base.ranks
    assert set(base.positions) == set(nodes)
    assert base.width > 0 and base.height > 0


def test_deep_chain_does_not_recurse():
    nodes = [f"c{i}" for i in range(5000)]
    edges = [(f"c{i}", f"c{i + 1}") for i in range(4999)]
    layout = layered_layout(nodes, edges)
    assert layout.ranks["c4999"] == 4999
    assert not layout.back_edges


def test_subdivide_clusters_splits_by_path_segments():
    members = {"src": [f"src/{a}/{b}/f{i}" for a in "ab" for b in "xy" for i in range(20)]}
    keys_of = lambda m: m.split("/")[:-1]  # noqa: E731
    result = subdivide_clusters(members, keys_of, max_cluster=30)
    assert all(len(v) <= 30 for v in result.values())
    assert sum(len(v) for v in result.values()) == 80
    assert set(result) == {"src / a / x", "src / a / y", "src / b / x", "src / b / y"}


def test_clustered_layout_places_every_node_inside_its_box():
    nodes = [f"m{i}" for i in range(50)]
    cluster_of = {n: f"grp{int(n[1:]) % 3}" for n in nodes}
    edges = [(f"m{i}", f"m{(i + 5) % 50}") for i in range(50)]
    result = clustered_layout(nodes, edges, cluster_of, max_cluster=60)
    boxes = {b["id"]: b for b in result["clusters"]}
    for node, (x, y) in result["positions"].items():
        box = boxes[cluster_of[node]]
        assert box["x"] <= x <= box["x"] + box["w"]
        assert box["y"] <= y <= box["y"] + box["h"]
    assert result["cluster_edges"] and result["width"] > 0
    again = clustered_layout(
        list(reversed(nodes)), list(reversed(edges)), cluster_of, max_cluster=60
    )
    assert again["positions"] == result["positions"]
