# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Query API and `cmx q` on the built corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextmax.cli import main
from contextmax.io.jsonl import read_jsonl
from contextmax.query.api import QueryError, open_index


@pytest.fixture
def index(built: Path):
    idx = open_index(str(built))
    yield idx
    idx.con.close()


def test_status_and_search(index):
    st = index.status()
    assert st["completeness"]["verdict"] == "full"
    assert st["coverage"]["code"]["n_symbols"] > 10
    hits = index.search("servo")
    assert hits["n"] >= 2
    kinds = {h["kind"] for h in hits["hits"]}
    assert "section" in kinds or "document" in kinds
    assert all(h["cite"] for h in hits["hits"])


def test_symbol_callers_callees_and_documents(index):
    sym = index.symbol("gain_sched")
    assert sym["symbol"]["cite"].startswith("matlab/gain_sched.m:")
    assert [c["qualname"] for c in sym["callers"]] == ["run_all"]
    assert [c["qualname"] for c in sym["callees"]] == ["lookup_gain"]
    assert any(d["title"] == "Introduction" for d in sym["documents"])
    walk = index.callers("lookup_gain", depth=None)
    assert walk["n_direct"] == 1 and walk["n_total"] == 2
    assert [(n["qualname"], n["hops"]) for n in walk["nodes"]] == [
        ("gain_sched", 1),
        ("run_all", 2),
    ]
    impact = index.impact("lookup_gain")
    assert impact["upstream"]["n_total"] == 2 and impact["downstream"]["n_total"] == 0


def test_ambiguous_name_is_reported(index):
    with pytest.raises(QueryError) as info:
        index.symbol("objfun_that_does_not_exist")
    assert "nothing matches" in str(info.value)


def test_file_deps_and_document_outline(index):
    f = index.file("src/native/util.c")
    assert [s["qualname"] for s in f["symbols"]] == ["SQUARE", "helper_c", "util_sum"]
    assert any(d["file"] == "file:src/native/core.c" for d in f["depends_on"])
    deps = index.deps("src/native/core.h", reverse=True)
    assert any(d["file"] == "file:src/native/util.c" for d in deps["files"])
    doc = index.document("docs/guide.tex")
    assert doc["document"]["title"] == "GPS Guide"
    assert [s["title"] for s in doc["outline"]] == ["Introduction", "Setup", "Method"]
    assert doc["references_summary"].get("citation resolved") == 1  # \cite{ublox2011} -> refs.bib
    assert "sym:matlab/gain_sched.m#gain_sched" in doc["symbols_mentioned"]
    sec = index.section("doc:docs/guide.tex#introduction", with_text=True)
    assert sec["text"].startswith("### Introduction") or sec["text"].startswith("# Introduction")
    assert "ublox2011" in sec["text"]


def test_related_explain_skipped_and_source(index):
    rel = index.related("doc:docs/guide.tex#method")
    assert any(k.startswith("crossref:out") for k in rel["relations"])
    ex = index.explain("sym:matlab/run_all.m#(file)", "sym:matlab/gain_sched.m#gain_sched")
    assert ex["n"] == 1 and ex["edges"][0]["rel"] == "calls"
    sk = index.skipped("grammar")
    assert sk["n"] > 0 and all("grammar" in r["reason_code"] for r in sk["rows"])
    src = index.source("gain_sched")
    assert src["cite"] == "matlab/gain_sched.m:1-7"
    assert src["lines"][0]["text"].startswith("function [K, Ki] = gain_sched")
    ranged = index.source("src/app/main.py:4-5")
    assert [line["n"] for line in ranged["lines"]] == [4, 5]


def test_links_edges_are_graded(built: Path):
    links = read_jsonl(built / ".contextmax" / "edges" / "links.jsonl")
    rels = {e["rel"] for e in links}
    assert {"links", "crossref", "mentions_symbol", "mentions_file", "depends_on"} <= rels
    mention = next(
        e
        for e in links
        if e["rel"] == "mentions_symbol" and e["dst"] == "sym:matlab/gain_sched.m#gain_sched"
    )
    assert mention["confidence"] in ("low", "medium", "high")
    assert all(
        e["confidence"] in ("low", "medium", "high") for e in links if e["status"] == "resolved"
    )


def test_graph_json_is_consistent(built: Path):
    graph = json.loads((built / ".contextmax" / "graph" / "graph.json").read_text(encoding="utf-8"))
    assert graph["code_full"]["truncated"] == 0
    ids = {n["id"] for n in graph["code_full"]["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["code_full"]["edges"])
    assert graph["counts"]["symbols"] == len(ids)
    assert graph["overview"]["nodes"] and all(
        "x" in n and "y" in n for n in graph["overview"]["nodes"]
    )


def test_cli_q_json_and_exit_codes(built: Path, capsys):
    assert main(["q", "search", "kalman", "--root", str(built), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n"] >= 1
    assert main(["q", "symbol", "does-not-exist-anywhere", "--root", str(built), "--json"]) == 1
    assert "nothing matches" in capsys.readouterr().err
    assert main(["q", "outline", "docs/guide.tex", "--root", str(built), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["n_sections"] == 3


def test_store_rebuilds_when_index_changes(built: Path):
    idx = open_index(str(built))
    first = idx.con.execute(
        "select value from meta where key = 'artifact_identity_hash'"
    ).fetchone()[0]
    idx.con.close()
    (built / "docs" / "extra.md").write_text(
        "# Extra\n\nA brand new document about kalman filters.\n", encoding="utf-8"
    )
    assert main(["index", "--root", str(built), "--quiet"]) == 0
    idx = open_index(str(built))
    second = idx.con.execute(
        "select value from meta where key = 'artifact_identity_hash'"
    ).fetchone()[0]
    assert second != first
    assert idx.find_document("extra")["n"] == 1
    idx.con.close()
