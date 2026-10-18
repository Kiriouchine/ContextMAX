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

from contextmax import office, parallel, util
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
PDF_VERSION = 3            # .pdf only. 3: where each page starts (page_lines), for a value's page
OCR_METHODS = {"ocr", "windows-ocr"}   # "windows-ocr": a document an earlier ContextMAX recognised
WORD_FILE_VERSION = 3      # .rtf and .doc only. 3: \uN escapes and symbol words in RTF read; Word's marks cleaned


def reader_version(ext: str) -> int:
    """The version of the reader whose output a cached text of this kind holds."""
    if ext in WORKBOOK_SUFFIXES:
        return sheets.SHEET_READER_VERSION
    if ext == ".pdf":
        return PDF_VERSION
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
    different documents share that base name. Keys therefore never shift between runs.
    Names are compared without regard to capitals: a key is also a file name (text/<key>.txt), and
    Windows takes ReadMe.txt and readme.txt for one file, so one document's text would replace the other's."""
    counts = Counter(_base(r["Name"]).casefold() for r in cands)
    keys = {}
    for r in cands:
        b = _base(r["Name"])
        if counts[b.casefold()] > 1:
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


def migrate(proj: Project) -> bool:
    """Before 0.4.1 the hash of a document's extracted text was called "sha256" in text-index.jsonl, which reads
    like the hash of the file itself (an AI concluded from it that two different PDFs were the same file). It is
    "text_sha256" now; an older index is renamed in place, once, keeping each row's order of fields."""
    path = proj.documents_dir / "text-index.jsonl"
    rows = util.load_jsonl(path) if path.exists() else []
    if not any("sha256" in r for r in rows):
        return False
    util.save_jsonl(path, [{("text_sha256" if k == "sha256" else k): v for k, v in r.items()} for r in rows])
    return True


