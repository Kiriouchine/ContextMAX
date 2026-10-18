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
                  named values stated in both (and, for a value many documents state, a link to the
                  document that anchors it), a value that differs from what most documents state,
                  and a shared part of the code. value-conflicts.jsonl lists every such difference
  docs_of_code    the same links read backwards: which documents describe a module or a function
  validate        a strict gate over everything above; a failure stops the build

Every output is sorted and carries no timestamp, so the same inputs give the same bytes.
"""
from __future__ import annotations

import bisect
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contextmax import parallel, util
from contextmax.docs import params as P
from contextmax.docs import search, value_code
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
QUALIFIED_RE = re.compile(r"[_A-Za-z]\w*(?:::~?[_A-Za-z]\w*)+")
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
    "m/s²", "m/s", "mm/s", "A", "V", "N", "g", r"kg[ ·]?m(?:²|\^?2)", "kg", "mg", "%", "K", "s", "m",
)                                  # longer spellings first: "ms" before "m", "mm/s" never as "mm", "kg m2" never as "kg"
_UNITS = _any(*UNIT_WORDS)
_NUMBER = r"[+-]?\d+(?:[,.]\d+)?"
# a range: 1~4 cm, 1 to 4 cm, 1-4 cm, and with the unit on both numbers, 1 cm - 4 cm (one unit, said twice)
# A unit is on the number's own line ("37" and "K" on two lines are a table, not 37 K), and written with its
# own capitals ("a13" in a table holds no ampere)
_GAP = r"[ \t\xa0]*"
VALUE_RANGE = re.compile(rf"(?<![.\w])({_NUMBER}){_GAP}(?:({_UNITS}){_GAP})?(?:(?i:to)|-|–|—|~)\s*({_NUMBER}){_GAP}({_UNITS})"
                         r"(?![a-zA-Z])")
VALUE_WITH_UNIT = re.compile(rf"(?<![,.\w])({_NUMBER}){_GAP}({_UNITS})(?![0-9A-Za-z])")
# a value whose unit a PDF put on the next line, in running text: the sentence goes on after the unit ("1.2 /
# m of wingspan", "5 / µs. The sensor"); after "1 / s + 10" or "q / 1 / N" it is a formula, not a value
_GOES_ON = r"(?=[ \t]+[a-z]{2,}\b|[,;:)](?:\s|$)|\.(?:\s|$))"
VALUE_ACROSS_LINES = re.compile(rf"(?<![,.\w])({_NUMBER})[ \t\xa0]*\n[ \t\xa0]*({_UNITS}){_GOES_ON}")
# and a range: "about 2 to 3 / cm." (the empty group keeps the groups of VALUE_RANGE)
RANGE_ACROSS_LINES = re.compile(rf"(?<![.\w])({_NUMBER}){_GAP}()(?:(?i:to)|-|–|—|~)\s*({_NUMBER})[ \t\xa0]*\n[ \t\xa0]*"
                                rf"({_UNITS}){_GOES_ON}")
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
MAX_VALUE_OWNERS = 12       # a value name stated by more documents links each of them to one anchor, not in pairs
SHARED_VALUE_MIN = 2        # documents sharing this many named values are linked; one is enough if specific


# Catalogue fields a document keeps as they are; and those each copy of a document lists.
_KEPT_FIELDS = ("category", "folder", "relative_path", "ext", "chars", "pages", "doc_numbers", "text_sha256", "cached_text",
                "sheet_cells", "file_mtime_utc", "method")
_COPY_FIELDS = ("title", "folder", "relative_path", "ext", "kind", "stage", "module", "category", "cached_text")
# The fields of one value row, as params.jsonl stores them and validate() expects them.
_VALUE_FIELDS = ("value", "unit", "kind", "value_as_written", "value_shown", "unit_as_written", "value_norm",
                 "value_exact_norm", "unit_norm", "origin", "label", "label_norm", "sheet", "cell", "formula", "hidden",
                 "context", "label_source", "line_no", "page", "section", "sentence", "symbol")
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
                   distinct_texts=len({v["text_sha256"] for v in variants if v.get("text_sha256")}),
                   products=sorted({t for v in variants for t in v["products"]}))
        core.append(rep)
        sources.extend(dict(file_key=v["key"], node_ref=rep["key"], **{f: v[f] for f in _COPY_FIELDS},
                            sheet_cells=v.get("sheet_cells"), text_sha256=v["text_sha256"]) for v in variants)
    core.sort(key=lambda d: (rules.stage_index(d["stage"]), d["module"] or "~", d["key"]))
    sources.sort(key=lambda s: (s["file_key"], s["node_ref"]))
    stats = {"rows": len(rows), "excluded": excluded, "nodes": len(core), "folded": len(docs) - len(core)}
    return core, sources, stats


# == code links ==

def _text(proj: Project, rel: str | None) -> str:
    return _text_in(proj.documents_dir, rel)


def _text_in(documents_dir, rel: str | None) -> str:
    if not rel:
        return ""
    try:
        return (Path(documents_dir) / rel).read_text(encoding="utf-8", errors="ignore")
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


_ALNUM_RUN = re.compile(r"[a-z0-9]+")


class TopicIndex:
    """The topic words, filed under their first run of letters and digits, so a text is read once
    however many words there are. A topic word counts as a whole word only (no letter or digit on
    either side), and its occurrences never overlap one another, as one search per word would find."""

    def __init__(self, keywords: dict[str, str]):
        self.by_first: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.searched: list[tuple[re.Pattern, str]] = []        # words that do not begin with a letter or digit
        for word, module in keywords.items():
            first = _ALNUM_RUN.match(word)
            if first:
                self.by_first[first.group()].append((word, module))
            else:
                self.searched.append((re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"), module))

    def counts(self, low: str) -> Counter:
        """Mentions per module in a lower-cased text. A match starts where a run begins, and that
        run is the word's own first run, so only the words filed under it can match there."""
        counts: Counter = Counter()
        next_free: dict[str, int] = {}
        size = len(low)
        for run in _ALNUM_RUN.finditer(low):
            words = self.by_first.get(run.group())
            if not words:
                continue
            at = run.start()
            for word, module in words:
                end = at + len(word)
                if at >= next_free.get(word, 0) and low.startswith(word, at) and \
                        (end >= size or not _ALNUM_RUN.match(low[end])):
                    counts[module] += 1
                    next_free[word] = end
        for rx, module in self.searched:
            n = len(rx.findall(low))
            if n:
                counts[module] += n
        return counts


