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
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from contextmax import checkup, project, util

ASSETS = Path(__file__).resolve().parent / "views" / "assets"
JOBS: dict[str, dict] = {}
ASKS: dict[str, dict] = {}             # questions to a model on this PC, answered in pieces
MAX_REQUEST_BYTES = 1_000_000          # the window's own requests are a few hundred bytes
STOPPED = 3                            # a build's exit code when it stopped as asked (cli.STOPPED)
EVENTS_PER_POLL = 12                   # live build events per answer: a few megabytes at most
PICK_TITLE = "Choose a folder for ContextMAX to read"
DEPTHS = {"documents": "Read documents and build", "quick": "Quick refresh", "full": "Rebuild everything",
          "catalogue": "Catalogue only"}
SKILL_HOSTS = {"claude": "Claude Code", "copilot": "VS Code with Copilot", "codex": "Codex"}
ATLAS_DATA = b'<script type="application/json" id="cmx-data">'
_TELL = threading.Lock()
_SEEN = {"slug": None}                 # the project the window shows now, to say when it changes


def tell(message: str, slug: str | None = None) -> None:
    """The CMD window that runs ContextMAX: what the window does, as it does it, and every line of a build."""
    line = time.strftime("%H:%M:%S") + "  " + (f"{slug} | " if slug else "") + message if message else ""
    with _TELL:
        try:
            print(line, flush=True)
        except (OSError, ValueError, AttributeError):     # no console (pythonw), or one that cannot show a character
            pass


def _card(slug: str, workspace: str) -> dict:
    """One project on the start screen: its folders and how fresh its index is."""
    out = {"slug": slug, "name": slug, "workspace": workspace, "found": False, "folders": []}
    try:
        p = project.lookup(slug)
    except (SystemExit, ValueError, OSError):
        return out
    out.update(name=p.name, found=True, folders=[f.name for f in p.folders])
    out.update(_facts(p))
    return out


def _facts(p) -> dict:
    """What the last build made, from build info: the one record of it."""
    man = util.load_json(p.workspace / "buildinfo.json", default={}) or {}
    comp, cbs = man.get("completeness") or {}, (man.get("code_bases") or {}).values()
    return {"built": man.get("built_utc"), "confidence": comp.get("confidence"), "problems": comp.get("problems", []),
            "stamp": man.get("outputs_hash"),
            "files": (man.get("catalogue") or {}).get("file_total"),
            "documents": (man.get("text_store") or {}).get("docs_count"),
            "functions": sum(int(c.get("functions_count") or 0) for c in cbs) if man.get("code_bases") else None,
            "links": (man.get("corpus") or {}).get("doc_doc_edges_count"),
            "home": f"/ws/{p.slug}/Home.html" if (p.workspace / "Home.html").exists() else None,
            "atlas": (p.pages_dir / "atlas.html").exists()}


def _skill_status(p) -> dict:
    """For each assistant: whether this project's skill is installed, and whether it is this build's."""
    from contextmax import agentskill, assistants

    want = agentskill.compose(p)
    on_pc = {"claude": (Path.home() / ".claude").is_dir() or bool(assistants._installed("claude")) or assistants._claude_in_vscode(),
             "copilot": bool(assistants._vscode()),
             "codex": (Path.home() / ".codex").is_dir() or bool(assistants._installed("codex"))}
    hosts = []
    for name, base in agentskill.HOSTS.items():
        f = base / f"contextmax-{p.slug}" / "SKILL.md"
        try:
            have = f.read_text(encoding="utf-8") if f.is_file() else None
        except OSError:
            have = None
        hosts.append({"host": name, "label": SKILL_HOSTS.get(name, name), "path": str(f.parent), "on_pc": on_pc.get(name, False),
                      "installed": have is not None, "current": have == want})
    guide = p.workspace / "CLAUDE.md"
    try:
        guided = guide.is_file() and assistants.BEGIN in guide.read_text(encoding="utf-8")
    except OSError:
        guided = False
    return {"hosts": hosts, "guide": guided, "workspace": str(p.workspace), "slug": p.slug}


