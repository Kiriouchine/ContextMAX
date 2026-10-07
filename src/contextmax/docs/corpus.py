"""Stage 4: the document map. Which documents there are, what they say, and what they link to.

Stages, in order (each one reads only what the earlier ones wrote):
  fold_documents  every cached document gets a lifecycle stage and a recorded reason; copies and
                  revisions of one document fold into a single node, and every copy stays listed
  code_links      a document names code only through distinctive names (symbols.py); the link is
                  graded by how many names it uses. A document about a part of the code that names
                  none of it is marked as about that part, which is never drawn as a link to code
  structure       headings, "shall" statements with their IDs, and every value with a unit
  values          every named value in one list with its origin and exact cell (params.jsonl), and
                  the same as an indexed SQLite database (params.sqlite)
  document_links  document to document: a quoted document number, a cited title or file name,
                  named values stated in both, and a shared part of the code
  docs_of_code    the same links read backwards: which documents describe a module or a function
  validate        a strict gate over everything above; a failure stops the build

Every output is sorted and carries no timestamp, so the same inputs give the same bytes.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from contextmax import util
from contextmax.docs import params as P
from contextmax.docs import symbols as SYM
from contextmax.project import Project

SHEET_SUFFIXES = {".csv", ".xls", ".xlsm", ".xlsx"}


def _any(*alternatives: str) -> str:
    """Regex alternatives, tried in the order given."""
    return "|".join(alternatives)


# File names that are never documents of the project, whatever folder they sit in.
NOISE_NAMES = re.compile(_any(r"licen[sc]e", "^copying$", "^notice$", "^configuration$",
                              "^settings$", "^thumbs", r"desktop\.ini", "^changelog$", r"^requirements(?:-dev)?$"), re.I)
# A .txt file is read when its name says it is written for people, and not when it is a log.
TXT_KEEP = re.compile(_any("manual", "specification", r"\bspec\b", "procedure", "protocol", "guideline", "instruction",
                           "datasheet", "data[_ ]?sheet", "readme", "requirement", "design", r"notes?\b", "description",
                           "overview"), re.I)
LOG_NAME_RE = re.compile(_any("^log[_-]", "[_-]log$", r"\blog\b", "resultlog", "eventlog", "errorlog", "trace", "dump",
                              "_run_", r"\brun\d", r"sn\d{3,}", r"measure(?:ment)?s?[_-]?\d"), re.I)
# Folders that hold superseded or commented copies; and words that mark the released one.
_SET_ASIDE = _any("old(?:er)?(?: files?| versions?)?", "reviews?(?: comments?)?", "drafts?", "archive", "backup",
                  "superseded", "obsolete")
REVIEW_COPY_RE = re.compile(r"(?:^|[/\\])(" + _SET_ASIDE + r")(?:[/\\]|$)|\bcommented\b", re.I)
RELEASE_WORDS = re.compile(r"\b(?:" + _any("released?", "approved", "final", "current", "signed") + r")\b|deliverables",
                           re.I)
# The tails that make one document look like several: versions, revisions, review states, copies.
_REVISION_MARKS = _any(r"v(?:er(?:sion)?)?[ _.]?\d+(?:[._]\d+)*[a-z]?", r"rev(?:ision)?[ _.-]?[a-z0-9]{1,3}",
                       r"issue[ _.-]?\d{1,3}", "draft", "final", "signed", "approved", "released?", "reviewed", "review",
                       "commented", "comments", "copy", "old", "new", r"\(\d+\)")
VERSION_TAIL = re.compile(r"(?:[ _.-]+(?:" + _REVISION_MARKS + r"))+$", re.I)
DATE_TAIL = re.compile(r"[ _-] (?:19|20) \d{6} (?: [ _-] [A-Za-z]{1,4} )? $", re.VERBOSE)
COPY_PREFIX = re.compile(r"^(?:" + _any("copy of", "kopie van", "kopie von", "copie de", "copia de") + r")\s+", re.I)
RECURRING = re.compile(_any("meeting", "minutes", r"\bmom\b", "status", "weekly", "daily", r"\bnotes?\b", "report",
                            r"\blog\b", "agenda"), re.I)
IDENT_RE = re.compile(r"[_0-9A-Za-z]+")
WORDS_RE = re.compile(r"[0-9a-z]+")
GENERIC_TITLE_WORDS = frozenset("""
    a and copy data doc document draft file final for in list meeting minutes new notes of old overview plan
    report results rev review sheet summary table test the to v1 v2 v3 version
""".split())
GENERIC_MODULES = frozenset("""
    (top) app common core doc docs general inc include lib main misc src test tests tools util utils
""".split())

NUMBERED_HEADING = re.compile(r"""
    ^ [\t ]{,6} ( \d+ (?: [.] \d+ ){,3} ) [.]? [\t ]+          # 3.1.2 or 3.1.2.
    ( [A-Z] [ ,&()/\-0-9A-Za-z]{2,58}? )                       # the title
    (?: [.\t ]+ \d{1,4} )? [\t ]* $                             # perhaps a page number
