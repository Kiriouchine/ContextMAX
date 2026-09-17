# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Tier B on provisioned grammars. Skipped when the pack or the bundle is absent."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from contextmax import grammars

REAL_DIR = Path.home() / ".contextmax" / "grammars"


@pytest.fixture
def real_grammars(monkeypatch):
    if not grammars.pack_installed():
        pytest.skip("tree-sitter-language-pack not installed")
    monkeypatch.setenv(
        grammars.GRAMMAR_DIR_ENV, str(os.environ.get("CONTEXTMAX_TEST_GRAMMAR_DIR") or REAL_DIR)
    )
    grammars.has_tags.cache_clear()
    if not grammars.bundle_present():
        pytest.skip(
            "grammar bundle not provisioned; run `cmx grammars fetch matlab c javascript python`"
        )
    if not grammars.is_provisioned("matlab"):
        grammars.fetch(["matlab", "c", "javascript", "python"])
    yield
    grammars.has_tags.cache_clear()


def test_matlab_tier_b_exact_spans_and_calls(real_grammars):
    from contextmax.code import treesitter

    text = (
        "function [K, Ki] = gain_sched(v, table)\n% GAIN_SCHED help text.\n"
        "K = lookup_gain(v, table, 'kp');\nx = v';\nend\n\nfunction g = local_fn(a)\ng = a;\nend\n"
    )
    a = treesitter.analyze("m/gain_sched.m", text, "matlab", "matlab")
    assert a.tier == "B" and a.adapter == "treesitter-tags-v1"
    by = {s.qualname: s for s in a.symbols}
    assert (
        by["gain_sched"].line == 1 and by["gain_sched"].end_line == 5 and by["gain_sched"].end_exact
    )
    assert by["local_fn"].line == 7 and by["local_fn"].end_line == 9
    assert by["gain_sched"].doc and "GAIN_SCHED" in by["gain_sched"].doc
    assert [p["name"] for p in by["gain_sched"].params] == ["v", "table"]
    calls = {(c.caller, c.name) for c in a.calls}
    assert ("gain_sched", "lookup_gain") in calls


def test_c_tier_b_functions_and_calls(real_grammars):
    from contextmax.code import treesitter

    text = (
        '#include "core.h"\n#define SQUARE(x) ((x) * (x))\n\nstatic int helper_c(int v) {\n    return SQUARE(v);\n}\n\n'
        "int util_sum(int a, int b) {\n    return core_add(helper_c(a), b);\n}\n"
    )
    a = treesitter.analyze("src/util.c", text, "c", "c")
    by = {s.qualname: s for s in a.symbols}
    assert by["helper_c"].line == 4 and by["helper_c"].end_line == 6
    assert by["util_sum"].line == 8 and by["util_sum"].end_line == 10
    assert ("util_sum", "core_add") in {(c.caller, c.name) for c in a.calls}
    assert [i.module for i in a.imports] == ["core.h"]


def test_dispatch_prefers_plugin_then_grammar_then_lexical(real_grammars):
    from contextmax.code.run import choose_analyzer

    assert choose_analyzer({"language": "python", "plugin": "python"})[0] == "A"
    assert choose_analyzer({"language": "matlab", "plugin": "matlab"})[0] == "B"
    assert choose_analyzer({"language": "vhdl", "plugin": "vhdl"})[0] == "C"  # no tags query
    assert choose_analyzer({"language": None, "plugin": None})[0] == "C"


def test_grammar_status_reports_tags(real_grammars):
    st = grammars.status()
    assert st["bundle_present"] and "matlab" in st["with_tags"]