def dominant_module(text: str, topics: TopicIndex) -> str | None:
    """A subject only when it clearly dominates: three mentions or more and a lead of two over the
    next. Documents that touch many parts stay unplaced instead of going to whoever wins a tie."""
    counts = topics.counts(text.lower())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return None
    top, lead_count = ranked[0]
    runner = ranked[1][1] if ranked[1:] else 0
    return top if lead_count >= 3 and lead_count >= runner + 2 else None


def _name_rows(text: str, exact: dict, folded: dict, qualified: bool = False) -> list[dict]:
    tokens = IDENT_RE.findall(text)
    if qualified:                                     # C++ names written with their scope: Controller::clamp
        tokens += QUALIFIED_RE.findall(text)
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
        elif sym[:1].isupper() and any(c == "_" or c.isdigit() for c in sym) and sym[:1].lower() + sym[1:] in exact:
            # a code name that starts a sentence ("Encoder_drive_handle10_5() ..."); a plain word never counts
            record(sym[:1].lower() + sym[1:], n, exact[sym[:1].lower() + sym[1:]])
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


def _names_in(rel: str | None) -> tuple[str | None, list[dict]]:
    """One document: the module it is about, and the code names it writes (a piece of parallel work)."""
    d = parallel.shared()
    text = _text_in(d["documents"], rel)
    return dominant_module(text, d["topics"]), _name_rows(text, d["exact"], d["folded"], d["qualified"])


def code_links(proj: Project, core: list[dict], rules: Rules) -> tuple[list[dict], dict]:
    targets = [t for t in proj.code_targets if (proj.code_dir / t["name"]).is_dir()]
    exact, folded = SYM.collect_names(proj.code_dir, targets)
    keywords = topic_words(rules, proj.code_dir, targets)
    topics = TopicIndex(keywords)
    qualified = any("::" in name for name in exact)
    edges = []
    util.say("corpus", f"looking for {len(exact) + len(folded):,} code names in {len(core):,} documents")
    finding = util.Progress("corpus", "documents searched for code names", len(core))
    found = parallel.map_in_order(_names_in, [doc.get("cached_text") for doc in core], progress=finding,
                                  data={"documents": str(proj.documents_dir), "exact": exact, "folded": folded,
                                        "qualified": qualified, "topics": topics})
    for doc, (about, rows) in zip(core, found, strict=True):
        doc.update(about_module=about, linked_code=bool(rows),
                   modules=[r["module"] for r in rows], main_module=next((r["module"] for r in rows), doc.get("module")))
        for i, r in enumerate(rows):
            # strength follows how many distinct code names the document uses for this module
            r["confidence"] = "strong" if r["weight"] >= 5 else "some" if r["weight"] >= 2 else "one"
            r["primary"] = i == 0
            edges.append({"document_key": doc["key"], **r})
    edges.sort(key=lambda e: (e["document_key"], -e["weight"], e["module"]))
    return edges, {"exact_names": len(exact), "hdl_entities": len(folded), "topic_words": len(keywords)}


# == structure ==

# == a value's name from its own sentence ==
# Most writing does not say "Settle time: 12 ms" but "a settle time of 12 ms", "the supply voltage shall be
# 24 V" or "the controller shall keep the gain margin at 6 dB". The words right before the value, up to a
# linking word, name it: two to four words, without articles, verbs or symbols, never only generic words.
# Fixed patterns only, so the same text always gives the same names. A name found this way is recorded as
# such (label_source "sentence"), apart from "label" (Name: value) and "cell" (a workbook's label).
_SYMBOL_IN_BRACKETS = re.compile(r"\([^()]{0,14}\)")
_CLAUSE_BREAK = re.compile(r"[.;!?](?=\s|$)|,(?=\s)|\s[–—-]\s|:(?=\s)")
# words apart by real spaces only: a PDF's lost ligature can come out as a control character ("sti\x1eness")
_WORDS = r"(?P<name> (?: [A-Za-z][A-Za-z\-]* [ \t]+ ){1,5} [A-Za-z][A-Za-z\-]* )"
_OTHER_WORDS = _WORDS.replace("name", "other")
_COMPARED = r"""(?: at \s+ (?:least|most) | less \s+ than | more \s+ than | greater \s+ than | lower \s+ than
                  | higher \s+ than | no \s+ (?:more|less) \s+ than | up \s+ to | below | above | under | over
                  | within | between | equal \s+ to | set \s+ to )"""
_NAMED_BY = re.compile(rf"""
    {_WORDS} \s+
    (?: of (?: \s+ (?:about|approximately|around|roughly|nearly|almost|up \s+ to) )?
      | (?:is|was|are|were|becomes|equals|amounts \s+ to) (?: \s+ (?:about|approximately|around|roughly|nearly
                                                                    |chosen \s+ as|taken \s+ as|{_COMPARED}) )?
      | (?:shall|must|should|will) \s+ (?:not \s+)? (?:be|equal|exceed|remain|stay) (?: \s+ {_COMPARED} )? )
    \s* $
    | {_OTHER_WORDS} \s* (?: = | ≈ | ~ ) \s* $
""", re.VERBOSE | re.IGNORECASE)
_SHALL_NAME = re.compile(rf"""
    \b (?:shall|must) \s+ (?:not \s+)? {_WORDS} \s+
    (?: at | to | by | of | not \s+ exceed(?:ing)? | exceed(?:ing)? | {_COMPARED} ) \s* $
""", re.VERBOSE | re.IGNORECASE)
_DETERMINERS = frozenset("""a an the its their our his her this that these those each every any all some no both several
many one two three four five six seven eight nine ten""".split())
# "much higher value", "higher accuracy": a comparison, not the name of what is measured
_DEGREE_WORDS = frozenset("much far even still rather quite slightly significantly considerably somewhat".split())
_COMPARATIVES = frozenset("higher lower larger smaller greater better worse faster slower more less bigger longer shorter "
                          "wider".split())