""", re.MULTILINE | re.VERBOSE)
MARKDOWN_HEADING = re.compile(r"^ (\#{1,6}) [\t ]+ (.{2,120}?) [\t \#]* $", re.MULTILINE | re.VERBOSE)
UNIT_WORDS = (
    "mm", "cm", "km", "µm", "um", "nm", "°/s²", "°/s", "°C", "°", "degrees?", "deg",
    "rad/s", "rad", "rpm", "mNm", "Nm", "kN", "kΩ", "Ω", "ohm", "mH", "µH", "uH", "nH",
    "kV", "mV", "µV", "uV", "GHz", "kHz", "MHz", "Hz", "mA", "µA", "uA", "ms", "µs", "us", "ns",
    "kW", "mW", "W", "mbar", "kPa", "MPa", "Pa", "bar", "dB", "ppm", "counts?", "bits?", "bytes?", "kB", "MB", "GB",
    "m/s²", "m/s", "mm/s", "A", "V", "N", "g", "kg", "mg", "%", "K", "s", "m",
)                                  # longer spellings first: "ms" before "m", "mm/s" never as "mm"
_UNITS = _any(*UNIT_WORDS)
_NUMBER = r"[+-]?\d+(?:[,.]\d+)?"
VALUE_RANGE = re.compile(rf"(?<![.\w])({_NUMBER})\s*(?:to|-|–|—)\s*({_NUMBER})\s*({_UNITS})(?![a-zA-Z])", re.I)
VALUE_WITH_UNIT = re.compile(rf"(?<![,.\w])({_NUMBER})\s*({_UNITS})(?![0-9A-Za-z])")
SHALL_LINE_RE = re.compile(r"\b shall \b", re.IGNORECASE | re.VERBOSE)
_SENTENCE_BREAK = re.compile(r"(?<=[!.?])\s+|\n+")
# The address sheets.py writes after a cell's value: "@Budget!B4".
CELL_ORIGIN = re.compile(r"@(?P<sheet>.+?)!(?P<cell>[$]?[A-Z]{1,3}[$]?\d{1,7})(?=\s|$)")
_NAME_DATE = re.compile(r"(?<!\d)((?:20|19)\d{6})(?!\d)")
_REF_FOLD = str.maketrans("_", ".")
# "settle time: 12 ms" or "- output limit = 1000 counts": a short name, then the value. A name is at
# most five words and never a sentence (no full stop inside, no "shall").
PROSE_LABEL = re.compile(r"""
    ^ \s* (?: [*\-•] \s* )?                                          # perhaps a bullet
    ( (?: [A-Za-z] [()/_\-0-9A-Za-z]* ) (?: \  [()/_\-0-9A-Za-z]+ ){0,4} )   # one to five words
    \s* (?: : | = ) \s* $
""", re.VERBOSE)

STRUCT_CAP = 1000
MAX_VALUE_OWNERS = 12       # a value name stated by more documents than this is generic
SHARED_VALUE_MIN = 2        # documents sharing this many named values are linked; one is enough if specific
SHARED_VALUE_CAP = 8        # strongest value links kept per document
CITE_CAP = 40


# Catalogue fields a document keeps as they are; and those each copy of a document lists.
_KEPT_FIELDS = ("category", "folder", "relative_path", "ext", "chars", "pages", "doc_numbers", "sha256", "cached_text",
                "sheet_cells", "file_mtime_utc", "method")
_COPY_FIELDS = ("title", "folder", "relative_path", "ext", "kind", "stage", "module", "category", "cached_text")
# The fields of one value row, as params.jsonl stores them and validate() expects them.
_VALUE_FIELDS = ("value", "unit", "kind", "value_as_written", "value_shown", "unit_as_written", "value_norm",
                 "value_exact_norm", "unit_norm", "origin", "label", "label_norm", "sheet", "cell", "formula", "hidden",
                 "context")
_OUTLINE_KEYS = ("value", "unit", "kind", "value_norm", "unit_norm", "context")
_SHEET_OUTLINE_KEYS = ("value", "unit", "kind", "value_norm", "unit_norm", "origin", "label", "label_norm", "context")
_NAMED_KINDS = frozenset({"constant", "entity", "function"})
_EDGE_IDENTITY = ("kind", "from", "to", "module", "doc_number")      # one document link per such tuple


def _stem(row: dict) -> str:
    name = os.path.basename(row.get("relative_path") or row.get("key") or "")
    return os.path.splitext(name)[0]


def _ext(row: dict) -> str:
    return (row.get("ext") or "").lower()


def _one_line(text: str) -> str:
    return " ".join(text.split())


def canonical(row: dict) -> str:
    """Fold the spellings of one document: version and review tails, a revision date, separators.
    Recurring records (minutes, reports, logs) keep their dates: each one is its own document."""
    s = _stem(row).strip()
    if not RECURRING.search(s):
        t = DATE_TAIL.sub("", s)
        if len(t) >= 4:
            s = t
    for _ in range(3):
        t = VERSION_TAIL.sub("", s)
        if len(t) < 3:
            break
        s = t
    s = COPY_PREFIX.sub("", s)
    return re.sub(r"[ _.\-]+", "-", s.lower()).strip("-") or s.lower()


def copy_preference(d: dict) -> tuple:
    """Which copy stands for the document: a released location beats a review folder, the newest
    revision date in the name beats the file's date (a sync can make an old file look new)."""
    path = (d.get("relative_path") or "") + " " + (d.get("key") or "")
    newest_date = max(_NAME_DATE.findall(path), default="")
    return (0 if REVIEW_COPY_RE.search(path) else 1, 1 if RELEASE_WORDS.search(path) else 0, newest_date,
            str(d.get("file_mtime_utc") or ""), int(d.get("chars") or 0), d.get("key") or "")


def included(row: dict) -> bool:
    stem = _stem(row)
    if NOISE_NAMES.search(stem):
        return False
    return _ext(row) != ".txt" or bool(TXT_KEEP.search(stem) and not LOG_NAME_RE.search(stem))


class Rules:
    """The project's classification vocabulary, compiled once."""

    def __init__(self, voc: dict):
        self.stages = list(voc.get("stages") or [])
        if "General" not in self.stages:
            self.stages.append("General")
        self.by_category = voc.get("stage_of_category") or {}
        self.by_filename = [(re.compile(r["pattern"], re.I), r["stage"]) for r in voc.get("stage_name_rules") or []]
        self.by_workbook = [(re.compile(r["pattern"], re.I), r["stage"]) for r in voc.get("stage_sheet_rules") or []]
        conv = voc.get("convention") or None
        self.conv = (re.compile(conv["pattern"], re.I), conv.get("types") or {}, conv.get("modules") or {}) if conv else None
        self.req_ids = [re.compile(p, re.I) for p in voc.get("requirement_id_patterns") or []]
        self.doc_numbers = [re.compile(p) for p in voc.get("doc_number_patterns") or []]
        self.topic_words = {k.lower(): v for k, v in (voc.get("topic_words") or {}).items()}

    def assign(self, row: dict) -> tuple[str, str | None, str]:
        """(stage, module or None, reason). Never empty: an unplaced document is 'General'."""
        name = _stem(row)
        module = None
        if self.conv:
            rx, types, modules = self.conv
            m = rx.search((row.get("key") or "") + " " + name)
            if m:
                typ = m.group(1).upper()
                module = modules.get(m.group(2).upper()) if m.lastindex and m.lastindex >= 2 else None
                if typ in types:
                    return types[typ], module, "convention:" + typ
        if _ext(row) in SHEET_SUFFIXES:
            for rx, stage in self.by_workbook:
                if rx.search(name):
                    return stage, module, "sheet-name:" + stage
        category = row.get("category")
        if category in self.by_category:
            return self.by_category[category], module, "category:" + category
        for rx, stage in self.by_filename:
            if rx.search(name):
                return stage, module, "name:" + stage
        return "General", module, "fallback"

    def stage_index(self, stage: str) -> int:
        return self.stages.index(stage) if stage in self.stages else len(self.stages)


