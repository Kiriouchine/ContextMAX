# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from contextmax.code.plugins import python as py
from contextmax.code.resolve import resolve_project

SRC = '''"""Module docstring."""
import os
from app.util import helper as h
from . import sibling

LIMIT = 3
config: dict = {}


@decorated
def main(x: int = 3, *args, flag=False, **kw) -> int:
    """Entry point.

    Details.
    """
    h(x)
    os.path.join("a")
    return helper2()


class Thing(Base):
    count = 0

    def __init__(self):
        self.value = 1

    def run(self, y):
        self.tick()
        return Thing()

    def tick(self):
        pass


def helper2():
    return 2


if __name__ == "__main__":
    main()
'''


def test_python_plugin_symbols_and_spans():
    a = py.analyze("src/app/main.py", SRC)
    by_q = {s.qualname: s for s in a.symbols}
    assert a.tier == "A" and a.adapter == "python-ast-v1"
    assert by_q["main"].kind == "function" and by_q["main"].end_exact
    assert by_q["main"].line == 11 and by_q["main"].end_line == 18
    assert by_q["main"].extra["decorated_from"] == 10
    assert by_q["main"].decorators == ["@decorated"]
    assert by_q["main"].doc == "Entry point."
    assert by_q["main"].returns == "int"
    assert [p["name"] for p in by_q["main"].params] == ["x", "*args", "flag", "**kw"]
    assert by_q["main"].params[0] == {"name": "x", "type": "int", "default": "3"}
    assert by_q["Thing"].kind == "class" and by_q["Thing"].params == [{"name": "Base"}]
    assert by_q["Thing.__init__"].kind == "constructor"
    assert by_q["Thing.run"].kind == "method" and by_q["Thing.run"].parent == "Thing"
    assert by_q["Thing.count"].kind == "field"
    assert by_q["LIMIT"].kind == "constant" and by_q["LIMIT"].signature == "LIMIT = 3"
    assert by_q["config"].kind == "variable" and by_q["config"].returns == "dict"
    assert by_q["(file)"].kind == "module" and by_q["(file)"].doc == "Module docstring."


def test_python_plugin_calls_hints_and_imports():
    a = py.analyze("src/app/main.py", SRC)
    calls = {(c.caller, c.name, c.qualifier): c for c in a.calls}
    assert calls[("main", "h", None)].hint == ("app.util", "helper")
    assert calls[("main", "join", "os.path")].hint == ("os", "path")
    assert calls[("Thing.run", "tick", "self")].hint == ("__self__", "tick")
    assert calls[("Thing.run", "Thing", None)].kind == "instantiate"
    assert calls[("(file)", "main", None)].line == 40
    assert ("Thing", "Base", None) in calls and calls[("Thing", "Base", None)].kind == "reference"
    imports = {(i.module, tuple(i.names), i.alias, i.relative) for i in a.imports}
    assert ("os", (), None, False) in imports
    assert ("app.util", ("helper",), "h", False) in imports
    assert (".", ("sibling",), None, True) in imports


def test_python_syntax_error_falls_back_to_lexical():
    a = py.analyze("bad.py", "def broken(:\n    pass\n")
    assert a.tier == "C" and a.adapter == "lexical-v1"
    assert any("syntax error" in n for n in a.notes)


def test_hints_resolve_through_imports_and_self():
    files = {
        "src/app/__init__.py": "",
        "src/app/util.py": "def helper():\n    return 1\n\n\ndef helper2():\n    return 2\n",
        "src/app/main.py": SRC,
        "src/other/dup.py": "def helper():\n    pass\n",
    }
    analyses = [py.analyze(k, v) for k, v in sorted(files.items())]
    result = resolve_project(
        analyses, dict.fromkeys(files, "product"), dict.fromkeys(files, "python-ast-v1")
    )
    edges = {(e["src"], e["dst_name"]): e for e in result["calls"]}
    edges.update(
        {
            (e["src"], e["dst_name"].rsplit(".", 1)[-1]): e
            for e in result["calls"]
            if e["status"] != "resolved"
        }
    )
    h_edge = edges[("sym:src/app/main.py#main", "h")]
    assert h_edge["dst"] == "sym:src/app/util.py#helper"
    assert h_edge["evidence"].endswith("import-resolved") and h_edge["confidence"] == "high"
    tick = edges[("sym:src/app/main.py#Thing.run", "tick")]
    assert tick["dst"] == "sym:src/app/main.py#Thing.tick" and tick["confidence"] == "high"
    inst = edges[("sym:src/app/main.py#Thing.run", "Thing")]
    assert inst["dst"] == "sym:src/app/main.py#Thing" and inst["rel"] == "instantiates"
    join = edges[("sym:src/app/main.py#main", "os.path.join")]
    assert join["status"] == "external"
    helper2 = edges[("sym:src/app/main.py#main", "helper2")]
    assert helper2["dst"] == "sym:src/app/main.py#helper2" and helper2["confidence"] == "high"