def _make_sure_it_stops(job: str, wait: float = 30.0) -> None:
    """A build asked to stop stops at its next step; one that is still busy after `wait` seconds (inside a
    long scan read one page after another) is ended, with every process it started."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        if JOBS[job]["done"]:
            return
        time.sleep(0.5)
    pid = JOBS[job].get("pid")
    if pid and not JOBS[job]["done"]:
        JOBS[job]["lines"].append("[stop] the build did not stop by itself within half a minute: it was ended")
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _refresh_skill(slug: str) -> list[str]:
    """After a build: the skill, where it is installed, describes this build, and the working folder's guide
    lists the folders the project has now. Where it is not installed, nothing is written."""
    from contextmax import agentskill, assistants

    p = project.lookup(slug)
    hosts = [name for name, base in agentskill.HOSTS.items() if (base / f"contextmax-{p.slug}" / "SKILL.md").is_file()]
    for name in hosts:
        agentskill.install(p, name)
    if hosts:
        assistants.prepare(p)
    return [SKILL_HOSTS.get(h, h) for h in hosts]


def _last_build(p) -> dict | None:
    """How the newest build of the project ended, from its saved log: finished, stopped, stopped by the
    gate (with what it found), failed, or cut off (a log with no end: the process was ended)."""
    logs = sorted(p.path("logs").glob("build-*.txt"))
    if not logs:
        return None
    try:
        lines = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    end = lines[-1] if lines else ""
    gate = [ln.split("- ", 1)[1] for ln in lines if ln.startswith("[gate]   - ")]
    if not end.startswith("ended "):
        state = "cut off"
    elif end.endswith("with exit code 0"):
        state = "finished"
    elif " stopped: " in end:
        state = "stopped"
    elif any("VALIDATION FAILED" in ln for ln in lines):
        state = "gate"
    else:
        state = "failed"
    return {"state": state, "when": lines[0].rsplit("started ", 1)[-1] if lines else "", "gate": gate[:5],
            "log": f"/ws/{p.slug}/logs/{logs[-1].name}"}


def _freshness(p) -> dict:
    """What to press next: how the last build ended, what it could not read, and what changed in the
    folders since. Looks at the folders now; writes nothing."""
    from contextmax import catalogue

    dm = p.documents_dir
    built = (p.workspace / "buildinfo.json").exists()
    rows = util.load_jsonl(dm / "text-index.jsonl")
    unread = [{"name": r.get("name") or r.get("key"), "why": r.get("reason", "")} for r in util.csv_rows(dm / "not-read.csv")]
    no_text = [r["key"] for r in rows if r.get("ocr_problem")]
    partial = [r["key"] for r in rows if r.get("ocr_partial")]
    cloud = [r.get("name") for r in util.csv_rows(dm / "not-downloaded.csv")]
    last = _last_build(p)
    changes = catalogue.since_last(p) if (p.catalogue_dir / "all-files.csv").exists() else None
    changed = bool(changes and (changes["new"] or changes["changed"] or changes["removed"]))
    if not built and not last:
        advice, why = "documents", "Not built yet."
    elif last and last["state"] != "finished" and last["state"] != "gate":
        advice, why = "documents", {"stopped": "The last build was stopped before the end.",
                                    "cut off": "The last build was ended before it finished (its window was closed).",
                                    "failed": "The last build stopped with an error."}[last["state"]]
    elif changed:
        advice, why = "documents", "The folders changed since the last build."
    elif last and last["state"] == "gate":
        advice, why = "documents", "The last build stopped at the validation gate."
    elif unread or no_text or partial:
        advice, why = "full", "Everything was read except the documents below; Rebuild everything tries them again."
    else:
        advice, why = None, "Up to date: the index holds everything in the folders."
    return {"slug": p.slug, "advice": advice, "why": why, "last": last, "changes": changes,
            "missed": {"unread": unread, "no_text": no_text, "partial": partial, "cloud": cloud}}


def _atlas_data(slug: str) -> bytes | None:
    """The Complete Atlas of the last build, as its page holds it: the window draws it with the same code."""
    page = project.lookup(slug).pages_dir / "atlas.html"
    try:
        html = page.read_bytes()
    except OSError:
        return None
    at = html.find(ATLAS_DATA)
    if at < 0:
        return None
    at += len(ATLAS_DATA)
    end = html.find(b"</script>", at)      # the data holds no "<" (util.html_json), so this is its end
    return html[at:end] if end > at else None


def _state(slug: str | None) -> dict:
    reg = project.list_projects()
    out = {"projects": [{"slug": s, "workspace": w} for s, w in reg.items()], "project": None}
    if slug and slug in reg:
        p = project.lookup(slug)
        if _SEEN["slug"] != slug:
            _SEEN["slug"] = slug
            tell(f"project opened in the window ({p.workspace})", slug)
        meta = util.load_json(p.catalogue_dir / "folders.json", default={}) or {}
        counts = {f["name"]: f for f in meta.get("folders", [])}
        out["project"] = {
            "name": p.name, "slug": p.slug, "workspace": str(p.workspace),
            "download_cloud_files": p.download_cloud_files,
            "folders": [{"name": f.name, "path": f.path, "holds": f.holds, "exists": Path(f.path).is_dir(),
                         "files": (counts.get(f.name) or {}).get("files")} for f in p.folders],
            **_facts(p),
        }
    return out


def _with_window(html: bytes, slug: str, token: str) -> bytes:
    """A project page served here learns it may ask this window (open a file, start an assistant): the
    token goes in, as for the window itself, so another web page still cannot ask."""
    tag = ("<script>window.CMX_PANEL=" + json.dumps({"token": token, "slug": slug}).replace("</", "<\\/")
           + ";</script>").encode("utf-8")
    at = html.find(b"<head>")
    return html[:at + 6] + tag + html[at + 6:] if at >= 0 else tag + html


def _page_window(slug: str, w: dict) -> dict:
    """A passage the model read, as the Ask page shows it: where it is, and how to open it (the code in the
    editor; a document as itself, or its text at the line; a picture as itself)."""
    out = {k: w.get(k) for k in ("kind", "cite", "first", "last", "line")}
    if w.get("root") and w.get("file"):
        full = Path(w["root"]) / w["file"]
        out["editor"] = "vscode://file/" + quote(str(full).replace("\\", "/"), safe="/:") + f":{w.get('line') or 1}"
        out["code_path"] = str(full)
    elif w.get("key"):
        p = project.lookup(slug)
        row = next((r for r in util.load_jsonl(p.documents_dir / "text-index.jsonl") if r["key"] == w["key"]), {})
        root = next((f.path for f in p.folders if f.name == row.get("folder")), None)
        out["path"] = str(Path(root) / row["relative_path"]) if root and row.get("relative_path") else None
        out["line_link"] = f"/lines?slug={quote(slug)}&key={quote(w['key'])}&n={int(w.get('line') or 1)}"
    elif w.get("path"):
        out["path"] = w["path"]
    return out


def _page_quote(slug: str, q: dict) -> dict:
    """One line of a source as the Ask page shows it: a line ContextMAX looked up itself opens where it is."""
    out = {k: v for k, v in q.items() if k not in ("root", "file", "key")}
    if q.get("root") and q.get("file"):
        full = Path(q["root"]) / q["file"]
        out["editor"] = "vscode://file/" + quote(str(full).replace("\\", "/"), safe="/:") + f":{q.get('line') or 1}"
    elif q.get("key"):
        out["line_link"] = f"/lines?slug={quote(slug)}&key={quote(q['key'])}&n={int(q.get('line') or 1)}"
    return out


LINES_SPAN = 60                        # lines the line viewer sends around the one asked for


def _lines(slug: str, key: str, n: int, before: int = LINES_SPAN, after: int = LINES_SPAN) -> dict:
    """Lines of one document's extracted text around line n, with the pages they are on (for a PDF)."""
    from contextmax import citations

    p = project.lookup(slug)
    row = next((r for r in util.load_jsonl(p.documents_dir / "text-index.jsonl") if r["key"] == key), None)
    if row is None:
        raise ValueError("this document is not in the project's index")
    path = (p.documents_dir / row["cached_text"]).resolve()
    if p.documents_dir.resolve() not in path.parents:
        raise ValueError("not a text of this project")
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    first, last = max(1, n - before), min(len(lines), n + after)
    stage = next((d.get("stage") for d in util.load_jsonl(p.documents_dir / "doc-list.jsonl") if d["key"] == key), None)
    root = next((f.path for f in p.folders if f.name == row.get("folder")), None)
    return {"title": row.get("doc_title") or Path(row.get("relative_path") or key).name, "stage": stage, "key": key,
            "n": n, "first": first, "total": len(lines), "lines": lines[first - 1:last],
            "pages": [citations.page_of(row.get("page_lines"), k) for k in range(first, last + 1)]
            if row.get("page_lines") else None,
            "path": str(Path(root) / row["relative_path"]) if root and row.get("relative_path") else None,
            "text_link": f"/ws/{slug}/documents/{row['cached_text']}"}