# a value right after a named one, joined by a comma or "and", shares its name: "are 128.3 rad/s and 104.8 rad/s",
# "of 21.21 mm (224 kHz), 30.21 mm"
_LIST_GAP = re.compile(r"\s*(?:\([^()\n]{0,40}\))?\s*(?:,|;|/)?\s*(?:and|or|&)?\s*", re.I)
# a word a PDF broke over two lines: "resis-" or "resis" with a soft hyphen at the end of the line before
_BROKEN_WORD = re.compile("([A-Za-z]+)(?:[\u00ad\ufffe]|(?<=[a-z])-)$")
_GENERIC_HEADS = frozenset("value values case cases example number amount".split())
# the name starts after an article, and after a verb or a preposition that leads to it ("RTK GPS has
# centimetre accuracies of", "a motor with rated current of"); never after "of", "by" or "from", where the
# words that follow are the second half of a name (_TAIL_OF_A_NAME)
_NAME_STARTS_AFTER = _DETERMINERS | frozenset("""has have had having with at in on for as under during via gives uses
using reaches requires needs""".split())     # never "reach", "use", "need": "maximum reach" is a name
_DECADE = re.compile(r"(?:1[6-9]|20)\d0s")
# a number that labels something: a figure, a table, an equation, a section
# (written with its capital: "cross section 10 mm" and "with no 0 g offset" are values)
_NUMBERED_THING = re.compile(r"(?:\b(?:Figs?|FIGS?|Figures?|FIGURES?|Tables?|TABLES?|Tab|Eqs?|Equations?|Sections?|Sect|Sec"
                             r"|Chapters?|Ch|Refs?|Examples?|Problems?|Exercises?|Steps?|Algorithms?|VIDEO|Video)\.?"
                             r"|\bfigs?\.|\bN[or]\.)\s*$")
# after "192 A" at the start of a line: an author's initials ("A. Smith", "K.A. Brown") or "A-star"
_INITIALS_AFTER = re.compile(r"\.\s?[A-Z]|\.[A-Z]\.|-[a-z]")
_UNSHOWN = re.compile("[\x00-\x08\x0b-\x1f\u00ad\ufffe\ufffd]")      # PDF marks for a broken word or a lost ligature
# words that join a name to what came before it ("the speed of the shaft", "measurable by the sensor")
_TAIL_OF_A_NAME = frozenset("of by from than".split())
_PARTICIPLES = frozenset("""consisting taking using having including giving being leading making resulting yielding
corresponding according""".split())
_FILLERS = frozenset("""with and or of for in on at to by from as is was are were be been being has have had which where
while when whose whereas also then thus hence so such per than not typically approximately approx
about around roughly nearly almost only just very shall must should will can may""".split())
_REQUIREMENT_VERBS = frozenset("""keep limit be have provide maintain support achieve reach operate run stay remain respond
settle measure report detect stop start use set hold reduce increase decrease ensure allow handle draw consume deliver
withstand tolerate exceed accept generate produce sample update""".split())
_NOT_A_NAME = frozenset("""figure fig table eq equation section chapter page step steps total value values increase decrease
change changes difference amount number order rate factor time times period range level size error errors part parts
case cases example result results""".split())


def sentence_name(before: str) -> str | None:
    """The name of a value from the words just before it on its line, or None."""
    return name_and_symbol(before)[0]


def name_and_symbol(before: str) -> tuple[str | None, str | None]:
    """The name of a value from the words just before it, and the symbol written with it ("total energy E",
    "cutoff frequency (fc)"), or (None, None)."""
    before = _SOFT_HYPHEN.sub("", before)                 # "resis\ufffetance": one word a PDF broke, joined
    aside = _SYMBOL_AT_END.search(before)                 # "the cutoff frequency (fc) is": the symbol of the name
    clause = _CLAUSE_BREAK.split(_SYMBOL_IN_BRACKETS.sub(" ", before))[-1]
    m, verb_first = _NAMED_BY.search(clause), False
    if m is None:
        m, verb_first = _SHALL_NAME.search(clause), True
        if m is None:
            return None, None
    name = _name_of(m, verb_first)
    if name is None:
        return None, None
    return name[0], name[1] or (aside.group(1) if aside else None)


_SOFT_HYPHEN = re.compile("[\u00ad\ufffe]")
_SYMBOL_AT_END = re.compile(r"\(([A-Za-z][A-Za-z0-9_]{0,3})\)\s*(?:(?:is|was|are|were|of|equals|equal\s+to|=|≈|~|about"
                            r"|approximately|around|roughly|nearly|set\s+to)\s*)+$", re.I)


def _name_of(m, verb_first: bool):
    words = (m.group("name") or m.groupdict().get("other") or "").split()
    symbol = None
    cut = max((i for i, w in enumerate(words) if w.lower() in _NAME_STARTS_AFTER), default=-1)
    if cut > 0 and words[cut - 1].lower() in _TAIL_OF_A_NAME:
        return None                              # "the speed of the drive shaft" names the speed, not the shaft
    # "The pump control shall keep the timeout at 435.7 s": one word after the article names it, and the
    # sentence's subject is the rest of its name (_fuller_names finds it in the document, or drops the word)
    one_word = verb_first and cut >= 0 and words[cut].lower() in _DETERMINERS and len(words) == cut + 2
    words = words[cut + 1:]
    if words and words[0].lower() in _TAIL_OF_A_NAME:
        return None                              # "(power) from sine wave is": the name began before
    while words and (words[0].lower() in _FILLERS or (verb_first and words[0].lower() in _REQUIREMENT_VERBS)):
        words = words[1:]
    if any(w.lower() in _PARTICIPLES for w in words):
        return None                              # "electronics consisting of 1 GHz"
    if len(words) > 1 and (len(words[-1]) <= 2 or len(words[-1]) <= 3 and any(c.isupper() for c in words[-1])
                           and words[-2].islower()):
        if words[-1].lower() not in _FILLERS:
            symbol = words[-1]                   # a symbol after the name: "sample time Ts", "total energy E"
        words = words[:-1]
    if not (2 <= len(words) <= 4 or one_word and len(words) == 1) or any(w.lower() in _FILLERS or len(w) < 2 for w in words):
        return None
    if words[0].lower() in _GENERIC_HEADS:
        return None                              # "a value lmin =", "in this case tc is"
    if words[0].lower() in _DEGREE_WORDS or (len(words) == 2 and words[0].lower() in _COMPARATIVES):
        return None                              # "much higher value", "higher accuracy"
    if not any(len(w) >= 4 for w in words) or all(w.lower() in _NOT_A_NAME for w in words):
        return None
    name = " ".join(words)
    return None if P.says_nothing(P.canon_label(name)) else (name, symbol)


def _same_kind(unit_a: str, unit_b: str) -> bool:
    """Two units that measure the same thing (mm and m, ms and s), so values in one list share a name."""
    a, b = P.canon_unit(unit_a), P.canon_unit(unit_b)
    if a == b:
        return True
    scale = value_code._UNIT_SCALE
    return a in scale and b in scale and scale[a][0] == scale[b][0]


