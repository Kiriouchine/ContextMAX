"""Named numbers in code: the values a program is built with, each with its file, line, unit and comment, so
they can be held against the values the documents state (docs/value_code.py).

  C, C++   #define NAME number, and const / constexpr variables set to a number
  Python   names set to a number at module level or in a class body (Config.TIMEOUT_MS)
  MATLAB   name = number, struct fields too (p.motor.Kt = 0.05)
  VHDL     constants and generics set to a number, time literals with their unit (10 ns)

Only a plain number counts, never an expression: 2*PI is not a value a document could state. Hexadecimal
numbers are left out (masks and addresses, not measures). Comments and strings are blanked before the search,
so code that is commented out is never read.

The unit comes from the name (TIMEOUT_MS, timeoutMs), from the comment ([ms], (ms), "in ms", or a comment that
starts with the unit) or from the literal (VHDL's 10 ns). When the name and the comment disagree the unit is
unknown, and the row says why. A unit nothing states stays unknown: it is never guessed.
"""
from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from collections import Counter, defaultdict

from contextmax import parallel, util
from contextmax.code import c_lang, cpp_lang, matlab_lang, vhdl_lang
from contextmax.docs import params as P

FORMAT_VERSION = 2               # 2: each named number's uses (used_in, uses_count, included_by_count)
_IDENT = re.compile(r"[A-Za-z_]\w*")
_NUMBER = r"[+-]?\s*(?:\d[\d']*(?:\.[\d']*)?|\.\d[\d']*)(?:[eE][+-]?\d+)?"
# units a name ends with. One letter only for s, V and A: _M or _G name too many other things
NAME_UNITS = {
    "ms": "ms", "msec": "ms", "us": "us", "usec": "us", "ns": "ns", "s": "s", "sec": "s", "secs": "s",
    "hz": "Hz", "khz": "kHz", "mhz": "MHz", "ghz": "GHz", "v": "V", "mv": "mV", "kv": "kV", "uv": "uV",
    "a": "A", "ma": "mA", "ua": "uA", "w": "W", "mw": "mW", "kw": "kW", "deg": "deg", "degc": "°C",
    "rad": "rad", "rpm": "rpm", "mm": "mm", "cm": "cm", "km": "km", "um": "um", "pct": "%", "percent": "%",
    "pa": "Pa", "kpa": "kPa", "mbar": "mbar", "bar": "bar", "ohm": "ohm", "ohms": "ohm", "kohm": "kΩ",
    "db": "dB", "ppm": "ppm", "bytes": "bytes", "bits": "bits", "kb": "kB", "kg": "kg", "mg": "mg",
}
# a one-letter ending is a unit only beside a word for its quantity: MAX_CURRENT_A, but not CHANNEL_A
_ONE_LETTER = {
    "a": frozenset("current curr amp amps ampere amperes stall".split()),
    "v": frozenset("voltage volt volts vbus vdd vcc supply bus battery batt ref reference rail".split()),
    "s": frozenset("time timeout delay period duration interval wait settle rise fall dwell hold debounce".split()),
}
_VHDL_TIME = {"fs": "fs", "ps": "ps", "ns": "ns", "us": "us", "ms": "ms", "sec": "s", "min": "min", "hr": "h"}
_C_DEFINE = re.compile(r"^\s*\#\s*define\s+([A-Za-z_]\w*)[ \t]+(.+?)\s*$")
# a number, perhaps cast and in brackets: 1000U, (12.5f), ((uint16_t)1000)
_C_NUMBER = re.compile(rf"^\(*\s*(?:\(\s*[A-Za-z_][\w\s]*\)\s*)?\(*\s*(?P<num>{_NUMBER})(?P<sfx>[uUlLfF]*)\s*\)*$")
_C_CONST = re.compile(rf"\b(?P<name>[A-Za-z_]\w*)\s*(?:=|\{{)\s*\(*\s*(?:\(\s*[A-Za-z_][\w\s]*\)\s*)?(?P<num>{_NUMBER})"
                      rf"(?P<sfx>[uUlLfF]*)\s*\)*\s*\}}?\s*;")
