"""Optional Windows readers: Word for old .doc files, Excel for .xls formulas, Windows OCR.

Each runs as its own PowerShell process with a hard timeout. When a file hangs Word or
Excel, the process is killed together with the one Word or Excel instance it started, and
only that file is reported as skipped. Nothing here is required: without Office the
affected files are listed with the reason, never silently missing.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PS_DIR = Path(__file__).resolve().parent / "ps"
_PROBE: dict | None = None
PROBE_PROBLEM: str | None = None       # why the check for Word, Excel and OCR did not finish, if it did not
# Marks in the text Word hands over: a table cell or row ends in BEL, a manual line break is VT, a page
# or section break FF, a column break SO; a non-breaking hyphen is RS (written as the RTF reader writes
# it) and an optional hyphen US.
_WORD_MARKS = str.maketrans({"\x07": None, "\x0b": "\n", "\x0c": "\n", "\x0e": "\n", "\x1e": "\N{NON-BREAKING HYPHEN}",
                             "\x1f": None})
_OTHER_CONTROLS = re.compile(r"[\x00-\x06\x08\x0d\x0f-\x1d]")


def clean_word_text(text: str) -> str:
    """Word's marks as plain text: a table row per line with its cells separated by tabs (as the RTF
    reader writes them), breaks as line breaks, hyphens as hyphens; the remaining control characters
    (anchors of pictures, fields and notes) are dropped."""
    text = text.replace("\r", "\n").replace("\n\x07\n\x07", "\t\n").replace("\n\x07", "\t")
    return _OTHER_CONTROLS.sub("", text.translate(_WORD_MARKS))


def powershell() -> str | None:
    if sys.platform != "win32":
        return None
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def _pids(image: str) -> set[int]:
    if sys.platform != "win32":
        return set()
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for row in csv.reader(io.StringIO(out)):
        if len(row) > 1 and row[1].isdigit():
            pids.add(int(row[1]))
    return pids


def _kill(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=20)


def run_script(script: str, args: list[str], timeout: int, app_images: tuple[str, ...] = ()) -> tuple[bool, str, str]:
    """Run ps/<script> with arguments. Returns (ok, stdout, error).

    Word and Excel started through COM are not children of the script, so on a timeout every
    instance of `app_images` that appeared while the script ran is stopped as well."""
    ps = powershell()
    if not ps:
        return False, "", "PowerShell is not available on this system"
    before = {image: _pids(image) for image in app_images}
    cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(PS_DIR / script), *args]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc.pid)
        for image, running_before in before.items():
            for pid in _pids(image) - running_before:     # only the instances this call started
                _kill(pid)
        proc.communicate()
        return False, "", f"timed out after {timeout} s (the file may be damaged or protected)"
    text_out = out.decode("utf-8", "replace")
    text_err = err.decode("utf-8", "replace").strip()
    return proc.returncode == 0, text_out, text_err


def probe() -> dict:
    """Which optional readers work on this PC. Asked once per run."""
    global _PROBE, PROBE_PROBLEM
    if os.environ.get("CONTEXTMAX_NO_OFFICE"):
        return {"word": False, "excel": False, "ocr": False, "ocr_languages": []}
    if _PROBE is None:
        ok, out, err = run_script("probe.ps1", [], 90, ("WINWORD.EXE", "EXCEL.EXE"))
        data = {}
        if not ok:
            PROBE_PROBLEM = "the check for Word, Excel and text recognition did not finish (" + \
                (err or "no answer") + "; security software may have held it)"
        if ok:
            for line in out.splitlines()[::-1]:
                if line.strip().startswith("{"):
                    try:
                        data = json.loads(line)
                    except ValueError:
                        pass
                    break
        _PROBE = {"word": bool(data.get("word")), "excel": bool(data.get("excel")),
                  "ocr": bool(data.get("ocr")), "ocr_languages": data.get("ocr_languages") or []}
    return _PROBE


def word_to_text(src: str, out: str, timeout: int = 60) -> tuple[bool, str]:
    ok, _, err = run_script("word_text.ps1", ["-Source", src, "-Target", out], timeout, ("WINWORD.EXE",))
    if ok and os.path.exists(out):
        from contextmax.docs.readers import write_out

        write_out(out, clean_word_text(Path(out).read_text(encoding="utf-8")))
        return True, err
    return False, err or "Word could not read the file"


def xls_to_xlsx(src: str, out: str, timeout: int = 120) -> tuple[bool, str]:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ok, _, err = run_script("excel_copy.ps1", ["-Source", src, "-Target", out], timeout, ("EXCEL.EXE",))
    if ok and os.path.exists(out):
        return True, err
    return False, err or "Excel could not convert the file"


def ocr_pdf(src: str, dpi: int = 200, timeout: int = 900) -> tuple[bool, str, int]:
    """Render each page and read it with Windows OCR. Returns (ok, text or error, pages)."""
    from contextmax.docs.readers import render_pdf_pages

    with tempfile.TemporaryDirectory(prefix="cmx-ocr-") as tmp:
        try:
            n = render_pdf_pages(src, Path(tmp), dpi=dpi)
        except Exception as exc:  # noqa: BLE001 - reported as this file's reason
            return False, f"cannot render pages: {type(exc).__name__}: {exc}", 0
        if n == 0:
            return False, "no pages", 0
        ok, out, err = run_script("ocr.ps1", ["-Pages", tmp], timeout)
        if not ok:
            return False, err or "text recognition failed", n
        return True, out.replace("\r\n", "\n"), n