# == fold_documents ==

def fold_documents(proj: Project, rules: Rules) -> tuple[list[dict], list[dict], dict]:
    rows = util.load_jsonl(proj.documents_dir / "text-index.jsonl")
    kept = [r for r in rows if included(r)]
    excluded = len(rows) - len(kept)
    docs = []
    for r in kept:
        stage, module, reason = rules.assign(r)
        doc = {field: r.get(field) for field in _KEPT_FIELDS}
        doc.update(key=r["key"], title=_stem(r), stage=stage, module=module, reason=reason,
                   kind="spreadsheet" if _ext(r) in SHEET_SUFFIXES else "document",
                   products=sorted({t for t in (r.get("products") or "").split(";") if t}),
                   priority=r.get("priority") or "", doc_title=r.get("doc_title") or "")
        docs.append(doc)
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        groups[canonical(d)].append(d)
    core, sources = [], []
    for ck in sorted(groups):
        variants = groups[ck]
        rep = dict(max(variants, key=copy_preference))
        rep.update(canonical=ck, copies=len(variants),
                   copy_list=sorted(v["key"] for v in variants if v["key"] != rep["key"]),
                   distinct_texts=len({v["sha256"] for v in variants if v.get("sha256")}),
                   products=sorted({t for v in variants for t in v["products"]}))
        core.append(rep)
        sources.extend(dict(file_key=v["key"], node_ref=rep["key"], **{f: v[f] for f in _COPY_FIELDS},
                            sheet_cells=v.get("sheet_cells"), sha256=v["sha256"]) for v in variants)
    core.sort(key=lambda d: (rules.stage_index(d["stage"]), d["module"] or "~", d["key"]))
    sources.sort(key=lambda s: (s["file_key"], s["node_ref"]))
    stats = {"rows": len(rows), "excluded": excluded, "nodes": len(core), "folded": len(docs) - len(core)}
    return core, sources, stats


# == code links ==

def _text(proj: Project, rel: str | None) -> str:
    if not rel:
        return ""
    p = proj.documents_dir / rel
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def topic_words(rules: Rules, code_dir: Path, targets: list[dict]) -> dict[str, str]:
    """Words that place a document on a part of the code: the project's own list, plus each
    module's own name when it is a real word and not a generic folder name."""
    kw = dict(rules.topic_words)
    for t in targets:
        for m in (util.load_json(code_dir / t["name"] / "module-list.json", default={}) or {}):
            last = m.rsplit("/", 1)[-1].lower()
            if len(last) >= 4 and last not in GENERIC_MODULES and re.fullmatch(r"[a-z][a-z0-9 _-]+", last):
                kw.setdefault(last.replace("_", " "), m)
    return kw


