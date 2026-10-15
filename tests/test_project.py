"""Determinism, the pages, the queries, the skill and the window."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from contextmax import agentskill, demo, pipeline, query, util


def test_two_copies_of_the_same_folders_give_the_same_index(built, tmp_path):
    other = demo.create_project(tmp_path / "elsewhere", workspace=str(tmp_path / "ws"))
    pipeline.build(other, depth="documents", ocr=False)
    a = util.load_json(built.workspace / "buildinfo.json")
    b = util.load_json(other.workspace / "buildinfo.json")
    assert a["outputs_hash"] == b["outputs_hash"]
    assert a["inputs_hash"] == b["inputs_hash"]


def test_a_rebuild_changes_nothing(built):
    before = util.load_json(built.workspace / "buildinfo.json")["outputs_hash"]
    pipeline.build(built, depth="quick", ocr=False)
    assert util.load_json(built.workspace / "buildinfo.json")["outputs_hash"] == before


def test_the_pages_are_offline_and_their_data_parses(built):
    pages = list(built.pages_dir.glob("*.html")) + [built.workspace / "Home.html"]
    assert len(pages) >= 8
    for p in pages:
        html = p.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["']https?://""", html), p.name
        m = re.search(r'<script type="application/json" id="cmx-data">(.*?)</script>', html, re.S)
        if m:
            json.loads(m.group(1))


def test_completeness_is_stated(built):
    m = util.load_json(built.workspace / "buildinfo.json")
    c = m["completeness"]
    assert c["code_ok"] and c["with_doc_map"] and c["confidence"] == "High"


def test_impact_says_what_it_could_not_follow(built):
    out = query.find(built, "impact", "write_log")
    hit = out["hits"][0]
    assert hit["impact"]["product_functions"] >= 3
    assert "not followed" in hit["impact"]["caveat"]


def test_sheet_trace_reaches_the_constants_and_lint_finds_the_miswired_row(built, capsys):
    assert query.sheet(built, key="Error_budget", trace="Budget!B7") == 0
    out = capsys.readouterr().out
    assert "Budget!B4" in out and "Budget!B6" in out
    query.sheet(built, key="Error_budget", lint=True)
    out = capsys.readouterr().out
    assert "Budget!A10" in out and "1 suspicious" in out


def test_the_skill_says_how_to_answer(built):
    text = agentskill.compose(built, "python.exe")
    assert "Documents: not opened" in text and "Mismatch" in text
    assert text.startswith("---\nname: contextmax-demo-project\n")
    assert query.status_line(built).startswith("- ContextMAX (demo-project): built ")


def test_the_window_refuses_requests_without_its_token(built):
    import threading
    from http.server import ThreadingHTTPServer

    from contextmax import panel

    panel.Handler.token = "secret"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/state"
    try:
        for _ in range(25):        # a refusal must arrive as a 403, never as a reset connection
            req = urllib.request.Request(url, data=b'{"slug": "x"}', method="POST")
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("no token, yet allowed")
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
        req = urllib.request.Request(url, data=json.dumps({"slug": built.slug}).encode(), method="POST",
                                     headers={"X-CMX-Token": "secret", "Content-Type": "application/json"})
        state = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert state["project"]["slug"] == built.slug
    finally:
        srv.shutdown()


def test_a_shared_copy_carries_no_path_of_this_pc(built, tmp_path):
    from contextmax import share

    dest = tmp_path / "shared"
    assert share.share(built, str(dest), dry_run=True) == 0
    assert not dest.exists()
    assert share.share(built, str(dest), yes=True) == 0
    assert (dest / "Home.html").exists() and (dest / "documents" / "params.sqlite").exists()
    assert not (dest / "documents" / "text").exists()
    local = [str(built.workspace), str(built.folders[0].path)]
    for p in list((dest / "pages").glob("*.html")) + [dest / "Home.html"]:
        html = p.read_text(encoding="utf-8")
        assert "file:///" not in html and "vscode://file" not in html, p.name
        for path in local:
            assert path not in html and path.replace("\\", "\\\\") not in html, p.name


def test_no_build_and_no_share_passes_a_broken_document_map(built, tmp_path):
    from contextmax import share

    doc_list = built.documents_dir / "doc-list.jsonl"
    before = doc_list.read_bytes()
    try:
        doc_list.write_bytes(b"\n".join(before.split(b"\n")[1:]))      # one document gone
        try:
            pipeline.build(built, depth="catalogue", ocr=False)
            raise AssertionError("the catalogue build wrote pages from a broken document map")
        except pipeline.GateFailed:
            pass
        assert share.share(built, str(tmp_path / "shared"), yes=True) == 1
        assert not (tmp_path / "shared").exists()
    finally:
        doc_list.write_bytes(before)
    pipeline.build(built, depth="catalogue", ocr=False)


def test_a_check_for_office_that_does_not_finish_says_why(monkeypatch):
    from contextmax import office

    monkeypatch.delenv("CONTEXTMAX_NO_OFFICE")
    monkeypatch.setattr(office, "_PROBE", None)
    monkeypatch.setattr(office, "PROBE_PROBLEM", None)
    monkeypatch.setattr(office, "run_script", lambda *a, **k: (False, "", "timed out after 90 s"))
    assert office.probe() == {"word": False, "excel": False, "ocr": False, "ocr_languages": []}
    assert "timed out after 90 s" in office.PROBE_PROBLEM and "security software" in office.PROBE_PROBLEM


def test_the_self_check_writes_a_report(built):
    from contextmax import share

    share.selfcheck(built)
    assert list(built.path("logs").glob("self-check-*.json"))


def test_a_project_never_takes_a_program_folder(tmp_path, monkeypatch):
    from contextmax import project

    monkeypatch.setenv("CONTEXTMAX_HOME", str(tmp_path))
    assert project.create("Python", []).workspace == tmp_path / "python-project"
    assert project.create("Bin", []).workspace == tmp_path / "bin-project"
    assert project.create("Python tools", []).workspace == tmp_path / "python-tools"
