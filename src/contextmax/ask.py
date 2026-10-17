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
from pathlib import Path
from urllib.parse import urlsplit

from contextmax import citations, util

SERVERS = (("Ollama", "http://127.0.0.1:11434", "ollama"), ("llama.cpp", "http://127.0.0.1:8080", "openai"),
           ("LM Studio", "http://127.0.0.1:1234", "openai"))
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
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
    passages, seen = [], set()
    for r in rows:
        if kept and r["key"] not in kept:
            continue
        lines = _lines_of(proj, r)
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
    in_code: dict[str, list[dict]] = {}
    for r in util.load_jsonl(proj.documents_dir / "links" / "value-to-code.jsonl"):
        in_code.setdefault(r["label_norm"], []).append(r)
    _INDEXES[proj.slug] = {"stamp": stamp, "functions": functions, "code_values": code_values, "passages": passages,
                           "df": df, "titles": titles, "stages": stages, "rows": by_key, "values": values,
                           "in_code": in_code, "documents_dir": proj.documents_dir}
    return _INDEXES[proj.slug]


def _lines_of(proj, r: dict) -> list[str]:
    try:
        return (proj.documents_dir / r["cached_text"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _code_excerpt(t: dict, f: dict, limit: int = 30) -> str:
    try:
        lines = (Path(t["root"]) / f["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    first, last = f.get("first_line") or 1, f.get("last_line") or f.get("first_line") or 1
    return "\n".join(lines[first - 1:min(last, first - 1 + limit)])


def _title_of(ix: dict, key: str) -> str:
    return ix["titles"].get(key, key)


def _source_lines(lines: list[str], line: int | None, around: int = 1) -> str:
    """The lines of the source itself around a cited line, numbered: what the model answers from."""
    if not line or not lines:
        return ""
    first, last = max(1, line - around), min(len(lines), line + around)
    return "\n".join(f"{k}: {lines[k - 1]}" for k in range(first, last + 1))


def _document_lines(ix: dict, key: str) -> list[str]:
    row = ix["rows"].get(key) or {}
    try:
        return (ix["documents_dir"] / row["cached_text"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, KeyError):
        return []


def _code_lines(t: dict, rel: str) -> list[str]:
    try:
        return (Path(t["root"]) / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def find_functions(ix: dict, ws: list[str], limit: int = 4) -> list[dict]:
    """Functions whose name the words say (a whole name counts most, a part of a name less)."""
    scored = []
    for t, f in ix["functions"]:
        name = f["name"].lower()
        parts = {x.lower() for x in re.split(r"[_\W]+|(?<=[a-z])(?=[A-Z])", f["name"]) if x}
        doc = (f.get("doc") or "").lower()
        s = sum(10 if w == name else 3 if w in parts else 1 if w in doc else 0 for w in ws)
        if s >= 3:
            scored.append((-s, f["name"], t, f))
    out = []
    for _, _, t, f in sorted(scored, key=lambda x: (x[0], x[1]))[:limit]:
        last = f.get("last_line") or f["first_line"]
        text = (f"{f.get('kind', 'function')} {f.get('qualname') or f['name']}({', '.join(f.get('params') or [])})"
                + (f" — {f['doc']}" if f.get("doc") else "") + f"\ncalled by {len(f.get('caller_ids') or [])}, "
                f"calls {len(f.get('callee_ids') or [])}\n```\n{_code_excerpt(t, f)}\n```")
        out.append({"kind": "code", "label": f.get("qualname") or f["name"],
                    "cite": citations.code(t["label"], f["file"], f["first_line"], last), "text": text[:1400],
                    "root": t["root"], "file": f["file"], "line": f["first_line"], "last": last, "base": t["label"]})
    return out


def find_code_values(ix: dict, ws: list[str], limit: int = 6) -> list[dict]:
    """Named numbers in the code whose name or comment holds the words."""
    from contextmax.code.values import name_words

    scored = []
    for t, v in ix["code_values"]:
        own = set(name_words(v["name"])) | set(_tokens(v.get("comment") or ""))
        hits = sum(1 for w in ws if w in own)
        if hits:
            scored.append((-hits, v["file"], v["line"], v["name"], t, v))
    out = []
    for _, _, _, _, t, v in sorted(scored, key=lambda x: x[:4])[:limit]:
        unit = v.get("unit") or "unit not stated"
        own = _source_lines(_code_lines(t, v["file"]), v["line"])
        out.append({"kind": "code value", "label": v["name"], "cite": citations.code(t["label"], v["file"], v["line"]),
                    "text": f"{v['name']} = {v['value']} ({unit}; {v['lang']} {v['kind']})"
                            + (f"  // {v['comment']}" if v.get("comment") else "")
                            + (f"\nthe code file itself:\n{own}" if own else ""),
                    "root": t["root"], "file": v["file"], "line": v["line"], "base": t["label"]})
    return out


def find_passages(ix: dict, ws: list[str], limit: int = 5, per_doc: int = 2) -> list[dict]:
    """Passages of the documents' text, ranked by how many of the words they hold, rare words most."""
    n = max(1, len(ix["passages"]))
    idf = {w: math.log(1 + n / (1 + ix["df"].get(w, 0))) for w in ws}
    ranked = []
    for p in ix["passages"]:
        s = sum(idf[w] * p["tf"][w] / (p["tf"][w] + 1.2) for w in ws if p["tf"].get(w))
        hits = sum(1 for w in ws if p["tf"].get(w))
        if hits:
            ranked.append((-(s * (1 + 0.5 * (hits - 1))), p["key"], p["start"], p))
    out, count = [], Counter()
    for _, _, _, p in sorted(ranked, key=lambda x: (x[0], x[1], x[2])):
        if count[p["key"]] >= per_doc or len(out) >= limit:
            continue
        count[p["key"]] += 1
        out.append(_passage_source(ix, p["row"], p["start"], p["end"], p["text"]))
    return out


def _passage_source(ix: dict, r: dict, first: int, last: int, text: str) -> dict:
    title = _title_of(ix, r["key"])
    return {"kind": "document", "label": title,
            "cite": citations.passage(title, ix["stages"].get(r["key"]), first, last, r.get("page_lines")),
            "text": text[:1600], "folder": r.get("folder"), "relative_path": r.get("relative_path"),
            "cached_text": r.get("cached_text"), "key": r["key"], "line": first}


def find_values(ix: dict, ws: list[str], limit: int = 6) -> list[dict]:
    """Named values whose name holds the words: where each is stated, and what the code says of it."""
    vals, said = [], set()
    for r in ix["values"]:
        said_as = (r["label_norm"], r.get("value_norm"), r.get("unit_norm"), r["doc_ref"])
        if said_as in said or r["file_key"] != r["doc_ref"]:       # a folded copy or older revision: its document is read
            continue
        said.add(said_as)
        hits = sum(1 for w in ws if re.search(r"\b" + re.escape(w) + r"\b", r["label_norm"]))
        if hits:
            vals.append((-hits, r["label_norm"], r["doc_ref"], r.get("line_no") or 0, r))
    out = []
    for _, _, _, _, r in sorted(vals, key=lambda x: x[:4])[:limit]:
        title = _title_of(ix, r["file_key"])
        named = (r.get("label") or r["label_norm"]) + (f" {r['symbol']}" if r.get("symbol") else "")
        text = f"{named} = {r.get('value_shown')} {r.get('unit') or ''}".strip()
        own = _source_lines(_document_lines(ix, r["file_key"]), r.get("line_no"))
        if own:
            text += f"\nthe document itself, lines around {r['line_no']}:\n{own}"
        elif r.get("sentence"):
            text += f"\nwritten as: {r['sentence']}"
        for c in ix["in_code"].get(r["label_norm"], []):
            if c["doc_value"] == r["value_norm"] and c["doc_unit"] == r["unit_norm"]:
                k = c["code"]
                text += (f"\nin the code: {k['name']} = {k['value']} {k.get('unit') or '(unit not stated)'} at "
                         f"{k['target_label']} {k['file']}:{k['line']}: {c['outcome']} ({c['note']})")
        row = ix["rows"].get(r["file_key"]) or {}
        out.append({"kind": "value", "label": r.get("label") or r["label_norm"], "label_norm": r["label_norm"],
                    "cite": citations.value(r, title),
                    "text": text[:1200], "folder": row.get("folder"), "relative_path": row.get("relative_path"),
                    "cached_text": row.get("cached_text"), "key": r["file_key"], "line": r.get("line_no")})
    return out


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
