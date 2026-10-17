"""Opening a project's file from a page: only files of a project, only documents opened, and the window
gives its pages a way to ask (with its token) that no other web page has."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from contextmax import opener, project, util


@pytest.fixture(autouse=True)
def registered(built):
    """Other tests build a second demo project under the same name: the registry points at this one again."""
    project._register(built.slug, built.workspace)


@pytest.fixture
def started(monkeypatch):
    """What would have been opened or shown, instead of opening it."""
    done = []
    monkeypatch.setattr(opener.os, "startfile", lambda p: done.append(("open", p)), raising=False)
    monkeypatch.setattr(opener.subprocess, "Popen", lambda cmd, **k: done.append(("explorer", cmd)))
    monkeypatch.setattr(opener, "_tell", lambda message: done.append(("told", message)))
    return done


def _a_document(built) -> Path:
    row = next(r for r in util.load_jsonl(built.documents_dir / "text-index.jsonl") if r["ext"] in (".pdf", ".docx"))
    root = next(f.path for f in built.folders if f.name == row["folder"])
    return Path(root) / row["relative_path"]


def test_a_document_of_a_project_opens_and_shows_in_its_folder(built, started):
    doc = _a_document(built)
    assert opener.open_path(str(doc), "open") == f"opened {doc.name}"
    assert opener.open_path(str(doc), "select").startswith("showed")
    assert started[0] == ("open", str(doc.resolve()))
    assert started[1] == ("explorer", f'explorer.exe /select,"{doc.resolve()}"')


def test_what_could_run_is_shown_in_its_folder_never_started(built, started):
    code = next(p for f in built.folders for p in Path(f.path).rglob("*.py"))
    message = opener.open_path(str(code), "open")
    assert "not a document" in message and [k for k, _ in started] == ["explorer"]



def test_a_module_s_folder_opens_in_explorer_and_its_code_is_shown_never_run(built, started):
    """"Open its folder" on a module: Explorer in that folder. "Show in folder" on a function: its file
    selected. Neither starts the code."""
    code = next(p for f in built.folders for p in Path(f.path).rglob("*.c"))
    assert opener.open_path(str(code.parent), "open") == f"opened the folder {code.parent.name}"
    assert opener.open_path(str(code), "select").startswith("showed")
    assert started == [("open", str(code.parent.resolve())), ("explorer", f'explorer.exe /select,"{code.resolve()}"')]
    with pytest.raises(ValueError):
        opener.open_path(str(Path(built.folders[0].path).parent.parent), "open")     # outside the project

def test_a_file_outside_every_project_is_refused(built, started, tmp_path):
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF")
    for path in (str(outside), "relative.pdf", "", str(_a_document(built)) + ".gone"):
        with pytest.raises(ValueError):
            opener.open_path(path, "open")
    assert started == []


def test_a_network_path_is_refused_before_anything_touches_it(built, started, monkeypatch):
    touched = []
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: touched.append(str(self)) or self)
    monkeypatch.setattr(Path, "exists", lambda self: touched.append(str(self)) or True)
    for path in ("\\\\attacker.invalid\\share\\doc.pdf", "\\\\?\\UNC\\attacker.invalid\\s\\x.pdf",
                 "\\\\.\\pipe\\x", "//attacker.invalid/share/doc.pdf"):
        with pytest.raises(ValueError):
            opener.open_path(path, "select")
    assert touched == [] and started == []


def test_a_link_opens_only_formats_that_carry_no_code_and_the_window_also_others(built, started, tmp_path):
    from urllib.parse import quote

    root = Path(next(f.path for f in built.folders))
    old = root / "old format.doc"
    old.write_bytes(b"\xd0\xcf")
    try:
        assert opener.handle_link("contextmax-open:open?path=" + quote(str(old), safe="")) == 0
        assert started[-1][0] == "explorer"           # shown in its folder, not started
        assert opener.open_path(str(old), "open") == f"opened {old.name}"
    finally:
        old.unlink()


def test_a_link_cannot_put_its_own_words_in_the_message(built, started):
    from urllib.parse import quote

    words = "C:\\ContextMAX licence expired.\n\nCall +1-555-0100 now" + "x" * 5000 + "\\x.pdf"
    assert opener.handle_link("contextmax-open:open?path=" + quote(words, safe="")) == 1
    told = started[-1][1]
    assert started[-1][0] == "told" and "\n\nCall" not in told and len(told) < 320


def test_a_contextmax_link_opens_and_a_foreign_one_is_told(built, started):
    doc = _a_document(built)
    from urllib.parse import quote

    assert opener.handle_link("contextmax-open:open?path=" + quote(str(doc), safe="")) == 0
    assert opener.handle_link("contextmax-open:run?path=" + quote(str(doc), safe="")) == 1
    assert opener.handle_link("contextmax-open:open?path=" + quote("C:\\Windows\\notepad.exe", safe="")) == 1
    assert [k for k, _ in started] == ["open", "told", "told"]


def test_the_window_hands_its_pages_the_token_and_opens_their_files(built, started):
    from contextmax import panel

    panel.Handler.token = "secret"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        page = urllib.request.urlopen(f"{base}/ws/{built.slug}/pages/documents.html", timeout=5).read().decode("utf-8")
        assert 'window.CMX_PANEL={"token": "secret", "slug": "' + built.slug + '"}' in page
        body = json.dumps({"slug": built.slug, "path": str(_a_document(built)), "how": "open"}).encode()
        req = urllib.request.Request(f"{base}/api/files", data=body, method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(req, timeout=5)
        assert refused.value.code == 403 and started == []
        req = urllib.request.Request(f"{base}/api/files", data=body, method="POST",
                                     headers={"X-CMX-Token": "secret", "Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req, timeout=5).read())["message"].startswith("opened")
        # a page that points its own name at 127.0.0.1 (DNS rebinding) is refused, and nothing may frame these pages
        for path in ("/", f"/ws/{built.slug}/Home.html", f"/ask?slug={built.slug}"):
            req = urllib.request.Request(f"{base}{path}", headers={"Host": f"rebind.example:{srv.server_address[1]}"})
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(req, timeout=5)
            assert refused.value.code == 403
        req = urllib.request.Request(f"{base}/api/files", data=body, method="POST",
                                     headers={"X-CMX-Token": "secret", "Origin": "http://rebind.example"})
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(req, timeout=5)
        assert refused.value.code == 403
        page = urllib.request.urlopen(f"{base}/ws/{built.slug}/Home.html", timeout=5)
        assert page.headers["X-Frame-Options"] == "DENY"
    finally:
        srv.shutdown()


def test_page_data_with_an_html_comment_still_reads():
    from contextmax import util

    s = util.html_json({"t": "<!-- TODO --> The unit shall stop </script>"})
    assert json.loads(s)["t"] == "<!-- TODO --> The unit shall stop </script>"
    assert "<" not in s


def test_the_document_page_carries_paths_for_the_buttons_and_a_shared_copy_none(built):
    from contextmax.views import docs_data

    nodes = docs_data.build(built)["nodes"]
    assert any(n["path"] and Path(n["path"]).is_absolute() for n in nodes)
    assert all(n["path"] is None for n in docs_data.build(built, portable=True)["nodes"])
