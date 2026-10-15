"""The ContextMAX window: choose folders, check this PC, build, open the pages, ask an AI.

A small web server on 127.0.0.1 only, with a random token per session: other machines cannot
reach it, and other web pages cannot drive it (every action needs the token in a header,
which a page from elsewhere can neither read nor send). The folder picker is the Windows
one, opened by a short helper process. Builds run as their own process, so the window keeps
answering and shows the build's output line by line.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from contextmax import checkup, project, util

ASSETS = Path(__file__).resolve().parent / "views" / "assets"
JOBS: dict[str, dict] = {}
ASKS: dict[str, dict] = {}             # questions to a model on this PC, answered in pieces
MAX_REQUEST_BYTES = 1_000_000          # the window's own requests are a few hundred bytes
PICK_TITLE = "Choose a folder for ContextMAX to read"


def _state(slug: str | None) -> dict:
    reg = project.list_projects()
    out = {"projects": [{"slug": s, "workspace": w} for s, w in reg.items()], "project": None}
    if slug and slug in reg:
        p = project.lookup(slug)
        meta = util.load_json(p.catalogue_dir / "folders.json", default={}) or {}
        counts = {f["name"]: f for f in meta.get("folders", [])}
        man = util.load_json(p.workspace / "buildinfo.json", default={}) or {}
        out["project"] = {
            "name": p.name, "slug": p.slug, "workspace": str(p.workspace),
            "download_cloud_files": p.download_cloud_files,
            "folders": [{"name": f.name, "path": f.path, "holds": f.holds, "exists": Path(f.path).is_dir(),
                         "files": (counts.get(f.name) or {}).get("files")} for f in p.folders],
            "built": man.get("built_utc"), "confidence": (man.get("completeness") or {}).get("confidence"),
            "problems": (man.get("completeness") or {}).get("problems", []),
            "home": f"/ws/{p.slug}/Home.html" if (p.workspace / "Home.html").exists() else None,
        }
    return out


def _with_window(html: bytes, slug: str, token: str) -> bytes:
    """A project page served here learns it may ask this window (open a file, start an assistant): the
    token goes in, as for the window itself, so another web page still cannot ask."""
    tag = ("<script>window.CMX_PANEL=" + json.dumps({"token": token, "slug": slug}).replace("</", "<\\/")
           + ";</script>").encode("utf-8")
    at = html.find(b"<head>")
    return html[:at + 6] + tag + html[at + 6:] if at >= 0 else tag + html


def _page_source(slug: str, s: dict) -> dict:
    """A source as the ask page shows it: where it is, and how to open it."""
    out = {k: s.get(k) for k in ("n", "kind", "label", "cite", "text")}
    if s["kind"] == "code":
        out["editor"] = "vscode://file/" + quote(str(Path(s["root"]) / s["file"]).replace("\\", "/"), safe="/:") + f":{s['line']}"
    elif s["kind"] == "document":
        p = project.lookup(slug)
        root = next((f.path for f in p.folders if f.name == s.get("folder")), None)
        out["path"] = str(Path(root) / s["relative_path"]) if root and s.get("relative_path") else None
        out["text_link"] = f"/ws/{slug}/documents/{s['cached_text']}" if s.get("cached_text") else None
    return out


def _run_ask(job: str, slug: str, question: str, kind: str, base: str, model: str) -> None:
    from contextmax import ask

    j = ASKS[job]
    try:
        p = project.lookup(slug)
        found = ask.sources(p, question)
        j["sources"] = [_page_source(slug, s) for s in found]
        for piece in ask.stream(kind, base, model, ask.messages(p, question, found)):
            j["text"] += piece
    except (ask.AskError, OSError, ValueError, SystemExit) as exc:
        j["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - whatever stops the answer is said, never shown as "done"
        j["error"] = f"the answer stopped: {type(exc).__name__}: {exc}"
    finally:
        j["done"] = True


def _run_build(job: str, slug: str, depth: str) -> None:
    cmd = [sys.executable, "-m", "contextmax", "build", slug] + ([f"--{depth}"] if depth in ("catalogue", "documents", "full") else [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for raw in proc.stdout:
        JOBS[job]["lines"].append(raw.decode("utf-8", "replace").rstrip())
    JOBS[job]["code"] = proc.wait()
    JOBS[job]["done"] = True


class Handler(BaseHTTPRequestHandler):
    token = ""

    def log_message(self, *args):  # quiet: the window shows what matters
        pass

    def _addressed_here(self) -> bool:
        """Only a request addressed to this window by its own address: a web page that points its own
        name at 127.0.0.1 (DNS rebinding) sends its own name, and is refused."""
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _reply(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):  # noqa: N802 - the http.server name
        if not self._addressed_here():
            return self._send(403, b"not allowed", "text/plain")
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html", "/ask"):
            page = "ask.html" if path == "/ask" else "panel.html"
            html = (ASSETS / page).read_text(encoding="utf-8").replace("__TOKEN__", self.token)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            f = ASSETS / path[len("/assets/"):]
            if f.resolve().parent == ASSETS.resolve() and f.is_file():
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        if path.startswith("/ws/"):
            parts = path[4:].split("/", 1)
            reg = project.list_projects()
            if len(parts) == 2 and parts[0] in reg:
                base = Path(reg[parts[0]]).resolve()
                f = (base / parts[1]).resolve()
                if (f == base or base in f.parents) and f.is_file():
                    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                    body = f.read_bytes()
                    if ctype == "text/html":
                        body = _with_window(body, parts[0], self.token)
                    if ctype.startswith("text/") or f.suffix in (".js", ".json"):
                        ctype += "; charset=utf-8"
                    return self._send(200, body, ctype)
        self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        # Read the body before any answer, a refusal included: closing a connection that still
        # holds unread data makes Windows reset it, and the caller sees an error, not the answer.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_REQUEST_BYTES:
            self.close_connection = True
            return self._reply({"error": "bad request"}, 400)
        raw = self.rfile.read(length) if length else b""
        if self.headers.get("X-CMX-Token") != self.token or not self._addressed_here():
            return self._reply({"error": "not allowed"}, 403)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._reply({"error": "bad request"}, 400)
        action = urlparse(self.path).path.rsplit("/", 1)[-1]
        try:
            return self._reply(self._act(action, body))
        except (ValueError, SystemExit) as exc:
            return self._reply({"error": str(exc)}, 400)

    def _act(self, action: str, b: dict):
        slug = b.get("slug")
        if action == "state":
            return _state(slug)
        if action == "checkup":
            return {"checks": checkup.checks()}
        if action == "create":
            name = (b.get("name") or "").strip()
            if not name:
                raise ValueError("give the project a name")
            p = project.create(name, [])
            return _state(p.slug)
        if action == "pick":
            # the dialog runs in a process of its own, so the window keeps answering while it is open
            try:
                r = subprocess.run([sys.executable, "-m", "contextmax.winshell", "pick", PICK_TITLE], capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=600,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired as exc:
                raise ValueError("the folder picker stayed open for ten minutes and was closed; try again") from exc
            if r.returncode != 0:
                last = (r.stderr or "").strip().splitlines()[-1:] or ["no message"]
                raise ValueError(f"the folder picker failed: {last[0]}")
            return {"path": (r.stdout or "").strip()}
        if action == "assistants":
            from contextmax import ask, assistants

            return {"tools": assistants.tools(), "servers": ask.servers(),
                    "ollama_installed": bool(shutil.which("ollama"))}
        if action == "ask-poll":
            j = ASKS.get(b.get("job")) or {"text": "", "done": True, "error": "no such question", "sources": []}
            since = int(b.get("since") or 0)
            done, text = j["done"], j["text"]      # done first: text read after it holds every last piece
            return {"text": text[since:], "next": len(text), "done": done, "error": j["error"],
                    "sources": j["sources"]}
        if action == "files":
            from contextmax import opener

            try:
                return {"message": opener.open_path(str(b.get("path") or ""), "select" if b.get("how") == "select" else "open")}
            except OSError as exc:
                raise ValueError(f"Windows could not open it: {exc}") from exc
        p = project.lookup(slug)
        if action == "add":
            project.add_folder(p, b["path"], b.get("name") or None, b.get("holds") or "both")
        elif action == "remove":
            project.remove_folder(p, b["name"])
        elif action == "holds":
            for f in p.data["folders"]:
                if f["name"] == b["name"]:
                    f["holds"] = b["holds"]
            p.save()
        elif action == "option":
            p.data["download_cloud_files"] = bool(b.get("download_cloud_files"))
            p.save()
        elif action == "build":
            job = secrets.token_hex(6)
            JOBS[job] = {"lines": [], "done": False, "code": None}
            threading.Thread(target=_run_build, args=(job, p.slug, b.get("depth") or "quick"), daemon=True).start()
            return {"job": job}
        elif action == "job":
            j = JOBS.get(b.get("job"), {"lines": [], "done": True, "code": None})
            since = int(b.get("since") or 0)
            done, lines = j["done"], list(j["lines"])
            return {"lines": lines[since:], "next": len(lines), "done": done, "code": j["code"]}
        elif action == "assistant":
            from contextmax import assistants

            try:
                return {"message": assistants.start(p, str(b.get("tool") or ""))}
            except OSError as exc:
                raise ValueError(f"could not start it: {exc}") from exc
        elif action == "ask":
            from contextmax import ask

            question = str(b.get("question") or "").strip()
            if not question:
                raise ValueError("ask a question")
            if not ask.listed(str(b.get("kind") or ""), str(b.get("base") or "")):
                raise ValueError("not one of the model servers ContextMAX looks for on this PC")
            job = secrets.token_hex(6)
            ASKS[job] = {"text": "", "done": False, "error": "", "sources": []}
            threading.Thread(target=_run_ask, args=(job, p.slug, question[:2000], str(b.get("kind") or "openai"),
                                                    str(b.get("base") or ""), str(b.get("model") or "")), daemon=True).start()
            return {"job": job}
        elif action == "skill":
            from contextmax import agentskill, assistants
            return {"lines": agentskill.install(p, "all") + assistants.prepare(p)}
        elif action == "open":
            target = p.workspace / "Home.html"
            if target.exists() and sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            return {"ok": target.exists()}
        else:
            raise ValueError(f"unknown action {action}")
        return _state(p.slug)


def serve(slug: str | None = None, port: int = 0, open_browser: bool = True) -> int:
    Handler.token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/" + (f"#{slug}" if slug else "")
    print(f"ContextMAX window: {url}\n(close this window, or press Ctrl+C, to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