_C_QUALIFIER = re.compile(r"\b(?:const|constexpr|constinit)\b")
_M_ASSIGN = re.compile(r"^\s*(?P<name>[A-Za-z]\w*(?:\.[A-Za-z]\w*)*)\s*=\s*(?P<num>[+-]?\s*(?:\d+(?:\.\d*)?|\.\d+)"
                       r"(?:[eEdD][+-]?\d+)?)\s*$")
_V_DECL = re.compile(r"""(?P<names>[A-Za-z]\w*(?:\s*,\s*[A-Za-z]\w*)*)\s*:\s*(?:in\s+)?[^:;=]+?:=\s*
                         (?P<num>[+-]?\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\s*(?P<unit>fs|ps|ns|us|ms|sec|min|hr)?\s*$""",
                     re.IGNORECASE | re.VERBOSE)
_V_CONSTANT = re.compile(r"\bconstant\s+([^;]*);", re.IGNORECASE)
_V_GENERIC = re.compile(r"\bgeneric\s*\(", re.IGNORECASE)
_NAME_PIECES = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_COMMENT_MARKS = re.compile(r"^\s*(?://+|/\*+|\*+|%+|--+|#+)\s*<?\s*|\s*\*+/\s*$")
_unit_pattern: list = []


def _units() -> re.Pattern:
    """The unit spellings the documents are read with: one list for both sides."""
    if not _unit_pattern:
        from contextmax.docs.corpus import UNIT_WORDS

        alt = "|".join(UNIT_WORDS)
        _unit_pattern.append(re.compile(rf"\[\s*({alt})\s*\]|\(\s*({alt})\s*\)|\b(?:in|units?:?)\s+({alt})(?![\w/])"
                                        rf"|^\s*({alt})(?![\w/])"))
    return _unit_pattern[0]


def name_words(name: str) -> list[str]:
    """The words of a code name, lower case: PID_SETTLE_TIME_MS, pidSettleTimeMs and p.pid.settle_ms alike."""
    return [w.lower() for piece in re.split(r"[_.\W]+", name) for w in _NAME_PIECES.findall(piece)]


def unit_of_name(name: str) -> str:
    words = name_words(name)
    if len(words) < 2:
        return ""
    if words[-1] in _ONE_LETTER and not _ONE_LETTER[words[-1]] & set(words[:-1]):
        return ""
    return NAME_UNITS.get(words[-1], "")


def unit_of_comment(comment: str) -> str:
    m = _units().search(comment or "")
    return P.canon_unit(next(g for g in m.groups() if g)) if m else ""


def _clean_comment(text: str) -> str:
    return " ".join(_COMMENT_MARKS.sub("", text.strip()).split())[:200]


def _row(lang: str, kind: str, name: str, written: str, line: int, comment: str, literal_unit: str = "") -> dict:
    written = written.replace(" ", "").replace("'", "").replace("_", "")
    named, said = unit_of_name(name), unit_of_comment(comment)
    unit, unit_from, note = "", "", ""
    for found, source in ((literal_unit, "literal"), (named, "name"), (said, "comment")):
        if not found:
            continue
        if not unit:
            unit, unit_from = found, source
        elif P.canon_unit(found) != P.canon_unit(unit):
            note = f"the {unit_from} says {unit}, the {source} says {found}"
            unit, unit_from = "", ""
            break
    return {"lang": lang, "kind": kind, "name": name, "value": written, "value_norm": P.canon_number(written),
            "unit": P.canon_unit(unit), "unit_from": unit_from, "unit_note": note, "line": line, "comment": comment}


def _comment_near(lines: list[str], n: int, code_end: int, starts: tuple[str, ...]) -> str:
    """The comment on line n (1-based) after the code, else a comment line right above it."""
    tail = lines[n - 1][code_end:].strip()
    if tail:
        return _clean_comment(tail)
    above = lines[n - 2].strip() if n >= 2 else ""
    return _clean_comment(above) if above.startswith(starts) else ""


def _c_values(text: str, lang: str) -> list[dict]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines, clean = raw.split("\n"), c_lang.blank_out(raw).split("\n")
    rows = []
    for n, code in enumerate(clean, 1):
        d = _C_DEFINE.match(code)
        if d:
            m = _C_NUMBER.match(d.group(2))
            if m:
                rows.append(_row(lang, "define", d.group(1), m.group("num"), n,
                                 _comment_near(lines, n, len(code.rstrip()), ("//", "/*", "*"))))
            continue
        for m in _C_CONST.finditer(code):
            before = code[:m.start()]
            if _C_QUALIFIER.search(before) and "(" not in before and "=" not in before and not before.strip().startswith("return"):
                rows.append(_row(lang, "const", m.group("name"), m.group("num"), n,
                                 _comment_near(lines, n, m.end(), ("//", "/*", "*"))))
    return rows