def _readable(line: str, at: int, end: int, width: int = 200) -> str:
    """The words around a value on its line (`at`..`end` is the value), cut only between words, without the
    marks a PDF's text carries for a broken word or a lost ligature."""
    if len(line) <= width:
        return _UNSHOWN.sub("", line).strip()
    lo, hi = max(0, at - width * 2 // 3), min(len(line), end + width // 3)
    if lo > 0:
        space = line.find(" ", lo, at)
        lo = space + 1 if space >= 0 else lo
    if hi < len(line):
        space = line.rfind(" ", end, hi)
        hi = space if space >= 0 else hi
    return ("…" if lo > 0 else "") + _UNSHOWN.sub("", line[lo:hi]).strip() + ("…" if hi < len(line) else "")


def outline_of(text: str, rules: Rules, ext: str = "", page_lines: list[int] | None = None) -> dict:
    """Headings, shall statements and values. Lines starting with '#' are headings only where
    the format makes them so (Markdown, and Word, whose reader marks its heading styles). Each value
    also says where it is: its line, its page (from `page_lines`, where each page starts), the
    heading it stands under, and the words around it."""
    found_heads: dict[str, str] = {}          # folded -> as first written
    marks: list[tuple[int, str]] = []          # (where in the text, heading): the section a value is in

    def heading(h: str, at: int) -> None:
        found_heads.setdefault(h.lower(), h)
        marks.append((at, h.lstrip("# ").strip()))

    ext = (ext or "").lower()
    if ext in (".md", ".docx", ".docm", ".rst"):
        for m in MARKDOWN_HEADING.finditer(text):
            heading(f"{'#' * len(m.group(1))} {m.group(2).strip()}", m.start())
    elif ext in SHEET_SUFFIXES:
        for m in re.finditer(r"^## sheet (.+?)(?:  \(|  \u00b7|$)", text, re.M):
            heading(f"sheet {m.group(1).strip()}", m.start())
    if ext not in SHEET_SUFFIXES:
        for m in NUMBERED_HEADING.finditer(text):
            title = m.group(2).strip()
            if re.search(r"[A-Za-z]{3,}", title):
                heading(f"{m.group(1)} {title}", m.start())
    marks.sort()
    mark_at = [at for at, _ in marks]
    line_starts: list[int] = []
    heads = list(found_heads.values())
    reqs = []
    for piece in _SENTENCE_BREAK.split(text):
        s = _one_line(piece)
        if 15 <= len(s) <= 320 and SHALL_LINE_RE.search(s):
            reqs.append({"text": s, "ids": sorted({hit[0] for rx in rules.req_ids for hit in rx.finditer(s)})})
    params, seen_values, occupied = [], set(), []
    last_named: list = []                 # (end, name, where it came from, unit) of the value named last

    def add(m, value, unit, kind):
        if unit == "s" and _DECADE.fullmatch(m.group(0)):
            return                                # "the 1980s" is a decade, not 1980 seconds
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _NUMBERED_THING.search(text[max(line_start, m.start() - 24):m.start()]):
            return                                # "Fig. 76.16 A mobile robot": a figure's number, not 76.16 A
        if len(unit) == 1 and unit.isupper() and not text[line_start:m.start()].strip() \
                and _INITIALS_AFTER.match(text, m.end()):
            return                                # "192 A. Smith and ...": a numbered reference, not 192 A
        context = _one_line(text[max(0, m.start() - 42):m.end()])[-72:]
        if (value, unit, context.lower()) in seen_values:
            return
        seen_values.add((value, unit, context.lower()))
        start = text.rfind("\n", 0, m.start()) + 1
        stop = text.find("\n", m.end())
        raw_line = text[start:None if stop < 0 else stop]
        line = _one_line(raw_line)
        from_cell = CELL_ORIGIN.search(line) is not None
        label, label_source, symbol = None, None, None
        # a word the line before broke ("resis-" / "tance required is"): joined again, for the name and the sentence
        broken = _BROKEN_WORD.search(text[max(0, start - 60):max(0, start - 1)]) if start else None
        head = broken.group(1) if broken and raw_line[:1].islower() else ""
        if not from_cell:
            before = head + text[start:m.start()]
            lm = PROSE_LABEL.match(before)
            if lm and not re.search(r"\bshall\b|\bmust\b", lm.group(1), re.I):
                label, label_source = lm.group(1).strip(), "label"
            else:
                label, symbol = name_and_symbol(before)
                label_source = "sentence" if label else None
                gap = text[last_named[0]:m.start()] if last_named else None
                if label is None and gap is not None and gap.count("\n") <= 1 and _LIST_GAP.fullmatch(gap) \
                        and _same_kind(last_named[3], unit):
                    label, symbol, label_source = last_named[1], None, last_named[2]   # one of a list
        if label:
            last_named[:] = [m.end(), label, label_source, unit]
        if not line_starts:
            line_starts.append(0)
            line_starts.extend(n.end() for n in re.finditer("\n", text))
        line_no = bisect.bisect_right(line_starts, m.start())
        k = bisect.bisect_right(mark_at, m.start()) - 1
        params.append(dict(value=value, unit=unit, kind=kind, value_norm=P.canon_number(value),
                           unit_norm=P.canon_unit(unit), context=line[:320] if from_cell else context, line=line,
                           prose_label=label, label_source=label_source, line_no=line_no,
                           page=bisect.bisect_right(page_lines, line_no) if page_lines else None,
                           section=marks[k][1][:120] if k >= 0 else None,
                           symbol=symbol,
                           sentence=_readable((head + raw_line).replace("\t", " "), m.start() - start + len(head),
                                              m.end() - start + len(head))))

    found = []
    for m in [*VALUE_RANGE.finditer(text), *RANGE_ACROSS_LINES.finditer(text)]:
        if m.group(2) and P.canon_unit(m.group(2)) != P.canon_unit(m.group(4)):
            continue                              # "5 V - 3 A": two values, not a range
        occupied.append(m.span())
        found.append((m.start(), m, m.group(1) + P.RANGE_MARK + m.group(3), m.group(4), "range"))
    for m in VALUE_WITH_UNIT.finditer(text):
        if not any(lo <= m.start() < hi for lo, hi in occupied):
            found.append((m.start(), m, m.group(1), m.group(2), "value"))
    for m in VALUE_ACROSS_LINES.finditer(text):
        if len(m.group(2)) == 1 and m.group(2).isupper() and text.startswith(".", m.end()):
            continue                              # "37 / K. Smith": an initial
        if not any(lo <= m.start() < hi for lo, hi in occupied):
            found.append((m.start(), m, m.group(1), m.group(2), "value"))
    for _, m, value, unit, kind in sorted(found, key=lambda f: f[0]):      # in the order they are written
        add(m, value, unit, kind)
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
               label=None, sheet=None, cell=None, formula=None, hidden: bool = False, context: str = "",
               label_source=None, line_no=None, page=None, section=None, sentence=None, symbol=None) -> dict:
    """One row of the value list. `unit` is already in its one spelling. Where it is: `line_no` in the
    document's text, `page` (PDFs), `section` (the heading above it), `sentence` (the words around it)."""
    return {"value": shown, "unit": unit, "kind": kind, "value_as_written": written, "value_shown": shown,
            "unit_as_written": unit_written, "value_norm": P.canon_number(shown),
            "value_exact_norm": P.canon_number(written), "unit_norm": unit, "origin": origin, "label": label,
            "label_norm": P.canon_label(label), "sheet": sheet, "cell": cell, "formula": formula, "hidden": hidden,
            "context": context, "label_source": label_source if label else None, "line_no": line_no, "page": page,
            "section": section, "sentence": sentence, "symbol": symbol if label else None}


