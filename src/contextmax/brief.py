"""contextmax brief <project> "<question>": the ways into a question in one call, for an AI or a person.

An assistant that searches a project by itself spends a turn on every grep and every file it opens. The
brief gives in one answer what those turns would find, from the index and checked in the files:

  ways in    the places to read first, of every kind (named values, named numbers in the code, sections by
             their heading, functions, passages), ranked on one scale with the kinds taking turns; each with
             the line it points at, quoted from the file
  look-ups   for the families and values among them: every file that sets that named number (its value and
             where it is used), every document that states that value (and whether they agree)
  next       the lookups that go deeper

It is the same procedure that guides a model on this PC (reading.py), without the model: nothing is judged,
everything is cited. The index is the way in; the brief says where to read, the files say what is true.
"""
from __future__ import annotations

from pathlib import Path

from contextmax import ask, citations, reading, util

LINES_SHOWN = 6           # lines of one look-up in the text (all of them in --json)
NOTE_CHARS = 170


def brief(proj, question: str) -> dict:
    ix = ask._index(proj)
    ws = ask.words(question)
    entries = reading.ways_in(proj, question)
    ways, groups, seen = [], [], set()
    for e in entries:
        ways.append(_way(proj, ix, e, ws))
        g = e.get("group")
        if g is not None and id(g) not in seen:
            seen.add(id(g))
            groups.append(g)
    lookups = [x for x in (reading.look_up(proj, g) for g in groups) if x]
    m = util.load_json(proj.workspace / "buildinfo.json", default={}) or {}
    comp = m.get("completeness") or {}
    part = ask.part_of(ix, ws)
    return {"project": proj.slug, "question": question, "words": ws,
            "built": (m.get("built_utc") or "never")[:10], "confidence": comp.get("confidence"),
            "confidence_reason": comp.get("confidence_reason"), "named": _named(proj, ix, ws),
            "part": _part(proj, ix, part) if part else None, "ways_in": ways, "lookups": lookups}


def _named(proj, ix: dict, ws: list[str]) -> list[dict]:
    """What the question names exactly: each function with its callers (and the line of each call) and how far a
    change reaches; each named number with its value and every use; and every document line that names it."""
    from contextmax import query

    out, seen = [], set()
    by_target: dict[str, list[dict]] = {}
    for t, f in ix["functions"]:
        by_target.setdefault(t["name"], []).append(f)
    for hit in ask.named_in(ix, ws)[:12]:
        t, x = hit["target"], hit["item"]
        name = x.get("qualname") or x["name"]
        if hit["kind"] == "function":
            funcs = by_target[t["name"]]
            callers = []
            for c in x.get("caller_ids") or []:
                f = funcs[c]
                lines = _code_lines(t["root"], f["file"])
                at = next((n for n in range(f["first_line"], (f.get("last_line") or f["first_line"]) + 1)
                           if 0 < n <= len(lines) and x["name"] in lines[n - 1]), f["first_line"])
                callers.append({"name": f.get("qualname") or f["name"], "cite": f"{f['file']}:{at}", "module": f["module"]})
            reach = query._impact(funcs, x["id"], 0, t)
            item = {"kind": "function", "name": name, "cite": citations.code(t["label"], x["file"], x["first_line"], x.get("last_line")),
                    "text": _quoted(_code_lines(t["root"], x["file"]), x["first_line"]), "callers": callers,
                    "calls": sorted(set(x.get("calls") or [])),
                    "reach": {k: reach[k] for k in ("product_functions", "tests", "direct_callers", "caveat")}
                    | {"modules_count": len(reach["modules"])}}
        else:
            item = {"kind": "named number", "name": x["name"], "cite": citations.code(t["label"], x["file"], x["line"]),
                    "text": _quoted(_code_lines(t["root"], x["file"]), x["line"]), "value": x["value"],
                    "unit": x.get("unit") or "", "uses": x.get("used_in") or [],
                    "included_by_count": x.get("included_by_count")}
        out.append(item)
        seen.add(name.lower())
    for item in out:              # the documents that name it, every line (a name is found whatever its case)
        if item["name"].lower() in seen:
            item["documents"] = _documents_naming(proj, item["name"])
            seen.discard(item["name"].lower())
    return out


