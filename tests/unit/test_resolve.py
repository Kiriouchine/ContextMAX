# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from contextmax.code.lexical import analyze
from contextmax.code.resolve import resolve_project


def build(files: dict[str, tuple[str, str]]):
    analyses = [analyze(key, text, lang) for key, (lang, text) in sorted(files.items())]
    return resolve_project(
        analyses, dict.fromkeys(files, "product"), dict.fromkeys(files, "lexical-v1")
    )


def edges(result, rel="calls"):
    return {(e["src"], e["dst"], e["status"], e["evidence"]) for e in result[rel]}


def test_same_file_and_unique_name_resolution():
    result = build(
        {
            "a.py": ("python", "def f():\n    g()\n    h()\n\ndef g():\n    pass\n"),
            "b.py": ("python", "def h():\n    pass\n"),
        }
    )
    got = edges(result)
    assert ("sym:a.py#f", "sym:a.py#g", "resolved", "lexical:unique-name") in got
    assert ("sym:a.py#f", "sym:b.py#h", "resolved", "lexical:unique-name") in got


def test_ambiguity_is_recorded_with_candidates():
    result = build(
        {
            "a.py": ("python", "def dup():\n    pass\n"),
            "b.py": ("python", "def dup():\n    pass\n"),
            "c.py": ("python", "def use():\n    dup()\n"),
        }
    )
    amb = [e for e in result["calls"] if e["status"] == "ambiguous"]
    assert len(amb) == 1
    assert amb[0]["candidates"] == ["sym:a.py#dup", "sym:b.py#dup"]
    assert amb[0]["dst"] is None and amb[0]["dst_name"] == "dup"
    assert result["stats"].n_ambiguous == 1


def test_matlab_file_by_name_and_bare_script_calls():
    result = build(
        {
            "m/gain_sched.m": ("matlab", "function K = gain_sched(v)\nK = lookup_gain(v);\nend\n"),
            "m/lookup_gain.m": ("matlab", "function g = lookup_gain(v)\ng = v;\nend\n"),
            "m/run_all.m": ("matlab", "K = gain_sched(1);\nplot_results\nnot_a_thing\n"),
            "m/plot_results.m": ("matlab", "figure;\n"),
        }
    )
    got = edges(result)
    assert (
        "sym:m/gain_sched.m#gain_sched",
        "sym:m/lookup_gain.m#lookup_gain",
        "resolved",
        "lexical:unique-name",
    ) in got
    assert (
        "sym:m/run_all.m#(file)",
        "sym:m/gain_sched.m#gain_sched",
        "resolved",
        "lexical:unique-name",
    ) in got
    # A bare word resolves to the script file that carries that name.
    assert (
        "sym:m/run_all.m#(file)",
        "sym:m/plot_results.m#(file)",
        "resolved",
        "lexical:file-name",
    ) in got
    # An unknown bare word is dropped, not reported as unresolved.
    assert not any(e["dst_name"] == "not_a_thing" for e in result["calls"])
    assert result["stats"].n_bare_dropped == 1


def test_external_and_unresolved_calls():
    result = build(
        {
            "a.py": ("python", "import os\n\ndef f():\n    os.path.join('x')\n    mystery()\n"),
        }
    )
    by_name = {e["dst_name"]: e for e in result["calls"]}
    assert by_name["os.path.join"]["status"] == "external"
    assert by_name["mystery"]["status"] == "unresolved"
    assert result["stats"].n_external == 1 and result["stats"].n_unresolved == 1


def test_import_resolution_and_contains_edges():
    result = build(
        {
            "src/app/__init__.py": ("python", ""),
            "src/app/main.py": (
                "python",
                "from app.util import helper\nfrom . import sibling\nimport json\n\ndef main():\n    helper()\n",
            ),
            "src/app/util.py": ("python", "def helper():\n    pass\n"),
            "src/app/sibling.py": ("python", "x = 1\n"),
        }
    )
    imports = {(e["dst_name"], e["dst"], e["status"]) for e in result["imports"]}
    assert ("app.util", "file:src/app/util.py", "resolved") in imports
    assert (".", "file:src/app/__init__.py", "resolved") in imports
    assert ("json", None, "external") in imports
    contains = {(e["src"], e["dst"]) for e in result["contains"]}
    assert ("file:src/app/main.py", "sym:src/app/main.py#main") in contains


def test_symbol_rows_have_stable_ids_counts_and_cites():
    result = build(
        {
            "a.py": (
                "python",
                "def f():\n    g()\n    g()\n\ndef g():\n    pass\n\ndef g():\n    pass\n",
            ),
        }
    )
    rows = {r["id"]: r for r in result["symbols"]}
    assert "sym:a.py#g" in rows and "sym:a.py#g~2" in rows
    f = rows["sym:a.py#f"]
    assert f["cite"] == "a.py:1-3" and f["n_callees"] == 0  # ambiguous calls are not counted
    call = next(e for e in result["calls"] if e["src"] == "sym:a.py#f")
    assert call["count"] == 2 and call["status"] == "ambiguous"