def _fuller_names(rows: list[dict]) -> None:
    """A value named by its own sentence ("The laser control shall keep the max current at 15.0 A" gives "max
    current") takes the fuller name the same document gives it elsewhere ("Laser control max current: 12.5 A"),
    when exactly one name there ends with it. The two statements are then compared, and every other part's
    "max current" is not pooled with them."""
    full: dict[str, str] = {}
    for r in rows:
        if r["label_source"] in ("label", "cell") and r["label_norm"]:
            full.setdefault(r["label_norm"], r["label"])
    for r in rows:
        if r["label_source"] == "sentence" and r["label_norm"]:
            longer = sorted(n for n in full if n.endswith(" " + r["label_norm"]))
            if len(longer) == 1:
                r["label"], r["label_norm"] = full[longer[0]], longer[0]
            elif " " not in r["label_norm"]:          # "the timeout", and no fuller name here: whose, not said
                r["label"], r["label_norm"], r["label_source"], r["symbol"] = None, "", None, None


def _doc_parameters(text: str, rules: Rules, ext: str = "", page_lines: list[int] | None = None) -> tuple[dict, list[dict]]:
    parsed = outline_of(text, rules, ext, page_lines)
    rows = []
    for p in parsed.pop("_all"):
        sheet, cell, label = _origin(p["line"])
        rows.append(_value_row("prose_value", p["value"], p["value"], p["unit"], P.canon_unit(p["unit"]), kind=p["kind"],
                               label=p.get("prose_label") if label is None else label, sheet=sheet, cell=cell,
                               context=p["context"], label_source=p["label_source"] if label is None else "cell",
                               line_no=p["line_no"], page=p["page"], section=p["section"], sentence=p["sentence"],
                               symbol=p["symbol"] if label is None else None))
    _fuller_names(rows)
    # the outline lists the values with their names, as a workbook's outline does
    parsed["values"] = [{k: r[k] for k in _SHEET_OUTLINE_KEYS} for r in rows[:STRUCT_CAP]]
    return parsed, rows


def _sheet_values(path: Path, text: str = "") -> list[dict]:
    """The values of a workbook's cell records, then the numbers typed into its formulas. Each with the line of
    the workbook's text that shows its cell."""
    values, literals = [], []
    line_of = {}
    for n, text_line in enumerate(text.split("\n"), 1):
        o = CELL_ORIGIN.search(text_line)
        if o:
            line_of.setdefault((o.group("sheet").strip().strip("'"), o.group("cell").replace("$", "")), n)
    for rec in util.load_jsonl(path):
        formula, label, sheet, cell = rec.get("formula"), rec.get("label"), rec.get("sheet"), rec.get("cell")
        where = dict(label=label, sheet=sheet, cell=cell, formula=formula, hidden=bool(rec.get("hidden")),
                     label_source="cell", line_no=line_of.get((sheet, cell)), section=f"sheet {sheet}" if sheet else None)
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
                                     context=line[:500], sentence=line[:200], **where))
        literals += [_value_row("formula_constant", lit, lit, "", "", **where,
                                context=f"constant {lit} inside @{sheet}!{cell} {{{formula}}}"[:500],
                                sentence=f"constant {lit} inside @{sheet}!{cell} {{{formula}}}"[:200])
                     for lit in P.formula_constants(formula)]
    return [v for v in values + literals if P.all_numbers(v["value_norm"])]


def _outline_one(job: tuple) -> tuple[dict, list[dict]]:
    """One source's headings, shall statements and values (a piece of parallel work)."""
    rel, sheet_cells, ext, page_lines = job
    d = parallel.shared()
    text = _text_in(d["documents"], rel)
    if sheet_cells:
        rows = _sheet_values(Path(d["documents"]) / sheet_cells, text)
        parsed = outline_of(text, d["rules"], ext)
        parsed.pop("_all")
        parsed.update(values_count=len(rows), values=[{k: r[k] for k in _SHEET_OUTLINE_KEYS} for r in rows[:STRUCT_CAP]],
                      values_cut=len(rows) > STRUCT_CAP)
        return parsed, rows
    return _doc_parameters(text, d["rules"], ext, page_lines)


def structure_and_parameters(proj: Project, core: list[dict], sources: list[dict], rules: Rules) -> dict:
    dm = proj.documents_dir
    by_source = {}
    params_path = dm / "params.jsonl"
    reg_count, source_tally, kinds = 0, {}, Counter()
    lines = []
    outlining = util.Progress("corpus", "documents read for headings, requirements and values", len(sources))
    pages = {r["key"]: r.get("page_lines") for r in util.load_jsonl(dm / "text-index.jsonl")}
    jobs = [(s.get("cached_text"), s.get("sheet_cells") if _ext(s) in SHEET_SUFFIXES else None, s.get("ext"),
             pages.get(s["file_key"])) for s in sources]
    outlined = parallel.map_in_order(_outline_one, jobs, progress=outlining,
                                     data={"documents": str(dm), "rules": rules})
    for s, (parsed, rows) in zip(sources, outlined, strict=True):
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
    util.say("corpus", f"writing the value database: {reg_count:,} values from {len(sources):,} documents")
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
    quoting = util.Progress("corpus", "documents searched for other documents' numbers", len(core))
    for d in core:
        quoting.tick(d["title"])
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


