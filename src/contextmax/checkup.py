"""What this PC can read. Required things fail; optional things warn and say what they unlock."""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import shutil
import struct
import sys
from pathlib import Path

from contextmax import VERSION, office, project


def checks() -> list[dict]:
    out = []

    def add(level, what, detail):
        out.append({"level": level, "what": what, "detail": detail})

    bits = struct.calcsize("P") * 8
    add("ok" if sys.version_info >= (3, 11) else "fail", f"Python {sys.version.split()[0]} ({bits}-bit)", sys.executable)
    for mod, what in (("openpyxl", "Excel .xlsx/.xlsm values and formulas"), ("xlrd", "old Excel .xls values"),
                      ("pypdfium2", "PDF text and page images for text recognition")):
        try:
            importlib.import_module(mod)
            try:
                version = importlib.metadata.version(mod)
            except importlib.metadata.PackageNotFoundError:
                version = ""
            add("ok", f"{mod} {version}".strip(), what)
        except ImportError:
            add("fail", f"{mod} missing", f"needed for {what}: run setup.cmd again")
    p = office.probe() if sys.platform == "win32" else {"word": False, "excel": False, "ocr": False, "ocr_languages": []}
    if office.PROBE_PROBLEM:
        # not an answer about this PC: the check itself was held, so no "not found" and no advice to install
        add("warn", "Word, Excel and Windows text recognition could not be checked",
            office.PROBE_PROBLEM + "; allow ContextMAX's Python in the security software, then run the check again")
    else:
        add("ok" if p["word"] else "warn", "Microsoft Word" + ("" if p["word"] else " not found"),
            "old .doc files can be read" if p["word"] else "old .doc files are listed as unreadable, with the reason")
        add("ok" if p["excel"] else "warn", "Microsoft Excel" + ("" if p["excel"] else " not found"),
            "formulas of old .xls files can be read" if p["excel"] else "old .xls files give values only, no formulas")
    from contextmax.docs import ocr

    langs = p.get("ocr_languages") or []
    rapid_why = ocr.rapid_problem()
    models = ocr.rapid_models()
    if not office.PROBE_PROBLEM:
        add("ok" if langs else "warn", "Windows text recognition" + (f" ({', '.join(langs)})" if langs else ": no language"),
            "reads scanned PDFs in these languages" if langs else
            "Windows can read scans in the languages added under Settings > Time & language" +
            ("; RapidOCR reads them now" if models else ""))
    if rapid_why:
        add("warn" if langs else "fail", "RapidOCR text recognition not available",
            rapid_why + ("" if langs else "; scanned PDFs stay without text"))
    else:
        cyrillic = "cyrillic" in models
        add("ok" if cyrillic else "warn", f"RapidOCR {importlib.metadata.version('rapidocr')}"
            + (" with Cyrillic" if cyrillic else ", no Cyrillic model"),
            "reads scans Windows cannot: Latin script (47 languages), Chinese, Japanese"
            + (", Cyrillic" if cyrillic else "; run setup.cmd with internet to add Russian and other Cyrillic"))
    code = shutil.which("code") or shutil.which("code.cmd")
    add("ok" if code else "warn", "VS Code" + ("" if code else " not on PATH"),
        "map nodes open the exact line in the editor" if code else "editor links need VS Code")
    for name, base in (("Claude Code", Path.home() / ".claude"), ("Copilot", Path.home() / ".copilot")):
        add("ok" if base.exists() else "warn", f"{name} settings folder" + ("" if base.exists() else " not found"),
            str(base))
    home = project.default_home()
    add("ok", "Projects folder", f"{home} ({len(project.list_projects())} project(s))")
    return out


def run(json_out: bool = False) -> int:
    res = checks()
    if json_out:
        print(json.dumps({"contextmax_version": VERSION, "checks": res}, indent=2))
    else:
        tag = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
        print(f"ContextMAX {VERSION}: what this PC can read\n")
        for c in res:
            print(f"  {tag[c['level']]} {c['what']}\n         {c['detail']}")
    return 1 if any(c["level"] == "fail" for c in res) else 0
