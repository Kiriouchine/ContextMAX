"""Stage 1: the catalogue. Every file in every chosen folder, one row each.

Writes into <workspace>/catalogue/:
  all-files.csv       one row per file: folder, priority, category, tags, document IDs, size, date, cloud state
  priority-files.csv  the rows in a location the project marked as important
  <folder>.csv   the same rows, one file per chosen folder
  overview.txt    counts a person can read at a glance
  folders.json   which folder was found where, and how many files it held
  catalogue-info.json     when this ran (kept apart so the files above stay byte-identical)

Read-only on the folders. Noise is tagged, never dropped, so a count is always the whole count.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from contextmax import util
from contextmax.project import SKIP_MARKER, Project

CODE_SUFFIXES = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".vhd", ".vhdl", ".v", ".sv", ".lua", ".py",
            ".cs", ".m", ".asm", ".s", ".inc", ".ld", ".mk", ".cmake", ".tcl", ".do", ".ucf", ".xdc", ".sdc",
            ".json", ".xml", ".yaml", ".yml", ".ino", ".js", ".ts", ".java", ".go", ".rs", ".ps1", ".sh"}
BINARY_SUFFIXES = {".hex", ".bin", ".elf", ".srec", ".s19", ".s37", ".mcs", ".mot", ".out", ".map"}
DOC_SUFFIXES = {".docx", ".doc", ".pdf", ".txt", ".md", ".rtf", ".odt", ".tex", ".rst", ".htm", ".html"}
WORKBOOK_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".xlsb", ".csv", ".ods"}
SLIDE_SUFFIXES = {".pptx", ".ppt", ".odp"}
CAD_SUFFIXES = {".step", ".stp", ".stl", ".iges", ".igs", ".dxf", ".dwg", ".brd", ".sch", ".pcb", ".odb", ".gbr",
           ".art", ".drl", ".asc", ".vsdm", ".vsdx", ".vsd", ".slx", ".mdl"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".svg", ".emf", ".wmf"}

# Folders that only ever hold tool caches. They are not walked; how many were stepped
# over is still reported, so the gap is visible.
SKIP_DIR_NAMES = {".git", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
                  ".mypy_cache", ".ruff_cache", ".vs", ".vscode", ".idea", ".tox"}

HEADER = ["Folder", "Priority", "FirstFolder", "Category", "Products", "DocNumbers", "Name", "Ext", "Kilobytes",
          "Modified", "OnlineOnly", "RelativePath"]


class Classifier:
    """Turns a relative path into a category, tags, document IDs and a priority."""

    def __init__(self, vocabulary: dict):
        self.topics = [(t["category"], re.compile(t["path"], re.I)) for t in vocabulary.get("topics", [])]
        self.tags = [(t["tag"], re.compile(t["pattern"], re.I)) for t in vocabulary.get("products", [])]
        self.doc_numbers = [re.compile(p) for p in vocabulary.get("doc_number_patterns", [])]
        self.priorities = []
        for p in vocabulary.get("priorities", []):
            self.priorities.append({
                "label": p["label"],
                "folder": p.get("folder"),
                "path": re.compile(p["path"], re.I) if p.get("path") else None,
                "doc_number": p.get("doc_number"),
            })

    def category(self, rel: str, ext: str) -> str:
        p = "/" + rel.lower()
        e = ext.lower()
        # noise first: tagged so it can be filtered, never dropped
        if re.search(r"/\.svn/|/\.git/|/node_modules/|/__pycache__/", p):
            return "Noise (version control)"
        if re.search(r"/(bin|obj|debug|release|build|dist)/", p) and e in {".dll", ".o", ".obj", ".lib", ".a",
                                                                          ".exe", ".pdb", ".ilk", ".so"}:
            return "Noise (build output)"
        name = p.rsplit("/", 1)[-1]
        if e in {".tmp", ".bak", ".lock", ".ldb"} or name in {"thumbs.db", "desktop.ini"} or name.startswith("~$"):
            return "Noise (temporary)"
        if re.search(r"\.odb/|/odb\+\+/|/odbjob", p):
            return "CAD internals"
        if e in CODE_SUFFIXES:
            return "Source code"
        if e in BINARY_SUFFIXES:
            return "Binary image"
        if e in CAD_SUFFIXES:
            return "CAD"
        for cat, rx in self.topics:
            if rx.search(p):
                return cat
        if e in DOC_SUFFIXES:
            return "Document"
        if e in WORKBOOK_SUFFIXES:
            return "Spreadsheet"
        if e in SLIDE_SUFFIXES:
            return "Slides"
        if e in IMAGE_SUFFIXES:
            return "Image"
        return "Other"

    def products(self, rel: str) -> str:
        found = [tag for tag, rx in self.tags if rx.search(rel)]
        return ";".join(dict.fromkeys(found))

    def doc_numbers_in(self, text: str) -> list[str]:
        found = []
        for rx in self.doc_numbers:
            for m in rx.finditer(text):
                found.append(m.group(0))
        return list(dict.fromkeys(found))

    def priority(self, folder: str, rel: str, doc_numbers: str) -> str:
        low = rel.lower()
        for p in self.priorities:
            if p["doc_number"]:
                if p["doc_number"] in doc_numbers.split(";"):
                    return p["label"]
                continue
            if p["folder"] and p["folder"] != folder:
                continue
            if p["path"] is None or p["path"].search(low):
                return p["label"]
        return ""


def _marked_roots(root: Path) -> list[str]:
    """Every folder that holds the skip marker, so its whole subtree is left alone."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        if SKIP_MARKER in filenames:
            found.append(os.path.normcase(os.path.abspath(dirpath)))
            dirnames[:] = []
    return found


