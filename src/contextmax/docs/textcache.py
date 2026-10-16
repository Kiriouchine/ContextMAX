"""Stage 3: the document text cache. Each distinct document's text, read once and kept.

Writes into <workspace>/documents/:
  text/<key>.txt      the words of one document (UTF-8, LF)
  sheets/<key>.jsonl  one record per spreadsheet cell, for the value list
  text-index.jsonl    one row per cached document, sorted by key, no timestamps
  copies.csv      every copy that was folded into a kept document (same name and size)
  not-downloaded.csv         documents still in the cloud: retried on the next run, never "failed"
  not-read.csv         documents that could not be read, each with its reason
  text-coverage.json       what was readable, what was read, what was not
  text-info.json          when, how, and the fingerprint of the whole cache

Incremental by default: a document is read again only when its date, its size, the
reader's version or (for old .xls) its .xlsx copy changed. Pruning removes text of
documents that left the folders, and only after the new index is safely written.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from contextmax import office, util
from contextmax.docs import ocr as recognition
from contextmax.docs import readers as ex
from contextmax.docs import sheets
from contextmax.project import Project

TEXT_EXT = {".txt", ".md", ".rst"}
DOC_SUFFIXES = {".pdf", ".docx", ".docm", ".rtf", ".doc"}
WORKBOOK_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".csv"}
READABLE_SUFFIXES = TEXT_EXT | DOC_SUFFIXES | WORKBOOK_SUFFIXES
SHEET_LIKE_UNREAD = {".xlsb", ".ods", ".xlt", ".xltx", ".xltm", ".numbers"}
PLAIN_VERSION = 2          # 2: documents also record their own title
OCR_METHODS = {"ocr", "windows-ocr"}   # "windows-ocr": a document an earlier ContextMAX recognised
WORD_FILE_VERSION = 3      # .rtf and .doc only. 3: \uN escapes and symbol words in RTF read; Word's marks cleaned


def reader_version(ext: str) -> int:
    """The version of the reader whose output a cached text of this kind holds."""
    if ext in WORKBOOK_SUFFIXES:
        return sheets.SHEET_READER_VERSION
    return WORD_FILE_VERSION if ext in (".rtf", ".doc") else PLAIN_VERSION


def _base(name: str) -> str:
    return util.safe_name(os.path.splitext(name)[0])


def _stamp(path: str) -> tuple[str, int]:
    st = os.stat(ex.win_path(path))
    return datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"), st.st_size


def select(proj: Project, scope: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Catalogue rows to read, after folding copies. Returns (candidates, duplicates, all readable)."""
    rows = util.csv_rows(proj.catalogue_dir / "all-files.csv")
    if not rows:
        raise SystemExit("no catalogue yet: run the catalogue first (contextmax build --catalogue)")
    readable = [r for r in rows if r["Ext"] in READABLE_SUFFIXES]
    if scope == "all":
        chosen = [r for r in readable if not r["Category"].startswith("Noise") and r["Category"] != "CAD internals"]
    else:
        pattern = re.compile(proj.vocabulary.get("design_doc_pattern") or r"design", re.I)
        chosen = [r for r in readable if (r["Priority"] or pattern.search(r["Name"]))
                  and not r["Category"].startswith("Noise")]
    groups = defaultdict(list)
    for r in chosen:
        groups[(r["Name"].lower(), r["Kilobytes"])].append(r)
    keep, dups = [], []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda r: (r["Modified"], r["Folder"], r["RelativePath"]), reverse=True)
        # newest first; among equal dates the order above is fixed, so the choice never changes
        keep.append(members[0])
        for m in members[1:]:
            dups.append({"name": m["Name"], "kilobytes": m["Kilobytes"], "folder": m["Folder"], "relative_path": m["RelativePath"],
                         "copy_of": members[0]["RelativePath"], "kept_as": members[0]["Folder"]})
    keep.sort(key=lambda r: (r["Folder"], r["RelativePath"]))
    return keep, dups, readable


def assign_keys(cands: list[dict]) -> dict[tuple[str, str], str]:
    """Stable keys: the file's base name, plus a short hash of where it lives only when two
    different documents share that base name. Keys therefore never shift between runs."""
    counts = Counter(_base(r["Name"]) for r in cands)
    keys = {}
    for r in cands:
        b = _base(r["Name"])
        if counts[b] > 1:
            h = hashlib.sha1(f"{r['Folder']}|{r['RelativePath']}".encode("utf-8")).hexdigest()[:8]
            keys[(r["Folder"], r["RelativePath"])] = f"{b}_{h}"
        else:
            keys[(r["Folder"], r["RelativePath"])] = b
    return keys


