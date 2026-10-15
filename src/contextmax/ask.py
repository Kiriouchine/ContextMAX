"""Ask a model on this PC about a project: the answer comes from the project's index, with its sources.

ContextMAX finds what a question is about in the index, by itself (no model in the search): functions by
name with their code, passages of the documents' text, named values with where they are stated. It
numbers them as sources and gives them to a model that runs on this PC (Ollama, llama.cpp's server or
LM Studio), with the instruction to answer from them only and to cite them as [n]. Nothing leaves this
PC: only an address on this PC (127.0.0.1, localhost) is ever asked. The answer is a lead; the sources
it cites are listed with links, to be checked.
"""
from __future__ import annotations

import http.client
import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from contextmax import util

SERVERS = (("Ollama", "http://127.0.0.1:11434", "ollama"), ("llama.cpp", "http://127.0.0.1:8080", "openai"),
           ("LM Studio", "http://127.0.0.1:1234", "openai"))
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CONTEXT_CHARS = 9000            # what the sources may take of the prompt: small local models have small windows
PASSAGE_LINES = 10
STOP = set("""the a an and or of to in on for is are was were be been by with from at as it its this that these those
what which who whom how why when where does do did can could should would will shall may might than then there here
about into over under not no yes our your their his her we you they me my mine use used using any all some each more most
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
    for t in proj.code_targets:
        for f in util.load_jsonl(proj.code_dir / t["name"] / "function-list.jsonl"):
            functions.append((t, f))
    rows = util.load_jsonl(proj.documents_dir / "text-index.jsonl")
    titles = {r["key"]: r.get("doc_title") or Path(r.get("relative_path") or r["key"]).name for r in rows}
    kept = {d["key"] for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl")}    # copies folded into one
    passages, seen = [], set()
    for r in rows:
        if kept and r["key"] not in kept:
            continue
        path = proj.documents_dir / r["cached_text"]
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for start in range(0, len(lines), PASSAGE_LINES):
            chunk = "\n".join(lines[start:start + PASSAGE_LINES]).strip()
            if chunk and chunk not in seen:
                seen.add(chunk)
                passages.append({"key": r["key"], "start": start + 1, "end": min(len(lines), start + PASSAGE_LINES),
                                 "text": chunk, "tf": Counter(_tokens(chunk)), "row": r})
    df = Counter()
    for p in passages:
        df.update(p["tf"].keys())
    values = [r for r in util.load_jsonl(proj.documents_dir / "params.jsonl")
              if r.get("label_norm") and r.get("origin") != "formula_constant"]
    _INDEXES[proj.slug] = {"stamp": stamp, "functions": functions, "passages": passages, "df": df,
                           "titles": titles, "values": values}
    return _INDEXES[proj.slug]


def _code_excerpt(t: dict, f: dict, limit: int = 30) -> str:
    try:
        lines = (Path(t["root"]) / f["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    first, last = f.get("first_line") or 1, f.get("last_line") or f.get("first_line") or 1
    return "\n".join(lines[first - 1:min(last, first - 1 + limit)])


def sources(proj, question: str) -> list[dict]:
    """The numbered sources for a question: code, then document passages, then named values."""
    ix, ws = _index(proj), words(question)
    if not ws:
        return []
    found = []
    # functions whose name the question says (a whole name counts most, a part of a name less)
    scored = []
    for t, f in ix["functions"]:
        name = f["name"].lower()
        parts = {x.lower() for x in re.split(r"[_\W]+|(?<=[a-z])(?=[A-Z])", f["name"]) if x}
        doc = (f.get("doc") or "").lower()
        s = sum(10 if w == name else 3 if w in parts else 1 if w in doc else 0 for w in ws)
        if s >= 3:
            scored.append((-s, f["name"], t, f))
    for _, _, t, f in sorted(scored, key=lambda x: (x[0], x[1]))[:4]:
        cite = f"{t['label']}: {f['file']}:{f['first_line']}-{f.get('last_line') or f['first_line']}"
        text = (f"{f.get('kind', 'function')} {f.get('qualname') or f['name']}({', '.join(f.get('params') or [])})"
                + (f" — {f['doc']}" if f.get("doc") else "") + f"\ncalled by {len(f.get('caller_ids') or [])}, "
                f"calls {len(f.get('callee_ids') or [])}\n```\n{_code_excerpt(t, f)}\n```")
        found.append({"kind": "code", "label": f.get("qualname") or f["name"], "cite": cite, "text": text[:1400],
                      "root": t["root"], "file": f["file"], "line": f["first_line"]})
    # passages of the documents' text, ranked by how many of the question's words they hold, rare words most
    n = max(1, len(ix["passages"]))
    idf = {w: math.log(1 + n / (1 + ix["df"].get(w, 0))) for w in ws}
    ranked = []
    for p in ix["passages"]:
        s = sum(idf[w] * p["tf"][w] / (p["tf"][w] + 1.2) for w in ws if p["tf"].get(w))
        hits = sum(1 for w in ws if p["tf"].get(w))
        if hits:
            ranked.append((-(s * (1 + 0.5 * (hits - 1))), p["key"], p["start"], p))
    per_doc: Counter = Counter()
    for _, _, _, p in sorted(ranked, key=lambda x: (x[0], x[1], x[2])):
        if per_doc[p["key"]] >= 2 or len([x for x in found if x["kind"] == "document"]) >= 5:
            continue
        per_doc[p["key"]] += 1
        r = p["row"]
        found.append({"kind": "document", "label": ix["titles"].get(p["key"], p["key"]),
                      "cite": f"{ix['titles'].get(p['key'], p['key'])}, text lines {p['start']}-{p['end']}",
                      "text": p["text"][:900], "folder": r.get("folder"), "relative_path": r.get("relative_path"),
                      "cached_text": r.get("cached_text")})
    # named values whose name the question says
    vals, said = [], set()
    for r in ix["values"]:
        said_as = (r["label_norm"], r.get("value_norm"), r.get("unit_norm"), ix["titles"].get(r["doc_ref"], r["doc_ref"]))
        if said_as in said:
            continue
        said.add(said_as)
        label = r["label_norm"]
        hits = sum(1 for w in ws if re.search(r"\b" + re.escape(w) + r"\b", label))
        if hits:
            vals.append((-hits, label, r["doc_ref"], r))
    for _, _, _, r in sorted(vals, key=lambda x: (x[0], x[1], x[2]))[:6]:
        where = ix["titles"].get(r["doc_ref"], r["doc_ref"]) + (f" ({r['sheet']}!{r['cell']})" if r.get("sheet") else "")
        found.append({"kind": "value", "label": r.get("label") or r["label_norm"], "cite": where,
                      "text": f"{r.get('label') or r['label_norm']} = {r.get('value_shown')} {r.get('unit_norm') or ''}".strip()
                              + (f"  (in context: {r['context'][:160]})" if r.get("context") else "")})
    # within the budget, numbered
    out, used = [], 0
    for s in found:
        if used + len(s["text"]) > CONTEXT_CHARS:
            continue
        used += len(s["text"])
        out.append(dict(s, n=len(out) + 1))
    return out


def messages(proj, question: str, found: list[dict]) -> list[dict]:
    system = (f"You answer questions about the project \"{proj.name}\". Use only the numbered sources ContextMAX "
              "found in the project's index (code, document text, named values). Cite every statement with its "
              "source number in square brackets, like [2]. If the sources do not answer the question, say so "
              "plainly and say what to look at next; never guess. Answer in the language of the question, briefly.")
    blocks = [f"[{s['n']}] ({s['kind']}) {s['cite']}\n{s['text']}" for s in found]
    user = f"Question: {question}\n\nSources:\n\n" + ("\n\n".join(blocks) if blocks else "(none found in the index)")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


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
