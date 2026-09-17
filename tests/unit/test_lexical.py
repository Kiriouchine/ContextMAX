# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from contextmax.code.lexical import analyze, mask, profile, profile_for, split_params


def names(analysis, kind=None):
    return [s.name for s in analysis.symbols if kind is None or s.kind == kind]


def calls(analysis):
    return sorted((c.caller, c.name, c.line, c.kind) for c in analysis.calls)


def test_mask_preserves_line_count_and_blanks_comments():
    prof = profile("clike")
    text = 'int a = 1; // note\n/* block\n comment */ int b = "str(x)";\n'
    no_comments, masked, ranges = mask(text, prof)
    assert no_comments.count("\n") == text.count("\n") == masked.count("\n")
    assert "note" not in no_comments and "comment" not in no_comments
    assert '"str(x)"' in no_comments and "str(x)" not in masked
    assert ranges == [(1, 3)]


def test_matlab_function_help_calls_and_transpose():
    text = (
        "function [K, Ki] = gain_sched(v, table)\n"
        "% GAIN_SCHED Interpolate gains.\n"
        "%   Second help line.\n"
        "K = lookup_gain(v, table, 'kp');\n"
        "x = v';\n"
        "y = zeros(3, 1);\n"
        "end\n"
    )
    a = analyze("m/gain_sched.m", text, "matlab")
    fn = next(s for s in a.symbols if s.kind == "function")
    assert fn.name == "gain_sched"
    assert fn.returns == ["K", "Ki"]
    assert [p["name"] for p in fn.params] == ["v", "table"]
    assert fn.doc.startswith("GAIN_SCHED Interpolate gains.")
    assert "Second help line" in fn.doc
    called = [c.name for c in a.calls]
    assert "lookup_gain" in called
    assert "zeros" not in called  # keyword list keeps builtins out
    assert all(c.caller == "gain_sched" for c in a.calls)
    # A function file has no file-level code, so no script symbol is added.
    assert "(file)" not in [s.qualname for s in a.symbols]


def test_matlab_script_cells_bare_calls_and_block_comments():
    text = (
        "%% Load\nload('flight.mat');\n%% Run\n[K, Ki] = gain_sched(15, table);\nplot_results\n"
        "%{\ngain_sched(999, table)\n%}\n"
    )
    a = analyze("m/run_all.m", text, "matlab")
    kinds = {s.qualname: s.kind for s in a.symbols}
    assert kinds["(file)"] == "script"
    assert [s.name for s in a.symbols if s.kind == "region"] == ["Load", "Run"]
    sites = calls(a)
    assert ("(file)", "gain_sched", 4, "call") in sites
    assert ("(file)", "plot_results", 5, "bare") in sites
    assert not any(c.line == 7 for c in a.calls)  # inside the block comment
    assert [i.kind for i in a.imports] == ["load"] and a.imports[0].module == "flight.mat"


def test_python_defs_docstrings_decorators_and_module_level_calls():
    text = (
        "import os\nfrom app.util import helper as h\n\n"
        '@cached\ndef main(x: int = 3, *args) -> int:\n    """Entry point.\n\n    More.\n    """\n    return h(x) + os.path.join(\'a\')\n\n'
        "class Thing:\n    def run(self, y):\n        return helper(y)\n\n\nif __name__ == '__main__':\n    main()\n"
    )
    a = analyze("src/app/main.py", text, "python")
    by_q = {s.qualname: s for s in a.symbols}
    assert by_q["main"].doc == "Entry point."
    assert by_q["main"].decorators == ["@cached"]
    assert by_q["main"].returns == "int"
    assert [p["name"] for p in by_q["main"].params] == ["x", "args"]
    assert by_q["main"].params[0] == {"name": "x", "type": "int", "default": "3"}
    assert by_q["Thing.run"].parent == "Thing"
    assert by_q["Thing"].end_line >= by_q["Thing.run"].line
    assert by_q["(file)"].kind == "module"
    sites = calls(a)
    assert ("(file)", "main", 18, "call") in sites
    assert ("main", "join", 10, "call") in sites  # qualifier os.path recorded separately
    assert [c.qualifier for c in a.calls if c.name == "join"] == ["os.path"]
    assert [(i.module, i.names, i.alias) for i in a.imports] == [
        ("app.util", ["helper"], "h"),
        ("os", [], None),
    ]