def dominant_module(text: str, keywords: dict[str, str]) -> str | None:
    """A subject only when it clearly dominates: three mentions or more and a lead of two over the
    next. Documents that touch many parts stay unplaced instead of going to whoever wins a tie."""
    low = text.lower()
    counts = Counter()
    for word, module in keywords.items():
        n = len(re.findall(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", low))
        if n:
            counts[module] += n
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return None
    top, lead_count = ranked[0]
    runner = ranked[1][1] if ranked[1:] else 0
    return top if lead_count >= 3 and lead_count >= runner + 2 else None


def _name_rows(text: str, exact: dict, folded: dict) -> list[dict]:
    tokens = IDENT_RE.findall(text)
    counts = Counter(tokens)
    fcounts = Counter(t.lower() for t in tokens)
    per = defaultdict(lambda: dict(symbols={}, targets=set()))

    def record(symbol, n, defs):
        grouped = defaultdict(set)
        for target, module, kind in defs:
            grouped[(module, kind)].add(target)
        for (module, kind), tgts in grouped.items():
            found = per[module]["symbols"]
            if (symbol, kind) not in found:
                found[(symbol, kind)] = dict(sym=symbol, kind=kind, n=0, targets=set())
            found[(symbol, kind)]["n"] += n
            found[(symbol, kind)]["targets"].update(tgts)
            per[module]["targets"].update(tgts)

    for sym, n in counts.items():
        if sym in exact:
            record(sym, n, exact[sym])
    for low, n in fcounts.items():
        if low in folded:
            defs = {(target, module, kind) for _name, target, module, kind in folded[low]}
            record(sorted(name for name, *_ in folded[low])[0], n, defs)
    rows = []
    for module, info in per.items():
        syms = []
        for rec in info["symbols"].values():
            rec["targets"] = sorted(rec["targets"])
            syms.append(rec)
        syms.sort(key=lambda s: (-s["n"], s["kind"], s["sym"].lower()))
        kinds = Counter(s["kind"] for s in syms)
        rows.append(dict(module=module, targets=sorted(info["targets"]), weight=len(syms),
                         mentions=sum(s["n"] for s in syms), functions_count=kinds["function"],
                         constants_count=kinds["constant"], entities_count=kinds["entity"],
                         symbols=syms, key_names=syms[:16]))
    return sorted(rows, key=lambda r: (-r["weight"], -r["mentions"], r["module"]))


def code_links(proj: Project, core: list[dict], rules: Rules) -> tuple[list[dict], dict]:
    targets = [t for t in proj.code_targets if (proj.code_dir / t["name"]).is_dir()]
    exact, folded = SYM.collect_names(proj.code_dir, targets)
    keywords = topic_words(rules, proj.code_dir, targets)
    edges = []
    for doc in core:
        text = _text(proj, doc.get("cached_text"))
        rows = _name_rows(text, exact, folded)
        doc.update(about_module=dominant_module(text, keywords), linked_code=bool(rows),
                   modules=[r["module"] for r in rows], main_module=next((r["module"] for r in rows), doc.get("module")))
        for i, r in enumerate(rows):
            # strength follows how many distinct code names the document uses for this module
            r["confidence"] = "strong" if r["weight"] >= 5 else "some" if r["weight"] >= 2 else "one"
            r["primary"] = i == 0
            edges.append({"document_key": doc["key"], **r})
    edges.sort(key=lambda e: (e["document_key"], -e["weight"], e["module"]))
    return edges, {"exact_names": len(exact), "hdl_entities": len(folded), "topic_words": len(keywords)}


# == structure ==

def outline_of(text: str, rules: Rules, ext: str = "") -> dict:
    """Headings, shall statements and values. Lines starting with '#' are headings only where
    the format makes them so (Markdown, and Word, whose reader marks its heading styles)."""
    found_heads: dict[str, str] = {}          # folded -> as first written

    def heading(h: str) -> None:
        found_heads.setdefault(h.lower(), h)

    ext = (ext or "").lower()
    if ext in (".md", ".docx", ".docm", ".rst"):
        for m in MARKDOWN_HEADING.finditer(text):
            heading(f"{'#' * len(m.group(1))} {m.group(2).strip()}")
    elif ext in SHEET_SUFFIXES:
        for m in re.finditer(r"^## sheet (.+?)(?:  \(|  \u00b7|$)", text, re.M):
            heading(f"sheet {m.group(1).strip()}")
    if ext not in SHEET_SUFFIXES:
        for m in NUMBERED_HEADING.finditer(text):
            title = m.group(2).strip()
            if re.search(r"[A-Za-z]{3,}", title):
                heading(f"{m.group(1)} {title}")
    heads = list(found_heads.values())
    reqs = []
    for piece in _SENTENCE_BREAK.split(text):
        s = _one_line(piece)
        if 15 <= len(s) <= 320 and SHALL_LINE_RE.search(s):
            reqs.append({"text": s, "ids": sorted({hit[0] for rx in rules.req_ids for hit in rx.finditer(s)})})
    params, seen_values, occupied = [], set(), []

    def add(m, value, unit, kind):
        context = _one_line(text[max(0, m.start() - 42):m.end()])[-72:]
        if (value, unit, context.lower()) in seen_values:
            return
        seen_values.add((value, unit, context.lower()))
        start = text.rfind("\n", 0, m.start()) + 1
        stop = text.find("\n", m.end())
        line = _one_line(text[start:None if stop < 0 else stop])
        from_cell = CELL_ORIGIN.search(line) is not None
        label = None
        if not from_cell:
            lm = PROSE_LABEL.match(text[start:m.start()])
            if lm and not re.search(r"\bshall\b|\bmust\b", lm.group(1), re.I):
                label = lm.group(1).strip()
        params.append(dict(value=value, unit=unit, kind=kind, value_norm=P.canon_number(value),
                           unit_norm=P.canon_unit(unit), context=line[:320] if from_cell else context, line=line,
                           prose_label=label))

    for m in VALUE_RANGE.finditer(text):
        occupied.append(m.span())
        add(m, m.group(1) + "–" + m.group(2), m.group(3), "range")
    for m in VALUE_WITH_UNIT.finditer(text):
        if not any(lo <= m.start() < hi for lo, hi in occupied):
            add(m, m.group(1), m.group(2), "value")
    capped = [{k: p[k] for k in _OUTLINE_KEYS} for p in params[:STRUCT_CAP]]
    return {"headings_count": len(heads), "headings": heads[:STRUCT_CAP], "headings_cut": len(heads) > STRUCT_CAP,
            "requirements_count": len(reqs), "requirements": reqs[:STRUCT_CAP],
            "requirements_cut": len(reqs) > STRUCT_CAP,
            "values_count": len(params), "values": capped, "values_cut": len(params) > STRUCT_CAP,
            "_all": params}


def _origin(line: str):
    """(sheet, cell, label) of a value line that sheets.py wrote; three Nones for prose."""
    m = CELL_ORIGIN.search(line or "")
    if m is None:
        return None, None, None
    name, equals, _rest = line.partition("=")
    label = (name.strip() or None) if equals else None
    return m["sheet"].strip().strip("'"), m["cell"].replace("$", ""), label[:500] if label else None


def _value_row(origin: str, written: str, shown: str, unit_written: str, unit: str, *, kind: str = "value",
               label=None, sheet=None, cell=None, formula=None, hidden: bool = False, context: str = "") -> dict:
    """One row of the value list. `unit` is already in its one spelling."""
    return {"value": shown, "unit": unit, "kind": kind, "value_as_written": written, "value_shown": shown,
            "unit_as_written": unit_written, "value_norm": P.canon_number(shown),
            "value_exact_norm": P.canon_number(written), "unit_norm": unit, "origin": origin, "label": label,
            "label_norm": P.canon_label(label), "sheet": sheet, "cell": cell, "formula": formula, "hidden": hidden,
            "context": context}


def _doc_parameters(text: str, rules: Rules, ext: str = "") -> tuple[dict, list[dict]]:
    parsed = outline_of(text, rules, ext)
    rows = []
    for p in parsed.pop("_all"):
        sheet, cell, label = _origin(p["line"])
        rows.append(_value_row("prose_value", p["value"], p["value"], p["unit"], P.canon_unit(p["unit"]), kind=p["kind"],
                               label=p.get("prose_label") if label is None else label, sheet=sheet, cell=cell,
                               context=p["context"]))
    return parsed, rows


def _sheet_values(path: Path) -> list[dict]:
    """The values of a workbook's cell records, then the numbers typed into its formulas."""
    values, literals = [], []
    for rec in util.load_jsonl(path):
        formula, label, sheet, cell = rec.get("formula"), rec.get("label"), rec.get("sheet"), rec.get("cell")
        where = dict(label=label, sheet=sheet, cell=cell, formula=formula, hidden=bool(rec.get("hidden")))
        if rec.get("value_class") == "number" and rec.get("value_string") not in (None, ""):
            raw = rec["value_string"]
            shown = rec.get("display") or raw
            if not P.all_numbers(P.canon_number(shown)):
                shown = raw
            unit_written = rec.get("unit_as_written") or ""
            unit = P.canon_unit(rec.get("unit") if rec.get("unit_norm") else (rec.get("unit") or unit_written))
            line = "{} = {}{}  @{}!{}{}".format(label or "(unlabelled)", rec.get("display") or raw,
                                                f" {rec['unit']}" if rec.get("unit") else "", sheet, cell,
                                                f"  {{{formula}}}" if formula else "")
            values.append(_value_row("computed_value" if formula else "cell_entry", raw, shown, unit_written, unit,
                                     context=line[:500], **where))
        literals += [_value_row("formula_constant", lit, lit, "", "", **where,
                                context=f"constant {lit} inside @{sheet}!{cell} {{{formula}}}"[:500])
                     for lit in P.formula_constants(formula)]
    return [v for v in values + literals if P.all_numbers(v["value_norm"])]


def structure_and_parameters(proj: Project, core: list[dict], sources: list[dict], rules: Rules) -> dict:
    dm = proj.documents_dir
    by_source = {}
    params_path = dm / "params.jsonl"
    reg_count, source_tally, kinds = 0, {}, Counter()
    lines = []
    for s in sources:
        text = _text(proj, s.get("cached_text"))
        if _ext(s) in SHEET_SUFFIXES and s.get("sheet_cells"):
            rows = _sheet_values(dm / s["sheet_cells"])
            parsed = outline_of(text, rules, s.get("ext"))
            parsed.pop("_all")
            parsed.update(values_count=len(rows), values=[{k: r[k] for k in _SHEET_OUTLINE_KEYS} for r in rows[:STRUCT_CAP]],
                          values_cut=len(rows) > STRUCT_CAP)
        else:
            parsed, rows = _doc_parameters(text, rules, s.get("ext"))
        by_source[s["file_key"]] = parsed
        base = {"format_version": P.FORMAT_VERSION, "doc": s["file_key"], "file_key": s["file_key"],
                "doc_ref": s["node_ref"], "stage": s.get("stage"), "module": s.get("module"), "ext": s.get("ext"),
                "doc_type": s.get("kind"), "category": s.get("category")}
        seen, count = set(), 0
        for r in rows:
            sig = (r["origin"], r.get("sheet"), r.get("cell"), r["value_as_written"], r["unit_as_written"], r["context"])
            if sig in seen:
                continue
            seen.add(sig)
            lines.append(json.dumps({**r, **base}, ensure_ascii=False, sort_keys=True))
            count += 1
            kinds[r["origin"]] += 1
        source_tally[s["file_key"]] = count
        reg_count += count
    util.save_text(params_path, "\n".join(lines) if lines else "")
    if not lines:
        params_path.write_bytes(b"")
    structure = []
    totals = Counter()
    for d in core:
        res = by_source.get(d["key"]) or {}
        res = {k: v for k, v in res.items() if k != "_all"}
        totals["headings"] += res.get("headings_count", 0)
        totals["requirements"] += res.get("requirements_count", 0)
        totals["values"] += res.get("values_count", 0)
        structure.append(dict(key=d["key"], title=d["title"], stage=d["stage"],
                              module=d.get("main_module") or d.get("module"), **res))
    util.save_jsonl(dm / "doc-outlines.jsonl", [json.loads(json.dumps(s, sort_keys=True)) for s in structure])
    db = P.write_database(params_path, dm / "params.sqlite", sources)
    meta = {"format_version": P.FORMAT_VERSION, "rows_count": reg_count, "sources_count": len(sources),
            "per_source_counts": dict(sorted(source_tally.items())), "origin_counts": dict(sorted(kinds.items())),
            "sqlite": db}
    util.save_json(dm / "params-info.json", meta, sort_keys=True)
    return {"totals": dict(totals), "value_rows": reg_count, "origins": dict(sorted(kinds.items()))}


# == doc links ==

def _lineage(core: list[dict], rules: Rules) -> list[dict]:
    edges = []
    module_tally = defaultdict(lambda: defaultdict(list))
    for d in core:
        m = d.get("module") or (d.get("main_module") if d.get("linked_code") else None) or d.get("about_module")
        if m:
            module_tally[m][d["stage"]].append(d["key"])
    for module in sorted(module_tally):
        stages = sorted(module_tally[module], key=rules.stage_index)
        for left, right in zip(stages, stages[1:], strict=False):
            for a in sorted(module_tally[module][left]):
                for b in sorted(module_tally[module][right]):
                    edges.append({"from": a, "to": b, "kind": "samepart", "module": module, "source": "same part, next stage"})
    return edges


def _norm_ref(v: str) -> str:
    return (v or "").strip().upper().translate(_REF_FOLD)


def _references(proj: Project, core: list[dict], rules: Rules, texts: dict) -> list[dict]:
    if not rules.doc_numbers:
        return []
    by_ref, own = defaultdict(list), {}
    for d in core:
        refs = {_norm_ref(x) for x in re.split(r"[\s,;]+", d.get("doc_numbers") or "") if x}
        ident = " ".join([d["key"], d["title"]] + d.get("copy_list", []))
        refs.update(_norm_ref(m.group(0)) for rx in rules.doc_numbers for m in rx.finditer(ident))
        if not refs:
            # A document that states its number in its opening text ("Document DOC-1001.") owns the
            # first number it writes; every other number in it is a reference to another document.
            head = texts[d["key"]][:1500]
            firsts = sorted((m.start(), _norm_ref(m.group(0))) for rx in rules.doc_numbers for m in rx.finditer(head))
            if firsts:
                refs.add(firsts[0][1])
        own[d["key"]] = refs
        for r in refs:
            by_ref[r].append(d)
    edges = []
    for d in core:
        text = texts[d["key"]]
        found = {_norm_ref(m.group(0)) for rx in rules.doc_numbers for m in rx.finditer(text)} - own[d["key"]]
        for ref in sorted(found):
            cands = [c for c in by_ref.get(ref, []) if c["key"] != d["key"]]
            if cands:
                t = max(cands, key=copy_preference)
                edges.append({"from": d["key"], "to": t["key"], "kind": "quotes", "doc_number": ref,
                              "source": "document number in the text"})
    return edges


def _title_words(s: str) -> tuple[str, ...]:
    return tuple(WORDS_RE.findall(s.lower()))


def _citations(core: list[dict], texts: dict) -> list[dict]:
    """A document cites another when it writes that document's title (three words or more, not all
    generic) or its file name with the extension. Matched on whole words, never inside a word."""
    patterns: dict[str, list[tuple[tuple[str, ...], str, str]]] = defaultdict(list)
    for d in core:
        name = d["title"]
        for title in dict.fromkeys(t for t in (name, d.get("doc_title") or "") if t):
            words = _title_words(VERSION_TAIL.sub("", title) or title)
            meaningful = [w for w in words if w not in GENERIC_TITLE_WORDS and not w.isdigit()]
            if len(words) >= 3 and len("".join(words)) >= 15 and len(meaningful) >= 2:
                patterns[words[0]].append((words, d["key"], "title"))
        ext = (d.get("ext") or "").lstrip(".").lower()
        full = _title_words(name) + ((ext,) if ext else ())
        if ext and len("".join(full)) >= 8 and len(full) >= 2:
            patterns[full[0]].append((full, d["key"], "file name"))
    edges = []
    for d in core:
        words = WORDS_RE.findall(texts[d["key"]].lower())
        hits: Counter = Counter()
        how: dict[str, str] = {}
        for i, w in enumerate(words):
            for pat, key, kind in patterns.get(w, ()):
                if key == d["key"]:
                    continue
                if tuple(words[i:i + len(pat)]) == pat:
                    hits[key] += 1
                    if how.get(key) != "file name":
                        how[key] = kind
        for key, n in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))[:CITE_CAP]:
            edges.append({"from": d["key"], "to": key, "kind": "cites", "count": n,
                          "source": f"{how[key]} written in the text"})
    return edges