def _python_values(text: str) -> list[dict]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    lines, rows = text.replace("\r\n", "\n").split("\n"), []

    def number(node):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            node = node.operand
        return isinstance(node, ast.Constant) and type(node.value) in (int, float)

    def take(body, owner: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef) and not owner:
                take(node.body, node.name + ".")
                continue
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if not number(value) or value.end_lineno != node.lineno:
                continue
            line = lines[node.lineno - 1]
            written = line.encode("utf-8")[value.col_offset:value.end_col_offset].decode("utf-8", "ignore")
            end = len(line.encode("utf-8")[:value.end_col_offset].decode("utf-8", "ignore"))
            hash_at = line.find("#", end)
            comment = _clean_comment(line[hash_at:]) if hash_at >= 0 else _comment_near(lines, node.lineno, len(line), ("#",))
            for t in targets:
                if isinstance(t, ast.Name):
                    rows.append(_row("Python", "assignment", owner + t.id, written, node.lineno, comment))

    take(tree.body, "")
    return rows


def _matlab_values(text: str) -> list[dict]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines, clean = raw.split("\n"), matlab_lang.strip_matlab(raw)
    rows = []
    for n, code in enumerate(clean, 1):
        statements = [s for s in code.split(";") if s.strip()]
        if not statements:
            continue
        comment = ""
        rest = lines[n - 1][len(code):]
        if rest.lstrip().startswith("%"):
            comment = _clean_comment(rest)
        for s in statements:
            m = _M_ASSIGN.match(s)
            if m and (len(m.group("name").rsplit(".", 1)[-1]) >= 2 or comment):     # I1, dt, Kp; not i or x
                rows.append(_row("MATLAB", "assignment", m.group("name"), m.group("num").replace("d", "e").replace("D", "e"),
                                 n, comment if len(statements) == 1 else ""))
    return rows


def _vhdl_values(text: str) -> list[dict]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines, clean = raw.split("\n"), vhdl_lang.erase_comments(raw)
    rows = []

    def at_line(pos: int) -> int:
        return clean.count("\n", 0, pos) + 1

    def comment_of(n: int) -> str:
        line = lines[n - 1]
        cut = line.find("--")
        return _clean_comment(line[cut:]) if cut >= 0 else ""

    def declare(decl: str, start: int, kind: str) -> None:
        m = _V_DECL.match(decl.strip())
        if not m:
            return
        n = at_line(start + len(decl) - len(decl.lstrip()))
        unit = _VHDL_TIME.get((m.group("unit") or "").lower(), "")
        for name in re.split(r"\s*,\s*", m.group("names")):
            rows.append(_row("VHDL", kind, name, m.group("num"), n, comment_of(n), unit))

    for m in _V_CONSTANT.finditer(clean):
        declare(m.group(1), m.start(1), "constant")
    for m in _V_GENERIC.finditer(clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"(": 1, ")": -1}.get(clean[i], 0)
            i += 1
        body, at = clean[m.end():i - 1], m.end()
        for piece in body.split(";"):
            declare(piece, at, "generic")
            at += len(piece) + 1
    return rows


def read(job: tuple[str, str, str]) -> list[dict]:
    """The named numbers of one file (a piece of parallel work): (full path, relative path, language)."""
    full, rel, lang = job
    try:
        text = util.load_text(full)
    except OSError:
        return []
    if lang in ("C", "C++"):
        rows = _c_values(text, lang)
    elif lang == "Python":
        rows = _python_values(text)
    elif lang == "MATLAB":
        rows = _matlab_values(text)
    elif lang == "VHDL":
        rows = _vhdl_values(text)
    else:
        return []
    # a one-letter name (i, k, n) is a counter, not a value, unless its comment says what it is
    return [dict(r, file=rel) for r in rows if P.all_numbers(r["value_norm"])
            and (len(r["name"].rsplit(".", 1)[-1]) >= 2 or r["comment"])]


