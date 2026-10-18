"""C: functions with exact line ranges, the calls between them, macros that stand for functions.

No compiler is needed. Comments and string literals are blanked first, keeping every newline
and column so line numbers stay exact; preprocessor lines are blanked next; then definitions
are found by their signature and their matching braces. A call becomes an edge only when its
name is defined in these folders; any other call is counted, never invented.

Two things a reader of text cannot know are reported instead of guessed: a call through a
pointer or a struct member (`ops->start()`), and a name defined in more than one place, where
the nearest definition is taken and the alternatives are listed.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict

from contextmax import parallel, util
from contextmax.code.common import leading_comment, line_at, line_offsets, module_for, role_for, squash_ws

EXTENSIONS = {".c", ".h"}

# Words that look like a call or a definition but are part of the language.
_FLOW = {"break", "case", "continue", "default", "do", "else", "for", "goto", "if", "return", "switch", "while"}
_TYPES = {"char", "double", "float", "int", "long", "short", "signed", "unsigned", "void"}
_QUALIFIERS = {"auto", "const", "extern", "inline", "register", "restrict", "static", "typedef", "volatile"}
_COMPOUND = {"enum", "struct", "union"}
_BUILTINS = {"_Alignof", "__asm", "__attribute__", "__declspec", "alignof", "and", "asm", "defined", "not",
             "offsetof", "or", "sizeof", "va_arg", "va_end", "va_start"}
NOT_A_FUNCTION = _FLOW | _TYPES | _QUALIFIERS | _COMPOUND | _BUILTINS
# Words that may end a return type ("static void", "struct pid *").
TYPE_ENDINGS = _TYPES | _COMPOUND | (_QUALIFIERS - {"auto", "restrict", "typedef"})

_ID = r"[_A-Za-z]\w*"
_TYPE_WORD = rf"(?: [*] | {_ID} )"             # a word of a return type, or a pointer star
_INCLUDE = re.compile(r"""
    ^ [\t ]* [#] [\t ]* include [\t ]*
    (["<]) ([^>"]+) [>"]                        # opening quote or bracket, then the file name
""", re.MULTILINE | re.VERBOSE)
_DEFINE = re.compile(rf"""
    ^ [\t ]* [#] [\t ]* define [\t ]+
    ({_ID}) ( [(] [^)]* [)] )? [\t ]*            # name, optional parameter list
    (.*) $                                      # the body
""", re.MULTILINE | re.VERBOSE)
_FIRST_CALL = re.compile(rf"({_ID}) [\t ]* [(]", re.VERBOSE)
_DIRECTIVE = re.compile(r"^ [\t ]* [#] .* $", re.MULTILINE | re.VERBOSE)
_DEFINITION = re.compile(rf"""
    (?P<ret>  {_TYPE_WORD} (?: [\r\n\t ]+ {_TYPE_WORD} | [\t ]* [*] )* [\r\n\t *]+ )
    (?P<name> {_ID} ) [\r\n\t ]*
    [(] (?P<params> [^;{{}}]*? ) [)] [\r\n\t ]*
    (?P<brace> [{{] )
""", re.DOTALL | re.VERBOSE)
_PROTOTYPE = re.compile(rf"""
    (?P<ret>  {_TYPE_WORD} (?: [\t ]+ {_TYPE_WORD} | [\t ]* [*] )* [\t ]* [*]? [\t ]+ )
    (?P<name> {_ID} ) [\t ]*
    [(] (?P<params> [^;{{}}]*? ) [)] [\t ]* ;
""", re.DOTALL | re.VERBOSE)
_CALL = re.compile(rf"(?<! [-\w.>] ) ({_ID}) [\r\n\t ]* \(", re.VERBOSE)
# Calls whose target is only known at run time: through a member, an arrow, a dereference, a table.
_THROUGH_MEMBER = re.compile(rf"""
    ( {_ID} (?: \[ [^\]]* \] )? (?: \s* (?: -> | \. ) \s* {_ID} )+ ) \s* \(
""", re.VERBOSE)
_THROUGH_POINTER = re.compile(r"\( \s* \* \s* ([_A-Za-z] [\[\]\w.>\-]*) \s* \) \s* \(", re.VERBOSE)
_THROUGH_TABLE = re.compile(rf"(?<! [\w.>] ) ( {_ID} \s* \[ [^\]\n]* \] ) \s* \(", re.VERBOSE)
_BRACES = re.compile(r"[{}]")


def blank_out(text: str) -> str:
    """Comments and string or character literals become spaces. Newlines, tabs, the quote marks
    and every column stay, so a line number found in the result is the line in the file."""
    out = list(text)
    n = len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] not in "\n\t":
                out[k] = " "

    i = 0
    while i < n:
        pair = text[i:i + 2]
        if pair == "//":
            end = text.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
        elif pair == "/*":
            close = text.find("*/", i + 2)
            end = n if close < 0 else close + 2
            blank(i, end)
            i = end
        elif text[i] in "\"'":
            i = _blank_literal(text, out, i)
        else:
            i += 1
    return "".join(out)


def includes_of(text: str, clean: str) -> list[str]:
    """The files a C or C++ file includes. Found on the blanked text, so an #include in a comment does not
    count; the name is taken from the file itself at the same columns, because blanking empties a "quoted"
    name (it is a string literal)."""
    return [text[m.start(2):m.end(2)].strip() for m in _INCLUDE.finditer(clean)]


def _blank_literal(text: str, out: list, start: int) -> int:
    """Blank one quoted literal; return where scanning resumes. The quotes themselves stay, and
    a literal left open ends at its line end instead of swallowing the next line."""
    quote, size, at = text[start], len(text), start + 1
    while at < size and text[at] not in (quote, "\n"):
        if text[at] == "\\":                   # an escape: both characters go, except a line break
            out[at] = " "
            escaped = at + 1
            if escaped < size and text[escaped] != "\n":
                out[escaped] = " "
            at = escaped + 1
            continue
        if text[at] != "\t":
            out[at] = " "
        at += 1
    return at + 1 if at < size else at


def blank_directives(code: str) -> str:
    return _DIRECTIVE.sub(lambda m: " " * (m.end() - m.start()), code)


def brace_end(code: str, opening: int) -> int:
    """Position of the brace that closes the one at `opening` (or the last position)."""
    depth = 0
    for m in _BRACES.finditer(code, opening):
        if m.group() == "{":
            depth += 1
            continue
        depth -= 1
        if depth == 0:
            return m.start()
    return len(code) - 1


def parameters_of(params: str) -> list[str]:
    text = squash_ws(params)
    if text in ("", "void"):
        return []
    pieces, depth, start = [], 0, 0
    for k, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            pieces.append(text[start:k].strip())
            start = k + 1
    tail = text[start:].strip()
    return pieces + [tail] if tail else pieces


def macro_bodies(clean: str) -> dict[str, str]:
    """#define name -> body, continuation lines joined; a later definition replaces an earlier one."""
    joined = clean.replace("\\\n", " ")
    return {m[1]: (m[3] or "").strip() for m in _DEFINE.finditer(joined)}


def macro_targets(bodies: dict[str, str], known: set[str]) -> dict[str, str]:
    """Macros that stand for a project function, followed through macros that name macros."""
    first_call = {}
    for name, body in bodies.items():
        m = _FIRST_CALL.search(body)
        if m and m.group(1) != name and m.group(1) not in NOT_A_FUNCTION:
            first_call[name] = m.group(1)
    targets = {}
    for name in first_call:
        target, visited = name, set()
        while target in first_call and target not in visited:
            visited.add(target)
            target = first_call[target]
        if target in known and target != name:
            targets[name] = target
    return targets


def _definitions(code: str, raw_lines: list[str], starts: list[int], rel: str, module: str, role: str):
    """Function definitions in one file: (record, body offset, body end) each."""
    for m in _DEFINITION.finditer(code):
        name = m["name"]
        if name in NOT_A_FUNCTION:
            continue
        ret = squash_ws(m["ret"])
        last_word = ret.rsplit(" ", 1)[-1].replace("*", "").strip() if ret else ""
        if last_word in NOT_A_FUNCTION and last_word not in TYPE_ENDINGS:
            continue                               # "else if (...) {" and friends
        opening = m.start("brace")
        closing = brace_end(code, opening)
        first = line_at(starts, m.start("ret"))
        while first < len(raw_lines) and not raw_lines[first - 1].strip():
            first += 1                             # the match may begin on blank lines above
        last = line_at(starts, closing)
        record = {
            "key": f"{rel}#{name}#{first}", "name": name, "lang": "C", "kind": "function", "module": module,
            "role": role, "file": rel, "ret": ret, "params": parameters_of(m.group("params")),
            "first_line": first, "last_line": last, "lines_count": last - first + 1,
            "file_local": bool(ret) and ret.partition(" ")[0] == "static", "doc": leading_comment(raw_lines, first),
            "call_keys": [], "via_macros": [], "external_calls": [], "ambiguous": [], "indirect_calls": [],
        }
        yield record, opening + 1, closing


def _chooser(defs: list[dict], by_name: dict[str, list[int]]):
    def choose(name: str, caller: dict) -> tuple[int, list[int]]:
        """The definition a call most likely means, and the alternatives when there is a doubt."""
        options = by_name[name]
        if len(options) == 1:
            return options[0], []
        here, home = caller["file"], caller["module"]
        same_file = [i for i in options if defs[i]["file"] == here]
        if same_file:
            return same_file[0], []                # a static next to its caller always wins
        for test in (lambda i: defs[i]["module"] == home, lambda i: not defs[i]["file_local"]):
            hit = next((i for i in options if test(i)), None)
            if hit is not None:
                return hit, options
        return options[0], options

    return choose


def _link_calls(record: dict, body: str, body_at: int, starts: list[int], known: set[str], macro_map: dict,
                choose, defs: list[dict]) -> None:
    linked, outside = set(), set()
    for m in _CALL.finditer(body):
        called = m.group(1)
        if called in NOT_A_FUNCTION:
            continue
        target, via = (macro_map[called], called) if called not in known and called in macro_map else (called, None)
        if target in known:
            if target in linked:
                continue
            linked.add(target)
            chosen, alternatives = choose(target, record)
            record["call_keys"].append(defs[chosen]["key"])
            if via:
                record["via_macros"].append([via, target])
            if alternatives:
                record["ambiguous"].append([target, [defs[a]["key"] for a in alternatives]])
        elif called not in outside:
            outside.add(called)
            record["external_calls"].append(called)
    unknown = [{"expr": re.sub(r"\s+", "", m.group(1)), "line": line_at(starts, body_at + m.start())}
               for rx in (_THROUGH_MEMBER, _THROUGH_POINTER, _THROUGH_TABLE) for m in rx.finditer(body)]
    record["indirect_calls"] = sorted(unknown, key=lambda x: (x["line"], x["expr"]))


def _read_file(pair: tuple[str, str]) -> dict:
    """One .c or .h file's own part of the reading: its macros, its definitions with their bodies, its
    prototypes and its facts (a piece of parallel work; the shared data is the module depth)."""
    full, rel = pair
    depth = parallel.shared()
    text = util.load_text(full)
    raw_lines = text.split("\n")
    clean = blank_out(text)
    starts = line_offsets(clean)
    code = blank_directives(clean)
    ext = os.path.splitext(rel)[1].lower()
    module, role = module_for(rel, depth), role_for(rel)
    found = [(record, code[body_at:body_end], body_at)
             for record, body_at, body_end in _definitions(code, raw_lines, starts, rel, module, role)]
    prototypes = [m.group("name") for m in _PROTOTYPE.finditer(code)
                  if m.group("name") not in NOT_A_FUNCTION] if ext == ".h" else []
    info = {"module": module, "role": role, "lang": "C", "ext": ext, "lines_count": clean.count("\n") + 1,
            "includes": includes_of(text, clean), "defs_count": len(found)}
    return {"macros": macro_bodies(clean), "found": found, "starts": starts, "prototypes": prototypes, "info": info}


def analyze(root: str, files: list[tuple[str, str]], depth: int):
    """Read every .c/.h file of one code base. Returns (defs, file_info, extras)."""
    defs: list[dict] = []
    file_info: dict[str, dict] = {}
    prototypes: dict[str, list[str]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    macros: dict[str, str] = {}
    bodies: list[tuple[int, str, int, list[int]]] = []
    # each file is read on its own (in parallel when there are many); what the files give is put
    # together here in the files' order, as when they were read one after another
    read = parallel.map_in_order(_read_file, files, data=depth, progress=util.current())
    for (_full, rel), got in zip(files, read, strict=True):
        macros.update(got["macros"])
        for record, body, body_at in got["found"]:
            by_name[record["name"]].append(len(defs))
            bodies.append((len(defs), body, body_at, got["starts"]))
            defs.append(record)
        for name in got["prototypes"]:
            prototypes[name].append(rel)
        file_info[rel] = got["info"]
    known = set(by_name)
    macro_map = macro_targets(macros, known)
    choose = _chooser(defs, by_name)
    for idx, body, body_at, starts in bodies:
        _link_calls(defs[idx], body, body_at, starts, known, macro_map, choose, defs)
    header_module = {os.path.basename(rel): fi["module"] for rel, fi in file_info.items() if fi["ext"] == ".h"}
    included: dict[str, Counter] = defaultdict(Counter)
    for fi in file_info.values():
        for name in fi["includes"]:
            other = header_module.get(os.path.basename(name))
            if other and other != fi["module"]:
                included[fi["module"]][other] += 1
    extras = {"prototypes": {n: sorted(set(v)) for n, v in prototypes.items()}, "macro_map": macro_map,
              "module_includes": {m: dict(c) for m, c in included.items()}}
    return defs, file_info, extras
