"""Ask a model on this PC about a project: the model servers on this PC, the search that finds the ways into
the index, and the models ContextMAX suggests.

The search is ContextMAX's own (no model in it): functions by name with their code, passages of the documents'
text, named values with where they are stated and what the code says of them, named numbers in the code.
reading.py then has the model read the files those point to, one passage at a time. Nothing leaves this PC:
only an address on this PC (127.0.0.1, localhost) is ever asked.
"""
from __future__ import annotations

import http.client
import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from contextmax import citations, util
from contextmax.docs import search

SERVERS = (("Ollama", "http://127.0.0.1:11434", "ollama"), ("llama.cpp", "http://127.0.0.1:8080", "openai"),
           ("LM Studio", "http://127.0.0.1:1234", "openai"))
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PASSAGE_LINES = search.PASSAGE_LINES
STOP = set("""the a an and or of to in on for is are was were be been by with from at as it its this that these those
what which who whom how why when where does do did can could should would will shall may might than then there here
about into over under not no yes our your their his her we you they me my mine use used using any all some each more most
have has had please tell regarding related concerning document documents agree agrees disagree
function functions call calls called caller callers code change changed changes affect affected affects else
value values define defined defines mention mentions mentioned
de het een en of van in op voor is zijn met die dat wat hoe waar wie welke wordt worden niet geen ook als bij naar
der die das und oder ist sind mit von fur für wie was wo wer welche wird werden nicht kein auch als bei nach
и в на с по что как где это для к от до у же ли не или из за при так""".split())
_INDEXES: dict = {}
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                     # a redirect could point off this PC: it is an error, not followed


# this PC only: never through a proxy, never redirected elsewhere
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


class AskError(Exception):
    pass


def _on_this_pc(base: str) -> str:
    parts = urlsplit(base)
    host = (parts.hostname or "").lower()
    if parts.scheme != "http" or host not in LOOPBACK or "@" in parts.netloc or "\\" in base:
        raise AskError(f"{base} is not a model on this PC; ContextMAX only asks 127.0.0.1 or localhost")
    return base.rstrip("/")


def _get_json(url: str, timeout: float):
    with _DIRECT.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def listed(kind: str, base: str) -> bool:
    """One of the servers ContextMAX looks for: the only ones a page may ask it to talk to."""
    return any(kind == k and base.rstrip("/") == b for _, b, k in SERVERS)


def servers(timeout: float = 0.8) -> list[dict]:
    """The model servers running on this PC, with their models."""
    out = []
    for name, base, kind in SERVERS:
        try:
            data = _get_json(base + "/v1/models", timeout)
        except (OSError, ValueError):
            continue
        models = sorted(m.get("id", "") for m in data.get("data") or [] if m.get("id"))
        if kind == "ollama":
            models = _ollama_order(base, models, timeout)
        out.append({"name": name, "base": base, "kind": kind, "models": models})
    return out


def capabilities(base: str, model: str, timeout: float = 3) -> list[str]:
    """What an Ollama model can do ("vision", "tools", ...): its own details say it; the list of models does
    not always."""
    req = urllib.request.Request(_on_this_pc(base) + "/api/show", data=json.dumps({"model": model}).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with _DIRECT.open(req, timeout=timeout) as r:
            return list(json.loads(r.read().decode("utf-8")).get("capabilities") or [])
    except (OSError, ValueError):
        return []


def _ollama_order(base: str, models: list[str], timeout: float) -> list[str]:
    """Recent instruction models first (Ollama marks them able to use tools), larger first: the first in
    the list is the one offered."""
    try:
        tags = {m["name"]: m for m in _get_json(base + "/api/tags", timeout).get("models") or []}
    except (OSError, ValueError):
        return models
    def rank(name):
        m = tags.get(name) or {}
        return (0 if "tools" in (m.get("capabilities") or []) else 1, -(m.get("size") or 0), name)
    return sorted(models, key=rank)


# ---- the sources: found in the index, by ContextMAX alone -----------------------------------------------

def words(question: str) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[^\W_][\w.\-]*[^\W_]|[^\W_]", question.lower()):
        w = w.strip(".-")
        if len(w) >= 3 and w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_][\w\-]*", text.lower())