def _copy_index(proj: Project) -> tuple[Path, dict]:
    d = proj.path("staging", "xlsx-copies")
    return d, util.load_json(d / "copies.json", default={}) or {}


def xlsx_copy_of(proj: Project, src: str, key: str, use_excel: bool, copies: dict, copies_dir: Path) -> str | None:
    """A checked .xlsx copy of an old .xls: Excel makes it once, and it is reused while both hashes match."""
    entry = copies.get(src.lower())
    source_digest = util.hash_file(ex.win_path(src))
    if entry and os.path.exists(entry.get("converted", "")):
        if entry.get("file_sha256") == source_digest and util.hash_file(entry["converted"]) == entry.get("copy_sha256"):
            return entry["converted"]
    if not use_excel:
        return None
    out = str(copies_dir / f"{key}.xlsx")
    ok, _err = office.xls_to_xlsx(src, out)
    if not ok:
        return None
    copies[src.lower()] = {"converted": out, "file_sha256": source_digest, "copy_sha256": util.hash_file(out)}
    return out


def build(proj: Project, scope: str = "all", resume: bool = True, prune: bool = True,
          retry_unreadable: bool = False, ocr: bool = True, max_files: int = 0) -> dict:
    out = proj.documents_dir
    texts_out, sheets_out = out / "text", out / "sheets"
    texts_out.mkdir(parents=True, exist_ok=True)
    sheets_out.mkdir(parents=True, exist_ok=True)
    roots = {f.name: f.path for f in proj.folders}
    voc = proj.vocabulary
    units = sheets.Units(voc.get("units"))
    aliases = {str(k).lower(): v for k, v in (voc.get("label_aliases") or {}).items()}
    if prune and max_files:
        raise SystemExit("pruning needs a complete pass; do not combine it with a file limit")

    cands, dups, readable = select(proj, scope)
    keys = assign_keys(cands)
    util.say("docs", f"scope {scope}: {len(cands)} distinct documents, {len(dups)} copies folded in")

    jsonl = out / "text-index.jsonl"
    existing = {r["key"]: r for r in util.load_jsonl(jsonl)} if resume else {}
    prior_fail = {}
    if resume and not retry_unreadable:
        for r in util.csv_rows(out / "not-read.csv"):
            if r.get("key") and r.get("file_mtime_utc"):
                prior_fail[r["key"]] = r

    wants_office = any(r["Ext"] in (".doc", ".rtf", ".xls") for r in cands)
    probe = office.probe() if (wants_office or ocr) else {"word": False, "excel": False, "ocr": False}
    copies_dir, copies = _copy_index(proj)

    plan, skipped, pending, eligible, invalid = [], [], [], set(), set()
    for r in cands:
        root = roots.get(r["Folder"])
        key = keys[(r["Folder"], r["RelativePath"])]
        if not root:
            skipped.append(_skip(r, key, "folder is no longer part of the project"))
            continue
        src = str(Path(root) / r["RelativePath"])
        if not os.path.exists(ex.win_path(src)):
            skipped.append(_skip(r, key, "file missing or moved since the catalogue was built"))
            continue
        eligible.add(key)
        if util.is_cloud_placeholder(src) and not proj.download_cloud_files:
            pending.append({"name": r["Name"], "folder": r["Folder"], "relative_path": r["RelativePath"], "kilobytes": r["Kilobytes"]})
            continue
        stamp, length = _stamp(src)
        ext = r["Ext"]
        version = reader_version(ext)
        if ext in (".doc",) and not probe["word"]:
            why = f"an old .doc file needs Microsoft Word: {office.PROBE_PROBLEM}" if office.PROBE_PROBLEM \
                else "an old .doc file needs Microsoft Word, which this PC does not have"
            skipped.append(_skip(r, key, why, stamp, length, version))
            invalid.add(key)
            continue
        failed = prior_fail.get(key)
        if failed and failed.get("file_mtime_utc") == stamp and str(failed.get("file_bytes")) == str(length) \
                and str(failed.get("reader_version")) == str(version):
            skipped.append(_skip(r, key, failed["reason"], stamp, length, version))
            invalid.add(key)
            continue
        old = existing.get(key)
        if old and (texts_out / f"{key}.txt").exists() and old.get("file_mtime_utc") == stamp \
                and int(old.get("file_bytes", -1)) == length and int(old.get("reader_version", 0)) == version:
            ok = True
            if ext in WORKBOOK_SUFFIXES:
                rec = out / (old.get("sheet_cells") or "")
                ok = bool(old.get("sheet_cells")) and rec.exists() and util.hash_file(rec) == old.get("cells_sha256")
            if ok and ext == ".xls":
                # an .xlsx copy made since the last run brings formulas: read the file again
                entry = copies.get(src.lower())
                copy_now = entry.get("copy_sha256") if entry else "no-copy"
                ok = old.get("extra_hash") == copy_now and not (copy_now == "no-copy" and probe["excel"])
            if ok:
                continue
        plan.append({"row": r, "key": key, "src": src, "ext": ext, "stamp": stamp, "length": length,
                     "version": version})
        if max_files and len(plan) >= max_files:
            break
    util.say("docs", f"to read now: {len(plan)}; pending in the cloud: {len(pending)}; unreadable: {len(skipped)}")
    live = util.live_on()
    if live:
        # every document: the ones already read first, then the ones read now in reading order, then the rest
        now = [p["key"] for p in plan]
        now_set = set(now)
        later = ({s["key"] for s in skipped} | {keys[(x["folder"], x["relative_path"])] for x in pending}) - now_set
        done = [k for k in (keys[(r["Folder"], r["RelativePath"])] for r in cands) if k not in later and k not in now_set]
        util.live("docs", keys=done + now + sorted(later), read=len(done))
        told = time.monotonic()

    results = {}
    for n, p in enumerate(plan, 1):
        r, key, src, ext = p["row"], p["key"], p["src"], p["ext"]
        txt = str(texts_out / f"{key}.txt")
        records = str(sheets_out / f"{key}.jsonl") if ext in WORKBOOK_SUFFIXES else None
        aux = None
        if ext in TEXT_EXT:
            meta = ex.read_plain(src, txt)
        elif ext == ".doc" or (ext == ".rtf" and probe["word"]):
            ok, err = office.word_to_text(src, txt)
            meta = {"ok": True, "method": "word", "pages": None, "needs_ocr": False} if ok else {"ok": False, "error": err}
            if not ok and ext == ".rtf":
                meta = ex.extract(src, txt)            # Word refused it: the plain RTF reader still can
        elif ext in DOC_SUFFIXES:
            meta = ex.extract(src, txt)
        else:
            xlsx_copy = None
            if ext == ".xls":
                xlsx_copy = xlsx_copy_of(proj, src, key, probe["excel"], copies, copies_dir)
                aux = util.hash_file(xlsx_copy) if xlsx_copy else "no-copy"
            meta = sheets.extract(src, txt, records, units, aliases, xlsx_copy)
            if not meta.get("ok") and ext in (".xlsx", ".xlsm") and probe["excel"]:
                # a workbook Python rejects: let Excel re-save it, read values and formulas from that
                xlsx_copy = xlsx_copy_of(proj, src, key, True, copies, copies_dir)
                if xlsx_copy:
                    meta = sheets.extract(xlsx_copy, txt, records, units, aliases)
                    if meta.get("ok"):
                        meta["method"] = "excel-resave"
                        aux = util.hash_file(xlsx_copy)
        if meta.get("ok") and os.path.exists(txt):
            row = _index_row(r, key, txt, meta, p, out, records, aux)
            results[key] = row
        else:
            skipped.append(_skip(r, key, f"could not read: {meta.get('error', 'unknown reason')}", p["stamp"],
                                 p["length"], p["version"]))
            invalid.add(key)
        if n % 25 == 0 or n == len(plan):
            util.say("docs", f"  [{n}/{len(plan)}] {key}")
        if live and (n == len(plan) or time.monotonic() - told > 0.25):
            util.live("read", n=len(done) + n)
            told = time.monotonic()
    if copies:
        util.save_json(copies_dir / "copies.json", dict(sorted(copies.items())))

    # merge with the rows kept from earlier runs, then write the index sorted by key
    merged = {}
    for k, row in existing.items():
        if k in invalid or (prune and k not in eligible):
            continue
        merged[k] = row
    merged.update(results)
    final = [merged[k] for k in sorted(merged) if (texts_out / f"{k}.txt").exists()]

    ocr_count = 0
    if ocr:
        ocr_count = _ocr_pass(final, roots, texts_out, probe.get("ocr_languages") or [], retry_unreadable)
    util.save_jsonl(jsonl, final)

    if prune:
        keep_txt = {Path(r["cached_text"]).name for r in final}
        keep_rec = {Path(r["sheet_cells"]).name for r in final if r.get("sheet_cells")}
        for f in texts_out.glob("*.txt"):
            if f.name not in keep_txt:
                f.unlink()
        for f in sheets_out.glob("*.jsonl"):
            if f.name not in keep_rec:
                f.unlink()

    dup_header = ["name", "kilobytes", "folder", "relative_path", "copy_of", "kept_as"]
    util.save_csv(out / "copies.csv", dup_header,
                   [[d[h] for h in dup_header] for d in sorted(dups, key=lambda d: (d["name"], d["folder"], d["relative_path"]))])
    pend_header = ["name", "folder", "relative_path", "kilobytes"]
    util.save_csv(out / "not-downloaded.csv", pend_header,
                   [[d[h] for h in pend_header] for d in sorted(pending, key=lambda d: (d["folder"], d["relative_path"]))])
    skip_header = ["name", "key", "folder", "relative_path", "reason", "file_mtime_utc", "file_bytes",
                   "reader_version"]
    util.save_csv(out / "not-read.csv", skip_header,
                   [[s.get(h, "") for h in skip_header] for s in sorted(skipped, key=lambda s: (s["folder"], s["relative_path"]))])

    methods = Counter(r["method"] for r in final)
    exts = Counter(r["ext"] for r in final)
    fingerprint = util.sha256_bytes(";".join(f"{r['key']}:{r['sha256']}" for r in final).encode("utf-8"))
    every_row = util.csv_rows(proj.catalogue_dir / "all-files.csv")
    coverage = {
        "format_version": 1,
        "scope": scope,
        "readable_extensions": sorted(READABLE_SUFFIXES),
        "in_catalogue": dict(sorted(Counter(r["Ext"] for r in readable).items())),
        "cached": dict(sorted(exts.items())),
        "not_readable_sheet_like": dict(sorted(Counter(r["Ext"] for r in every_row if r["Ext"] in SHEET_LIKE_UNREAD).items())),
        "cached_count": len(final),
        "skipped_count": len(skipped),
        "pending_count": len(pending),
        "duplicates_count": len(dups),
        "ocr_count": sum(1 for r in final if r["method"] in OCR_METHODS),
        "ocr_partial_count": sum(1 for r in final if r.get("ocr_partial")),
        "scanned_unread_count": sum(1 for r in final if r.get("needs_ocr") and r["method"] not in OCR_METHODS),
        "ocr_doubtful_count": sum(1 for r in final if r["method"] in OCR_METHODS and r.get("ocr_doubtful_pages")),
    }
    util.save_json(out / "text-coverage.json", coverage)
    util.save_json(out / "text-info.json", {
        "built_utc": util.utc_now(), "scope": scope, "docs_count": len(final), "duplicates_count": len(dups),
        "pending_count": len(pending), "skipped_count": len(skipped), "methods": dict(sorted(methods.items())),
        "extensions": dict(sorted(exts.items())), "sheet_schema": sheets.SHEET_SCHEMA_VERSION,
        "sheet_reader_version": sheets.SHEET_READER_VERSION, "word_file_version": WORD_FILE_VERSION,
        "docs_hash": fingerprint,
        "readers": dict(probe, problem=office.PROBE_PROBLEM) if office.PROBE_PROBLEM else probe, "ocr_this_run": ocr_count,
        "note": "PDF, .docx, text and spreadsheet text depends only on the file and the reader version; "
                "text that Word or text recognition produced can differ between their versions."})
    util.say("docs", f"{len(final)} documents cached, {len(dups)} copies, {len(pending)} pending, "
                     f"{len(skipped)} unreadable; by method: " + ", ".join(f"{k} {v}" for k, v in sorted(methods.items())))
    return coverage


