"""Opening a project's file from a page: with the program Windows gives it, or selected in Explorer.

Two ways in, one set of rules:
  - a page the ContextMAX window serves asks the window (POST /api/files, with the window's token);
  - a page opened from disk follows a contextmax-open: link, which `contextmax install` registers for
    this user: contextmax-open:open?path=<file> or contextmax-open:select?path=<file>.
Only a file inside a ContextMAX project (its folders or its working folder) is touched. The path is
checked as text before anything on disk is: a network path outside the projects is never even looked
at, so a link cannot make Windows contact another computer. Only a document is opened; anything that
could run when opened (a program, a script, source code) is shown in its folder instead. A link, which
any web page can start, opens only formats that carry no code (PDF, the Office formats without macros,
text, images); the window, which only its own pages can ask, also opens the older Office formats, the
macro-enabled ones and web pages.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from contextmax import project

# what a contextmax-open: link may start: formats that cannot carry code
LINK_OPENABLE = frozenset({
    ".pdf", ".docx", ".dotx", ".xlsx", ".xltx", ".pptx", ".odt", ".ott", ".ods", ".odp", ".txt", ".md", ".csv",
    ".tsv", ".log", ".vsdx", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"})
# what the window may start besides: the older and macro-enabled Office formats, mail, web pages, data
WINDOW_OPENABLE = LINK_OPENABLE | frozenset({
    ".doc", ".docm", ".dot", ".rtf", ".xls", ".xlsm", ".xlsb", ".ppt", ".pptm", ".vsd", ".msg", ".eml", ".htm",
    ".html", ".svg", ".xml", ".json"})


def _roots() -> list[str]:
    """Every folder a page may point into, as normalised text: each project's folders and working folder."""
    roots = []
    for slug in project.list_projects():
        try:
            p = project.lookup(slug)
        except (SystemExit, ValueError, OSError):
            continue
        roots += [str(p.workspace)] + [f.path for f in p.folders]
    return [os.path.normcase(os.path.abspath(r)) for r in roots if r]


def _inside(path: str, roots: list[str]) -> bool:
    q = os.path.normcase(path)
    return any(q == r or q.startswith(r.rstrip("\\/") + os.sep) for r in roots)


def check(path: str) -> Path:
    """The file, if it lies inside a project; ValueError otherwise. As text first, then on disk."""
    if not path or not os.path.isabs(path) or re.match(r"^[\\/]{2}[?.][\\/]", path):
        raise ValueError("not a full path to a file")
    roots = _roots()
    lexical = os.path.abspath(path)          # text only: nothing on disk (or on the network) is touched yet
    if not _inside(lexical, roots):
        raise ValueError("this file is not in a ContextMAX project's folders")
    p = Path(lexical).resolve()               # a link or junction inside a project that points elsewhere: no
    if not _inside(str(p), roots):
        raise ValueError("this file is not in a ContextMAX project's folders")
    if not p.exists():
        raise ValueError(f"{p.name} is not there (moved or deleted since the last build?)")
    return p


def open_path(path: str, how: str = "open", openable: frozenset = WINDOW_OPENABLE) -> str:
    """Open the file, or show it selected in its folder. Returns what was done."""
    p = check(path)
    if how == "open" and p.is_file() and p.suffix.lower() in openable:
        os.startfile(str(p))  # type: ignore[attr-defined]
        return f"opened {p.name}"
    # a path holds no quote characters on Windows, so this is the one form Explorer reads reliably
    subprocess.Popen(f'explorer.exe /select,"{p}"')
    if how == "open":
        return f"{p.name} is not a document ContextMAX opens from here; it is shown in its folder"
    return f"showed {p.name} in its folder"


def handle_link(url: str) -> int:
    """What a contextmax-open: link does (Windows runs `pythonw -m contextmax link <url>`)."""
    parts = urlsplit(url)
    how = parts.path.strip("/")
    path = (parse_qs(parts.query).get("path") or [""])[0]
    try:
        if parts.scheme != "contextmax-open" or how not in ("open", "select"):
            raise ValueError("this is not a ContextMAX link")
        open_path(path, how, LINK_OPENABLE)
        return 0
    except (ValueError, OSError) as exc:
        # a fixed sentence and a short file name only: a link must not put its own words in this box
        name = re.sub(r"[\x00-\x1f\x7f]", "", Path(path).name)[:80] if path else ""
        reason = str(exc) if isinstance(exc, ValueError) else "Windows could not open it"
        reason = re.sub(r"[\x00-\x1f\x7f]", " ", reason)[:160]
        _tell("ContextMAX did not open this file" + (f" ({name})" if name else "") + f":\n{reason}.")
        return 1


def _tell(message: str) -> None:
    """A message box: the link handler runs without a console."""
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "ContextMAX", 0x40)
    else:
        print(message)
