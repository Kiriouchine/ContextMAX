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

Assistants started from here: VS Code (Copilot, or Claude Code's chat in VS Code), Claude Code and Codex
in a terminal. A model on this PC is asked through ask.py instead.

Claude starts with the project's skill: a message that begins with the skill's name, /contextmax-<project>,
always loads it. In a terminal, Claude Code is started with that message, so the skill is loaded at once.
In VS Code, Claude's chat is opened with the message typed in (Claude Code never sends a typed-in message
by itself): its link goes to whichever VS Code window is in front, so ContextMAX first waits for the
project's own window and brings it to the front.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from contextmax import agentskill, util

WINDOW_WAIT = 30.0                         # seconds VS Code may take to show the project's window
BEGIN, END = "<!-- contextmax: begin (written by ContextMAX; edit outside these marks) -->", "<!-- contextmax: end -->"
GRANTED = "contextmax-folders.json"       # in .claude: the folders ContextMAX gave Claude Code, to take back
GUIDE = """## {name}: the ContextMAX working folder

Your own notes for the skill belong in `notes/project-notes.md`, which the skill carries; anything you add
to this file outside the ContextMAX marks stays as it is.

This folder holds the index of the project "{name}", built by scripts with no AI in the build: the
catalogue of every file, the code maps, the document map and every named value with its source, and the
pages (`Home.html`). The project's own folders, which the index points into:

{folders}

Use the **contextmax-{slug}** skill for every question about this project. Start with one command, in Bash:
`"{python}" -m contextmax brief {slug} "<the question>"`: in a few seconds it shows where the
question leads (code, named values, documents), with the lines to read. The skill says how to look further
and how to answer: with the file and line, the document, or the sheet and cell, and with what was not
checked. The index is the way in, not the answer: open the document or the code it points to (the
line it cites), read it, answer from it and link it. End every answer with `Confidence: High`, `Medium` or
`Low` and why, judged on what you read; when nothing answers the question, say so plainly and what you
searched. Do not change files in the project's folders unless you are asked to.
"""


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".cmd")


def _installed(name: str) -> str | None:
    """An assistant's command (claude, codex): on the PATH, or where its own installer puts it. Claude Code's
    installer puts claude.exe in ~/.local/bin without adding that folder to the PATH, and npm puts its
    commands in %APPDATA%/npm, which a window started before the install does not have on its PATH."""
    found = _which(name)
    if found:
        return found
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    places = [home / ".local" / "bin" / f"{name}.exe", appdata / "npm" / f"{name}.cmd"]
    if os.name != "nt":
        places = [home / ".local" / "bin" / name]
    return next((str(p) for p in places if p.is_file()), None)


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


def skill_command(proj) -> str:
    """The message that loads the project's skill in Claude Code."""
    return f"/contextmax-{proj.slug}"


def _vscode_windows(part: str) -> list[int]:
    """VS Code's windows whose title holds `part` (a workspace window's title holds "<name> (Workspace)")."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32, found = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if part in buf.value and "Visual Studio Code" in buf.value:
                    found.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return found


def _in_front(hwnd: int) -> bool:
    if os.name != "nt":
        return False
    import ctypes

    return ctypes.windll.user32.GetForegroundWindow() == hwnd


def _open_in_vscode(app, target: str) -> None:
    if app:
        subprocess.Popen([str(app), target])
    else:
        os.startfile(target)  # type: ignore[attr-defined]  # the .code-workspace file's own program


def _claude_in_vscode_chat(proj, app, target: str) -> str:
    """Claude's chat in the project's VS Code window, with the skill's name typed in. The chat's link goes to
    the VS Code window in front: wait for the project's window, have VS Code bring it to the front (opening
    a workspace that a window has open brings that window forward), then open the link."""
    title, command = f"{proj.slug} (Workspace)", skill_command(proj)
    t0 = time.monotonic()
    while not _vscode_windows(title):
        if time.monotonic() - t0 > WINDOW_WAIT:
            return (f"VS Code is opening the project, but its window did not appear within {int(WINDOW_WAIT)} s. "
                    f"In it, open Claude's chat (the Claude icon) and start your question with {command}")
        time.sleep(0.5)
    time.sleep(1.5)                                     # the window finishes loading
    _open_in_vscode(app, target)                        # VS Code brings the project's window to the front
    windows = _vscode_windows(title)
    for _ in range(10):
        if any(_in_front(h) for h in windows):
            break
        time.sleep(0.5)
    os.startfile("vscode://anthropic.claude-code/open?prompt=" + quote(command + " ", safe=""))  # type: ignore[attr-defined]
    return (f"VS Code opened the project and Claude's chat, with {command} typed in: write your question after it "
            "and press Enter. (If the chat opened in another VS Code window, click the project's window and open "
            f"Claude there; {command} loads the project's skill.)")


def _claude_in_vscode() -> bool:
    return any((Path.home() / ".vscode" / "extensions").glob("anthropic.claude-code-*"))


def tools() -> list[dict]:
    """The assistants this PC has, in the order the page shows them."""
    code, claude_ext = _vscode(), _claude_in_vscode()
    return [
        {"id": "vscode-claude", "label": "VS Code with Claude", "ok": bool(code and claude_ext),
         "why": "" if code and claude_ext else "needs VS Code with the Claude Code extension",
         "title": "Opens the project in VS Code, then Claude's chat with the project's skill typed in"},
        {"id": "vscode", "label": "VS Code", "ok": bool(code), "why": "" if code else "VS Code is not installed",
         "title": "Opens the project in VS Code, for Copilot's chat or any other assistant there"},
        {"id": "claude", "label": "Claude Code", "ok": bool(_installed("claude")), "why": "" if _installed("claude") else
         "the claude command is not installed", "title": "Starts Claude Code in a terminal, in the project's folder, with its skill loaded"},
        {"id": "codex", "label": "Codex", "ok": bool(_installed("codex")), "why": "" if _installed("codex") else
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
    python = sys.executable.replace("\\", "/")
    block = BEGIN + "\n" + GUIDE.format(name=proj.name, slug=proj.slug, folders=folders, python=python).rstrip("\n") + "\n" + END
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


def _new_console(program: str, cwd: Path, *args: str) -> None:
    """The program by its full path, and cmd told not to look in the folder first: a claude.bat left in
    the working folder is never what runs."""
    subprocess.Popen(["cmd.exe", "/k", program, *args], cwd=str(cwd), env=dict(os.environ, NoDefaultCurrentDirectoryInExePath="1"),
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
        _open_in_vscode(app, target)
        if tool == "vscode-claude":
            return _claude_in_vscode_chat(proj, app, target)
        return "VS Code opens the project; ask in its chat (Copilot, or another assistant)"
    if tool == "claude":
        # the skill's name as the first message: Claude Code loads the skill at once; the question comes next
        _new_console(_installed(tool) or tool, ws, skill_command(proj))
        return (f"Claude Code starts in a terminal in {ws} and loads the project's skill ({skill_command(proj)}): "
                "ask your question when it is ready")
    _new_console(_installed(tool) or tool, ws)
    return f"{known[tool]['label']} starts in a terminal in {ws}"
