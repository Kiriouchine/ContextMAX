"""Ask your AI: start an assistant on a project, with the ContextMAX skill, in the project's working folder.

The working folder (<home>\\<project>) is the project's root for an assistant: it holds the index the
skill reads, and ContextMAX makes it ready for each assistant:
  CLAUDE.md, AGENTS.md      what this folder is, which folders hold the code and the documents, the skill
                            to use and how to answer (Claude Code reads CLAUDE.md; Codex and others AGENTS.md),
                            in a block between two marks: the rest of the file is the assistant's or yours
  .claude/settings.json     Claude Code may read the project's folders without asking for each one
  <project>.code-workspace  VS Code opens the working folder and the project's folders together
The skill itself goes into each assistant's skills folder (agentskill.py). ContextMAX writes its block
and its entries again each time and leaves everything else as it finds it: a settings file it cannot
read as plain JSON is not touched at all.

Assistants started from here: VS Code (Copilot, or Claude Code's chat in VS Code, opened with a first
question), Claude Code and Codex in a terminal. A model on this PC is asked through ask.py instead.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote

from contextmax import agentskill, util

BEGIN, END = "<!-- contextmax: begin (written by ContextMAX; edit outside these marks) -->", "<!-- contextmax: end -->"
GRANTED = "contextmax-folders.json"       # in .claude: the folders ContextMAX gave Claude Code, to take back
GUIDE = """## {name}: the ContextMAX working folder

Your own notes for the skill belong in `notes/project-notes.md`, which the skill carries; anything you add
to this file outside the ContextMAX marks stays as it is.

This folder holds the index of the project "{name}", built by scripts with no AI in the build: the
catalogue of every file, the code maps, the document map and every named value with its source, and the
pages (`Home.html`). The project's own folders, which the index points into:

{folders}

Use the **contextmax-{slug}** skill for every question about this project. It says how to look things up
in the index and how to answer: with the file and line, the document, or the sheet and cell, and with what
was not checked. The index is a finding aid, not the record: read the source it points to before you rely
on it. Do not change files in the project's folders unless you are asked to.
"""


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".cmd")


def _vscode() -> str | None:
    found = _which("code")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
    return str(local) if local.is_file() else None


def _vscode_app(code: str) -> Path | None:
    """Code.exe beside the code command: started directly, a path with spaces or & needs no cmd quoting."""
    app = Path(code).resolve().parent.parent / "Code.exe"
    return app if app.is_file() else None


def _claude_in_vscode() -> bool:
    return any((Path.home() / ".vscode" / "extensions").glob("anthropic.claude-code-*"))


def tools() -> list[dict]:
    """The assistants this PC has, in the order the page shows them."""
    code, claude_ext = _vscode(), _claude_in_vscode()
    return [
        {"id": "vscode-claude", "label": "VS Code with Claude", "ok": bool(code and claude_ext),
         "why": "" if code and claude_ext else "needs VS Code with the Claude Code extension",
         "title": "Opens the project in VS Code and Claude's chat with a first question"},
        {"id": "vscode", "label": "VS Code", "ok": bool(code), "why": "" if code else "VS Code is not installed",
         "title": "Opens the project in VS Code, for Copilot's chat or any other assistant there"},
        {"id": "claude", "label": "Claude Code", "ok": bool(_which("claude")), "why": "" if _which("claude") else
         "the claude command is not installed", "title": "Starts Claude Code in a terminal, in the project's folder"},
        {"id": "codex", "label": "Codex", "ok": bool(_which("codex")), "why": "" if _which("codex") else
         "the codex command is not installed", "title": "Starts Codex in a terminal, in the project's folder"},
    ]


def _with_block(old: str, block: str) -> str:
    """The file with ContextMAX's block put in place (or added at the end); the rest unchanged."""
    if BEGIN in old and END in old.split(BEGIN, 1)[1]:
        before, rest = old.split(BEGIN, 1)
        return before + block + rest.split(END, 1)[1]
    return (old.rstrip("\n") + "\n\n" if old.strip() else "") + block + "\n"


