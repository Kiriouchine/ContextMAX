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


class _Build:
    """A build process that prints the given lines and ends with the given code."""
    lines: list[bytes] = []
    code = 0
    pid = 0

    def __init__(self, cmd, env, **kw):
        _Build.env = env
        self.stdout = iter(_Build.lines)

    def wait(self):
        return _Build.code


def test_the_window_keeps_live_events_out_of_the_text_log(built, monkeypatch, capsys):
    _Build.lines = [b"[docs] reading\n", util.LIVE_MARK.encode() + b'{"e":"read","n":3}\n', b"[done] built\n"]
    monkeypatch.setattr(panel.subprocess, "Popen", _Build)
    panel.JOBS["t"] = {"lines": [], "events": [], "done": False, "code": None}
    panel._run_build("t", built.slug, "quick")
    # the events are always recorded: the window may switch the drawing on halfway, and starts from the first
    assert _Build.env["CONTEXTMAX_LIVE"] == "1"
    got = panel.Handler._act(panel.Handler, "job", {"slug": built.slug, "job": "t", "since": 0, "events_since": 0})
    assert got["lines"] == ["[docs] reading", "[done] built"] and got["events"] == [{"e": "read", "n": 3}]
    assert got["done"] and got["code"] == 0
    # a window that does not draw is sent no events, and is not kept waiting for them
    got = panel.Handler._act(panel.Handler, "job", {"slug": built.slug, "job": "t", "since": 0, "events_since": -1})
    assert got["events"] == [] and not got["more"] and got["done"] and got["lines"] == ["[docs] reading", "[done] built"]
    # every line of the build is also shown in the CMD window; the drawing's events are not
    out = capsys.readouterr().out
    assert f"{built.slug} | [docs] reading" in out and "build finished" in out and '"e":"read"' not in out


def test_a_build_in_the_window_brings_an_installed_skill_up_to_date(built, monkeypatch):
    from contextmax import agentskill

    _Build.lines, _Build.code = [b"[done] built\n"], 0
    monkeypatch.setattr(panel.subprocess, "Popen", _Build)
    panel.JOBS["s"] = {"lines": [], "events": [], "done": False, "code": None}
    panel._run_build("s", built.slug, "quick")
    assert not any((base / f"contextmax-{built.slug}").exists() for base in agentskill.HOSTS.values())   # none installed: none written
    skill = agentskill.HOSTS["claude"] / f"contextmax-{built.slug}" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("from an older build", encoding="utf-8")
    status = {h["host"]: h for h in panel._skill_status(built)["hosts"]}
    assert status["claude"]["installed"] and not status["claude"]["current"] and not status["copilot"]["installed"]
    panel.JOBS["s"] = {"lines": [], "events": [], "done": False, "code": None}
    panel._run_build("s", built.slug, "quick")
    assert skill.read_text(encoding="utf-8") == agentskill.compose(built)
    assert not (agentskill.HOSTS["copilot"] / f"contextmax-{built.slug}").exists()     # only where it was installed
    assert panel.JOBS["s"]["lines"][-1] == "[skill] the AI skill now describes this build, for Claude Code"
    assert {h["host"]: h for h in panel._skill_status(built)["hosts"]}["claude"]["current"]
    # a build that fails leaves the skill as it is
    skill.write_text("from an older build", encoding="utf-8")
    _Build.code = 1
    panel.JOBS["s"] = {"lines": [], "events": [], "done": False, "code": None}
    panel._run_build("s", built.slug, "quick")
    _Build.code = 0
    assert skill.read_text(encoding="utf-8") == "from an older build"


def test_the_window_has_the_atlas_and_the_start_screen_facts(built):
    page = json.loads(panel._atlas_data(built.slug))
    assert page["stages"] and page["docs"]["k"]
    cards = {c["slug"]: c for c in panel.Handler._act(panel.Handler, "projects", {})["projects"]}
    card = cards[built.slug]
    assert card["found"] and card["built"] and card["documents"] and card["functions"] and card["atlas"]
    assert card["home"] == f"/ws/{built.slug}/Home.html"