def _shared_values(proj: Project) -> list[dict]:
    """Documents that state the same named values. Names stated almost everywhere are generic and
    ignored. The line records how many of the shared values agree, so a conflict is visible."""
    by_label = defaultdict(dict)       # label -> node -> set of normalized values
    shown = {}
    for r in util.load_jsonl(proj.documents_dir / "params.jsonl"):
        lab = r.get("label_norm") or ""
        if P.says_nothing(lab) or r["origin"] == "formula_constant":
            continue
        by_label[lab].setdefault(r["doc_ref"], set()).add((r["value_norm"], r["unit_norm"]))
        shown.setdefault(lab, r.get("label") or lab)
    pairs = defaultdict(list)
    for lab in sorted(by_label):
        nodes = by_label[lab]
        if not 2 <= len(nodes) <= MAX_VALUE_OWNERS:
            continue
        keys = sorted(nodes)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                agree = bool(nodes[a] & nodes[b])
                pairs[(a, b)].append((lab, agree))
    cands = []
    for (a, b), labs in pairs.items():
        # one shared value is enough when its name is specific (two words, or eight letters)
        specific = any(" " in lab.strip() or len(lab) >= 8 for lab, _ in labs)
        if len(labs) >= SHARED_VALUE_MIN or specific:
            cands.append((a, b, labs))
    cands.sort(key=lambda c: (-len(c[2]), c[0], c[1]))
    taken = Counter()
    edges = []
    for a, b, labs in cands:
        if taken[a] >= SHARED_VALUE_CAP and taken[b] >= SHARED_VALUE_CAP:
            continue
        taken[a] += 1
        taken[b] += 1
        differ = [shown[lab] for lab, ok in labs if not ok]
        edges.append({"from": a, "to": b, "kind": "shares", "shared_count": len(labs),
                      "agree_count": sum(1 for _, ok in labs if ok), "differ_count": len(differ),
                      "shared": [shown[lab] for lab, _ in labs[:8]], "differ": differ[:8],
                      "source": "named values stated in both"})
    return edges