def _citations(core: list[dict], texts: dict, documents_dir) -> list[dict]:
    """A document cites another when it writes that document's title (three words or more, not all
    generic) or its file name with the extension. Matched on whole words, never inside a word."""
    # Every title, filed under its first word and its length: at each word of a text, one lookup per
    # length tells which titles are written there, however many titles begin with that word.
    patterns: dict[tuple[str, int], dict[tuple[str, ...], list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for d in core:
        name = d["title"]
        for title in dict.fromkeys(t for t in (name, d.get("doc_title") or "") if t):
            words = _title_words(VERSION_TAIL.sub("", title) or title)
            meaningful = [w for w in words if w not in GENERIC_TITLE_WORDS and not w.isdigit()]
            if len(words) >= 3 and len("".join(words)) >= 15 and len(meaningful) >= 2:
                patterns[(words[0], len(words))][words].append((d["key"], "title"))
        ext = (d.get("ext") or "").lstrip(".").lower()
        full = _title_words(name) + ((ext,) if ext else ())
        if ext and len("".join(full)) >= 8 and len(full) >= 2:
            patterns[(full[0], len(full))][full].append((d["key"], "file name"))
    lengths: dict[str, list[int]] = defaultdict(list)
    for first, size in sorted(patterns):
        lengths[first].append(size)
    edges = []
    citing = util.Progress("corpus", "documents searched for other documents' titles and file names", len(core))
    # each worker reads its documents' text itself (the same files, read the same way): 200 MB of text for
    # 10,000 documents would otherwise be copied to every worker
    cited = parallel.map_in_order(_cites_in, [(d["key"], d.get("cached_text")) for d in core], progress=citing,
                                  data={"patterns": {k: dict(v) for k, v in patterns.items()}, "lengths": dict(lengths),
                                        "documents": str(documents_dir)})
    for d, found in zip(core, cited, strict=True):
        for key, n, how in found:
            edges.append({"from": d["key"], "to": key, "kind": "cites", "count": n,
                          "source": f"{how} written in the text"})
    return edges


def _cites_in(job: tuple[str, str]) -> list[tuple[str, int, str]]:
    """The documents one text cites, with how often and how (a piece of parallel work)."""
    own, rel = job
    d = parallel.shared()
    patterns, lengths = d["patterns"], d["lengths"]
    words = WORDS_RE.findall(_text_in(d["documents"], rel).lower())
    hits: Counter = Counter()
    how: dict[str, str] = {}
    for i, w in enumerate(words):
        for size in lengths.get(w, ()):
            for key, kind in patterns[(w, size)].get(tuple(words[i:i + size]), ()):
                if key == own:
                    continue
                hits[key] += 1
                if how.get(key) != "file name":
                    how[key] = kind
    return [(key, n, how[key]) for key, n in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))]


# == named values stated in several documents ==

def _place(r: dict) -> str:
    """Where a value is written inside its document: the sheet and cell of a workbook."""
    return f"{r['sheet']}!{r['cell']}" if r.get("sheet") and r.get("cell") else ""


def value_owners(rows: list[dict]) -> dict:
    """Every named value by its name: the documents that state it, the values each states (normalized), and
    how and where each was first written. Names that say nothing and constants inside formulas are left out."""
    by_label: dict[str, dict[str, set]] = defaultdict(dict)
    shown, written = {}, {}
    for r in rows:
        lab = r.get("label_norm") or ""
        if P.says_nothing(lab) or r["origin"] == "formula_constant":
            continue
        v = (r["value_norm"], r["unit_norm"])
        by_label[lab].setdefault(r["doc_ref"], set()).add(v)
        shown.setdefault(lab, r.get("label") or lab)
        written.setdefault((lab, r["doc_ref"], v), (f"{r['value_shown']} {r['unit']}".strip(), _place(r)))
    return {"by_label": by_label, "shown": shown, "written": written}


def _stating(owners: dict[str, set]) -> dict[tuple, list[str]]:
    """Each value of one name, with the documents that state it, in key order."""
    out: dict[tuple, list[str]] = defaultdict(list)
    for doc in sorted(owners):
        for v in sorted(owners[doc]):           # a set's order changes from run to run: never let it decide
            out[v].append(doc)
    return out


def _majority(owners: dict[str, set]) -> tuple[tuple, str] | None:
    """The value more than half of the documents state (at least two of them), and its anchor: the first
    document, by key, that states it. None when no value has such a majority: then no value is the odd one out.
    Documents that list several values for one name ("are 128.3 rad/s and 104.8 rad/s") can give more than
    one value a majority: the one most documents state, then the smaller key, is taken."""
    held = [(v, docs) for v, docs in _stating(owners).items() if len(docs) >= 2 and 2 * len(docs) > len(owners)]
    if not held:
        return None
    v, docs = min(held, key=lambda h: (-len(h[1]), h[0]))
    return v, docs[0]


def _odd_ones(values: dict) -> dict[tuple[str, str], list[list[str]]]:
    """(document, anchor) -> one row per name for which most documents agree on a value and this document
    states another: [name, value here, value in most documents, where here, where in the anchor]."""
    by_label, shown, written = values["by_label"], values["shown"], values["written"]
    odd = defaultdict(list)
    for lab in sorted(by_label):
        owners = by_label[lab]
        most = _majority(owners)
        if not most:
            continue
        best, anchor = most
        for doc in sorted(owners):
            if best not in owners[doc]:
                mine = min(owners[doc])
                here, there = written[(lab, doc, mine)], written[(lab, anchor, best)]
                odd[(doc, anchor)].append([shown[lab], here[0], there[0], here[1], there[1]])
    return odd


def _value_links(values: dict) -> list[dict]:
    """Documents linked through the named values they state; every link says how many values agree.
      shares   two documents state values of the same names, for names stated by two to MAX_VALUE_OWNERS
               documents (with one shared name enough when the name is specific)
      anchor   for a name stated by more documents than that, each document links to the first document
               that states the same value: documents that agree are joined however many there are
      differs  for any name on whose value most documents agree, a document that states another value
               links to the first document stating the value most give, with both values and their cells"""
    by_label, shown = values["by_label"], values["shown"]
    pairs, stars = defaultdict(list), defaultdict(list)
    for lab in sorted(by_label):
        owners = by_label[lab]
        if len(owners) < 2:
            continue
        if len(owners) <= MAX_VALUE_OWNERS:
            keys = sorted(owners)
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    pairs[(a, b)].append((lab, bool(owners[a] & owners[b])))
        else:
            for docs in _stating(owners).values():
                for doc in docs[1:]:
                    stars[(doc, docs[0])].append((lab, True))

    def joined(kind: str, a: str, b: str, labs: list, source: str) -> dict:
        differ = [shown[lab] for lab, ok in labs if not ok]
        return {"from": a, "to": b, "kind": kind, "shared_count": len(labs), "agree_count": len(labs) - len(differ),
                "differ_count": len(differ), "shared": [shown[lab] for lab, _ in labs[:8]], "differ": differ[:8],
                "source": source}

    edges = []
    for (a, b), labs in sorted(pairs.items()):
        # one shared value is enough when its name is specific (two words, or eight letters)
        if len(labs) >= SHARED_VALUE_MIN or any(" " in lab.strip() or len(lab) >= 8 for lab, _ in labs):
            edges.append(joined("shares", a, b, labs, "named values stated in both"))
    for (a, b), labs in sorted(stars.items()):
        edges.append(joined("anchor", a, b, labs, "the same value of a name many documents state, linked to the "
                                                  "first document that states it"))
    for (a, b), rows in sorted(_odd_ones(values).items()):
        edges.append({"from": a, "to": b, "kind": "differs", "differ_count": len(rows), "values": rows,
                      "source": "another value than most documents state for the same name"})
    return edges