def _ocr_pass(rows: list[dict], roots: dict, texts_out: Path, windows_languages: list[str],
              retry: bool = False) -> int:
    """Scanned PDFs (almost no text per page) are read again by text recognition (docs/ocr.py), and so
    are those an older version of it read. A scan recognition could not read is tried again when the
    file changes, when this PC gains a reader or a newer recognition, or with --full (`retry`)."""
    rapid = recognition.rapid_models()
    attempt = f"{recognition.OCR_VERSION}: " + ", ".join(sorted(windows_languages) + rapid)

    def wanted(r: dict) -> bool:
        if not (r.get("needs_ocr") and r["ext"] == ".pdf"):
            return False
        if r["method"] in OCR_METHODS and r.get("ocr_version") == recognition.OCR_VERSION:
            return False
        return retry or r.get("ocr_tried") != attempt

    todo = [r for r in rows if wanted(r)]
    if not todo:
        return 0
    if not windows_languages and not rapid:
        why = recognition.rapid_problem() or "no reader"
        for r in todo:
            if r["method"] not in OCR_METHODS:
                r["ocr_problem"] = f"no text recognition on this PC: no Windows recognition language, and {why}"
        return 0
    done = 0
    for r in todo:
        src = str(Path(roots.get(r["folder"], "")) / r["relative_path"])
        if not os.path.exists(ex.win_path(src)):
            continue
        try:
            result = recognition.read_pdf(src, windows_languages)
        except Exception as exc:  # noqa: BLE001 - one scan's failure is that scan's reason, never the build's
            result = recognition.Outcome(False, error=f"{type(exc).__name__}: {exc}")
        if not result.ok or len(re.sub(r"\s", "", result.text)) < 20:
            r["ocr_tried"] = attempt                 # not again until something changes
            if r["method"] not in OCR_METHODS:      # an older recognition stays until a newer one reads
                r["ocr_problem"] = result.error if not result.ok else "text recognition found no text"
            continue
        path = texts_out / f"{r['key']}.txt"
        ex.write_out(path, result.text)
        for stale in ("ocr_problem", "ocr_partial", "ocr_tried"):
            r.pop(stale, None)
        r.update({"method": "ocr", "ocr_version": recognition.OCR_VERSION, "chars": len(result.text),
                  "sha256": util.hash_file(path), "ocr_pages": result.pages,
                  "ocr_readers": dict(sorted(result.readers.items())), "ocr_turned_pages": result.turned,
                  "ocr_empty_pages": result.empty, "ocr_doubtful_pages": result.doubtful})
        if result.pages < (r.get("pages") or result.page_count):
            r["ocr_partial"] = True           # said, never silent: only the first pages were recognised
        done += 1
        readers = ", ".join(f"{k} {v}" for k, v in sorted(result.readers.items()))
        util.say("docs", f"  text recognition: {r['key']} ({result.pages} of {r.get('pages') or result.page_count} "
                         f"pages; {readers}{f'; {result.turned} turned' if result.turned else ''}"
                         f"{f'; {result.doubtful} doubtful' if result.doubtful else ''})")
    return done


