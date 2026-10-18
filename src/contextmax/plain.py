"""The lookups as plain text: what `contextmax find` and `contextmax params` print unless asked for --json.

Short lines, every place cited as file:line or document · line, long lists cut with a count of the rest. An
assistant reads this directly, with no parser to write and no turn spent on one; --json gives everything.
"""
from __future__ import annotations

SHOWN = 25


def _more(items: list, shown: int = SHOWN) -> list[str]:
    return [f"  … and {len(items) - shown} more (--json for all)"] if len(items) > shown else []


def _uses(v: dict, shown: int = 8) -> str:
    uses = v.get("used_in") or []
    if not uses:
        return "used nowhere in the code (outside comments)"
    named = [f"{u['in'] or '(top level)'} ({u['file'].rsplit('/', 1)[-1]}:{u['line']})" for u in uses[:shown]]
    return f"used {len(uses)} times: " + ", ".join(named) + (", …" if len(uses) > shown else "")


def _value_line(v: dict) -> list[str]:
    head = f"{v['name']} = {v['value']}" + (f" {v['unit']}" if v.get("unit") else " (no unit)")
    extra = []
    if v.get("defined_count", 1) > 1:
        extra.append(f"one of {v['defined_count']} definitions of this name")
    if v.get("included_by_count") is not None:
        extra.append(f"its header is included by {v['included_by_count']} files")
    return [f"- {head}  [{v['kind']}, {v['target']} · {v['cite']}]" + (" · " + "; ".join(extra) if extra else ""),
            f"    {_uses(v)}"]


def _fn_line(h: dict) -> str:
    where = h.get("cite") or f"{h.get('file')}:{h.get('line')}"
    counts = f" · callers {h['callers']}, calls {h['calls']}" if "callers" in h else ""
    return f"- {h['name']}  [{h.get('kind') or 'function'}, {h.get('target', '')} · {where}]{counts}" + \
        (f" · {h['doc'][:120]}" if h.get("doc") else "")


def find(out: dict, what: str) -> str:
    lines = [f"find {what} {out.get('query')!r}"]
    if what == "doc":
        hits, text, files = out.get("hits") or [], out.get("text_hits") or [], out.get("other_files") or []
        lines.append(f"documents whose title or path holds it: {len(hits)}")
        lines += [f"- {h['title']} · {h['stage']} · {h['relative_path']}" + (f" ({h['copies']} copies)" if h.get("copies", 1) > 1
                                                                              else "") for h in hits[:SHOWN]]
        lines += _more(hits)
        lines.append(f"documents whose text says it: {len(text)} (every line that says it, up to 8 a document)")
        for h in text[:SHOWN]:
            lines.append(f"- {h['cite']}")
            lines += [f"    line {ln['line']}: {ln['says']}" for ln in h.get("lines") or [{"line": h["line"], "says": h["says"]}]]
        if files:
            lines.append(f"other files with it in their name: {len(files)}")
            lines += [f"- {f['relative_path']} ({f['category']})" for f in files[:10]] + _more(files, 10)
        return "\n".join(lines)
    if what in ("symbol", "callers", "callees", "impact"):
        for h in out.get("hits") or []:
            if "value" in h:                      # a named number
                lines += _value_line(h)
                if what in ("callers", "impact") and h.get("used_by") is not None:
                    lines.append(f"    in {len(h['used_by'])} functions: " + ", ".join(
                        f"{f['name']} ({f['cite']})" for f in h["used_by"][:12]) + (", …" if len(h["used_by"]) > 12 else ""))
            else:
                lines.append(_fn_line(h))
            for key, label in (("callers_list", "called by"), ("callees_list", "calls")):
                got = h.get(key)
                if got is not None:
                    lines.append(f"    {label} {len(got)}:" if got else f"    {label} nothing the map can see")
                    lines += [f"    {'  ' * (f['level'] - 1)}L{f['level']} {f['name']} ({f['cite']}, {f['role']})"
                              for f in got[:SHOWN]] + _more(got)
            if h.get("outside_calls"):
                lines.append("    outside the code base: " + ", ".join(h["outside_calls"][:20]))
            imp = h.get("impact")
            if imp:
                lines.append(f"    reach: {imp['product_functions']} product functions in {len(imp['modules'])} modules, "
                             f"{imp['tests']} tests; direct: {imp['direct_callers']}")
                if imp["modules"]:
                    lines.append("    modules: " + ", ".join(imp["modules"][:30]) + (", …" if len(imp["modules"]) > 30 else ""))
                if imp["entry_points_reached"]:
                    lines.append("    entry points reached: " + ", ".join(imp["entry_points_reached"][:15]))
                lines.append("    caveat: " + imp["caveat"])
            for key in ("not_followed", "ambiguous"):
                if h.get(key):
                    lines.append(f"    {key.replace('_', ' ')}: {h[key]}")
        if out.get("note"):
            lines.append(out["note"])
        return "\n".join(lines)
    hits = out.get("hits") or []
    lines.append(f"{len(hits)} hits")
    for h in hits[:SHOWN]:
        lines.append("- " + ", ".join(f"{k}: {v}" for k, v in h.items() if not isinstance(v, (list, dict)))[:300])
        for k, v in h.items():
            if isinstance(v, list) and v:
                lines.append(f"    {k}: " + ", ".join(str(x if not isinstance(x, dict) else x.get('name') or x.get('doc') or x)
                                                       for x in v[:12])[:400])
    return "\n".join(lines + _more(hits))


def params(out: dict) -> str:
    if out.get("error"):
        return out["error"]
    if "compare" in out:
        lines = [f"params --compare {out['query'].get('name')!r}: {len(out['compare'])} names"]
        for c in out["compare"]:
            lines.append(f"- {c['name']}: {c['verdict']} · stated in {c['documents']} documents")
            for v in c["values"]:
                cites = list(dict.fromkeys(s["cite"] for s in v["stated_in"]))   # a copy states it at the same place
                docs = len({s["document"] for s in v["stated_in"]})
                where = f"{docs} document{'' if docs == 1 else 's'}" + (f" ({len(cites)} places)" if len(cites) > docs else "")
                lines.append(f"    {v['value']} in {where}: " + "; ".join(cites[:4]) + (" …" if len(cites) > 4 else ""))
        lines.append(out.get("note") or "")
        return "\n".join(lines)
    rows = out.get("rows") or []
    lines = [f"params: {out.get('n', 0)} values" + (f", showing {len(rows)}" if out.get("n", 0) > len(rows) else "")]
    lines += [f"- {r.get('label') or '(no name)'} = {r['value_shown']}" + (f" {r['unit_norm']}" if r.get("unit_norm") else "")
              + f"  [{r['cite']}]" for r in rows]
    if out.get("n", 0) > len(rows):
        lines.append(f"  narrow it: a longer --name, --unit, --value, or --limit {out['n']}")
    if out.get("near"):
        lines.append("no value has that name; names that share its words: "
                     + "; ".join(f"{n['name']} ({n['documents']} document{'' if n['documents'] == 1 else 's'})"
                                 for n in out["near"]))
    if out.get("note"):
        lines.append(out["note"])
    return "\n".join(lines)
