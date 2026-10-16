"""The Complete Atlas: one drawing of the code, the documents and every link, on its page and live in the window."""
from __future__ import annotations

import json

from contextmax import panel, pipeline, util
from contextmax.views import atlas_data


def _events(text: str) -> list[dict]:
    return [json.loads(line[len(util.LIVE_MARK):]) for line in text.split("\n") if line.startswith(util.LIVE_MARK)]


def test_the_atlas_holds_the_code_the_documents_and_every_link(built):
    data = atlas_data.build(built)
    modules = sum(len(set(util.load_json(built.code_dir / t["name"] / "module-list.json", default={}) or {})
                      | set(util.load_json(built.code_dir / t["name"] / "hdl-modules.json", default={}) or {}))
                  for t in built.code_targets)
    core = util.load_jsonl(built.documents_dir / "doc-list.jsonl")
    between = util.load_jsonl(built.documents_dir / "links" / "between-docs.jsonl")
    assert len(data["modules"]) == modules and data["docs"]["k"] == [d["key"] for d in core]
    assert len(data["links"]["a"]) == len(between)                     # every link between documents, none left out
    assert [data["kinds"][k] for k in data["links"]["k"]] == [e["kind"] for e in between]
    named = {(e["document_key"], e["module"]) for e in util.load_jsonl(built.documents_dir / "links" / "doc-to-code.jsonl")}
    assert {(data["docs"]["k"][r[0]], data["modules"][r[1]][1]) for r in data["dcode"]} == named
    n_fn, n_doc = len(data["functions"]["m"]), len(core)
    assert all(0 <= a < n_fn and 0 <= b < n_fn for a, b in data["fcalls"])
    assert all(0 <= f < n_fn and 0 <= d < n_doc for f, d, _ in data["fdocs"])
    control = next(i for i, m in enumerate(data["modules"]) if m[1] == "control")
    assert any(m == control for m in data["functions"]["m"])
    assert any(data["functions"]["n"][f] == "pid_step" for f, _, _ in data["fdocs"])     # a document names pid_step


def test_vhdl_is_on_the_atlas_too(built):
    """VHDL modules join the wheel, an entity placing another is a call, and a document that names an entity
    is linked to the module that holds it (the document map files it under the code base)."""
    data = atlas_data.build(built)
    at = {(data["targets"][m[0]]["name"], m[1]): i for i, m in enumerate(data["modules"])}
    top, encoder = at[("logic", "top")], at[("logic", "encoder")]
    assert "VHDL" in data["modules"][top][4] and [top, encoder, 2] in data["calls"]
    fn = data["functions"]
    names = {(fn["n"][a], fn["n"][b]) for a, b in data["fcalls"]}
    assert ("motion_top", "quad_decoder") in names and ("motion_top", "sys_timer") in names
    edge = {"document_key": "Detailed_design_v2.1", "targets": ["logic"], "module": "logic", "weight": 1,
            "confidence": "one", "symbols": [{"sym": "QUAD_DECODER", "kind": "entity", "n": 3}]}
    rows = atlas_data.code_link_rows([edge], {"Detailed_design_v2.1": 0}, atlas_data.module_index(data),
                                     atlas_data.entity_modules(data))
    assert rows == [[0, encoder, 1, 0, [["QUAD_DECODER", "entity", 3]], 0]]


def test_the_atlas_page_is_written_and_every_page_leads_to_it(built):
    page = (built.pages_dir / "atlas.html").read_text(encoding="utf-8")
    assert 'data-page="atlas"' in page and '<script src="atlas.js">' in page and (built.pages_dir / "atlas.js").exists()
    assert '<a class="is-on" href="atlas.html">Complete Atlas</a>' in page
    assert 'href="atlas.html">Complete Atlas</a>' in (built.pages_dir / "documents.html").read_text(encoding="utf-8")
    assert 'href="pages/atlas.html">Open the Complete Atlas</a>' in (built.workspace / "Home.html").read_text(encoding="utf-8")


def test_a_live_build_draws_the_atlas_and_writes_the_same_index(tmp_path, monkeypatch, capsys):
    """With CONTEXTMAX_LIVE=1 the build also prints what it found, and nothing else changes; the events
    add up to the very data the Complete Atlas page draws."""
    from contextmax import demo

    monkeypatch.setenv("CONTEXTMAX_HOME", str(tmp_path / "home"))
    proj = demo.create_project(tmp_path / "src" / "demo")
    monkeypatch.delenv("CONTEXTMAX_LIVE", raising=False)
    pipeline.build(proj, depth="documents", ocr=False)
    quiet = util.load_json(proj.workspace / "buildinfo.json")["outputs_hash"]
    assert not _events(capsys.readouterr().out)
    monkeypatch.setenv("CONTEXTMAX_LIVE", "1")
    pipeline.build(proj, depth="documents", ocr=False)
    events = _events(capsys.readouterr().out)
    assert util.load_json(proj.workspace / "buildinfo.json")["outputs_hash"] == quiet

    order = [e["e"] for e in events]
    assert order[0] == "start" and order[-1] == "done"
    firsts = [order.index(e) for e in ("catalogue", "docs", "codefiles", "code", "stages", "dcode", "placed", "values",
                                       "links", "gate", "pages", "done")]
    assert firsts == sorted(firsts)
    assert [e["state"] for e in events if e["e"] == "gate"] == ["checking", "passed"]

    page = atlas_data.build(proj, portable=True)
    code = next(e for e in events if e["e"] == "code")
    assert (code["targets"], code["modules"], code["calls"]) == (page["targets"], page["modules"], page["calls"])
    stages = next(e for e in events if e["e"] == "stages")
    assert stages["stages"] == page["stages"] and stages["docs"] == page["docs"]
    assert [r for e in events if e["e"] == "dcode" for r in e["rows"]] == page["dcode"]
    links = [e for e in events if e["e"] == "links"]
    assert [e["kinds"][k] for e in links for k in e["k"]] == [page["kinds"][k] for k in page["links"]["k"]]
    for field in ("a", "b", "d"):
        assert [x for e in links for x in e[field]] == page["links"][field]
    docs = next(e for e in events if e["e"] == "docs")
    assert sorted(docs["keys"]) == sorted(r["key"] for r in util.load_jsonl(proj.documents_dir / "text-index.jsonl"))


def test_the_window_keeps_live_events_out_of_the_text_log(built, monkeypatch):
    lines = [b"[docs] reading\n", util.LIVE_MARK.encode() + b'{"e":"read","n":3}\n', b"[done] built\n"]

    class Process:
        stdout = iter(lines)

        def __init__(self, cmd, env, **kw):
            Process.env = env

        def wait(self):
            return 0

    monkeypatch.setattr(panel.subprocess, "Popen", Process)
    panel.JOBS["t"] = {"lines": [], "events": [], "done": False, "code": None}
    panel._run_build("t", built.slug, "quick", live=True)
    assert Process.env["CONTEXTMAX_LIVE"] == "1"
    got = panel.Handler._act(panel.Handler, "job", {"slug": built.slug, "job": "t", "since": 0, "events_since": 0})
    assert got["lines"] == ["[docs] reading", "[done] built"] and got["events"] == [{"e": "read", "n": 3}]
    assert got["done"] and got["code"] == 0
    Process.stdout = iter(lines)
    panel._run_build("t", built.slug, "quick", live=False)
    assert "CONTEXTMAX_LIVE" not in Process.env