def value_conflicts(values: dict) -> list[dict]:
    """Every name that documents state with more than one value: each value with the documents that state it
    and where. When most documents agree, the value they give, its anchor document, and the documents that
    differ; otherwise those three are empty. Sorted by name."""
    by_label, shown, written = values["by_label"], values["shown"], values["written"]
    out = []
    for lab in sorted(by_label):
        owners = by_label[lab]
        stating = _stating(owners)
        if len(owners) < 2 or len(stating) < 2:
            continue
        most = _majority(owners)
        best = most[0] if most else None
        order = sorted(stating, key=lambda v: (v != best, -len(stating[v]), stating[v][0], v))
        out.append({"label": shown[lab], "label_norm": lab, "documents_count": len(owners),
                    "anchor": most[1] if most else None, "value": written[(lab, most[1], best)][0] if most else None,
                    "differing": [d for d in sorted(owners) if best not in owners[d]] if most else [],
                    "values": [{"value": written[(lab, stating[v][0], v)][0], "value_norm": v[0], "unit": v[1],
                                "documents_count": len(stating[v]),
                                "documents": [{"key": d, "place": written[(lab, d, v)][1]} for d in stating[v]]}
                               for v in order]})
    return out


def document_links(proj: Project, core: list[dict], rules: Rules, values: dict | None = None) -> list[dict]:
    util.say("corpus", f"links between documents: loading the text of {len(core):,} documents")
    texts = {d["key"]: _text(proj, d.get("cached_text")) for d in core}
    if values is None:
        values = value_owners(util.load_jsonl(proj.documents_dir / "params.jsonl"))
    edges = _lineage(core, rules) + _references(proj, core, rules, texts) + _citations(core, texts, proj.documents_dir)
    util.say("corpus", f"links between documents: {len(values['by_label']):,} value names, each document linked to the "
                       "others that state it")
    edges += _value_links(values)
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
        scoped = {}                                    # `Controller::clamp` -> `clamp`, for C++ names
        for short, definitions in sym.items():
            for d in definitions:
                pieces = (d.get("qualname") or "").split("::")
                for k in range(len(pieces) - 1):
                    scoped.setdefault("::".join(pieces[k:]), short)
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
                name = s["sym"] if s["sym"] in sym else scoped.get(s["sym"]) or vh_lower.get(s["sym"].lower())
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
    live = util.live_on()
    if live:
        from contextmax.views import atlas_data
        atlas_data.live_documents(proj, core)
    dc_edges, sym_stats = code_links(proj, core, rules)
    util.say("corpus", f"{sum(1 for d in core if d['linked_code'])} documents name code "
                       f"({len(dc_edges)} links, {sym_stats['exact_names']} distinctive code names known)")
    if live:
        atlas_data.live_code_links(proj, core, dc_edges)
    st = structure_and_parameters(proj, core, sources, rules)
    util.say("corpus", f"{st['totals'].get('headings', 0)} headings, {st['totals'].get('requirements', 0)} shall "
                       f"statements, {st['value_rows']} values in the value list")
    util.live("values", rows=st["value_rows"], headings=st["totals"].get("headings", 0),
              requirements=st["totals"].get("requirements", 0))
    value_rows = util.load_jsonl(dm / "params.jsonl")
    values = value_owners(value_rows)
    util.say("corpus", "the documents' values against the named numbers in the code")
    in_code = value_code.links(value_rows, value_code.code_rows(proj))
    util.save_jsonl(dm / "links" / "value-to-code.jsonl", [json.loads(json.dumps(r, sort_keys=True)) for r in in_code])
    vc = value_code.summary(in_code)
    util.say("corpus", f"{util.count(vc['names_count'], 'value name')} found in the code: "
                       + (", ".join(f"{k} {v}" for k, v in vc["outcomes"].items()) or "nothing to compare"))
    dd_edges = document_links(proj, core, rules, values)
    conflicts = value_conflicts(values)
    kinds = Counter(e["kind"] for e in dd_edges)
    util.say("corpus", "document links: " + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "none"))
    if live:
        atlas_data.live_document_links(core, dd_edges)
    util.say("corpus", "writing the document map: documents, links, conflicts, the guide")
    util.save_jsonl(dm / "doc-list.jsonl", [json.loads(json.dumps(d, sort_keys=True)) for d in core])
    util.save_jsonl(dm / "doc-sources.jsonl", [json.loads(json.dumps(s, sort_keys=True)) for s in sources])
    util.save_jsonl(dm / "links" / "doc-to-code.jsonl", [json.loads(json.dumps(e, sort_keys=True)) for e in dc_edges])
    util.save_jsonl(dm / "links" / "between-docs.jsonl", [json.loads(json.dumps(e, sort_keys=True)) for e in dd_edges])
    util.save_jsonl(dm / "value-conflicts.jsonl", [json.loads(json.dumps(c, sort_keys=True)) for c in conflicts])
    util.save_json(dm / "links" / "code-to-doc.json", docs_of_code(proj, core, dc_edges), indent=None, sort_keys=True)
    _write_guide(proj, core, dc_edges, dd_edges, rules)
    util.say("corpus", "the search store: every document's text and headings, searchable word by word")
    store = search.write(proj)
    summary = {"docs_count": len(core), "sources_count": len(sources), "code_linked_count": sum(1 for d in core if d["linked_code"]),
               "doc_code_edges_count": len(dc_edges), "doc_doc_edges_count": len(dd_edges),
               "doc_doc_kinds": dict(sorted(kinds.items())), "outline_totals": st["totals"],
               "param_rows": st["value_rows"], "param_origins": st["origins"], "value_conflicts_count": len(conflicts),
               "named_values_count": sum(1 for r in value_rows if r.get("label")),
               "value_names_count": len(values["by_label"]),
               "names_from_sentences_count": sum(1 for r in value_rows if r.get("label_source") == "sentence"),
               "value_code": vc, "search": store,
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
         "value with its cell), `links/doc-to-code.jsonl`, `links/between-docs.jsonl`, `links/code-to-doc.json`, `value-conflicts.jsonl` "
         "(every named value that some documents give differently, with each value's documents and cells).", ""]
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