def document_links(proj: Project, core: list[dict], rules: Rules) -> list[dict]:
    texts = {d["key"]: _text(proj, d.get("cached_text")) for d in core}
    edges = _lineage(core, rules) + _references(proj, core, rules, texts) + _citations(core, texts) + _shared_values(proj)
    seen, out = set(), []
    for e in edges:
        sig = tuple(e.get(field) for field in _EDGE_IDENTITY)
        if e["from"] != e["to"] and sig not in seen:
            seen.add(sig)
            out.append(e)
    out.sort(key=lambda e: (e["kind"], e["from"], e["to"], e.get("module") or "", e.get("doc_number") or ""))
    return out


# == docs_of_code ==

def docs_of_code(proj: Project, core: list[dict], edges: list[dict]) -> dict:
    """For each code base: module -> documents, function -> documents, strongest first."""
    by_key = {d["key"]: d for d in core}
    out = {}
    for t in proj.code_targets:
        sym = util.load_json(proj.code_dir / t["name"] / "name-lookup.json", default={}) or {}
        vh = util.load_json(proj.code_dir / t["name"] / "hdl-name-lookup.json", default={}) or {}
        vh_lower = {k.lower(): k for k in vh}
        modules, functions = defaultdict(dict), defaultdict(dict)
        for e in edges:
            if t["name"] not in e["targets"]:
                continue
            doc = by_key.get(e["document_key"], {})
            entry = {"key": e["document_key"], "title": doc.get("title", e["document_key"]), "stage": doc.get("stage"),
                     "weight": e["weight"], "confidence": e["confidence"]}
            modules[e["module"]][e["document_key"]] = entry
            for s in e["symbols"]:
                if t["name"] not in s["targets"]:
                    continue
                name = s["sym"] if s["sym"] in sym else vh_lower.get(s["sym"].lower())
                if name and s["kind"] in _NAMED_KINDS:
                    functions[name][e["document_key"]] = {**entry, "n": s["n"]}
        out[t["name"]] = {
            "modules": {m: sorted(v.values(), key=lambda x: (-x["weight"], x["key"]))[:20] for m, v in sorted(modules.items())},
            "functions": {f: sorted(v.values(), key=lambda x: (-x.get("n", 0), x["key"]))[:20] for f, v in sorted(functions.items())},
        }
    return out


