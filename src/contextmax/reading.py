"""How a model on this PC analyses the project: ContextMAX holds the procedure, the model reads.

In an editor, Claude finds a way in, opens the file, reads the whole passage, follows what it points to and
checks what it found. A model on this PC is not good at deciding all of that by itself, so ContextMAX does
it step by step, the same way every time, and gives the model only what models do well: reading one passage
and saying what it says.

  1. the ways in    ContextMAX's own search (values with their line, named numbers in the code, sections by
                    their heading, functions, passages) gives the files to read, every kind scored on one
                    scale and taking turns, so that no kind fills every place; where documents state a value
                    differently, one document of each value is read, so they are compared
  2. open           a real window of each file: the section around the cited line (from the heading above to
                    the next one), the whole function, the rows of a sheet; a PDF's page numbers with it
  3. read           the model reads one window at a time and answers in JSON: is it relevant, the exact words
                    it relies on with their line numbers, what the passage says, and what it points to
  4. check          every quote is looked up in the file at its line: a quote the file does not hold is left
                    out, and said
  5. look up        where the model found a way in relevant, ContextMAX looks up the rest of it in the files
                    itself: every document that states that value, every file that sets that named number
                    (LASER_CONTROL_LIMIT_0 … _46) and where each is used; each line is checked in its file
  6. follow         what a passage points to (a table, a requirement, another document, a function) is
                    found through the index and read the same way, a few at most
  7. answer         from the checked quotes and ContextMAX's own look-ups only, each cited. When the first
                    round of ways in gives nothing, a second round is read; nothing relevant read then means
                    "not found", said by ContextMAX itself, without asking the model to guess

A model that can see (Ollama says "vision") also gets the PDF page itself as a picture, so it reads formulas,
tables and figures the extracted text garbles, and picture files whose name the question says. Every call
runs at temperature 0 with a fixed seed. ContextMAX's own confidence comes from what was read and checked.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from contextmax import ask, citations, util
from contextmax.docs import search
from contextmax.docs.corpus import MARKDOWN_HEADING, NUMBERED_HEADING

WINDOW_LINES = 30            # lines on each side of the cited line, at most
WINDOW_CHARS = 5000          # what one window may hold: small models have small context windows
CODE_LINES = 120             # a function longer than this is read from its start
MAX_SOURCES = 6              # windows read in one round of ways in
MAX_ROUNDS = 2               # a second round when nothing read in the first says anything about the question
MAX_FOLLOW = 3               # windows read for what the passages point to
KINDS = ("value", "code value", "section", "function", "passage", "picture")     # the order of a tie
KEEP_SHARE = 0.5             # a kind is read when its best way in holds at least half of what the best one holds
LISTED = 40                  # lines of one look-up the answering model is given (the Ask page shows them all)
PICTURE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PICTURE_BYTES = 8_000_000
SEED = 7
READ_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "quotes": {"type": "array", "items": {"type": "object", "properties": {
            "line": {"type": "integer"}, "text": {"type": "string"}}, "required": ["line", "text"]}},
        "says": {"type": "string"},
        "follow": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["relevant", "quotes", "says", "follow"],
}
_SOFT = re.compile("[\u00ad\ufffe\x00-\x08\x0b-\x1f]")      # a PDF's marks for a broken word or a lost glyph
CODE_NAME = re.compile(r"[A-Za-z_]\w{3,}(?:::\w+)*")


# == 1. the ways in ==

def ways_in(proj, question: str, vision: bool = False) -> list[dict]:
    """The places to read, in the order they are read: MAX_SOURCES for the first round, as many for a second.

    Every kind of way in is found and scored on one scale (how much of the question it holds, a rare word more):
    named values, named numbers in the code, sections by their heading, functions, passages, and, for a model
    that can see, pictures. Then the kinds take turns, best first, so that no kind fills every place: a document
    value stated in fifty spreadsheets does not keep the code from being read. A kind that holds less than half
    of what the best way in holds is not read."""
    ix, ws = ask._index(proj), ask.words(question)
    if not ws:
        return []
    asked = ask.Asked(ix, ws)
    roots = {t["name"]: (t["root"], t.get("label", t["name"])) for t in proj.code_targets}
    room = MAX_SOURCES * MAX_ROUNDS            # no kind can have more places than this read
    # a question that names a part of the code ("the laser control's max current") is about that part: the
    # code of other parts and the values of other parts are left out (a name the question gives stays)
    part = ask.part_of(ix, ws)
    said_part = part.replace("_", " ").lower() if part else ""
    if part:
        asked.part = asked.held(ask._code_words(part))

    def in_part(group: dict) -> bool:
        return not part or group.get("named") or all(ask.module_of(x) == part for _, x in group["members"][:1])

    values = ask.value_groups(ix, asked)
    of_part = re.compile(rf"\b{re.escape(said_part)}\b") if said_part else None    # the encoder drive, not the encoder driver
    if of_part and any(of_part.search(g["label_norm"]) for g in values):
        values = [g for g in values if of_part.search(g["label_norm"])]
    groups = []
    for g in values[:room]:
        stating = len({r["doc_ref"] for r in g["rows"]})
        many = f" ({stating} documents state it)" if stating > 1 else ""
        g["lead"] = [_value_way(r, f"states {g['label']}{many}" if i == 0 else
                                f"states {g['label']} as {_as_written(r)}: the documents differ", g)
                     for i, r in enumerate(g["lead"])]
        g["rest"] = [_value_way(r, f"states {g['label']} too", g) for r in g["rest"]]
        groups.append(g)
        # what the index links this value to in the code: read, and looked up like any named number of the code
        linked, families = [], set()
        for c in ix["in_code"].get(g["label_norm"], []):
            k = c["code"]
            fam = ask.family_of(ix, k["target"], k["file"], k["name"]) if k["target"] in roots else None
            if fam is None or (k["target"], fam["name"]) in families or not in_part(fam):
                continue              # one way in per family: the 15 headers that define one name are one
            families.add((k["target"], fam["name"]))
            t, v = fam["members"][0]  # a definition in effect first
            n = len(fam["members"])
            linked.append({"kind": "code", "root": t["root"], "file": v["file"], "line": v["line"], "base": t["label"],
                           "why": f"the index links {g['label']} to {fam['name']} in the code"
                                  + (f" (defined {n} times)" if n > 1 else ""), "group": fam})
        if linked:
            groups.append({"kind": "code value", "score": g["score"], "lead": linked[:1], "rest": linked[1:]})
    for g in [g for g in ask.code_value_groups(ix, asked) if in_part(g)][:room]:
        t, v = g["members"][0]
        n = len(g["members"])
        g["lead"] = [{"kind": "code", "root": t["root"], "file": v["file"], "line": v["line"], "base": t["label"], "group": g,
                      "why": ("named in the question: " if g.get("named") else "") + f"sets {v['name']}"
                             + (f"; {n} files set {g['name']}" if n > 1 else "")}]
        g["rest"] = [{"kind": "document", "key": d["doc_ref"], "line": d.get("line_no"),
                      "why": f"the index links it to {c['code']['name']} in the code"}
                     for _, m in g["members"][:1] for c in ix["in_code_of"].get((t["name"], m["file"], m["name"]), [])
                     for d in c["documents"]]
        groups.append(g)
    for g in ask.section_groups(ix, asked)[:room]:
        line = g.get("line") or search.heading_line(ask._document_lines(ix, g["key"]), g["heading"])
        if line:
            g["lead"], g["rest"] = [{"kind": "document", "key": g["key"], "line": line, "why": f"its section {g['heading']}"}], []
            groups.append(g)
    for g in [g for g in ask.function_groups(ix, asked) if in_part(g)][:room]:
        t, f = g["members"][0]
        n = len(g["members"])
        g["lead"] = [{"kind": "code", "root": t["root"], "file": f["file"], "line": f["first_line"], "last": f.get("last_line"),
                      "base": t["label"], "why": ("named in the question: " if g.get("named") else "")
                      + f"defines {f.get('qualname') or f['name']}" + (f" ({g['initials']})" if g.get("initials") else "")
                      + (f"; {n} functions are named {g['name']}" if n > 1 else "")}]
        g["rest"] = []
        groups.append(g)
    for p in ask.find_passages(ix, ws, limit=room, per_doc=1):
        own = asked.held(ask._tokens(p["text"]))
        groups.append({"kind": "passage", "score": asked.score(own, asked.held(ask._tokens(ask._title_of(ix, p["key"])))),
                       "lead": [{"kind": "document", "key": p["key"], "line": p["line"],
                                 "last": p["line"] + ask.PASSAGE_LINES - 1, "why": "its text holds the question's words"}],
                       "rest": []})
    if vision:
        for e in pictures(proj, ws):
            groups.append({"kind": "picture", "score": asked.score(asked.held(ask._tokens(e["name"]))), "lead": [e], "rest": []})
    for g in groups:
        for e in g["lead"] + g["rest"]:
            if e.get("key"):       # one document, one reading: copies and versions share a title (or a text)
                e["text"] = _same_document(ix, e["key"])
    return _in_turns(groups, room)


def _value_way(r: dict, why: str, group: dict) -> dict:
    return {"kind": "document", "key": r["file_key"], "line": r.get("line_no"), "why": why, "group": group}


def _as_written(r: dict) -> str:
    return f"{r.get('value_shown')} {r.get('unit') or ''}".strip()


def _in_turns(groups: list[dict], room: int) -> list[dict]:
    """The ways in, kinds taking turns: the best of each kind, then the second of each, and so on; the kind of
    the best way in goes first. A group's first places (one per value where documents differ) come before the
    rest of any group. A place already taken (the section a value is stated in) gives that kind's turn to its
    next way in."""
    if not groups:
        return []
    best = max(g["score"] for g in groups)
    queues: dict[str, tuple[list, list]] = {}
    # what the question names exactly comes first, whatever its score; then the kinds by their best way in
    for g in sorted(groups, key=lambda g: (not g.get("named"), -g["score"], KINDS.index(g["kind"]))):
        if g.get("named") or g["score"] >= KEEP_SHARE * best:
            lead, rest = queues.setdefault(g["kind"], ([], []))
            lead += g["lead"]
            rest += g["rest"]
    lines = [lead + rest for lead, rest in queues.values()]
    out, taken = [], set()
    while any(lines) and len(out) < room:
        for q in lines:
            while q and _place(q[0]) in taken:
                q.pop(0)
            if q and len(out) < room:
                taken.add(_place(q[0]))
                out.append(q.pop(0))
    return out


def _distinct(entries: list[dict]) -> list[dict]:
    """One window per place: a second way into the same part of a file reads nothing new."""
    seen, out = set(), []
    for e in entries:
        if _place(e) not in seen:
            seen.add(_place(e))
            out.append(e)
    return out


def _place(e: dict) -> tuple:
    """Which file, and which part of it: two ways in that close together read one window, and two files with the
    same text (the same thesis in three folders) are one file."""
    where = e.get("path") if e["kind"] == "picture" else e.get("text") or e.get("key") or f"{e.get('root')}|{e.get('file')}"
    return where, (e.get("line") or 0) // (2 * WINDOW_LINES)


def pictures(proj, ws: list[str], limit: int = 2) -> list[dict]:
    """Picture files whose name holds a word of the question (four letters or more), for a model that can see."""
    roots = {f.name: f.path for f in proj.folders}
    wanted = [w for w in ws if len(w) >= 4]
    found = []
    for r in util.csv_rows(proj.catalogue_dir / "all-files.csv"):
        if (r.get("Ext") or "").lower() not in PICTURE_SUFFIXES or not roots.get(r.get("Folder")):
            continue
        name = (r.get("Name") or "").lower()
        hits = sum(1 for w in wanted if w in name)
        if hits:
            found.append((-hits, r["RelativePath"], {"kind": "picture", "path": str(Path(roots[r["Folder"]]) / r["RelativePath"]),
                                                     "name": r["Name"], "why": "its name holds the question's words"}))
    return [e for *_, e in sorted(found, key=lambda x: (x[0], x[1]))[:limit]]


# == 2. open ==

def _same_document(ix: dict, key: str) -> str:
    title = " ".join((ix["titles"].get(key) or "").lower().split())
    return f"title:{title}" if len(title) >= 12 else f"text:{(ix['rows'].get(key) or {}).get('text_sha256') or key}"


def _heading(line: str) -> bool:
    return bool(MARKDOWN_HEADING.match(line) or NUMBERED_HEADING.match(line))


def open_window(proj, entry: dict) -> dict | None:
    """A window of the source: numbered lines (with their page for a PDF), where it is, and how to open it."""
    ix = ask._index(proj)
    if entry["kind"] == "picture":
        try:
            data = Path(entry["path"]).read_bytes()
        except OSError:
            return None
        if len(data) > PICTURE_BYTES:
            return None
        return {"kind": "picture", "cite": f"picture · {entry['name']}", "lines": [], "images": [data],
                "path": entry["path"], "why": entry["why"]}
    if entry["kind"] == "code":
        try:
            lines = (Path(entry["root"]) / entry["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        line = max(1, min(entry.get("line") or 1, len(lines) or 1))
        last = entry.get("last") or 0
        first, end = (line, min(last, line + CODE_LINES - 1)) if last >= line else (max(1, line - 15), line + 15)
        end = min(end, len(lines))
        return _trimmed({"kind": "code", "cite": "", "first": first, "lines": lines[first - 1:end], "pages": None,
                         "root": entry["root"], "file": entry["file"], "base": entry["base"], "line": line,
                         "why": entry["why"], "images": []}, line)
    row = ix["rows"].get(entry["key"])
    if not row:
        return None
    lines = ask._document_lines(ix, entry["key"])
    if not lines:
        return None
    line = max(1, min(entry.get("line") or 1, len(lines)))
    last = max(line, min(entry.get("last") or line, len(lines)))      # a passage hit is read whole
    start = line
    while start > 1 and line - start < WINDOW_LINES and not _heading(lines[start - 1]):
        start -= 1
    end = last
    while end < len(lines) and end - last < WINDOW_LINES and not _heading(lines[end]):
        end += 1
    page_lines = row.get("page_lines")
    pages = [citations.page_of(page_lines, n) for n in range(start, end + 1)] if page_lines else None
    title = ask._title_of(ix, entry["key"])
    roots = {f.name: f.path for f in proj.folders}
    pdf = str(Path(roots[row["folder"]]) / row["relative_path"]) if row.get("ext") == ".pdf" and roots.get(row.get("folder")) else None
    return _trimmed({"kind": "document", "cite": citations.passage(title, ix["stages"].get(entry["key"]), start, end, page_lines),
                     "first": start, "lines": lines[start - 1:end], "pages": pages, "key": entry["key"], "line": line,
                     "text": _same_document(ix, entry["key"]),
                     "pdf": pdf, "why": entry["why"], "images": [], "title": title,
                     "stage": ix["stages"].get(entry["key"]), "page_lines": page_lines}, line)


def _trimmed(w: dict, line: int) -> dict:
    """At most WINDOW_CHARS, kept around the cited line."""
    while sum(len(x) + 8 for x in w["lines"]) > WINDOW_CHARS and len(w["lines"]) > 3:
        if line - w["first"] > w["first"] + len(w["lines"]) - 1 - line:
            w["lines"], w["first"] = w["lines"][1:], w["first"] + 1
            if w.get("pages"):
                w["pages"] = w["pages"][1:]
        else:
            w["lines"] = w["lines"][:-1]
            if w.get("pages"):
                w["pages"] = w["pages"][:-1]
    last = w["first"] + len(w["lines"]) - 1
    if w["kind"] == "document":
        w["cite"] = citations.passage(w["title"], w["stage"], w["first"], last, w["page_lines"])
    elif w["kind"] == "code":
        w["cite"] = citations.code(w["base"], w["file"], w["first"], last)
    return w


def numbered(w: dict) -> str:
    """The window as the model reads it: each line with its number, a mark where a PDF page begins."""
    out, page = [], None
    for i, text in enumerate(w["lines"]):
        p = w["pages"][i] if w.get("pages") else None
        if p and p != page:
            out.append(f"--- page {p} ---")
            page = p
        out.append(f"{w['first'] + i}: {text}")
    return "\n".join(out)


def page_pictures(w: dict) -> list[bytes]:
    """The PDF pages a window is on, as pictures (two at most), for a model that can see."""
    if not w.get("pdf") or not w.get("pages"):
        return []
    from contextmax.docs import ocr

    out = []
    for p in sorted({p for p in w["pages"] if p})[:2]:
        try:
            out.append(ocr.page_png(w["pdf"], p - 1))
        except Exception:  # noqa: BLE001 - no picture of this page: the text is still read
            continue
    return out


# == 3. read, and 4. check ==

def read(kind: str, base: str, model: str, proj_name: str, question: str, w: dict, vision: bool) -> dict:
    """What one window says about the question, as the model reads it."""
    pictures_ = (w["images"] or page_pictures(w)) if vision else []
    system = (f"You read one passage of a file of the project \"{proj_name}\" to help answer a question. Report only what "
              "this passage itself says about the question, nothing you know from elsewhere. Copy the exact words you "
              "rely on, each with the number of its line (lines start with their number). A passage that answers any "
              "part of the question, even one value of it, is relevant; say relevant: false only when it says nothing "
              "about the question. In follow, name what this passage points to for the answer (a "
              "table, a figure, a requirement, a section, another document, a function), if anything. A range is "
              "written 1~4. Never convert or reinterpret a number or a unit: copy them as written. Answer in JSON only.")
    if pictures_:
        system += (" A picture of the page is attached: read figures, tables and formulas from it, copy what you read "
                   "as printed, and give line 0 for what you read only in the picture.")
    user = (f"Question: {question}\n\nFile: {w['cite']}\nWhy ContextMAX opened it here: {w['why']}\n\n"
            + (numbered(w) if w["lines"] else "(a picture: see the attached image)"))
    try:
        if kind == "ollama":
            msg = {"role": "user", "content": user}
            if pictures_:
                msg["images"] = [base64.b64encode(p).decode("ascii") for p in pictures_]
            body = {"model": model, "messages": [{"role": "system", "content": system}, msg], "stream": False,
                    "format": READ_SCHEMA, "think": False, "options": {"temperature": 0, "seed": SEED, "num_ctx": 8192}}
            reply = _post(ask._on_this_pc(base) + "/api/chat", body, retry_without="think")
            text = (reply.get("message") or {}).get("content") or ""
        else:
            body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "stream": False, "temperature": 0, "seed": SEED, "response_format": {"type": "json_object"}}
            reply = _post(ask._on_this_pc(base) + "/v1/chat/completions", body, retry_without="response_format")
            text = ((reply.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except ask.AskError as exc:
        return {"relevant": False, "quotes": [], "says": "", "follow": [], "error": str(exc)}
    return parse(text) | {"saw_pictures": len(pictures_)}


def _post(url: str, body: dict, retry_without: str, timeout: float = 600) -> dict:
    for _ in range(2):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with ask._DIRECT.open(req, timeout=timeout) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if retry_without in body:
                body = {k: v for k, v in body.items() if k != retry_without}     # a model or server without it
                continue
            raise ask.AskError(f"the model server said: {detail or exc}") from exc
        except (OSError, ValueError) as exc:
            raise ask.AskError(f"no answer from the model server: {exc}") from exc
        if isinstance(d, dict) and d.get("error"):
            raise ask.AskError(str(d["error"]))
        return d
    raise ask.AskError("the model server refused the question")


def parse(text: str) -> dict:
    """The model's reading, or an empty one that says it could not be read."""
    text = re.sub(r"<think>[\s\S]*?(</think>|$)", "", text or "")
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        d = None
    if not isinstance(d, dict):
        return {"relevant": False, "quotes": [], "says": "", "follow": [], "unparsed": True}
    quotes = [q for q in d.get("quotes") or [] if isinstance(q, dict) and str(q.get("text") or "").strip()]
    return {"relevant": bool(d.get("relevant")), "says": str(d.get("says") or "")[:600],
            "quotes": [{"line": _int(q.get("line")), "text": str(q["text"])[:400]} for q in quotes[:8]],
            "follow": [str(x)[:120] for x in (d.get("follow") or []) if str(x).strip()][:3]}