def _skip(r: dict, key: str, reason: str, stamp: str = "", length: int | str = "", version: int | str = "") -> dict:
    return {"name": r["Name"], "key": key, "folder": r["Folder"], "relative_path": r["RelativePath"], "reason": reason,
            "file_mtime_utc": stamp, "file_bytes": length, "reader_version": version}


def _index_row(r: dict, key: str, txt: str, meta: dict, p: dict, out: Path, records: str | None, aux) -> dict:
    with open(ex.win_path(txt), encoding="utf-8") as fh:
        chars_count = len(fh.read())
    row = {
        "key": key,
        "cached_text": f"text/{key}.txt",
        "folder": r["Folder"],
        "relative_path": r["RelativePath"],
        "doc_numbers": r["DocNumbers"],
        "category": r["Category"],
        "products": r["Products"],
        "priority": r["Priority"],
        "ext": r["Ext"],
        "method": meta.get("method", "?"),
        "chars": chars_count,
        "pages": meta.get("pages"),
        "needs_ocr": bool(meta.get("needs_ocr")),
        "sha256": util.hash_file(ex.win_path(txt)),
        "file_mtime_utc": p["stamp"],
        "file_bytes": p["length"],
        "reader_version": p["version"],
        "doc_title": meta.get("title") or "",
        "doc_title_source": meta.get("title_source") or "",
    }
    if records and os.path.exists(records):
        row.update({
            "sheet_cells": f"sheets/{key}.jsonl",
            "sheet_schema": meta.get("sheet_schema"),
            "cells_sha256": meta.get("cells_sha256") or util.hash_file(records),
            "records_count": meta.get("records_count", 0),
            "formulas_count": meta.get("formulas_count", 0),
            "extra_hash": aux,
        })
    return row