# == the stage ==

def build(proj: Project) -> dict:
    dm = proj.documents_dir
    (dm / "links").mkdir(parents=True, exist_ok=True)
    rules = Rules(proj.vocabulary)
    core, sources, stats = fold_documents(proj, rules)
    util.say("corpus", f"{stats['nodes']} documents from {stats['rows']} cached files "
                       f"({stats['folded']} copies and revisions folded in, {stats['excluded']} logs and licences left out)")
    dc_edges, sym_stats = code_links(proj, core, rules)
    util.say("corpus", f"{sum(1 for d in core if d['linked_code'])} documents name code "
                       f"({len(dc_edges)} links, {sym_stats['exact_names']} distinctive code names known)")
    st = structure_and_parameters(proj, core, sources, rules)
    util.say("corpus", f"{st['totals'].get('headings', 0)} headings, {st['totals'].get('requirements', 0)} shall "
                       f"statements, {st['value_rows']} values in the value list")
    dd_edges = document_links(proj, core, rules)
    kinds = Counter(e["kind"] for e in dd_edges)
    util.say("corpus", "document links: " + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "none"))
    util.save_jsonl(dm / "doc-list.jsonl", [json.loads(json.dumps(d, sort_keys=True)) for d in core])
    util.save_jsonl(dm / "doc-sources.jsonl", [json.loads(json.dumps(s, sort_keys=True)) for s in sources])
    util.save_jsonl(dm / "links" / "doc-to-code.jsonl", [json.loads(json.dumps(e, sort_keys=True)) for e in dc_edges])
    util.save_jsonl(dm / "links" / "between-docs.jsonl", [json.loads(json.dumps(e, sort_keys=True)) for e in dd_edges])
    util.save_json(dm / "links" / "code-to-doc.json", docs_of_code(proj, core, dc_edges), indent=None, sort_keys=True)
    _write_guide(proj, core, dc_edges, dd_edges, rules)
    summary = {"docs_count": len(core), "sources_count": len(sources), "code_linked_count": sum(1 for d in core if d["linked_code"]),
               "doc_code_edges_count": len(dc_edges), "doc_doc_edges_count": len(dd_edges),
               "doc_doc_kinds": dict(sorted(kinds.items())), "outline_totals": st["totals"],
               "param_rows": st["value_rows"], "param_origins": st["origins"],
               "stages": rules.stages}
    util.save_json(dm / "overview.json", summary)
    return summary


def _write_guide(proj: Project, core, dc_edges, dd_edges, rules: Rules) -> None:
    by_doc = defaultdict(list)
    for e in dc_edges:
        by_doc[e["document_key"]].append(e)
    links = defaultdict(list)
    for e in dd_edges:
        links[e["from"]].append(e)
    L = [f"# {proj.name}: document map", "",
         "> Generated by ContextMAX from the documents' text alone. Stages, links and values are finding "
         "aids: open the original document before relying on a number or a requirement.", "",
         f"- Documents: {len(core)} · naming code: {sum(1 for d in core if d['linked_code'])}",
         "- Files: `doc-list.jsonl` (one row per document), `doc-sources.jsonl` (every copy and which document it "
         "folds into), `doc-outlines.jsonl` (headings, shall statements, values), `params.sqlite` (every named "
         "value with its cell), `links/doc-to-code.jsonl`, `links/between-docs.jsonl`, `links/code-to-doc.json`.", ""]
    for stage in rules.stages:
        docs = [d for d in core if d["stage"] == stage]
        if not docs:
            continue
        L += [f"## {stage} ({len(docs)})", ""]
        for d in sorted(docs, key=lambda d: d["title"].lower()):
            bits = [f"`{d['key']}`", d.get("ext") or ""]
            if d["copies"] > 1:
                bits.append(f"{d['copies']} copies")
            line = f"- **{d['title']}** · " + " · ".join(b for b in bits if b)
            L.append(line)
            for e in by_doc.get(d["key"], [])[:3]:
                names = ", ".join(s["sym"] for s in e["key_names"][:6])
                L.append(f"  - names code in {e['module']} ({e['confidence']}): {names}")
            if not by_doc.get(d["key"]) and d.get("about_module"):
                L.append(f"  - about {d['about_module']} (names none of its code)")
            for e in links.get(d["key"], [])[:4]:
                if e["kind"] != "samepart":
                    L.append(f"  - {e['kind']} → `{e['to']}`")
        L.append("")
    util.save_text(proj.documents_dir / "document-guide.md", "\n".join(L))


# == validate ==

