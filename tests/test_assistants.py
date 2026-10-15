"""Ask your AI: the working folder made ready for assistants, what starting one runs, and asking a model on
this PC (a fake Ollama and a fake OpenAI-style server stand in for the real ones)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from contextmax import agentskill, ask, assistants


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
    wsfile = str(built.workspace / f"{built.slug}.code-workspace")
    assistants.start(built, "vscode")
    assert runs[-1] == ([str(tmp_path / "VS Code" / "Code.exe"), wsfile], None) and skills == ["copilot"]
    assistants.start(built, "vscode-claude")
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.name.startswith("Thread"):
            t.join(timeout=2)
    assert opened == [f"vscode://anthropic.claude-code/open?prompt=Using%20the%20contextmax-{built.slug}%20skill%3A%20"]
    assistants.start(built, "codex")
    assert runs[-1] == (["cmd.exe", "/k", "codex"], str(built.workspace)) and skills[-1] == "codex"
    with pytest.raises(ValueError):
        assistants.start(built, "notepad")
    monkeypatch.setattr(assistants, "_which", lambda name: f"C:\\Tools\\{name}.exe")
    assistants.start(built, "claude")
    assert runs[-1] == (["cmd.exe", "/k", "C:\\Tools\\claude.exe"], str(built.workspace))


def test_codex_gets_the_skill_only_where_codex_is(built, monkeypatch, tmp_path):
    monkeypatch.setattr(agentskill, "HOSTS", {"claude": tmp_path / ".claude" / "skills",
                                              "codex": tmp_path / ".codex" / "skills"})
    assert [line.split(":")[0] for line in agentskill.install(built, "all")] == ["claude"]
    (tmp_path / ".codex").mkdir()
    assert [line.split(":")[0] for line in agentskill.install(built, "all")] == ["claude", "codex"]


def test_the_sources_come_from_the_index_each_once(built):
    found = ask.sources(built, "What is the settle time, and do the documents agree?")
    values = [s for s in found if s["kind"] == "value"]
    assert values and all("settle" in s["text"] for s in values)
    assert len({(s["kind"], s["cite"], s["text"]) for s in found}) == len(found)
    assert [s["n"] for s in found] == list(range(1, len(found) + 1))
    code = ask.sources(built, "How does read_sensor remove the offset?")
    assert code[0]["kind"] == "code" and code[0]["label"] == "read_sensor" and "sensor.c" in code[0]["cite"]
    assert ask.sources(built, "the and of") == []


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
    msgs = ask.messages(built, "settle time?", ask.sources(built, "settle time?"))
    assert "".join(ask.stream("ollama", fake_model, "big", msgs)) == "Twelve ms [1]."
    assert "".join(ask.stream("openai", fake_model, "big", msgs)) == "Twelve ms [1]."
    sent = _FakeModel.asked[0][1]
    assert sent["options"]["num_ctx"] == 8192 and sent["messages"][0]["role"] == "system"
    assert "[1] (" in sent["messages"][1]["content"]
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
        doc = next(s for s in r["sources"] if s["kind"] == "document")
        assert Path(doc["path"]).is_absolute() and doc["text_link"].startswith(f"/ws/{built.slug}/documents/text/")
    finally:
        srv.shutdown()