def test_clike_definitions_macros_and_brace_spans():
    text = (
        '#include "core.h"\n#define SQUARE(x) ((x) * (x))\n'
        "static int helper_c(int v) {\n    return SQUARE(v);\n}\n\n"
        "int util_sum(int a, int b) {\n    if (a) {\n        return core_add(helper_c(a), b);\n    }\n    return 0;\n}\n"
    )
    a = analyze("src/native/util.c", text, "c")
    by_q = {s.qualname: s for s in a.symbols}
    assert (
        by_q["util_sum"].line == 7
        and by_q["util_sum"].end_line == 12
        and by_q["util_sum"].end_exact
    )
    assert by_q["helper_c"].visibility == "private"
    assert by_q["SQUARE"].kind == "macro"
    sites = calls(a)
    assert ("util_sum", "core_add", 9, "call") in sites
    assert ("util_sum", "helper_c", 9, "call") in sites
    assert not any(c.name == "if" for c in a.calls)
    assert [i.module for i in a.imports] == ["core.h"]


def test_shell_functions_and_gated_bare_calls():
    text = "#!/usr/bin/env bash\nsource ./lib.sh\nlog_msg deploying\nrsync -a a b\nmy_fn() {\n  echo hi\n}\nmy_fn\n"
    a = analyze("scripts/deploy.sh", text, "shell")
    assert names(a, "function") == ["my_fn"]
    bare = {(c.name, c.kind) for c in a.calls}
    assert ("log_msg", "bare") in bare and ("rsync", "bare") in bare
    assert ("echo", "bare") not in bare
    assert a.imports[0].module == "./lib.sh" and a.imports[0].kind == "source"


def test_javascript_forms():
    text = (
        "import { x } from './x.js';\nconst api = require('./api');\n"
        "export function render(a, b) {\n  return helper(a);\n}\n"
        "const draw = async (c) => {\n  render(c);\n};\n"
        "class View {\n  constructor(el) {\n    this.el = el;\n  }\n  paint() {\n    draw(this.el);\n  }\n}\n"
    )
    a = analyze("src/web/index.js", text, "javascript")
    by_q = {s.qualname: s for s in a.symbols}
    assert set(by_q) >= {"render", "draw", "View", "View.constructor", "View.paint"}
    assert ("View.paint", "draw", 14, "call") in calls(a)
    assert sorted(i.module for i in a.imports) == ["./api", "./x.js"]


def test_unknown_language_uses_default_profile():
    a = analyze("unknown.zzz", "some text\nfoo(bar)\n", None)
    assert profile_for(None).id == "default"
    assert ("(file)", "foo", 2, "call") in calls(a)
    assert a.symbols[0].kind == "module"


def test_split_params_handles_defaults_types_and_nesting():
    assert split_params("a, b: int = 3, *args, cb: Callable[[int], str]") == [
        {"name": "a"},
        {"name": "b", "type": "int", "default": "3"},
        {"name": "args"},
        {"name": "cb", "type": "Callable[[int], str]"},
    ]
    assert split_params("int a, const char *name") == [
        {"name": "a", "type": "int"},
        {"name": "name", "type": "const char"},
    ]
    assert split_params("void") == []


def test_analysis_is_deterministic():
    text = "def a():\n    b()\n\ndef b():\n    a()\n"
    first = analyze("x.py", text, "python")
    second = analyze("x.py", text, "python")
    assert [(s.qualname, s.line, s.end_line, s.content_hash) for s in first.symbols] == [
        (s.qualname, s.line, s.end_line, s.content_hash) for s in second.symbols
    ]