def _key(name: str) -> str:
    """What a named number is called where it is used: Config.TIMEOUT_MS is used as TIMEOUT_MS after the dot."""
    return name.rsplit(".", 1)[-1]


def _code_lines(text: str, lang: str) -> list[str]:
    """A file's lines with comments and strings blanked: a name left there is used, not only mentioned."""
    if lang in ("C", "C++"):
        return c_lang.blank_out(text).split("\n")
    if lang == "MATLAB":
        return matlab_lang.strip_matlab(text)
    if lang == "VHDL":
        return vhdl_lang.erase_comments(text).split("\n")
    return []


def _python_names(text: str) -> list[tuple[str, int]]:
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME:
                out.append((tok.string, tok.start[0]))
    except (tokenize.TokenError, SyntaxError):
        pass                                   # a file Python cannot read: the names found up to there
    return out


def uses_in(job: tuple[str, str, str]) -> list[tuple[str, int]]:
    """Where the code base's named numbers are used in one file (a piece of parallel work): (name, line)."""
    full, _rel, lang = job
    names = parallel.shared()
    try:
        text = util.load_text(full)
    except OSError:
        return []
    if lang == "Python":
        pairs = _python_names(text)
    else:
        pairs = [(m.group(0), n) for n, line in enumerate(_code_lines(text, lang), 1) for m in _IDENT.finditer(line)]
    return sorted({(name, n) for name, n in pairs if name in names})


def _function_at(functions: list[dict], line: int) -> str | None:
    inside = [f for f in functions if f["first_line"] <= line <= (f.get("last_line") or f["first_line"])]
    if not inside:
        return None
    f = max(inside, key=lambda f: (f["first_line"], f["name"]))       # the innermost
    return f.get("qualname") or f["name"]


def _record_uses(rows: list[dict], jobs: list[tuple], file_info: dict, defs) -> None:
    """Each named number's uses (file, line, the function they are in), comments and strings left out. A name
    defined in more than one place is used where its definition is in effect: one in the same file, else one
    in a header the file includes, else every definition of that name could be meant. A value in a C or C++
    header also records how many files include that header (none: nothing can use it)."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[_key(r["name"])].append(r)     # every name, r1 too: a short name is still the name it is used by
        r["used_in"] = []
    found = parallel.map_in_order(uses_in, jobs, data=frozenset(by_key))
    functions: dict[str, list[dict]] = defaultdict(list)
    for d in defs:
        functions[d["file"]].append(d)
    includers = Counter(os.path.basename(x) for fi in file_info.values() for x in fi.get("includes") or [])
    for (_full, rel, _lang), got in zip(jobs, found, strict=True):
        included = {os.path.basename(x) for x in (file_info.get(rel) or {}).get("includes") or []}
        for name, line in got:
            meant = by_key[name]
            if any(c["file"] == rel and c["line"] == line for c in meant):
                continue                                         # the definition itself
            meant = [c for c in meant if c["file"] == rel] or [c for c in meant if os.path.basename(c["file"])
                                                                in included] or meant
            use = {"file": rel, "line": line, "in": _function_at(functions[rel], line)}
            for c in meant:
                c["used_in"].append(use)
    headers = cpp_lang.HEADER_EXTENSIONS
    for r in rows:
        r["used_in"].sort(key=lambda u: (u["file"], u["line"]))
        r["uses_count"] = len(r["used_in"])
        if r["lang"] in ("C", "C++") and os.path.splitext(r["file"])[1].lower() in headers:
            r["included_by_count"] = includers[os.path.basename(r["file"])]


def write(out, files: dict[str, list[tuple[str, str]]], file_info: dict, defs=()) -> int:
    """code/<base>/values.jsonl: every named number of the code base, in file and line order, with its uses."""
    jobs = [(full, rel, lang) for lang, pairs in files.items() for full, rel in pairs]
    jobs.sort(key=lambda j: j[1])
    rows = []
    for got in parallel.map_in_order(read, jobs):
        for r in got:
            r["module"] = (file_info.get(r["file"]) or {}).get("module")
            rows.append(r)
    rows.sort(key=lambda r: (r["file"], r["line"], r["name"]))
    _record_uses(rows, jobs, file_info, defs)
    util.save_jsonl(out / "values.jsonl", [dict(sorted(r.items())) for r in rows])
    return len(rows)