def _json_object(path: Path) -> dict | None:
    """The file as a JSON object; {} when it is not there; None when it is there but is something else
    (JSON with comments, or a list): then it is not ContextMAX's to rewrite."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def prepare(proj) -> list[str]:
    """Make the working folder ready for an assistant; returns what was done."""
    ws = proj.workspace
    folders = "\n".join(f"- **{f.name}** ({f.holds}): `{f.path}`" for f in proj.folders) or "- (none yet)"
    block = BEGIN + "\n" + GUIDE.format(name=proj.name, slug=proj.slug, folders=folders).rstrip("\n") + "\n" + END
    done = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = ws / name
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        util.save_text(path, _with_block(old, block))
        done.append(str(path))
    current = [f.path for f in proj.folders]
    settings_path, granted_path = ws / ".claude" / "settings.json", ws / ".claude" / GRANTED
    settings = _json_object(settings_path)
    if settings is None or not isinstance((settings.get("permissions") or {}), dict):
        done.append(f"left as it is (not plain JSON ContextMAX can add to): {settings_path}")
    else:
        granted = util.load_json(granted_path, default=[]) or []
        allowed = settings.setdefault("permissions", {}).setdefault("additionalDirectories", [])
        if isinstance(allowed, list):
            # what ContextMAX gave before and the project no longer has is taken back; the rest is the user's
            allowed[:] = [d for d in allowed if d not in granted or d in current]
            allowed += [d for d in current if d not in allowed]
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            granted_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            done.append(str(settings_path))
    wsfile = ws / f"{proj.slug}.code-workspace"
    workspace = _json_object(wsfile)
    if workspace is None:
        done.append(f"left as it is (not plain JSON ContextMAX can add to): {wsfile}")
    else:
        workspace["folders"] = [{"name": f"ContextMAX: {proj.name}", "path": "."}] + \
            [{"name": f.name, "path": f.path} for f in proj.folders]
        wsfile.write_text(json.dumps(workspace, indent=2) + "\n", encoding="utf-8")
        done.append(str(wsfile))
    return done


def _new_console(program: str, cwd: Path) -> None:
    """The program by its full path, and cmd told not to look in the folder first: a claude.bat left in
    the working folder is never what runs."""
    subprocess.Popen(["cmd.exe", "/k", program], cwd=str(cwd), env=dict(os.environ, NoDefaultCurrentDirectoryInExePath="1"),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def start(proj, tool: str) -> str:
    """Start an assistant on the project, with its skill installed. Returns what happened."""
    known = {t["id"]: t for t in tools()}
    if tool not in known:
        raise ValueError(f"unknown assistant {tool}")
    if not known[tool]["ok"]:
        raise ValueError(f"{known[tool]['label']}: {known[tool]['why']}")
    host = {"vscode-claude": "claude", "vscode": "copilot", "claude": "claude", "codex": "codex"}[tool]
    agentskill.install(proj, host)
    prepare(proj)
    ws = proj.workspace
    if tool in ("vscode", "vscode-claude"):
        target = str(ws / f"{proj.slug}.code-workspace")
        app = _vscode_app(_vscode())
        if app:
            subprocess.Popen([str(app), target])
        else:
            os.startfile(target)  # type: ignore[attr-defined]  # the .code-workspace file's own program
        if tool == "vscode-claude":
            url = "vscode://anthropic.claude-code/open?prompt=" + quote(f"Using the contextmax-{proj.slug} skill: ", safe="")

            def chat():
                time.sleep(5)        # the window has to be there for the chat to open in it
                os.startfile(url)  # type: ignore[attr-defined]  # VS Code's own vscode: link

            threading.Thread(target=chat, daemon=True).start()
            return "VS Code opens the project, then Claude's chat with a first line: type your question after it"
        return "VS Code opens the project; ask in its chat (Copilot, or another assistant)"
    _new_console(_which(tool) or tool, ws)
    return f"{known[tool]['label']} starts in a terminal in {ws}"
