"""Ask your AI: the working folder made ready for assistants, what starting one runs, and asking a model on
this PC (a fake Ollama and a fake OpenAI-style server stand in for the real ones)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from contextmax import agentskill, ask, assistants, reading


def test_what_others_wrote_in_the_working_folder_stays(built, tmp_path):
    ws = built.workspace
    (ws / "CLAUDE.md").write_text("# Memory\n- the build needs the VPN\n", encoding="utf-8")
    assistants.prepare(built)
    assistants.prepare(built)
    claude = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("# Memory\n- the build needs the VPN\n") and claude.count(assistants.BEGIN) == 1
    # settings that are not plain JSON (comments) are left exactly as they are
    odd = '{\n  // mine\n  "model": "x"\n}\n'
    (ws / ".claude" / "settings.json").write_text(odd, encoding="utf-8")
    done = assistants.prepare(built)
    assert (ws / ".claude" / "settings.json").read_text(encoding="utf-8") == odd and any("left as it is" in d for d in done)
    (ws / ".claude" / "settings.json").write_text('["not an object"]', encoding="utf-8")
    assistants.prepare(built)                      # no crash
    (ws / ".claude" / "settings.json").unlink()


def test_a_folder_taken_out_of_the_project_loses_its_read_access(built, monkeypatch):
    from contextmax.project import Folder

    ws = built.workspace
    (ws / ".claude" / "settings.json").unlink(missing_ok=True)
    (ws / ".claude" / assistants.GRANTED).unlink(missing_ok=True)
    extra = Folder(name="old", path="D:\\old-folder", holds="both")
    real = list(built.folders)
    monkeypatch.setattr(type(built), "folders", property(lambda self: real + [extra]))
    assistants.prepare(built)
    monkeypatch.setattr(type(built), "folders", property(lambda self: real))
    assistants.prepare(built)
    allowed = json.loads((ws / ".claude" / "settings.json").read_text())["permissions"]["additionalDirectories"]
    assert allowed == [f.path for f in real]


def test_the_working_folder_is_made_ready_and_a_persons_settings_are_kept(built):
    ws = built.workspace
    settings = ws / ".claude" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(json.dumps({"model": "mine", "permissions": {"additionalDirectories": ["D:\\other"]}}))
    assistants.prepare(built)
    def block(name):
        text = (ws / name).read_text(encoding="utf-8")
        return text[text.index(assistants.BEGIN):text.index(assistants.END)]

    guide = block("CLAUDE.md")
    assert guide == block("AGENTS.md")
    assert f"contextmax-{built.slug}" in guide and all(f.path in guide for f in built.folders)
    kept = json.loads(settings.read_text())
    assert kept["model"] == "mine"
    assert kept["permissions"]["additionalDirectories"] == ["D:\\other"] + [f.path for f in built.folders]
    folders = json.loads((ws / f"{built.slug}.code-workspace").read_text())["folders"]
    assert folders[0]["path"] == "." and [f["path"] for f in folders[1:]] == [f.path for f in built.folders]
    assistants.prepare(built)                     # again: nothing doubles
    assert json.loads(settings.read_text())["permissions"]["additionalDirectories"] == kept["permissions"]["additionalDirectories"]


def test_starting_an_assistant_installs_its_skill_and_runs_what_it_should(built, monkeypatch, tmp_path):
    runs, opened, skills = [], [], []
    monkeypatch.setattr(assistants, "tools", lambda: [{"id": i, "label": i, "ok": True, "why": ""}
                                                      for i in ("vscode-claude", "vscode", "claude", "codex")])
    monkeypatch.setattr(assistants, "_vscode", lambda: str(tmp_path / "VS Code" / "bin" / "code.cmd"))
    (tmp_path / "VS Code" / "Code.exe").parent.mkdir(parents=True)
    (tmp_path / "VS Code" / "Code.exe").write_bytes(b"")
    monkeypatch.setattr(assistants.agentskill, "install", lambda p, host: skills.append(host) or [])
    monkeypatch.setattr(assistants.subprocess, "Popen", lambda cmd, **k: runs.append((cmd, k.get("cwd"))))
    monkeypatch.setattr(assistants.os, "startfile", lambda target: opened.append(target), raising=False)
    monkeypatch.setattr(assistants.time, "sleep", lambda s: None)
    code, wsfile = str(tmp_path / "VS Code" / "Code.exe"), str(built.workspace / f"{built.slug}.code-workspace")
    assistants.start(built, "vscode")
    assert runs[-1] == ([code, wsfile], None) and skills == ["copilot"]

    # Claude in VS Code: the project's window is waited for and brought forward, then the chat opens in it
    seen = iter([[], [], [7], [7]])
    monkeypatch.setattr(assistants, "_vscode_windows", lambda part: next(seen, [7]) if part == f"{built.slug} (Workspace)" else [])
    monkeypatch.setattr(assistants, "_in_front", lambda hwnd: hwnd == 7)
    runs.clear()
    message = assistants.start(built, "vscode-claude")
    assert runs == [([code, wsfile], None), ([code, wsfile], None)]          # started, then brought forward
    assert opened == [f"vscode://anthropic.claude-code/open?prompt=%2Fcontextmax-{built.slug}%20"]
    assert f"/contextmax-{built.slug} typed in" in message
    # no window within the wait: said, and no link sent to whichever window happens to be in front
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(assistants, "_vscode_windows", lambda part: [])
    monkeypatch.setattr(assistants.time, "monotonic", lambda: next(clock))
    message = assistants.start(built, "vscode-claude")
    assert "did not appear" in message and len(opened) == 1

    assistants.start(built, "codex")
    assert runs[-1] == (["cmd.exe", "/k", "codex"], str(built.workspace)) and skills[-1] == "codex"
    with pytest.raises(ValueError):
        assistants.start(built, "notepad")
    monkeypatch.setattr(assistants, "_which", lambda name: rf"C:\Tools\{name}.exe")
    message = assistants.start(built, "claude")
    # Claude Code in a terminal starts with the skill's name as its first message: the skill loads at once
    assert runs[-1] == (["cmd.exe", "/k", r"C:\Tools\claude.exe", f"/contextmax-{built.slug}"], str(built.workspace))
    assert "loads the project's skill" in message


def test_codex_gets_the_skill_only_where_codex_is(built, monkeypatch, tmp_path):
    monkeypatch.setattr(agentskill, "HOSTS", {"claude": tmp_path / ".claude" / "skills",
                                              "codex": tmp_path / ".codex" / "skills"})
    assert [line.split(":")[0] for line in agentskill.install(built, "all")] == ["claude"]
    (tmp_path / ".codex").mkdir()
    assert [line.split(":")[0] for line in agentskill.install(built, "all")] == ["claude", "codex"]


def test_the_ways_in_come_from_the_index_each_place_once(built):
    ins = reading.ways_in(built, "What is the settle time, and do the documents agree?")
    assert ins[0]["kind"] == "document" and "settle time" in ins[0]["why"]
    docs = {e["key"] for e in ins if e["kind"] == "document"}
    assert {"Detailed_design_v2.1", "Test_plan", "System_requirements_v1.2"} <= docs   # every one that states it
    assert "System_requirements_v1.1" not in docs                                      # a copy is read once
    assert len({reading._place(e) for e in ins}) == len(ins) <= reading.MAX_SOURCES
    code = reading.ways_in(built, "How does read_sensor remove the offset?")
    assert any(e["kind"] == "code" and e["file"].endswith("sensor.c") for e in code)
    assert reading.ways_in(built, "the and of") == []


class _FakeModel(BaseHTTPRequestHandler):
    """Ollama's /api/chat and /api/tags, and the OpenAI-style /v1 API, answering in two pieces."""
    asked: list = []

    def log_message(self, *a):
        pass

    def _out(self, body: bytes, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/v1/models":
            return self._out(json.dumps({"data": [{"id": "small"}, {"id": "big"}]}).encode())
        if self.path == "/api/tags":
            return self._out(json.dumps({"models": [{"name": "small", "size": 1, "capabilities": ["completion"]},
                                                    {"name": "big", "size": 9, "capabilities": ["tools"]}]}).encode())
        self.send_error(404)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeModel.asked.append((self.path, body))
        if self.path == "/api/chat" and body.get("format"):
            # one passage read: the line with "settle time" quoted, and one quote the file does not hold
            text = body["messages"][-1]["content"]
            hit = next((ln for ln in text.split("\n") if "settle time" in ln.lower() and ln.split(":")[0].isdigit()), None)
            reading_ = {"relevant": bool(hit), "says": "it states the settle time" if hit else "", "follow": [],
                        "quotes": [{"line": int(hit.split(":")[0]), "text": hit.split(":", 1)[1].strip()},
                                   {"line": 1, "text": "the settle time is 99 hours"}] if hit else []}
            return self._out(json.dumps({"message": {"role": "assistant", "content": json.dumps(reading_)}}).encode())
        if self.path == "/api/chat":
            lines = [{"message": {"content": "Twelve "}}, {"message": {"content": "ms [1]."}, "done": True}]
            return self._out(b"".join(json.dumps(x).encode() + b"\n" for x in lines), "application/x-ndjson")
        chunks = [{"choices": [{"delta": {"content": "Twelve "}}]}, {"choices": [{"delta": {"content": "ms [1]."}}]}]
        return self._out(b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n",
                         "text/event-stream")


@pytest.fixture
def fake_model():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _FakeModel.asked = []
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_a_model_on_this_pc_answers_in_pieces_in_both_dialects(built, fake_model):
    msgs = [{"role": "system", "content": "answer"}, {"role": "user", "content": "settle time? [1] ..."}]
    assert "".join(ask.stream("ollama", fake_model, "big", msgs)) == "Twelve ms [1]."
    assert "".join(ask.stream("openai", fake_model, "big", msgs)) == "Twelve ms [1]."
    sent = _FakeModel.asked[0][1]
    assert sent["options"]["num_ctx"] == 8192 and sent["messages"][0]["role"] == "system"
    assert ask._ollama_order(fake_model, ["small", "big"], 2) == ["big", "small"]


def test_an_answer_cut_off_is_an_error_not_an_answer(built, monkeypatch):
    import io

    class Cut(io.BytesIO):
        def __iter__(self):
            yield b'{"message": {"content": "The settle time is 12 ms [1] and the"}}\n'
            import http.client
            raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(ask._DIRECT, "open", lambda req, timeout=None: Cut())
    pieces = []
    with pytest.raises(ask.AskError, match="stopped in the middle"):
        for piece in ask.stream("ollama", "http://127.0.0.1:11434", "m", []):
            pieces.append(piece)
    assert pieces == ["The settle time is 12 ms [1] and the"]


def test_only_a_model_on_this_pc_is_ever_asked(built):
    for base in ("http://192.168.1.20:11434", "https://127.0.0.1:11434", "http://example.com",
                 "http://evil.example\\@127.0.0.1", "http://user@127.0.0.1:11434"):
        with pytest.raises(ask.AskError, match="not a model on this PC"):
            list(ask.stream("ollama", base, "m", []))


def test_the_window_asks_and_hands_back_answer_and_sources(built, fake_model, monkeypatch):
    import time
    import urllib.error
    import urllib.request

    from contextmax import panel

    panel.Handler.token = "secret"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def api(action, **body):
        req = urllib.request.Request(f"{base}/api/{action}", data=json.dumps(dict(slug=built.slug, **body)).encode(),
                                     method="POST", headers={"X-CMX-Token": "secret", "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())

    try:
        assert "__TOKEN__" not in urllib.request.urlopen(f"{base}/ask?slug={built.slug}", timeout=5).read().decode()
        with pytest.raises(urllib.error.HTTPError) as refused:     # a server ContextMAX does not list
            api("ask", question="What is the settle time?", kind="ollama", base=fake_model, model="big")
        assert refused.value.code == 400
        monkeypatch.setattr(ask, "SERVERS", (("Fake", fake_model, "ollama"),))
        job = api("ask", question="What is the settle time?", kind="ollama", base=fake_model, model="big")["job"]
        for _ in range(100):
            r = api("ask-poll", job=job, since=0)
            if r["done"]:
                break
            time.sleep(0.05)
        assert r["text"] == "Twelve ms [1]." and not r["error"]
        reads = [s for s in r["steps"] if s["step"] == "read"]
        done = [s for s in r["steps"] if s["step"] == "read done"]
        assert reads and len(reads) == len(done) <= reading.MAX_SOURCES + reading.MAX_FOLLOW
        hit = next(s for s in done if s["relevant"])
        assert hit["held"] == 1 and hit["missing"] == 1           # the invented quote is not in the file: left out
        assert r["confidence"]["level"] == "Medium"               # the documents give the settle time two values
        doc = r["sources"][0]["window"]
        assert Path(doc["path"]).is_absolute() and doc["line_link"].startswith(f"/lines?slug={built.slug}&key=")
        quote = r["sources"][0]["quotes"][0]
        assert quote["checked"] and "settle time" in quote["text"].lower() and "99 hours" not in json.dumps(r["sources"])
        assert " · " in doc["cite"] and "line" in doc["cite"]              # one citation format
        sent = [b for path, b in _FakeModel.asked if path == "/api/chat"]
        assert sent[0]["format"] and sent[0]["options"]["temperature"] == 0 and sent[-1]["stream"] is True
        assert "checked against the file" in sent[-1]["messages"][0]["content"]
        # the line viewer: the cited line, with the lines around it
        key = doc["line_link"].split("key=")[1].split("&")[0]
        lines = api("lines", key=key, n=2, before=1, after=1)
        assert lines["first"] == 1 and len(lines["lines"]) == 3 and lines["total"] >= 3
        assert "__TOKEN__" not in urllib.request.urlopen(f"{base}/lines?slug={built.slug}&key={key}&n=2", timeout=5).read().decode()
        with pytest.raises(urllib.error.HTTPError):
            api("lines", key="not-a-document", n=1)
        with pytest.raises(urllib.error.HTTPError):                 # only a model ContextMAX suggests is downloaded
            api("ollama-pull", model="evil & calc")
    finally:
        srv.shutdown()