def build(proj: Project, scope: str = "all", resume: bool = True, prune: bool = True,
          retry_unreadable: bool = False, ocr: bool = True, max_files: int = 0) -> dict:
    migrate(proj)
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
    if wants_office or ocr:
        util.say("docs", "checking which readers this PC has: Word, Excel, text recognition")
    probe = office.probe() if (wants_office or ocr) else {"word": False, "excel": False, "ocr": False}
    copies_dir, copies = _copy_index(proj)

    plan, skipped, pending, eligible, invalid = [], [], [], set(), set()
    looking = util.Progress("docs", "checking which documents are new or changed", len(cands))
    for r in cands:
        looking.tick(r["Name"])
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
                and int(old.get("file_bytes", -1)) == length \
                and (int(old.get("reader_version", 0)) == version or old.get("method") in OCR_METHODS):
            # a recognised scan is kept: its text is the recognition's, whatever reads the PDF's own text
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
    reading = util.Progress("docs", "reading documents", len(plan))
    read_count = 0

    def record(p: dict, meta: dict, row: dict | None, records: str | None = None, aux=None) -> None:
        nonlocal read_count, told
        key = p["key"]
        txt = str(texts_out / f"{key}.txt")
        if row is None and meta.get("ok") and os.path.exists(txt):
            row = _index_row(p["row"], key, txt, meta, p, out, records, aux)
        if row is not None:
            results[key] = row
        else:
            skipped.append(_skip(p["row"], key, f"could not read: {meta.get('error', 'unknown reason')}", p["stamp"],
                                 p["length"], p["version"]))
            invalid.add(key)
        read_count += 1
        reading.tick(key)
        if live and (read_count == len(plan) or time.monotonic() - told > 0.25):
            util.live("read", n=len(done) + read_count)
            told = time.monotonic()

    def checkpoint() -> None:
        """The index as far as it goes, for a build that stops: the documents not read again, those read
        now, and none of those still to be read (the next build reads them)."""
        planned = {p["key"] for p in plan}
        rows = {k: row for k, row in existing.items()
                if k not in planned and k not in invalid and (not prune or k in eligible)}
        rows.update(results)
        util.save_jsonl(jsonl, [rows[k] for k in sorted(rows) if (texts_out / f"{k}.txt").exists()])

    # Word and Excel open one document at a time, here; the workers read every other document meanwhile
    by_office = [p for p in plan if _needs_office(p["ext"], probe)]
    elsewhere = [p for p in plan if not _needs_office(p["ext"], probe)]
    jobs = [{"p": p, "txt": str(texts_out / f"{p['key']}.txt"),
             "records": str(sheets_out / f"{p['key']}.jsonl") if p["ext"] in WORKBOOK_SUFFIXES else None,
             "units": voc.get("units"), "aliases": aliases} for p in elsewhere]
    # handed out in batches: ten thousand single documents would spend their time going to and from the
    # workers. A batch whose worker dies is read again document by document, each in a process of its own
    size = max(1, min(32, len(jobs) // (parallel.workers() * 8) or 1))
    batches = [list(range(i, min(i + size, len(jobs)))) for i in range(0, len(jobs), size)]
    try:
        with parallel.Spread(_read_some, [[jobs[j] for j in b] for b in batches], min_items=4) as spread:
            if spread.n > 1:
                util.say("docs", f"reading {len(jobs):,} documents, {spread.n} at a time"
                                 + (f"; {len(by_office)} with Word or Excel, one at a time" if by_office else ""))
            for p in by_office:
                reading.doing(p["key"])
                records = str(sheets_out / f"{p['key']}.jsonl") if p["ext"] in WORKBOOK_SUFFIXES else None
                meta, aux = _read_with_office(proj, p, str(texts_out / f"{p['key']}.txt"), records, probe, copies,
                                              copies_dir, units, aliases)
                record(p, meta, None, records, aux)
            for b, got in spread.results():
                for i, res in zip(batches[b], _one_by_one(got, [jobs[j] for j in batches[b]]), strict=True):
                    p, job = elsewhere[i], jobs[i]
                    if isinstance(res, Exception):
                        res = {"meta": {"ok": False, "error": f"{type(res).__name__}: {res}"}, "row": None}
                    meta, aux = res["meta"], None
                    if res["row"] is None and p["ext"] in (".xlsx", ".xlsm") and probe["excel"]:
                        # a workbook Python rejects: let Excel re-save it, read values and formulas from that
                        xlsx_copy = xlsx_copy_of(proj, p["src"], p["key"], True, copies, copies_dir)
                        if xlsx_copy:
                            meta = sheets.extract(xlsx_copy, job["txt"], job["records"], units, aliases)
                            if meta.get("ok"):
                                meta["method"] = "excel-resave"
                                aux = util.hash_file(xlsx_copy)
                    record(p, meta, res["row"], job["records"], aux)
    except (util.Stopped, KeyboardInterrupt):
        checkpoint()
        raise
    if copies:
        util.save_json(copies_dir / "copies.json", dict(sorted(copies.items())))

    # merge with the rows kept from earlier runs, then write the index sorted by key
    merged = {}
    for k, row in existing.items():
        if k in invalid or (prune and k not in eligible):
            continue
        merged[k] = row
    for k, row in results.items():
        old = existing.get(k)
        if old and old.get("file_mtime_utc") == row["file_mtime_utc"] and str(old.get("file_bytes")) == str(row["file_bytes"]):
            # the same file read again by a newer reader: what recognition already tried on it still holds
            row.update({f: old[f] for f in ("ocr_tried", "ocr_problem") if f in old and f not in row})
    merged.update(results)
    final = [merged[k] for k in sorted(merged) if (texts_out / f"{k}.txt").exists()]

    ocr_count = 0
    if ocr:
        util.save_jsonl(jsonl, final)           # what is read so far is kept, should the build stop
        try:
            ocr_count = _ocr_pass(final, roots, texts_out, probe.get("ocr_languages") or [], retry_unreadable,
                                  save=lambda: util.save_jsonl(jsonl, final))
        except (util.Stopped, KeyboardInterrupt):
            util.save_jsonl(jsonl, final)       # the scans recognised so far are kept too
            raise
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
    fingerprint = util.sha256_bytes(";".join(f"{r['key']}:{r['text_sha256']}" for r in final).encode("utf-8"))
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
        "ocr_unpaged_count": sum(1 for r in final if r["method"] in OCR_METHODS and not r.get("page_lines")),
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
    # the counts of this run go to the log's summary only: text-coverage.json stays the same either way
    return dict(coverage, read_now=len(plan), ocr_now=ocr_count)


def _ocr_pass(rows: list[dict], roots: dict, texts_out: Path, windows_languages: list[str],
              retry: bool = False, save=None) -> int:
    """Scanned PDFs (almost no text per page) are read again by text recognition (docs/ocr.py), and so
    are those an older version of it read. A scan recognition could not read is tried again when the
    file changes, when this PC gains a reader or a newer recognition, or with --full (`retry`)."""
    rapid = recognition.rapid_models()
    attempt = f"{recognition.OCR_VERSION}: " + ", ".join(sorted(windows_languages) + rapid)

    def wanted(r: dict) -> bool:
        if not (r.get("needs_ocr") and r["ext"] == ".pdf"):
            return False
        if r["method"] in OCR_METHODS and r.get("ocr_version") == recognition.OCR_VERSION and not r.get("ocr_partial") \
                and (r.get("page_lines") or not retry):
            # read by this recognition, every page (once there was a cap). A scan recognised before pages
            # were recorded is read again only when asked (--full): its values cite a line until then
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
    # every scan in pieces of a few pages (ocr.chunks), the pieces of the largest scans first, so every
    # worker is busy until the end. A page's text depends on that page only: the order the pieces are
    # read in, and how many workers read them, change nothing in the index
    scans = []
    for r in todo:
        src = str(Path(roots.get(r["folder"], "")) / r["relative_path"])
        if not os.path.exists(ex.win_path(src)):
            continue
        try:
            count = int(r.get("pages") or recognition.page_count(src))
        except Exception as exc:  # noqa: BLE001 - this scan's reason, never the build's
            scans.append({"row": r, "count": 0, "pieces": [], "parts": {}, "fatal": f"cannot render pages: {exc}"})
            continue
        scans.append({"row": r, "count": count, "pieces": recognition.chunks(count), "parts": {}, "src": src})
    order = sorted(range(len(scans)), key=lambda i: (-scans[i]["count"], scans[i]["row"]["key"]))
    pieces = [(i, a, b) for i in order for a, b in scans[i]["pieces"]]
    pages = sum(s["count"] for s in scans)
    done, last_save = 0, time.monotonic()

    def settle(scan: dict) -> None:
        """A scan whose pieces are all read: its text, and what the index says of it."""
        nonlocal done, last_save
        r = scan["row"]
        if scan.get("fatal"):
            result = recognition.Outcome(False, error=scan["fatal"])
        else:
            result = recognition.merge([scan["parts"][a] for a, _ in scan["pieces"]])
        if not result.ok or len(re.sub(r"\s", "", result.text)) < 20:
            r["ocr_tried"] = attempt                 # not again until something changes
            if r["method"] not in OCR_METHODS:      # an older recognition stays until a newer one reads
                r["ocr_problem"] = result.error if not result.ok else "text recognition found no text"
            util.say("docs", f"  text recognition: {r['key']}: no text found"
                             + (f" ({result.error})" if not result.ok and result.error else ""))
        else:
            path = texts_out / f"{r['key']}.txt"
            ex.write_out(path, result.text)
            for stale in ("ocr_problem", "ocr_partial", "ocr_tried"):
                r.pop(stale, None)
            r.pop("page_lines", None)
            if result.page_lines:
                r["page_lines"] = result.page_lines
            r.update({"method": "ocr", "ocr_version": recognition.OCR_VERSION, "chars": len(result.text),
                      "text_sha256": util.hash_file(path), "ocr_pages": result.pages,
                      "ocr_readers": dict(sorted(result.readers.items())), "ocr_turned_pages": result.turned,
                      "ocr_empty_pages": result.empty, "ocr_doubtful_pages": result.doubtful})
            if result.pages < (r.get("pages") or result.page_count):
                r["ocr_partial"] = True           # said, never silent: only the first pages were recognised
            done += 1
            readers = ", ".join(f"{k} {v}" for k, v in sorted(result.readers.items()))
            util.say("docs", f"  text recognition: {r['key']} ({result.pages} of {r.get('pages') or result.page_count} "
                             f"pages; {readers}{f'; {result.turned} turned' if result.turned else ''}"
                             f"{f'; {result.doubtful} doubtful' if result.doubtful else ''})")
        if save and time.monotonic() - last_save > 30:
            save()
            last_save = time.monotonic()

    jobs = [{"src": scans[i]["src"], "first": a, "last": b, "languages": windows_languages} for i, a, b in pieces]
    with parallel.Spread(_recognise_pages, jobs) as spread:
        util.say("docs", f"text recognition: {util.count(len(scans), 'scanned PDF')}, {util.count(pages, 'page')}, "
                         f"{util.count(len(pieces), 'piece')} of up to {recognition.CHUNK_PAGES} pages"
                         + (f"; {spread.n} pieces at a time, the largest scans first" if spread.n > 1 else ""))
        recognising = util.Progress("docs", "text recognition, pages", pages)
        for scan in scans:
            if not scan["pieces"]:
                settle(scan)
        for k, part in spread.results():
            i, a, b = pieces[k]
            scan = scans[i]
            if isinstance(part, Exception):          # the piece's reader failed: the scan says why
                part = {"fatal": f"{type(part).__name__}: {part}"}
            scan["parts"][a] = part
            recognising.tick(scan["row"]["key"], b - a)
            if len(scan["parts"]) == len(scan["pieces"]):
                settle(scan)
    return done


def _needs_office(ext: str, probe: dict) -> bool:
    """Read by Word or with Excel's help: one document at a time, in the main process."""
    return ext in (".doc", ".xls") or (ext == ".rtf" and bool(probe.get("word")))


_UNITS: dict = {}


def _read_one(job: dict) -> dict:
    """One document read without Word or Excel: its text (and its cell records) written under its own key,
    and its index row. In a worker process, or here when the documents are read one at a time."""
    p, txt, records = job["p"], job["txt"], job["records"]
    ext, src = p["ext"], p["src"]
    if ext in TEXT_EXT:
        meta = ex.read_plain(src, txt)
    elif ext in DOC_SUFFIXES:
        meta = ex.extract(src, txt)
    else:
        units_key = repr(job["units"])
        if units_key not in _UNITS:
            _UNITS[units_key] = sheets.Units(job["units"])
        meta = sheets.extract(src, txt, records, _UNITS[units_key], job["aliases"], None)
    row = _index_row(p["row"], p["key"], txt, meta, p, None, records, None) if meta.get("ok") and os.path.exists(txt) else None
    return {"meta": meta, "row": row}


def _read_some(jobs: list[dict]) -> list:
    """A batch of documents read without Word or Excel; one document's error is that document's."""
    out = []
    for job in jobs:
        try:
            out.append(_read_one(job))
        except util.Stopped:
            raise                           # one at a time, here: a stop is the build's, not the document's
        except Exception as exc:  # noqa: BLE001 - the document's reason, never the batch's
            out.append(exc)
    return out


def _one_by_one(got, jobs: list[dict]) -> list:
    """A batch's results; when its worker died (or the batch failed whole), each document read again in a
    process of its own, so only a document that kills its process is unreadable."""
    if isinstance(got, list) and len(got) == len(jobs):
        return got
    return [parallel.isolated(_read_one, job) for job in jobs]


def _read_with_office(proj: Project, p: dict, txt: str, records: str | None, probe: dict, copies: dict,
                      copies_dir: Path, units, aliases: dict) -> tuple[dict, object]:
    """An old .doc, an .rtf Word reads, or an old .xls with the .xlsx copy Excel makes of it."""
    ext, src = p["ext"], p["src"]
    if ext == ".xls":
        xlsx_copy = xlsx_copy_of(proj, src, p["key"], probe["excel"], copies, copies_dir)
        aux = util.hash_file(xlsx_copy) if xlsx_copy else "no-copy"
        return sheets.extract(src, txt, records, units, aliases, xlsx_copy), aux
    ok, err = office.word_to_text(src, txt)
    meta = {"ok": True, "method": "word", "pages": None, "needs_ocr": False} if ok else {"ok": False, "error": err}
    if not ok and ext == ".rtf":
        meta = ex.extract(src, txt)            # Word refused it: the plain RTF reader still can
    return meta, None


def _recognise_pages(job: dict) -> dict:
    """A few pages of one scan recognised: in a worker process, or here when one at a time."""
    return recognition.read_pages(job["src"], job["first"], job["last"], job["languages"])


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
        "text_sha256": util.hash_file(ex.win_path(txt)),
        "file_mtime_utc": p["stamp"],
        "file_bytes": p["length"],
        "reader_version": p["version"],
        "doc_title": meta.get("title") or "",
        "doc_title_source": meta.get("title_source") or "",
    }
    if meta.get("page_lines"):
        row["page_lines"] = meta["page_lines"]
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