def _place_problem(r: dict, lines: list[str], page_lines: list[int] | None) -> str | None:
    """What is wrong with where a value says it is, or None: the line it names must show it (the number as
    written, or its cell), and the page it names must hold that line."""
    n = r.get("line_no")
    if n is None:
        return "a value in the text without its line" if r["origin"] == "prose_value" else None
    if not 1 <= n <= len(lines):
        return f"line {n} is past the end of the document's text"
    line = lines[n - 1]
    if r["origin"] == "prose_value":
        # the value starts on its line; a range ("from 35 to / 150 mm") may end on one of the next lines
        first, *rest = r["value_as_written"].split(P.RANGE_MARK)
        after = "\n".join(lines[n - 1:n + 3])
        if first not in line or not all(part in after for part in rest):
            return f"line {n} does not show {r['value_as_written']!r}"
    elif not (r.get("cell") and f"!{r['cell']}" in line):
        return f"line {n} does not show cell {r.get('cell')!r}"
    if (bisect.bisect_right(page_lines, n) if page_lines else None) != r.get("page"):
        return f"line {n} is not on page {r.get('page')}"
    if (r.get("label") is None) != (r.get("label_source") is None):
        return "a name without where it comes from, or the other way round"
    return None


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
    conflicts = rows_of(dm / "value-conflicts.jsonl")

    def key_set(rows, name, field="key"):
        ks = [r.get(field) for r in rows]
        if len(ks) != len(set(ks)):
            errors.append(f"{name}: {len(ks) - len(set(ks))} duplicate keys")
        return set(ks)

    cached_keys, map_keys = key_set(index, "text-index"), key_set(core, "doc-list")
    if key_set(structure, "doc-outlines") != map_keys:
        errors.append("doc-outlines and doc-list hold different documents")
    hashing = util.Progress("gate", "texts checked against their fingerprints", len(index))

    def problems_of(r: dict) -> list[str]:
        """One cached text, and its cell records, against the fingerprints the index holds."""
        found = []
        p = dm / (r.get("cached_text") or "")
        if not p.is_file():
            return [f"text missing for {r.get('key')}"]
        if util.hash_file(p) != r.get("text_sha256"):
            found.append(f"text of {r.get('key')} changed since it was indexed")
        if (r.get("ext") or "") in SHEET_SUFFIXES:
            rec = dm / (r.get("sheet_cells") or "")
            if not r.get("sheet_cells") or not rec.is_file():
                found.append(f"spreadsheet {r.get('key')} has no cell records")
            elif util.hash_file(rec) != r.get("cells_sha256"):
                found.append(f"cell records of {r.get('key')} changed since they were indexed")
        return found

    # reading and fingerprinting files waits on the disk more than on Python: threads share that out, and
    # the problems come back in the index's order, as one at a time
    with ThreadPoolExecutor(max_workers=min(8, parallel.workers())) as threads:
        for r, found in zip(index, threads.map(problems_of, index), strict=True):
            hashing.tick(r.get("key") or "")
            errors += found
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
    # values that differ: the list and the red links are worked out again from the value list, and must agree
    values = value_owners(value_rows)
    if conflicts != [json.loads(json.dumps(c, sort_keys=True)) for c in value_conflicts(values)]:
        errors.append("value-conflicts.jsonl does not match the value list")
    for c in conflicts:
        named = {*c.get("differing", []), *(d["key"] for v in c.get("values", []) for d in v["documents"])}
        if c.get("anchor"):
            named.add(c["anchor"])
        if named - map_keys:
            errors.append(f"value conflict {c.get('label_norm')!r} names unknown documents")
    util.say("gate", "  the documents' values against the code's named numbers, compared again")
    in_code = rows_of(dm / "links" / "value-to-code.jsonl") if (dm / "links" / "value-to-code.jsonl").exists() else None
    if in_code is None:
        errors.append("links/value-to-code.jsonl is missing")
    elif in_code != [json.loads(json.dumps(r, sort_keys=True)) for r in value_code.links(value_rows, value_code.code_rows(proj))]:
        errors.append("links/value-to-code.jsonl does not match the value list and the code's named numbers")
    else:
        for r in in_code:
            if {d["doc_ref"] for d in r["documents"]} - map_keys:
                errors.append(f"value {r['label_norm']!r} in the code names unknown documents")
    odd = {(a, b): len(rows) for (a, b), rows in _odd_ones(values).items()}
    if {(e["from"], e["to"]): e.get("differ_count") for e in dd if e.get("kind") == "differs"} != odd:
        errors.append("the links for values that differ do not match the value list")
    src_map = {s["file_key"]: s["node_ref"] for s in sources}
    for sk, nk in src_map.items():
        if sk not in cached_keys:
            errors.append(f"source {sk} is not in the text cache")
        if nk not in map_keys:
            errors.append(f"source {sk} folds into an unknown document {nk}")
    required = {*_VALUE_FIELDS, "format_version", "doc", "file_key", "doc_ref"}
    source_tally, seen_rows = Counter(), set()
    by_key = {r.get("key"): r for r in index}
    shown_in: tuple = (None, [], None)                 # (document, its lines, where its pages start)
    checking = util.Progress("gate", "values checked: name, number, unit and the line that shows them", len(value_rows))
    for n, r in enumerate(value_rows, 1):
        checking.tick()
        missing = required - set(r)
        if missing:
            errors.append(f"params.jsonl:{n}: missing {sorted(missing)}")
            continue
        if shown_in[0] != r["file_key"]:
            cached = by_key.get(r["file_key"]) or {}
            shown_in = (r["file_key"], _text_in(dm, cached.get("cached_text")).split("\n"), cached.get("page_lines"))
        wrong_place = _place_problem(r, shown_in[1], shown_in[2])
        if wrong_place:
            errors.append(f"params.jsonl:{n}: {wrong_place}")
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
    util.say("gate", "  the value database: its integrity, and the same values as the value list")
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
    errors += search.check(proj)
    counts = {"cached documents": len(cached_keys), "map documents": len(map_keys), "source files": len(sources),
              "values": len(value_rows), "code links": len(dc), "document links": len(dd), "values that differ": len(conflicts)}
    return errors, counts