def walk_folder(root: Path, skip_also: list[str] | None = None):
    """Yield (full_path, relative_path, stat) for every file, in one sorted order.

    Returns the steps over through `stepped` so the caller can report them.
    """
    marker_roots = _marked_roots(root)
    blocked = marker_roots + [os.path.normcase(os.path.abspath(s)) for s in (skip_also or [])]
    stepped = Counter()
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = os.path.normcase(os.path.abspath(dirpath))
        if any(here == b or here.startswith(b + os.sep) for b in blocked):
            stepped["skip marker or working folder"] += 1
            dirnames[:] = []
            continue
        keep = []
        for d in sorted(dirnames):
            if d in SKIP_DIR_NAMES:
                stepped[f"tool cache folder ({d})"] += 1
            else:
                keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            if name == SKIP_MARKER:
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                stepped["cannot be listed"] += 1
                continue
            rows.append((full, util.rel_key(full, root), st))
    rows.sort(key=lambda r: r[1])
    return rows, stepped


def build(proj: Project) -> dict:
    """Write the catalogue and return its counts."""
    cls = Classifier(proj.vocabulary)
    out = proj.catalogue_dir
    out.mkdir(parents=True, exist_ok=True)
    every_row: list[list] = []
    folders_meta = []
    stepped_total = Counter()
    for folder in proj.folders:
        root = Path(folder.path)
        if not root.is_dir():
            folders_meta.append({"name": folder.name, "path": folder.path, "holds": folder.holds,
                                 "found": False, "files": 0})
            util.say("catalogue", f"{folder.name}: not found at {folder.path}")
            continue
        util.say("catalogue", f"scanning {folder.name}: {root}")
        files, stepped = walk_folder(root, skip_also=[str(proj.workspace)])
        stepped_total.update(stepped)
        rows = []
        for _full, rel, st in files:
            ext = os.path.splitext(rel)[1].lower()
            ids = ";".join(cls.doc_numbers_in(rel))
            attrs = getattr(st, "st_file_attributes", 0)
            row = [
                folder.name,
                cls.priority(folder.name, rel, ids),
                rel.split("/", 1)[0] if "/" in rel else "",
                cls.category(rel, ext),
                cls.products(rel),
                ids,
                os.path.basename(rel),
                ext,
                f"{st.st_size / 1024:.1f}",
                datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%d"),
                "True" if attrs & util.CLOUD_MASK else "False",
                rel,
            ]
            rows.append(row)
        util.save_csv(out / f"{util.slugify(folder.name)}.csv", HEADER, rows)
        every_row.extend(rows)
        folders_meta.append({"name": folder.name, "path": folder.path, "holds": folder.holds,
                             "found": True, "files": len(rows)})
        util.say("catalogue", f"  {len(rows)} files")

    every_row.sort(key=lambda r: (r[0], r[11]))
    util.save_csv(out / "all-files.csv", HEADER, every_row)
    prio = sorted((r for r in every_row if r[1]), key=lambda r: (r[1], r[0], r[11]))
    util.save_csv(out / "priority-files.csv", HEADER, prio)
    util.save_json(out / "folders.json", {"folders": folders_meta,
                                           "stepped_over": dict(sorted(stepped_total.items())),
                                           "file_total": len(every_row)})
    _write_summary(proj, out / "overview.txt", every_row, stepped_total)
    util.save_json(out / "catalogue-info.json", {"built_utc": util.utc_now(), "file_total": len(every_row)})
    return {"files": len(every_row), "priority": len(prio), "folders": len(folders_meta)}


def _write_summary(proj: Project, path: Path, rows: list[list], stepped: Counter) -> None:
    L = [f"{proj.name}: file catalogue", f"Total files: {len(rows)}", ""]
    prio = Counter(r[1] for r in rows if r[1])
    if prio:
        L.append("== Priority locations (see priority-files.csv) ==")
        for label in sorted(prio):
            L.append(f"   {label:<30} {prio[label]}")
        L.append("")
    by_folder = defaultdict(list)
    for r in rows:
        by_folder[r[0]].append(r)
    for name in sorted(by_folder):
        group = by_folder[name]
        L.append(f"== {name}  ({len(group)} files) ==")
        cats = Counter(r[3] for r in group)
        for cat, n in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0])):
            L.append(f"   {cat:<24} {n}")
        L.append("")
    tags = Counter(t for r in rows if r[4] for t in r[4].split(";"))
    if tags:
        L.append("== Product tags (files mentioning each) ==")
        for tag, n in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])):
            L.append(f"   {tag:<16} {n}")
        L.append("")
    cloud = sum(1 for r in rows if r[10] == "True")
    if cloud:
        L.append(f"Files still in the cloud (not on this disk): {cloud}")
    if stepped:
        L.append("Folders stepped over:")
        for why, n in sorted(stepped.items()):
            L.append(f"   {why:<36} {n}")
    util.save_text(path, "\n".join(L))