def validate(proj: Project) -> tuple[list[str], dict]:
    """Recompute and cross-check. Returns (errors, counts); any error fails the build."""
    dm = proj.documents_dir
    errors: list[str] = []

    def rows_of(path: Path) -> list[dict]:
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except OSError as exc:
            errors.append(f"cannot read {path.name}: {exc}")
            return []
        rows = []
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                errors.append(f"{path.name}:{number}: not valid JSON ({exc})")
        return rows

    index = rows_of(dm / "text-index.jsonl")
    core = rows_of(dm / "doc-list.jsonl")
    structure = rows_of(dm / "doc-outlines.jsonl")
    sources = rows_of(dm / "doc-sources.jsonl")
    value_rows = rows_of(dm / "params.jsonl")
    dc = rows_of(dm / "links" / "doc-to-code.jsonl")
    dd = rows_of(dm / "links" / "between-docs.jsonl")

    def key_set(rows, name, field="key"):
        ks = [r.get(field) for r in rows]
        if len(ks) != len(set(ks)):
            errors.append(f"{name}: {len(ks) - len(set(ks))} duplicate keys")
        return set(ks)

    cached_keys, map_keys = key_set(index, "text-index"), key_set(core, "doc-list")
    if key_set(structure, "doc-outlines") != map_keys:
        errors.append("doc-outlines and doc-list hold different documents")
    for r in index:
        p = dm / (r.get("cached_text") or "")
        if not p.is_file():
            errors.append(f"text missing for {r.get('key')}")
            continue
        if util.hash_file(p) != r.get("sha256"):
            errors.append(f"text of {r.get('key')} changed since it was indexed")
        if (r.get("ext") or "") in SHEET_SUFFIXES:
            rec = dm / (r.get("sheet_cells") or "")
            if not r.get("sheet_cells") or not rec.is_file():
                errors.append(f"spreadsheet {r.get('key')} has no cell records")
            elif util.hash_file(rec) != r.get("cells_sha256"):
                errors.append(f"cell records of {r.get('key')} changed since they were indexed")
    for e in dc:
        if e.get("document_key") not in map_keys:
            errors.append(f"code link from an unknown document: {e.get('document_key')}")
    seen = set()
    for e in dd:
        if e.get("from") not in map_keys or e.get("to") not in map_keys:
            errors.append(f"document link to an unknown document: {e.get('from')} -> {e.get('to')}")
        if e.get("from") == e.get("to"):
            errors.append(f"document linked to itself: {e.get('from')}")
        sig = tuple(e.get(field) for field in _EDGE_IDENTITY)
        if sig in seen:
            errors.append(f"duplicate document link {sig}")
        seen.add(sig)
    src_map = {s["file_key"]: s["node_ref"] for s in sources}
    for sk, nk in src_map.items():
        if sk not in cached_keys:
            errors.append(f"source {sk} is not in the text cache")
        if nk not in map_keys:
            errors.append(f"source {sk} folds into an unknown document {nk}")
    required = {*_VALUE_FIELDS, "format_version", "doc", "file_key", "doc_ref"}
    source_tally, seen_rows = Counter(), set()
    for n, r in enumerate(value_rows, 1):
        missing = required - set(r)
        if missing:
            errors.append(f"params.jsonl:{n}: missing {sorted(missing)}")
            continue
        problems = [
            (src_map.get(r["file_key"]) != r["doc_ref"], "belongs to the wrong document"),
            ((r.get("ext") or "") in SHEET_SUFFIXES and not (r.get("sheet") and r.get("cell")),
             "a spreadsheet value without its sheet and cell"),
            (r["origin"] == "formula_constant" and bool(r["unit_norm"]), "a constant inside a formula was given a unit"),
            (r["value_norm"] != P.canon_number(r["value_shown"]), "value normalization does not reproduce"),
            (r["value_exact_norm"] != P.canon_number(r["value_as_written"]), "exact value normalization does not reproduce"),
            (not (P.all_numbers(r["value_norm"]) and P.all_numbers(r["value_exact_norm"])),
             f"not a number: {r['value_norm']!r}"),
            (r["unit_norm"] != P.canon_unit(r["unit"]), "unit normalization does not reproduce"),
            (r["label_norm"] != P.canon_label(r["label"]), "name normalization does not reproduce"),
        ]
        errors += [f"params.jsonl:{n}: {message}" for failed, message in problems if failed]
        sig = (r["file_key"], r["origin"], r["sheet"], r["cell"], r["value_as_written"], r["unit_as_written"], r["context"])
        if sig in seen_rows:
            errors.append(f"params.jsonl:{n}: duplicate")
        seen_rows.add(sig)
        source_tally[r["file_key"]] += 1
    meta = util.load_json(dm / "params-info.json", default={}) or {}
    if meta.get("rows_count") != len(value_rows):
        errors.append("params-info.json does not count the value list's rows")
    if {k: int(v) for k, v in (meta.get("per_source_counts") or {}).items()} != {k: source_tally.get(k, 0) for k in src_map}:
        errors.append("params-info.json per-document counts do not match the value list")
    db_path = dm / "params.sqlite"
    workbook_suffixes = ", ".join(f"'{e}'" for e in sorted(SHEET_SUFFIXES))
    expected = (
        ("PRAGMA integrity_check", "ok", "params.sqlite fails its integrity check"),
        ("PRAGMA user_version", P.FORMAT_VERSION, "params.sqlite has another schema version"),
        ("SELECT count(*) FROM entries", len(value_rows), "params.sqlite and params.jsonl hold different numbers of values"),
        ("SELECT count(*) FROM sources", len(sources), "params.sqlite and doc-sources.jsonl list different documents"),
    )
    try:
        if util.hash_file(db_path) != (meta.get("sqlite") or {}).get("sha256"):
            errors.append("params.sqlite changed since it was built")
        read_only = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(read_only, uri=True)
        try:
            errors += [message for sql, want, message in expected if con.execute(sql).fetchone()[0] != want]
            cellless = con.execute(
                "SELECT count(*) FROM entries e JOIN places pl ON pl.id = e.place JOIN sources s ON s.id = pl.source "
                f"WHERE s.ext IN ({workbook_suffixes}) AND (coalesce(pl.sheet, '') = '' OR coalesce(pl.cell, '') = '')"
            ).fetchone()[0]
            if cellless:
                errors.append(f"params.sqlite: {cellless} spreadsheet values without a cell")
        finally:
            con.close()
    except (OSError, sqlite3.Error) as exc:
        errors.append(f"cannot read params.sqlite: {exc}")
    cdocs = util.load_json(dm / "links" / "code-to-doc.json", default=None)
    if cdocs is None:
        errors.append("links/code-to-doc.json is missing")
    else:
        for target, data in cdocs.items():
            sym = util.load_json(proj.code_dir / target / "name-lookup.json", default={}) or {}
            vh = util.load_json(proj.code_dir / target / "hdl-name-lookup.json", default={}) or {}
            unknown = set(data.get("functions", {})) - set(sym) - set(vh)
            if unknown:
                errors.append(f"docs_of_code[{target}]: {len(unknown)} names that the code map does not have")
    counts = {"cached documents": len(cached_keys), "map documents": len(map_keys), "source files": len(sources),
              "values": len(value_rows), "code links": len(dc), "document links": len(dd)}
    return errors, counts