def _index(proj) -> dict:
    """What the search reads, loaded once per build of the project."""
    stamp = (util.load_json(proj.workspace / "buildinfo.json", default={}) or {}).get("outputs_hash") or ""
    cached = _INDEXES.get(proj.slug)
    if cached and cached["stamp"] == stamp:
        return cached
    functions = []
    code_values = []
    for t in proj.code_targets:
        for f in util.load_jsonl(proj.code_dir / t["name"] / "function-list.jsonl"):
            functions.append((t, f))
        for v in util.load_jsonl(proj.code_dir / t["name"] / "values.jsonl"):
            code_values.append((t, v))
    rows = util.load_jsonl(proj.documents_dir / "text-index.jsonl")
    titles = {r["key"]: r.get("doc_title") or Path(r.get("relative_path") or r["key"]).name for r in rows}
    doc_list = util.load_jsonl(proj.documents_dir / "doc-list.jsonl")
    kept = {d["key"] for d in doc_list}                       # copies folded into one
    stages = {d["key"]: d.get("stage") for d in doc_list}
    by_key = {r["key"]: r for r in rows}
    in_code: dict[str, list[dict]] = {}
    in_code_of: dict[tuple, list[dict]] = {}        # the same links, from the code's side
    for r in util.load_jsonl(proj.documents_dir / "links" / "value-to-code.jsonl"):
        in_code.setdefault(r["label_norm"], []).append(r)
        in_code_of.setdefault((r["code"]["target"], r["code"]["file"], r["code"]["name"]), []).append(r)
    by_file: dict[tuple, list[dict]] = {}
    in_module: dict[tuple, set] = {}
    for t, f in functions:
        by_file.setdefault((t["name"], f["file"]), []).append(f)
    for t, x in functions + code_values:
        in_module.setdefault((t["name"], module_of(x)), set()).add(x["file"])
    ix = {"stamp": stamp, "functions": functions, "code_values": code_values, "titles": titles, "stages": stages,
          "rows": by_key, "in_code": in_code, "in_code_of": in_code_of, "documents_dir": proj.documents_dir,
          "functions_in": by_file, "files_in": {k: sorted(v) for k, v in in_module.items()}}
    store = search.open_store(proj)
    if store is not None:          # the documents' text, values and headings are looked up, not loaded
        with closing(store):
            ix["passages_count"] = store.execute("SELECT count(*) FROM passage_at").fetchone()[0]
        ix["store"] = search.path_of(proj)
        ix["values_db"] = proj.documents_dir / "params.sqlite"
    else:                          # an index from before 0.4.1: every document read again, as then
        ix.update(_in_memory(proj, rows, kept))
    _INDEXES[proj.slug] = ix
    return ix


def _look_up(ix: dict, sql: str, args) -> list[tuple]:
    """One query on the search store, opened for it alone (a build may replace the store at any time)."""
    con = search.connect(ix["store"])
    if con is None:
        return []
    with closing(con):
        return con.execute(sql, args).fetchall()


def _in_memory(proj, rows: list[dict], kept: set) -> dict:
    passages, seen = [], set()
    for r in rows:
        if kept and r["key"] not in kept:
            continue
        for first, last, chunk in search.chunks(_lines_of(proj, r)):
            if chunk not in seen:
                seen.add(chunk)
                passages.append({"key": r["key"], "start": first, "end": last, "text": chunk, "tf": Counter(_tokens(chunk))})
    df = Counter()
    for p in passages:
        df.update(p["tf"].keys())
    values = [r for r in util.load_jsonl(proj.documents_dir / "params.jsonl")
              if r.get("label_norm") and r.get("origin") != "formula_constant"]
    outlines = {d["key"]: d.get("headings") or [] for d in util.load_jsonl(proj.documents_dir / "doc-outlines.jsonl")
                if not kept or d["key"] in kept}
    return {"passages": passages, "passages_count": len(passages), "df": df, "values": values, "outlines": outlines}


def doc_freq(ix: dict, ws: list[str]) -> dict[str, int]:
    """In how many passages each word stands."""
    if "store" not in ix:
        return {w: ix["df"].get(w, 0) for w in ws}
    found = dict(_look_up(ix, f"SELECT term, doc FROM words WHERE term IN ({','.join('?' * len(ws))})", ws)) if ws else {}
    return {w: found.get(w, 0) for w in ws}