def _documents_naming(proj, name: str, per_document: int = 6) -> list[dict]:
    from contextmax import query

    found = []
    for h in query.text_hits(proj, name, limit=40):
        found.append({"cite": h["cite"].rsplit(" · line", 1)[0].rsplit(" · page", 1)[0], "key": h["key"],
                      "lines": [ln for ln in h.get("lines", [{"line": h["line"], "says": h["says"]}])
                                if name.lower() in ln["says"].lower()][:per_document]})
    return [d for d in found if d["lines"]]


def _part(proj, ix: dict, part: str) -> dict:
    """The part of the code the question names: every named number of it (each family once, the definition in
    effect, the uses), and every value the documents give under that part's name, with whether they agree."""
    import sqlite3

    fams: dict[str, list] = {}
    for t, v in ix["code_values"]:
        if ask.module_of(v) == part:
            fams.setdefault(ask._family(v["name"]), []).append((t, v))
    numbers = []
    for _family, members in sorted(fams.items()):
        members.sort(key=ask._member_order)
        vs = [v for _, v in members]
        in_effect = [v for v in vs if v.get("included_by_count")]
        headers = [v for v in vs if v.get("included_by_count") is not None]
        numbers.append({"name": ask._shown({v["name"] for v in vs}, vs[0]["name"]), "count": len(vs),
                        "values": reading._spread([v["value"] for v in vs]), "unit": vs[0].get("unit") or "",
                        "uses": sum(v.get("uses_count") or 0 for v in vs),
                        "first": f"{vs[0]['file']}:{vs[0]['line']} = {vs[0]['value']}",
                        "in_effect": [f"{v['file']}:{v['line']} = {v['value']} (included by {v['included_by_count']})"
                                      for v in in_effect][:3] if len(headers) > 1 else []})
    said = part.replace("_", " ").lower()
    stated: dict[str, dict] = {}
    db = proj.documents_dir / "params.sqlite"
    if db.exists():
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        try:
            for label, shown, unit, docs in con.execute(
                    "SELECT pl.label_norm, max(e.value_shown), e.unit_norm, count(DISTINCT s.doc_ref) FROM entries e "
                    "JOIN places pl ON pl.id = e.place JOIN sources s ON s.id = pl.source WHERE pl.label_norm LIKE ? "
                    "AND e.origin <> 'formula_constant' GROUP BY pl.label_norm, e.value_norm, e.unit_norm",
                    (f"{said} %",)):
                stated.setdefault(label, {"name": label, "values": []})["values"].append(
                    {"value": f"{shown} {unit}".strip(), "documents": docs})
        finally:
            con.close()
    values = sorted(stated.values(), key=lambda s: (len(s["values"]) == 1, s["name"]))
    for s in values:
        s["values"].sort(key=lambda v: -v["documents"])
    return {"module": part, "named_numbers": numbers, "document_values": values}


def _way(proj, ix: dict, e: dict, ws: list[str]) -> dict:
    """One way in, with the line it points at: a passage's line that holds most of the question's words."""
    if e["kind"] == "picture":
        return {"kind": "picture", "cite": e["name"], "path": e["path"], "why": e["why"]}
    if e["kind"] == "code":
        lines = _code_lines(e["root"], e["file"])
        line = e.get("line") or 1
        return {"kind": "code", "cite": citations.code(e["base"], e["file"], line, e.get("last")),
                "path": str(Path(e["root"]) / e["file"]), "line": line,
                "text": _quoted(lines, line), "why": e["why"]}
    lines = ask._document_lines(ix, e["key"])
    line = e.get("line") or 1
    if e.get("last"):                                     # a passage: the line of it that says most
        span = range(line, min(e["last"], len(lines)) + 1)
        line = max(span, key=lambda n: (sum(w in lines[n - 1].lower() for w in ws), -n), default=line)
    row = ix["rows"].get(e["key"]) or {}
    title = ask._title_of(ix, e["key"])
    return {"kind": "document", "key": e["key"], "line": line,
            "cite": citations.passage(title, ix["stages"].get(e["key"]), line, line, row.get("page_lines")),
            "text_file": str(ix["documents_dir"] / row["cached_text"]) if row.get("cached_text") else None,
            "text": _quoted(lines, line), "why": e["why"]}