def _run_ask(job: str, slug: str, question: str, kind: str, base: str, model: str) -> None:
    """The guided reading (reading.py): every step goes to the page as it happens, then the answer."""
    from contextmax import ask, reading

    j = ASKS[job]
    try:
        p = project.lookup(slug)

        def said(e: dict) -> None:
            if e.get("window"):
                e = dict(e, window=_page_window(slug, e["window"]))
            if e["step"] == "sources":
                j["sources"] = [dict(x, window=_page_window(slug, x["window"]), quotes=[_page_quote(slug, q) for q in x["quotes"]])
                                for x in e["sources"]]
                return
            if e["step"] == "confidence":
                j["confidence"] = {"level": e["level"], "why": e["why"]}
            j["steps"].append(e)
            if e["step"] == "read":
                tell(f"the model reads {e['window']['cite']}", slug)

        for piece in reading.analyse(p, kind, base, model, question, said):
            j["text"] += piece
    except (ask.AskError, OSError, ValueError, SystemExit) as exc:
        j["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - whatever stops the answer is said, never shown as "done"
        j["error"] = f"the answer stopped: {type(exc).__name__}: {exc}"
    finally:
        j["done"] = True


def _run_build(job: str, slug: str, depth: str) -> None:
    """The build in its own process. It also reports what it has found so far (util.live), always: the
    window can then draw the build live from its first event even when that is switched on halfway.
    Those lines go to the drawing; every other line goes to the text log and to the CMD window."""
    cmd = [sys.executable, "-m", "contextmax", "build", slug] + ([f"--{depth}"] if depth in ("catalogue", "documents", "full") else [])
    stop_file = Path(tempfile.gettempdir()) / f"contextmax-stop-{job}"
    stop_file.unlink(missing_ok=True)
    JOBS[job]["stop_file"] = str(stop_file)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", CONTEXTMAX_LIVE="1", CONTEXTMAX_STOP_FILE=str(stop_file))
    t0 = time.monotonic()
    tell(f"build started: {DEPTHS.get(depth, depth)}", slug)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        JOBS[job]["lines"].append(f"the build could not start: {exc}")
        tell(f"the build could not start: {exc}", slug)
        JOBS[job]["code"], JOBS[job]["done"] = 1, True
        return
    JOBS[job]["pid"] = proc.pid
    mark = util.LIVE_MARK.encode("utf-8")
    for raw in proc.stdout:
        if raw.startswith(mark):
            try:
                JOBS[job]["events"].append(json.loads(raw[len(mark):]))
                continue
            except ValueError:
                pass
        line = raw.decode("utf-8", "replace").rstrip()
        JOBS[job]["lines"].append(line)
        tell(line, slug)
    code = proc.wait()
    stop_file.unlink(missing_ok=True)
    if code == 0:
        try:
            hosts = _refresh_skill(slug)
        except (OSError, ValueError, SystemExit) as exc:
            hosts = []
            JOBS[job]["lines"].append(f"[skill] could not bring the AI skill up to date: {exc}")
        if hosts:
            JOBS[job]["lines"].append("[skill] the AI skill now describes this build, for " + ", ".join(hosts))
            tell("AI skill brought up to date for " + ", ".join(hosts), slug)
    tell(f"build finished in {util.clock(time.monotonic() - t0)}" if code == 0 else
         "build stopped, as asked; what it finished is kept" if code == STOPPED or JOBS[job].get("stopping") else
         f"build stopped with a problem (exit code {code}); the lines above say why", slug)
    JOBS[job]["code"] = code
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
        if path in ("/", "/index.html", "/ask", "/lines"):
            page = {"/ask": "ask.html", "/lines": "lines.html"}.get(path, "panel.html")
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
            if action == "atlas":
                data = _atlas_data(str(body.get("slug") or ""))
                return self._send(200, data) if data else self._reply({"error": "this project has no Complete Atlas yet"}, 404)
            return self._reply(self._act(action, body))
        except (ValueError, SystemExit) as exc:
            tell(f"could not {action}: {exc}", body.get("slug") if isinstance(body, dict) else None)
            return self._reply({"error": str(exc)}, 400)

    def _act(self, action: str, b: dict):
        slug = b.get("slug")
        if action == "state":
            return _state(slug)
        if action == "projects":
            return {"projects": [_card(s, w) for s, w in project.list_projects().items()]}
        if action == "checkup":
            return {"checks": checkup.checks()}
        if action == "demo":
            # the made-up project of the README's animation: written once, opened every time after
            from contextmax import demo

            if demo.SLUG not in project.list_projects():
                demo.create_project(project.default_home() / "demo-source", None)
                tell("the made-up demo project was written; it builds now", demo.SLUG)
            return _state(demo.SLUG)
        if action == "create":
            name = (b.get("name") or "").strip()
            if not name:
                raise ValueError("give the project a name")
            p = project.create(name, [])
            tell(f"new project {p.name}, working folder {p.workspace}", p.slug)
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

            found = ask.servers()
            return {"tools": assistants.tools(), "servers": found, "ollama_installed": bool(shutil.which("ollama")),
                    "local": ask.local_models(found, bool(shutil.which("ollama")))}
        if action == "ask-poll":
            j = ASKS.get(b.get("job")) or {"text": "", "done": True, "error": "no such question", "sources": []}
            since = int(b.get("since") or 0)
            done, text = j["done"], j["text"]      # done first: text read after it holds every last piece
            return {"text": text[since:], "next": len(text), "done": done, "error": j["error"],
                    "sources": j["sources"], "steps": j.get("steps", []), "confidence": j.get("confidence")}
        if action == "lines":
            return _lines(str(b.get("slug") or ""), str(b.get("key") or ""), int(b.get("n") or 1),
                          int(b.get("before") or LINES_SPAN), int(b.get("after") or LINES_SPAN))
        if action == "ollama-pull":
            from contextmax import ask, assistants

            model = str(b.get("model") or "")
            exe = shutil.which("ollama")
            if not ask.suggested(model):
                raise ValueError("ContextMAX only downloads the models it suggests")
            if not exe:
                raise ValueError(f"Ollama is not installed: get it from {ask.OLLAMA_DOWNLOAD}")
            assistants._new_console(exe, Path.home(), "pull", model)
            tell(f"downloading the model {model} with Ollama, in a window of its own", None)
            return {"message": f"Ollama downloads {model} in a new window. When it says success, reload this page."}
        if action == "files":
            from contextmax import opener

            try:
                message = opener.open_path(str(b.get("path") or ""), "select" if b.get("how") == "select" else "open")
            except OSError as exc:
                raise ValueError(f"Windows could not open it: {exc}") from exc
            tell(message, slug)
            return {"message": message}
        p = project.lookup(slug)
        if action == "add":
            added = project.add_folder(p, b["path"], b.get("name") or None, b.get("holds") or "both")
            tell(f"folder added: {added.name} ({b['path']}), holds {b.get('holds') or 'both'}", p.slug)
        elif action == "remove":
            project.remove_folder(p, b["name"])
            tell(f"folder removed: {b['name']} (its files are not touched)", p.slug)
        elif action == "holds":
            for f in p.data["folders"]:
                if f["name"] == b["name"]:
                    f["holds"] = b["holds"]
            p.save()
            tell(f"folder {b['name']} now holds {b['holds']}", p.slug)
        elif action == "option":
            p.data["download_cloud_files"] = bool(b.get("download_cloud_files"))
            p.save()
            tell("files still in the cloud: " + ("downloaded before reading" if p.download_cloud_files else "left in the cloud"), p.slug)
        elif action == "build":
            for old in JOBS.values():
                if old["done"]:
                    old["events"] = []      # a finished build's drawing was delivered; a big one holds megabytes
            job = secrets.token_hex(6)
            JOBS[job] = {"lines": [], "events": [], "done": False, "code": None}
            threading.Thread(target=_run_build, args=(job, p.slug, b.get("depth") or "quick"), daemon=True).start()
            return {"job": job}
        elif action == "job":
            j = JOBS.get(b.get("job"), {"lines": [], "events": [], "done": True, "code": None})
            since, seen = int(b.get("since") or 0), int(b.get("events_since") or 0)
            done, lines = j["done"], list(j["lines"])
            # the drawing's events only when the window draws: events_since below 0 says it does not
            events = j["events"][seen:seen + EVENTS_PER_POLL] if seen >= 0 else []
            more = seen >= 0 and seen + len(events) < len(j["events"])   # a big build's events come over a few polls
            return {"lines": lines[since:], "next": len(lines), "events": events, "events_next": max(seen, 0) + len(events),
                    "more": more, "done": done and not more, "code": j["code"]}
        elif action == "stop":
            j = JOBS.get(b.get("job"))
            if not j or j["done"]:
                return {"message": "no build is running"}
            Path(j["stop_file"]).touch()
            j["stopping"] = True
            tell("stop asked: the build stops at its next step and keeps what it finished", p.slug)
            threading.Thread(target=_make_sure_it_stops, args=(b.get("job"),), daemon=True).start()
            return {"message": "stopping"}
        elif action == "skillstatus":
            return _skill_status(p)
        elif action == "freshness":
            return _freshness(p)
        elif action == "assistant":
            from contextmax import assistants

            try:
                message = assistants.start(p, str(b.get("tool") or ""))
            except OSError as exc:
                raise ValueError(f"could not start it: {exc}") from exc
            tell(message, p.slug)
            return {"message": message}
        elif action == "ask":
            from contextmax import ask

            question = str(b.get("question") or "").strip()
            if not question:
                raise ValueError("ask a question")
            if not ask.listed(str(b.get("kind") or ""), str(b.get("base") or "")):
                raise ValueError("not one of the model servers ContextMAX looks for on this PC")
            job = secrets.token_hex(6)
            ASKS[job] = {"text": "", "done": False, "error": "", "sources": [], "steps": []}
            tell(f"question to {b.get('model') or 'the model'}: {question[:100]}", p.slug)
            threading.Thread(target=_run_ask, args=(job, p.slug, question[:2000], str(b.get("kind") or "openai"),
                                                    str(b.get("base") or ""), str(b.get("model") or "")), daemon=True).start()
            return {"job": job}
        elif action == "skill":
            from contextmax import agentskill, assistants
            lines = agentskill.install(p, "all") + assistants.prepare(p)
            tell("AI skill installed:", p.slug)
            for line in lines:
                tell("  " + line, p.slug)
            return {"lines": lines, "status": _skill_status(p)}
        elif action == "open":
            target = p.workspace / "Home.html"
            if target.exists() and sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            return {"ok": target.exists()}
        else:
            raise ValueError(f"unknown action {action}")
        return _state(p.slug)


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """A page closed while it was being answered is no error worth a screen of text in the CMD window."""
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(slug: str | None = None, port: int = 0, open_browser: bool = True) -> int:
    Handler.token = secrets.token_urlsafe(24)
    httpd = _Server(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/" + (f"#{slug}" if slug else "")
    print(f"ContextMAX window: {url}\n(close this window, or press Ctrl+C, to stop)\n"
          "This window shows what ContextMAX does: builds line by line, folders, the AI skill, assistants.\n", flush=True)
    names = list(project.list_projects())
    tell("projects: " + (", ".join(names) if names else "none yet"))
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