def candidate_passages(ix: dict, ws: list[str], limit: int) -> list[dict]:
    """Passages that hold any of the words, the likeliest first: from the store, or from memory."""
    if "store" not in ix:
        return [p for p in ix["passages"] if any(p["tf"].get(w) for w in ws)]
    q = search.match_query(ws)
    if not q:
        return []
    out, texts = [], {}
    for key, first, last in _look_up(ix, search.PASSAGES_SQL, (q, limit)):
        if key not in texts:                           # the store holds the index; the text is the document's own
            texts[key] = _document_lines(ix, key)
        text = "\n".join(texts[key][first - 1:last]).strip()
        out.append({"key": key, "start": first, "end": last, "text": text, "tf": Counter(_tokens(text))})
    return out


def candidate_headings(ix: dict, ws: list[str]) -> dict[str, list[tuple[str, int | None]]]:
    """Per document, its headings that hold any of the words, with the line each stands on (None: not known)."""
    if "store" not in ix:
        return {k: [(h, None) for h in heads] for k, heads in ix["outlines"].items()}
    q = search.match_query(ws)
    out: dict[str, list] = {}
    for key, line, heading in (_look_up(ix, search.HEADINGS_SQL, (q,)) if q else []):
        out.setdefault(key, []).append((heading, line))
    return out


_VALUE_SQL = ("SELECT pl.label, pl.label_norm, e.value_shown, e.value_as_written, e.value_norm, e.unit_norm, e.origin, "
              "pl.sheet, pl.cell, pl.label_source, pl.line_no, pl.page, pl.section, pl.symbol, s.file_key, s.doc_ref, "
              "s.stage FROM entries e JOIN places pl ON pl.id = e.place JOIN sources s ON s.id = pl.source "
              "WHERE e.origin <> 'formula_constant' AND pl.label_norm <> '' AND ({}) ORDER BY s.file_key, e.id")


def candidate_values(ix: dict, ws: list[str]) -> list[dict]:
    """Named values whose name may hold one of the words (the caller checks whole words): from the value
    database, or from memory."""
    if "values_db" not in ix:
        return ix["values"]
    stems = sorted({stem(w) for w in ws})
    if not stems:
        return []
    import sqlite3

    con = sqlite3.connect(f"{Path(ix['values_db']).as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(_VALUE_SQL.format(" OR ".join("pl.label_norm LIKE ?" for _ in stems)),
                                             [f"%{s}%" for s in stems])]
    finally:
        con.close()
    for r in rows:
        r["unit"] = r["unit_norm"]
    return rows


def module_of(x: dict) -> str:
    """The module a function or a named number is in (control/inc/pid.h and control/src/pid.c are both in
    "control"), or its folder when the code map gives none."""
    return x.get("module") or str(Path(x["file"]).parent)