def _code_lines(root: str, rel: str) -> list[str]:
    try:
        return (Path(root) / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _quoted(lines: list[str], line: int) -> str:
    return " ".join(lines[line - 1].split())[:220] if 0 < line <= len(lines) else ""


def render(b: dict) -> str:
    """The brief as plain text: short lines, every place cited, the way an AI reads it best."""
    out = [f"ContextMAX brief · {b['project']} · built {b['built']} · index confidence {b.get('confidence')}"
           + (f" ({b['confidence_reason']})" if b.get("confidence_reason") else ""),
           f"question words: {', '.join(b['words']) or '(none)'}", ""]
    for n in b.get("named") or []:
        out.append(f"NAMED IN THE QUESTION: {n['name']} ({n['kind']}) · {n['cite']}")
        if n.get("text"):
            out.append(f"   > {n['text']}")
        if n["kind"] == "function":
            c = n["callers"]
            out.append(f"   called by {len(c)}" + (": " + ", ".join(f"{x['name']} ({x['cite']})" for x in c[:12])
                                                  + (", …" if len(c) > 12 else "") if c else ": no function the map can see"))
            r = n["reach"]
            out.append(f"   a change reaches {r['product_functions']:,} product functions in {r['modules_count']} modules"
                       f" and {r['tests']} tests ({r['caveat']})")
        else:
            uses = n["uses"]
            out.append(f"   = {n['value']}" + (f" {n['unit']}" if n["unit"] else " (no unit)")
                       + (f"; its header is included by {n['included_by_count']} files" if n.get("included_by_count") is not None else "")
                       + f"; used {len(uses)} times" + (": " + ", ".join(f"{u['in'] or '(top level)'} ({u['file'].rsplit('/', 1)[-1]}:{u['line']})"
                                                                     for u in uses[:8]) + (", …" if len(uses) > 8 else "") if uses else ""))
        docs = n.get("documents") or []
        out.append(f"   named in {len(docs)} document{'s' if len(docs) != 1 else ''}" + (":" if docs else " (searched in every document's text)"))
        for d in docs[:10]:
            out.append(f"   - {d['cite']}: " + "; ".join(f"line {ln['line']}" for ln in d["lines"]))
            out.append(f"       > {d['lines'][0]['says']}")
        out.append("")
    p = b.get("part")
    if p:
        out.append(f"THE PART THE QUESTION NAMES: {p['module']}")
        if p["named_numbers"]:
            out.append("   its named numbers in the code:")
            for x in p["named_numbers"]:
                out.append(f"   - {x['name']}: {x['count']} definition{'s' if x['count'] > 1 else ''}, {x['values']}"
                           + (f" {x['unit']}" if x["unit"] else " (no unit)") + f", used {x['uses']} times; e.g. {x['first']}"
                           + (f"; in effect: {'; '.join(x['in_effect'])}" if x["in_effect"] else ""))
        if p["document_values"]:
            out.append(f"   the values its documents state (names that start with '{p['module'].replace('_', ' ')}'):")
            for s in p["document_values"][:30]:
                out.append(f"   - {s['name']}: " + "; ".join(f"{v['value']} in {v['documents']} document{'s' if v['documents'] != 1 else ''}"
                                                       for v in s["values"]) + ("   <- the documents differ" if len(s["values"]) > 1 else ""))
        out.append("")
    if not b["ways_in"]:
        out.append("Nothing in the index holds these words. Try the words the documents or the code would use, "
                   "or search the text: find doc \"<words>\".")
        return "\n".join(out)
    out.append("WAYS IN (read these first; the line each points at is quoted)")
    for n, w in enumerate(b["ways_in"], 1):
        out.append(f"{n}. {w['cite']}  [{w['why']}]")
        if w.get("text"):
            out.append(f"   > {w['text']}")
    for x in b["lookups"]:
        out += ["", f"LOOKED UP: {x['window']['cite']}", f"   {x['says']}"]
        for q in x["quotes"][:LINES_SHOWN]:
            out.append(f"   {q['where']}: {q['text']}")
            if q.get("note"):
                note = q["note"] if len(q["note"]) <= NOTE_CHARS else q["note"][:NOTE_CHARS].rsplit(",", 1)[0] + ", …"
                out.append(f"      {note}")
        more = len(x["quotes"]) - LINES_SHOWN
        if more > 0:
            out.append(f"   … and {more} more of the same kind (all of them: --json, or find symbol / params --name)")
    out += ["", "NEXT: open the lines above and read the whole passage or function before you rely on it. Deeper:",
            f"  find {b['project']} symbol|callers|impact <name>   (functions and named numbers, with their uses)",
            f"  find {b['project']} doc \"<words>\"               (titles, and the documents' text with the line)",
            f"  params {b['project']} --name \"<name>\" --compare   (every document stating a value: do they agree?)"]
    return "\n".join(out)