def _int(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _norm(s: str) -> str:
    return " ".join(_SOFT.sub("", s).split()).lower().strip(" .,;:\"'`")


def check(w: dict, reading: dict) -> dict:
    """Each quote looked up in the file: held at its line (or found elsewhere in the window, and its line set
    right), read only in a picture, or not in the file at all (left out)."""
    held, pictured, missing = [], [], []
    lines = w["lines"]
    for q in reading["quotes"]:
        words = _norm(q["text"])
        if len(words) < 2:
            continue
        if not lines or q["line"] == 0 and (w["images"] or reading.get("saw_pictures")):
            pictured.append(q)
            continue
        i = q["line"] - w["first"]
        near = _norm(" ".join(lines[max(0, i - 1):i + 2])) if 0 <= i < len(lines) else ""
        if near and words in near:
            held.append({"line": q["line"], "text": q["text"]})
            continue
        at = next((k for k, text in enumerate(lines) if words in _norm(text)), None)
        if at is None and len(words) > 20:
            joined = [_norm(" ".join(lines[k:k + 3])) for k in range(len(lines))]
            at = next((k for k, text in enumerate(joined) if words in text), None)
        if at is not None:
            held.append({"line": w["first"] + at, "text": q["text"]})
        else:
            missing.append(q)
    return {"held": held, "pictured": pictured, "missing": missing}


# == 5. look up ==

def look_up(proj, group: dict) -> dict | None:
    """The rest of a way in the model found relevant, looked up by ContextMAX in the files itself: every file
    that sets that named number and where each one is used, or every document that states that value. Each line
    is read in its file, and one that does not show what the index says (a file changed since the build) is
    left out."""
    if group.get("kind") == "code value" and group.get("members"):
        return _code_look_up(proj, group)
    if group.get("kind") == "value":
        return _value_look_up(proj, group)
    return None


def _code_look_up(proj, group: dict) -> dict | None:
    ix = ask._index(proj)
    members = group["members"]
    targets = {t["name"]: t for t, _ in members}
    texts: dict[tuple, list[str]] = {}

    def lines_of(target: str, rel: str) -> list[str]:
        if (target, rel) not in texts:
            try:
                texts[target, rel] = (Path(targets[target]["root"]) / rel).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                texts[target, rel] = []
        return texts[target, rel]

    # where each is used: recorded by the build over the whole code base, each use with the definition in effect
    # there; an index from before 0.4.1 has none, so the files of its module are searched now
    recorded = all("used_in" in v for _, v in members)
    scanned = {} if recorded else _uses_in_module(ix, members, lines_of)
    quotes, in_effect = [], []
    for t, v in members:
        lines = lines_of(t["name"], v["file"])
        text = lines[v["line"] - 1] if 0 < v["line"] <= len(lines) else ""
        if v["name"] not in text:
            continue
        uses = v["used_in"] if recorded else scanned.get(v["name"], [])
        mine = [u for u in uses if u["file"] == v["file"]]
        others = sorted({u["file"] for u in uses if u["file"] != v["file"]})
        note = ", ".join((f"{u['in']} (line {u['line']})" if u["in"] else f"line {u['line']}") for u in mine)
        note = (f"used in {note}" if mine else "not used in its own file") + \
            (f"; used in {len(others)} other file{'s' if len(others) > 1 else ''}: "
             + ", ".join(f"{Path(f).name} ({sum(1 for u in uses if u['file'] == f)}×)" for f in others[:6])
             + (" …" if len(others) > 6 else "") if others else "")
        if v.get("included_by_count") is not None:
            note += f"; its header is included by {v['included_by_count']} file{'' if v['included_by_count'] == 1 else 's'}"
            if v["included_by_count"]:
                in_effect.append(v)
        quotes.append({"where": f"{v['file']}:{v['line']}", "line": v["line"], "text": text.strip()[:300], "checked": True,
                       "note": note, "used": len(uses), "root": t["root"], "file": v["file"]})
    if not quotes:
        return None
    t, v = members[0]
    folders = sorted({str(Path(x["file"]).parent).replace("\\", "/") for _, x in members})
    files = len({x["file"] for _, x in members})
    where = f"{t['label']} · {folders[0]}" + (f" and {len(folders) - 1} other folder{'s' if len(folders) > 2 else ''}" if len(folders) > 1 else "")
    found = {x["file"] for x in quotes}
    said = [x for _, x in members if x["file"] in found]
    used = sum(q["used"] for q in quotes)
    headers = [x for x in said if x.get("included_by_count") is not None]
    effect = ""
    if len(headers) > 1:
        effect = (f"; {len(in_effect)} of its {len(headers)} headers are included anywhere"
                  + (": " + ", ".join(f"{Path(x['file']).name} = {x['value']}" for x in in_effect[:4]) if in_effect else ""))
    return {"window": {"kind": "code", "cite": f"{where} · {group['name']} in {files} file{'s' if files > 1 else ''}",
                       "root": t["root"], "file": v["file"], "line": v["line"], "first": v["line"], "last": v["line"]},
            "says": (f"{group['name']} is set {_times(len(quotes))}, in {len(found)} file{'s' if len(found) > 1 else ''}, "
                     + _spread([x["value"] for x in said])
                     + (f"; used {_times(used)} in the code" if recorded else
                        f"; named {_times(used)} elsewhere in the files of its module")
                     + effect + "; each line was found in its file"),
            "quotes": quotes}


def _uses_in_module(ix: dict, members: list, lines_of) -> dict[str, list[dict]]:
    """For an index from before 0.4.1: every line of the files of the members' module that names them, and the
    function that line is in."""
    names = sorted({v["name"] for _, v in members})
    named = re.compile(r"(?<![\w$])(" + "|".join(map(re.escape, names)) + r")(?![\w$])")
    defined = {(t["name"], v["file"], v["line"]) for t, v in members}
    uses: dict[str, list[dict]] = {}
    for tn, rel in sorted({(t["name"], f) for t, v in members
                           for f in ix["files_in"].get((t["name"], ask.module_of(v)), []) + [v["file"]]}):
        functions = ix["functions_in"].get((tn, rel), [])
        for n, text in enumerate(lines_of(tn, rel), 1):
            if (tn, rel, n) in defined:
                continue
            for name in sorted({m.group(1) for m in named.finditer(text)}):
                fn = next((f for f in functions if f["first_line"] <= n <= (f.get("last_line") or f["first_line"])), None)
                uses.setdefault(name, []).append({"file": rel, "line": n, "in": (fn.get("qualname") or fn["name"]) if fn else None})
    return uses


def _documents(n: int) -> str:
    return f"{n} document{'s' if n != 1 else ''}"


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def _spread(values: list[str]) -> str:
    """What a family of numbers holds: one value, or how many different ones and from which to which."""
    distinct = sorted(set(values), key=lambda x: (_number(x) is None, _number(x) or 0, x))
    if len(distinct) == 1:
        return f"always {distinct[0]}"
    low, high = distinct[0], distinct[-1]
    span = f", from {low} to {high}" if _number(low) is not None and _number(high) is not None else ""
    return f"with {len(distinct)} different values{span}"


def _number(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _value_look_up(proj, group: dict) -> dict | None:
    from contextmax.docs.params import RANGE_MARK

    ix = ask._index(proj)
    quotes, by_value = [], {}
    for r in group["rows"]:
        lines = ask._document_lines(ix, r["file_key"])
        n = r.get("line_no")
        text = lines[n - 1] if n and 0 < n <= len(lines) else ""
        shown = f"!{r['cell']}" in text if r.get("cell") else \
            bool(r.get("value_as_written")) and r["value_as_written"].split(RANGE_MARK)[0] in text
        if not shown:
            continue
        title = ask._title_of(ix, r["file_key"])
        quotes.append({"where": citations.value(r, title), "line": n, "text": text.strip()[:300], "checked": True,
                       "key": r["file_key"]})
        by_value.setdefault(_as_written(r), []).append(title)
    if not quotes:
        return None
    r = group["rows"][0]
    counted = sorted(by_value.items(), key=lambda x: (-len(x[1]), x[0]))
    return {"window": {"kind": "document", "cite": f"{group['label']}: every document that states it",
                       "key": r["file_key"], "line": r.get("line_no"), "first": r.get("line_no"), "last": r.get("line_no")},
            "says": (f"{group['label']} is stated in {_documents(len({q['key'] for q in quotes}))}, "
                     + (f"always {counted[0][0]}" if len(counted) == 1 else
                        f"with {len(counted)} different values (the documents differ): "
                        + "; ".join(f"{v} in {len(set(ts))}" for v, ts in counted)
                        + (f"; {_documents(both)} give{'s' if both == 1 else ''} more than one of them" if (both := sum(
                            1 for t in {t for _, ts in counted for t in ts} if sum(t in ts for _, ts in counted) > 1)) else ""))
                     + "; each line was found in its document"),
            "quotes": quotes}


# == 6. follow ==

def follow(proj, w: dict, items: list[str], read_already: set) -> list[dict]:
    """Where what a passage points to is: a function or a named number of that name in the code first, then the
    same file (a table, a section, a figure it names), then a document of that title or number, then the best
    passage for those words."""
    ix = ask._index(proj)
    out = []
    for item in items:
        words_ = _norm(item)
        if len(words_) < 3 or len(words_.split()) > 8:
            continue                     # a name or a short phrase ("Table 4.2", "REQ-012"), not a sentence
        why = f"the passage points to {item}"
        # the pointer is a name, or holds one ("line 4: #define LASER_CONTROL_LIMIT_0 528", "calls pid_step()")
        names = [item.strip().strip("`'\"()")] + [x for x in CODE_NAME.findall(item) if "_" in x or "::" in x
                                                 or re.search(r"[a-z][A-Z]", x) or item.count(x + "(")]
        fn = cv = None
        for name in dict.fromkeys(names):
            fn = next(((t, f) for t, f in ix["functions"] if name in (f["name"], f.get("qualname"))), None)
            cv = None if fn else next(((t, v) for t, v in ix["code_values"] if v["name"] == name), None)
            if fn or cv:
                break
        if fn:
            t, f = fn
            out.append({"kind": "code", "root": t["root"], "file": f["file"], "line": f["first_line"],
                        "last": f.get("last_line"), "base": t["label"], "why": why})
            continue
        if cv:
            t, v = cv
            out.append({"kind": "code", "root": t["root"], "file": v["file"], "line": v["line"], "base": t["label"], "why": why})
            continue
        if w["kind"] == "document":
            lines = ask._document_lines(ix, w["key"])
            last = w["first"] + len(w["lines"]) - 1
            at = next((n for n, text in enumerate(lines, 1) if words_ in _norm(text) and not w["first"] <= n <= last), None)
            if at:
                out.append({"kind": "document", "key": w["key"], "line": at, "why": why})
                continue
        doc = next((k for k, title in sorted(ix["titles"].items()) if words_ in _norm(title)
                    or words_ in _norm((ix["rows"].get(k) or {}).get("doc_numbers") or "")), None)
        if doc:
            out.append({"kind": "document", "key": doc, "line": 1, "why": why})
            continue
        best = ask.find_passages(ix, ask.words(item), limit=1, per_doc=1)
        if best:
            out.append({"kind": "document", "key": best[0]["key"], "line": best[0]["line"] + 4, "why": why})
    for e in out:
        if e.get("key"):
            e["text"] = _same_document(ix, e["key"])
    return [e for e in _distinct(out) if _place(e) not in read_already]


# == 7. answer ==

def analyse(proj, kind: str, base: str, model: str, question: str, said=None):
    """The answer in pieces; said(event) reports every step: what is read, what it gave, what is followed and
    what ContextMAX looked up itself."""
    said = said or (lambda event: None)
    vision = sees(kind, base, model)
    entries = ways_in(proj, question, vision)
    if not entries:
        said({"step": "none"})
        yield ("ContextMAX found nothing in the index for these words, so there was nothing to read. Try the words "
               "the documents or the code would use.\n\nConfidence: Not found")
        return
    findings, read_list, done, answered = [], [], set(), []
    followed = 0
    for start in range(0, len(entries), MAX_SOURCES):
        if findings:
            break
        if start:
            said({"step": "more", "why": f"nothing of the {len(read_list)} passages read says anything about the "
                                        "question, so ContextMAX opens the next ways in"})
        queue = [(e, 0) for e in entries[start:start + MAX_SOURCES]]
        while queue:
            entry, hop = queue.pop(0)
            if _place(entry) in done:
                continue
            done.add(_place(entry))
            w = open_window(proj, entry)
            if w is None:
                continue
            said({"step": "read", "window": _public(w), "why": entry["why"], "hop": hop})
            reading = read(kind, base, model, proj.name, question, w, vision)
            got = check(w, reading)
            relevant = reading["relevant"] and bool(got["held"] or got["pictured"])
            said({"step": "read done", "window": _public(w), "relevant": relevant, "held": len(got["held"]),
                  "pictured": len(got["pictured"]), "missing": len(got["missing"]), "says": reading["says"] if relevant else "",
                  "saw_pictures": reading.get("saw_pictures", 0),
                  "error": reading.get("error") or ("the model's reading could not be understood" if reading.get("unparsed") else "")})
            read_list.append(w["cite"])
            if relevant:
                findings.append({"window": w, "held": got["held"], "pictured": got["pictured"], "says": reading["says"],
                                 "missing": got["missing"]})
                if entry.get("group") is not None and not any(entry["group"] is g for g in answered):
                    answered.append(entry["group"])
            if hop == 0 and followed < MAX_FOLLOW and reading["follow"]:
                for nxt in follow(proj, w, reading["follow"], done)[:MAX_FOLLOW - followed]:
                    followed += 1
                    queue.append((nxt, 1))
    looked = [x for x in (look_up(proj, g) for g in answered) if x]
    for x in looked:
        said({"step": "looked up", "window": x["window"], "says": x["says"], "count": len(x["quotes"])})
    level, why = confidence(proj, findings, question)
    said({"step": "confidence", "level": level, "why": why})
    said({"step": "sources", "sources": [
        {"n": n, "window": _public(f["window"]), "says": f["says"],
         "quotes": [{"line": q["line"], "text": q["text"], "checked": True} for q in f["held"]]
         + [{"line": 0, "text": q["text"], "checked": False} for q in f["pictured"]]}
        for n, f in enumerate(findings, 1)] + [
        {"n": n, "window": x["window"], "says": x["says"], "looked_up": True, "quotes": x["quotes"]}
        for n, x in enumerate(looked, len(findings) + 1)]})
    if not findings:
        yield ("Not found. ContextMAX had the model read " + "; ".join(read_list) + ". None of these passages says "
               "anything about the question.\n\nConfidence: Not found")
        return
    yield from ask.stream(kind, base, model, answer_messages(proj, question, findings, looked))


def answer_messages(proj, question: str, findings: list[dict], looked: list[dict] = ()) -> list[dict]:
    blocks = []
    for n, f in enumerate(findings, 1):
        quotes = [f"line {q['line']}: \"{q['text']}\"" for q in f["held"]] + \
                 [f"in the picture: \"{q['text']}\"" for q in f["pictured"]]
        blocks.append(f"[{n}] {f['window']['cite']}\nwhat the passage says: {f['says']}\nits exact words:\n" + "\n".join(quotes))
    for n, x in enumerate(looked, len(findings) + 1):
        rows = [f"{q['where']}: \"{q['text']}\""
                + (f" ({q['note']})" if q.get("note") and i < 5 else f" (used {q['used']} times)" if q.get("note") else "")
                for i, q in enumerate(x["quotes"][:LISTED])]
        more = len(x["quotes"]) - LISTED
        blocks.append(f"[{n}] {x['window']['cite']}\nContextMAX looked this up in the files itself: {x['says']}\n"
                      + "\n".join(rows) + (f"\n… and {more} more of the same kind" if more > 0 else ""))
    system = (f"You answer a question about the project \"{proj.name}\". The passages below were read from the "
              "project's documents and code, and every quote was checked against the file. Some sources are "
              "ContextMAX's own look-ups: every document that states a value, or every file that sets a named number "
              "and where it is used, each line found in its file; use them for the whole picture (how many, which "
              "values, where) and cite them the same way. Answer only from those quotes; cite each statement with its "
              "number, like [2]; a number you state must be in the quote you cite for it. When passages disagree, say "
              "so and quote both. A range is written 1~4. Never convert or "
              "reinterpret a number or a unit: copy them as the quotes write them. Do not add anything the "
              "quotes do not say. Answer in the language of the question, briefly. End with one last line: "
              "\"Confidence: High\", \"Confidence: Medium\" or \"Confidence: Low\" and the reason in a few words (High: "
              "the quotes state the answer directly and agree; Medium: in part, indirectly, or one source only; Low: "
              "they disagree or barely touch the question).")
    user = (f"Question: {question}\n\nWhat was read ({len(blocks)} source{'s' if len(blocks) > 1 else ''}: cite only "
            + ", ".join(f"[{n}]" for n in range(1, len(blocks) + 1)) + "):\n\n" + "\n\n".join(blocks))
    if looked:
        user += ("\n\nAnswer every part of the question. Where ContextMAX's look-up shows one name set in many files or "
                 "stated in many documents, say so: how many, which values (all the same, or how they differ), and "
                 "where they are used, citing the look-up.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def confidence(proj, findings: list[dict], question: str) -> tuple[str, str]:
    """ContextMAX's own confidence, from what was read and checked, not from what the model says of itself."""
    if not findings:
        return "Not found", "no passage read says anything about the question"
    held = sum(len(f["held"]) for f in findings)
    pictured = sum(len(f["pictured"]) for f in findings)
    missing = sum(len(f["missing"]) for f in findings)
    files = len({f["window"].get("text") or f["window"].get("key") or f["window"].get("file") or f["window"].get("path")
                 for f in findings if f["held"]})
    conflicts = {c["label_norm"] for c in util.load_jsonl(proj.documents_dir / "value-conflicts.jsonl")}
    asked = " " + " ".join(ask.words(question)) + " "
    disputed = sorted(lab for lab in conflicts if f" {lab} " in asked)
    if held == 0:
        return ("Medium", "read only in the picture of a page, which cannot be checked against the text") if pictured \
            else ("Low", "no quote could be found in the files")
    if missing > held:
        return "Low", f"{missing} of the model's quotes are not in the files"
    if disputed:
        return "Medium", "the documents give " + ", ".join(disputed[:2]) + " more than one value"
    if missing:
        return "Medium", f"{held} quote{'s' if held > 1 else ''} found in the files, {missing} not"
    return "High", (f"{held} quote{'s' if held > 1 else ''} found in {files} document{'s' if files > 1 else ''}; "
                    "nothing read contradicts it")


def sees(kind: str, base: str, model: str) -> bool:
    """Ollama says which of its models can see pictures."""
    return kind == "ollama" and "vision" in ask.capabilities(base, model)


def _public(w: dict) -> dict:
    """What the window page needs of a window: where it is and how to open it."""
    return {k: w.get(k) for k in ("kind", "cite", "key", "line", "root", "file", "path", "first")} | \
        {"last": w["first"] + len(w["lines"]) - 1 if w.get("lines") else None}