def _lines_of(proj, r: dict) -> list[str]:
    try:
        return (proj.documents_dir / r["cached_text"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _title_of(ix: dict, key: str) -> str:
    return ix["titles"].get(key, key)


def _document_lines(ix: dict, key: str) -> list[str]:
    row = ix["rows"].get(key) or {}
    try:
        return (ix["documents_dir"] / row["cached_text"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, KeyError):
        return []


def stem(w: str) -> str:
    """A word without its plural s, so "voltages" finds "voltage"."""
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def natural(s: str) -> list:
    """f2 before f10: the numbers in a name compared as numbers."""
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]


class Asked:
    """The question's words, how much each counts (a word few passages hold counts more), and which of them a
    name or a text holds. One scale for every way in: values, code, sections, passages."""

    CONTEXT = 0.5     # a word only in the document's title or the code's module counts half

    def __init__(self, ix: dict, ws: list[str]):
        n = max(1, ix["passages_count"])
        forms = {w: {w, stem(w), stem(w) + "s"} for w in ws}
        known = doc_freq(ix, sorted(set().union(*forms.values()))) if ws else {}
        df = {w: max(known.get(x, 0) for x in forms[w]) for w in ws}       # a plural as rare as its word
        self.words = ws
        self.weight = {w: math.log(1 + n / (1 + df[w])) for w in ws}
        self.by_stem: dict[str, str] = {}
        for w in ws:
            self.by_stem.setdefault(stem(w), w)
        # a code name often holds the initials of what the question spells out: ekf_attitude_step for "the
        # extended Kalman filter", pid_step for "proportional integral derivative"; three or four words in a row
        self.short = {"".join(w[0] for w in ws[i:i + n]): tuple(ws[i:i + n])
                      for n in (3, 4) for i in range(len(ws) - n + 1)}
        self.part: set[str] = set()       # the words of the part the question names: see score

    def held(self, tokens) -> set:
        got = set()
        for t in tokens:
            s = stem(t)
            if s in self.by_stem:
                got.add(self.by_stem[s])
            elif t in self.short:
                got.update(self.short[t])
        return got

    def initials(self, name: str) -> str:
        """How a code name holds the question's words by their initials ("EKF: extended kalman filter"), or ""."""
        hit = next((w for w in _code_words(name) if w in self.short and stem(w) not in self.by_stem), None)
        return f"{hit.upper()}: {' '.join(self.short[hit])}" if hit else ""

    def score(self, own: set, context: set = frozenset()) -> float:
        """What a way in holds of the question. In a question about one part ("the encoder drive's nominal
        voltage"), the part's own words say where, not what: every name in that part holds them, so they count
        as context, and encoder_drive_read0_3 does not hold the question as the nominal voltage does. A way in
        that holds only where (the part's words, its title's) and nothing of what is asked holds nothing."""
        content = own - self.part
        if self.part and not content and set(self.words) - self.part:
            return 0.0
        return sum(self.weight[w] for w in content) + self.CONTEXT * sum(self.weight[w] for w in (context | own) - content)


def _code_words(name: str) -> list[str]:
    from contextmax.code.values import name_words

    return name_words(name) + [name.lower()]


def _family(name: str) -> str:
    return re.sub(r"\d+", "#", name)


def _shown(names: set, name: str) -> str:
    """One name, or the pattern a family of names shares (LASER_CONTROL_LIMIT_<n>)."""
    return name if len(names) == 1 else re.sub(r"\d+", "<n>", name)


def function_groups(ix: dict, asked: Asked) -> list[dict]:
    """Functions whose name holds the question's words (or two of them in its comment). Functions whose names
    differ only in their numbers (handle10_5, handle24_4) are one family, read once."""
    fams: dict[tuple, dict] = {}
    stems = list(asked.by_stem) + list(asked.short)
    for t, f in ix["functions"]:
        name = f.get("qualname") or f["name"]
        low, doc_low = name.lower(), (f.get("doc") or "").lower()
        if not any(s in low for s in stems) and sum(s in doc_low for s in stems) < 2:
            continue                  # a stem is part of its word: no question word can be in this name
        own = asked.held(_code_words(f["name"]) + ([name.lower()] if name != f["name"] else []))
        doc = asked.held(_tokens(f.get("doc") or ""))
        if not own and len(doc) < 2:
            continue
        g = fams.setdefault((t["name"], module_of(f), _family(name)),
                            {"own": set(), "members": []})
        g["own"] |= own | doc
        g["members"].append((t, f))
    out, want = [], code_name_words(asked.words)
    for g in fams.values():
        members = _named_first(sorted(g["members"], key=lambda tf: (natural(tf[1]["file"]), tf[1]["first_line"])), want)
        t, f = members[0]
        names = {x.get("qualname") or x["name"] for _, x in members}
        out.append({"kind": "function", "members": members, "name": _shown(names, f.get("qualname") or f["name"]),
                    "named": _is_named(f, want), "initials": asked.initials(f["name"]),
                    "score": asked.score(g["own"], asked.held(_code_words(f.get("module") or "")))})
    return sorted(out, key=lambda g: (not g["named"], -g["score"], natural(g["members"][0][1]["file"])))


def _is_named(x: dict, want: set) -> bool:
    return any(n.lower() in want for n in (x["name"], x.get("qualname") or x["name"], x["name"].rsplit(".", 1)[-1]))


def _named_first(members: list, want: set) -> list:
    """A family's member the question names exactly leads it (laser_control_limit10_0, not limit1_3)."""
    named = [m for m in members if _is_named(m[1], want)]
    return named + [m for m in members if not _is_named(m[1], want)]


def code_name_words(ws: list[str]) -> set[str]:
    """The words of a question that can be a code name: they have an underscore or a digit, or are long."""
    return {w for w in ws if "_" in w or any(c.isdigit() for c in w) or len(w) >= 8}


def named_in(ix: dict, ws: list[str]) -> list[dict]:
    """The functions and named numbers a question names exactly ("who calls laser_control_limit10_0?"), as
    {"kind", "target", "item"}: an assistant asking about one wants it first. A name that reads as a word of prose
    ("update") does not count."""
    from contextmax.docs.symbols import reads_as_code

    want = code_name_words(ws)
    if not want:
        return []
    out = []
    for t, f in ix["functions"]:
        name = f.get("qualname") or f["name"]
        if (f["name"].lower() in want or name.lower() in want) and reads_as_code(f["name"]):
            out.append({"kind": "function", "target": t, "item": f})
    for t, v in ix["code_values"]:
        if (v["name"].lower() in want or v["name"].rsplit(".", 1)[-1].lower() in want) and len(v["name"]) >= 4:
            out.append({"kind": "value", "target": t, "item": v})
    return out


def part_of(ix: dict, ws: list[str]) -> str | None:
    """The part of the code a question names: a module whose name has two words or more and whose words all
    stand in the question ("the laser control's max current" names laser_control). None when no module or more
    than one fits equally."""
    words = set(ws) | {stem(w) for w in ws}
    fits: dict[str, int] = {}
    for _t, x in ix["functions"] + ix["code_values"]:
        module = module_of(x)
        if module in fits:
            continue
        parts = [p for p in re.split(r"[_\W]+", module.lower()) if p]
        fits[module] = len(parts) if len(parts) >= 2 and all(p in words or stem(p) in words for p in parts) else 0
    best = max(fits.values(), default=0)
    found = [m for m, n in fits.items() if n == best and n]
    return found[0] if len(found) == 1 else None


def _member_order(tv: tuple) -> tuple:
    """A family's members, the ones in effect first: a value in a header that no file includes is never used."""
    v = tv[1]
    return (v.get("included_by_count") == 0, natural(v["file"]), v["line"])


def family_of(ix: dict, target: str, file: str, name: str) -> dict | None:
    """The family of one named number of the code (every number of its module whose name differs from it only
    in its digits, or has the same name in another header), as code_value_groups makes them."""
    me = next(((t, v) for t, v in ix["code_values"] if t["name"] == target and v["file"] == file and v["name"] == name), None)
    if me is None:
        return None
    key = (target, module_of(me[1]), _family(name))
    members = sorted(((t, v) for t, v in ix["code_values"]
                      if (t["name"], module_of(v), _family(v["name"])) == key), key=_member_order)
    return {"kind": "code value", "members": members, "name": _shown({v["name"] for _, v in members}, name)}


def code_value_groups(ix: dict, asked: Asked) -> list[dict]:
    """Named numbers in the code whose name or comment holds the question's words. Numbers whose names differ
    only in their digits, in one module (LASER_CONTROL_LIMIT_0 … _46), are one family: read once, and every
    member looked up in its file."""
    fams: dict[tuple, dict] = {}
    for t, v in ix["code_values"]:
        own = asked.held(_code_words(v["name"])) | asked.held(_tokens(v.get("comment") or ""))
        if not own:
            continue
        g = fams.setdefault((t["name"], module_of(v), _family(v["name"])),
                            {"own": set(), "members": []})
        g["own"] |= own
        g["members"].append((t, v))
    out, want = [], code_name_words(asked.words)
    for g in fams.values():
        members = _named_first(sorted(g["members"], key=_member_order), want)
        t, v = members[0]
        out.append({"kind": "code value", "members": members, "name": _shown({x["name"] for _, x in members}, v["name"]),
                    "named": _is_named(v, want),
                    "score": asked.score(g["own"], asked.held(_code_words(v.get("module") or "")))})
    return sorted(out, key=lambda g: (not g["named"], -g["score"], natural(g["members"][0][1]["file"])))


def section_groups(ix: dict, asked: Asked) -> list[dict]:
    """Sections whose heading holds the question's words ("3.5 Fault handling"): the best one of each document.
    A heading that only repeats the document's title (a Markdown file's "# Title") is not a section."""
    out = []
    for key, heads in candidate_headings(ix, asked.words).items():
        best = None
        title = _tokens(_title_of(ix, key))
        context = asked.held(title)
        for heading, line in heads:
            tokens = _tokens(heading)
            own = asked.held(tokens)
            if own and not set(tokens) <= set(title):
                s = asked.score(own, context)
                if best is None or s > best[0]:
                    best = (s, heading, line)
        if best:
            out.append({"kind": "section", "key": key, "heading": best[1], "line": best[2], "score": best[0]})
    return sorted(out, key=lambda g: (-g["score"], g["key"]))


def find_passages(ix: dict, ws: list[str], limit: int = 5, per_doc: int = 2) -> list[dict]:
    """Passages of the documents' text, ranked by how many of the words they hold, rare words most."""
    n = max(1, ix["passages_count"])
    df = doc_freq(ix, ws)
    idf = {w: math.log(1 + n / (1 + df[w])) for w in ws}
    ranked = []
    for p in candidate_passages(ix, ws, max(400, limit * 40)):
        s = sum(idf[w] * p["tf"][w] / (p["tf"][w] + 1.2) for w in ws if p["tf"].get(w))
        hits = sum(1 for w in ws if p["tf"].get(w))
        if hits:
            ranked.append((-(s * (1 + 0.5 * (hits - 1))), p["key"], p["start"], p))
    out, count = [], Counter()
    for _, _, _, p in sorted(ranked, key=lambda x: (x[0], x[1], x[2])):
        if count[p["key"]] >= per_doc or len(out) >= limit:
            continue
        count[p["key"]] += 1
        out.append(_passage_source(ix, ix["rows"].get(p["key"]) or {"key": p["key"]}, p["start"], p["end"], p["text"]))
    return out


def _passage_source(ix: dict, r: dict, first: int, last: int, text: str) -> dict:
    title = _title_of(ix, r["key"])
    return {"kind": "document", "label": title,
            "cite": citations.passage(title, ix["stages"].get(r["key"]), first, last, r.get("page_lines")),
            "text": text[:1600], "folder": r.get("folder"), "relative_path": r.get("relative_path"),
            "cached_text": r.get("cached_text"), "key": r["key"], "line": first}


def value_groups(ix: dict, asked: Asked) -> list[dict]:
    """Named values whose name holds the question's words, one group per name with every document that states
    it. First the statement whose document's title holds the question's words too, then one statement of each
    other value (where the documents differ), then the rest (the same value, stated again)."""
    labels: dict[str, set] = {}
    titles: dict[str, set] = {}
    rows_of: dict[str, list] = {}
    for r in candidate_values(ix, asked.words):
        if r["file_key"] != r["doc_ref"]:            # a folded copy or older revision: its document is read
            continue
        label = r["label_norm"]
        if label not in labels:
            labels[label] = asked.held(_tokens(label))
        if labels[label]:
            rows_of.setdefault(label, []).append(r)
    out = []
    for label, rows in rows_of.items():
        own = labels[label]
        for r in rows:
            if r["file_key"] not in titles:
                titles[r["file_key"]] = asked.held(_tokens(_title_of(ix, r["file_key"])))
        rows.sort(key=lambda r: (-asked.score(own, titles[r["file_key"]]), r["doc_ref"], r.get("line_no") or 0))
        kept, said = [], set()
        for r in rows:
            if (r["doc_ref"], r.get("value_norm"), r.get("unit_norm")) not in said:
                said.add((r["doc_ref"], r.get("value_norm"), r.get("unit_norm")))
                kept.append(r)
        lead, values = [], set()
        for r in kept:
            if (r.get("value_norm"), r.get("unit_norm")) not in values:
                values.add((r.get("value_norm"), r.get("unit_norm")))
                lead.append(r)
        first = {id(r) for r in lead}
        out.append({"kind": "value", "label": kept[0].get("label") or label, "label_norm": label, "rows": kept,
                    "lead": lead, "rest": [r for r in kept if id(r) not in first],
                    "score": asked.score(own, titles[kept[0]["file_key"]])})
    return sorted(out, key=lambda g: (-g["score"], g["label_norm"]))


# ---- the model on this PC ----------------------------------------------------------------------------------

def stream(kind: str, base: str, model: str, msgs: list[dict], timeout: float = 600):
    """The answer, in pieces as the model writes it."""
    base = _on_this_pc(base)
    if kind == "ollama":         # Ollama's own API: a context window large enough for the sources
        url, body = base + "/api/chat", {"model": model, "messages": msgs, "stream": True, "think": False,
                                         "options": {"num_ctx": 8192, "temperature": 0.2}}
    else:
        url, body = base + "/v1/chat/completions", {"model": model, "messages": msgs, "stream": True, "temperature": 0.2}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        resp = _DIRECT.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if kind == "ollama" and "think" in detail.lower():
            body.pop("think")         # a model without a thinking switch
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json"})
            resp = _DIRECT.open(req, timeout=timeout)
        else:
            raise AskError(f"the model server said: {detail or exc}") from exc
    except OSError as exc:
        raise AskError(f"no model server answers at {base}: {exc}") from exc
    with resp:
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if kind == "ollama":
                    d = json.loads(line)
                    if d.get("error"):
                        raise AskError(d["error"])
                    piece = (d.get("message") or {}).get("content") or ""
                else:
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    d = json.loads(line[5:])
                    piece = ((d.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                if piece:
                    yield piece
        except (http.client.HTTPException, OSError, ValueError) as exc:
            # the server closed or crashed while it answered: half an answer is not an answer
            raise AskError(f"the model server stopped in the middle of its answer ({type(exc).__name__})") from exc


# ---- which model on this PC, and getting one -------------------------------------------------------------

# Models ContextMAX suggests: they call tools reliably and cite well. (name, download GB, memory GB it needs)
RECOMMENDED = (
    ("qwen3.8:27b", 18, 20, "Qwen 3.8, 27B: the best at looking things up and citing; needs a graphics card with 20 GB or more"),
    ("qwen3:14b", 9.3, 11, "Qwen 3, 14B: good, for a graphics card with 12 GB or more"),
    ("qwen3:8b", 5.2, 7, "Qwen 3, 8B: for a graphics card with 8 GB, or a PC without one (slower)"),
    ("qwen3:4b", 2.5, 4, "Qwen 3, 4B: small and quick; its answers are weaker"),
)
OLLAMA_DOWNLOAD = "https://ollama.com/download"
_MEMORY: dict = {}


def graphics_memory_gb() -> float:
    """The largest graphics card's memory, from NVIDIA's own tool; 0 when there is none to ask."""
    if "gpu" not in _MEMORY:
        import shutil
        import subprocess

        gb = 0.0
        exe = shutil.which("nvidia-smi")
        if exe:
            try:
                out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True,
                                     text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
                gb = max((float(x) / 1024 for x in out.split() if x.replace(".", "", 1).isdigit()), default=0.0)
            except (OSError, subprocess.SubprocessError, ValueError):
                gb = 0.0
        _MEMORY["gpu"] = round(gb, 1)
    return _MEMORY["gpu"]


def system_memory_gb() -> float:
    if "ram" not in _MEMORY:
        gb = 0.0
        try:
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                           [(name, ctypes.c_ulonglong) for name in ("total", "free", "pf", "pff", "vt", "vf", "ve")]

            st = _Status()
            st.length = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                gb = st.total / 2 ** 30
        except (AttributeError, OSError):
            import os

            try:
                gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
            except (AttributeError, ValueError, OSError):
                gb = 0.0
        _MEMORY["ram"] = round(gb, 1)
    return _MEMORY["ram"]


def local_models(found_servers: list[dict], ollama_installed: bool) -> dict:
    """What the window says about models on this PC: the installed ones that can look things up, and the model
    ContextMAX suggests for this PC's memory (a graphics card first; without one, a small model)."""
    tool_models, vision_models = [], []
    for s in found_servers:
        if s["kind"] != "ollama":
            continue
        try:
            tags = _get_json(s["base"] + "/api/tags", 2).get("models") or []
        except (OSError, ValueError):
            tags = []
        ranked = sorted(tags, key=lambda m: (-(m.get("size") or 0), m["name"]))
        tool_models += [{"name": m["name"], "gb": round((m.get("size") or 0) / 1e9, 1)}
                        for m in ranked if "tools" in (m.get("capabilities") or [])]
        vision_models += [m["name"] for m in ranked
                          if "vision" in (m.get("capabilities") or []) or "vision" in capabilities(s["base"], m["name"])]
    gpu, ram = graphics_memory_gb(), system_memory_gb()
    fits = [r for r in RECOMMENDED if (gpu and r[2] <= gpu) or (not gpu and r[2] <= min(ram / 2, 8))]
    name, gb, _need, why = (fits or [RECOMMENDED[-1]])[0]
    have = {m["name"] for m in tool_models}
    return {"tool_models": tool_models, "vision_models": vision_models, "gpu_gb": gpu, "ram_gb": ram,
            "ollama_installed": ollama_installed,
            "ollama_running": any(s["kind"] == "ollama" for s in found_servers), "download": OLLAMA_DOWNLOAD,
            "suggest": {"model": name, "gb": gb, "why": why, "installed": name in have or f"{name}:latest" in have}}


def suggested(model: str) -> bool:
    """Only a model ContextMAX suggests is ever downloaded from the window."""
    return any(model == r[0] for r in RECOMMENDED)
