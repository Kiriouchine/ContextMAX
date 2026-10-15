"""C++: functions and methods with exact line ranges, and the calls between them, read by a parser.

Every file is parsed with tree-sitter's C++ grammar: no compiler and no build settings are needed,
and the same text always gives the same tree. Each definition gets its full name from the
namespaces and classes around it, so `motor::Controller::clamp` is one name however the source
spells it (inside the class, or `Controller::clamp` in a .cpp file inside `namespace motor`).

A call becomes an edge only when the text says which definition it means:
  - `f()` looks in the caller's own class and its base classes, then in the enclosing namespaces
    and those the file names with `using namespace`, then at free functions of that name anywhere
    in these folders, then at a class of that name (a constructor), then at the C functions of the
    same code base;
  - `ns::f()` and `Base::f()` name their scope;
  - `obj.f()` and `ptr->f()` follow the declared type of the object: a parameter, a local variable,
    a field of the class (also through `this`), or a pointer, reference or smart pointer to one,
    and type aliases. Constructors are calls too: `Motor m(2)`, `new Motor`, `Motor(2)`, and the
    base classes and fields a constructor initialises.
A member call on an object whose type the text does not state is never guessed: it is counted
with every method of that name in these folders as a candidate. Overloads are told apart by the
number of arguments when that settles it; otherwise one is chosen and the others are listed, as in
C. A call to a virtual method lists the overrides in derived classes. Implicit calls (operators,
destructors, conversions) are not followed.
"""
from __future__ import annotations

import importlib.metadata
import os
import re
from collections import defaultdict

from contextmax import util
from contextmax.code import c_lang
from contextmax.code.common import leading_comment, module_for, role_for, squash_ws

EXTENSIONS = {".cc", ".cpp", ".cxx", ".c++", ".hh", ".hpp", ".hxx", ".h++", ".ipp", ".tpp", ".inl"}
HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx", ".h++", ".ipp", ".tpp", ".inl"}

try:
    import tree_sitter_cpp
    from tree_sitter import Language, Parser
    _LANGUAGE = Language(tree_sitter_cpp.language())
    PROBLEM = ""
except (ImportError, OSError, ValueError, AttributeError) as exc:      # a damaged installation
    _LANGUAGE = None
    PROBLEM = f"the C++ parser (tree-sitter-cpp) could not be loaded: {exc}"

# A .h file is C++ when its text uses what C does not have. Comments, strings and preprocessor
# lines are blanked first, so `extern "C"` guards and comments never decide it.
_CPP_ONLY = re.compile(r"""
      \b class \s+ [_A-Za-z]\w* \s* (?: final \s* )? [:{]      # a class with a body or base classes
    | \b namespace \b \s* (?: [_A-Za-z][\w:]* \s* )? [{]       # a namespace
    | \b template \s* <                                         # a template
    | \b (?: public | private | protected ) \s* : (?! : )       # an access section of a class
    | [_A-Za-z]\w* \s* :: \s* ~? [_A-Za-z]                      # a scope operator between two names
""", re.VERBOSE)

_CLASSES = {"class_specifier", "struct_specifier", "union_specifier"}
_MARKS = {"pointer_declarator": "*", "reference_declarator": "&"}
_NAMES = {"identifier", "field_identifier", "qualified_identifier", "operator_cast", "destructor_name", "operator_name",
          "template_function", "type_identifier"}
_SMART = {"unique_ptr", "shared_ptr", "weak_ptr", "optional", "reference_wrapper"}
_MAKERS = {"make_unique", "make_shared"}
_NOT_CALLS = c_lang.NOT_A_FUNCTION | {"static_cast", "dynamic_cast", "const_cast", "reinterpret_cast", "typeid",
                                      "decltype", "noexcept", "static_assert"}
_DECLARATIONS = {"declaration", "parameter_declaration", "optional_parameter_declaration", "for_range_loop"}
_CONSTANT = re.compile(r"\b (?: constexpr | const ) \b [^;=(){}]*? \b ([A-Z][A-Z0-9_]{3,}) \s* (?: = | [{] )", re.VERBOSE)
_ANY = (0, 10 ** 6)
# A call site lists its possible targets when they are this few; more are counted, and every one of
# them is in name-lookup.json under the method's name (and in the method's own `overridden_by`).
LISTED_AT_CALL = 12


def is_cpp_header(text: str) -> bool:
    """Whether a .h file is C++ (read by this reader) rather than C (read by the C reader)."""
    return bool(_CPP_ONLY.search(c_lang.blank_directives(c_lang.blank_out(text))))


def parser_name() -> str:
    try:
        return (f"tree-sitter-cpp {importlib.metadata.version('tree-sitter-cpp')} "
                f"(tree-sitter {importlib.metadata.version('tree-sitter')})")
    except importlib.metadata.PackageNotFoundError:
        return "tree-sitter-cpp"


def constants(text: str) -> list[str]:
    """Names of constants a document may quote: #define, and constexpr or const in capitals."""
    clean = c_lang.blank_out(text)
    return [m.group(1) for m in c_lang._DEFINE.finditer(clean.replace("\\\n", " "))] + \
        [m.group(1) for m in _CONSTANT.finditer(c_lang.blank_directives(clean))]


# == reading the tree ==

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _plain(node, src: bytes) -> str:
    """A name without template arguments or spaces: `std::vector<int>` -> `std::vector`."""
    if node is None:
        return ""
    t = node.type
    if t in ("template_type", "template_function", "template_method"):
        return _plain(node.child_by_field_name("name"), src)
    if t == "qualified_identifier":
        scope, name = node.child_by_field_name("scope"), node.child_by_field_name("name")
        head = _plain(scope, src) if scope is not None else ""
        return head + "::" + _plain(name, src) if head else _plain(name, src)
    if t == "operator_cast":
        return "operator " + squash_ws(_text(node.child_by_field_name("type"), src))
    if t == "operator_name":
        return squash_ws(_text(node, src))
    return re.sub(r"\s+", "", _text(node, src))


def _parts(node, src: bytes) -> list[str]:
    """`ns::Cls::fn` -> ['ns', 'Cls', 'fn']; a leading `::` gives no empty part."""
    if node.type == "qualified_identifier":
        scope, name = node.child_by_field_name("scope"), node.child_by_field_name("name")
        head = _parts(scope, src) if scope is not None else []
        return head + (_parts(name, src) if name is not None else [])
    return [_plain(node, src)]


def _inner(node):
    """The declarator inside a pointer, reference, parenthesis or initialiser."""
    nxt = node.child_by_field_name("declarator")
    if nxt is None:
        nxt = next((c for c in node.named_children if c.type.endswith("declarator") or c.type in _NAMES), None)
    return nxt


def _function_declarator(decl):
    """(function declarator, marks such as * or & around it) of a definition's declarator."""
    marks = ""
    node = decl
    while node is not None:
        if node.type in ("function_declarator", "operator_cast"):
            return node, marks
        marks += _MARKS.get(node.type, "")
        node = _inner(node) if node.type not in _NAMES else None
    return None, marks


def _points_to_function(fdecl) -> bool:
    """`void (*start)(int)`: a pointer to a function, which is a variable or a field, not a function."""
    inner = fdecl.child_by_field_name("declarator") if fdecl.type == "function_declarator" else None
    return inner is not None and inner.type == "parenthesized_declarator"


def _declared_name(decl):
    """The identifier a variable declarator declares: None for a function, but a function pointer
    `void (*handler)(int)` declares the variable `handler`."""
    node = decl
    while node is not None and node.type not in ("identifier", "field_identifier"):
        if node.type == "function_declarator" and not _points_to_function(node):
            return None
        node = _inner(node)
    return node


def _lexical(node, src: bytes):
    """Enclosing namespaces and classes (outermost first), whether the innermost scope is a class,
    whether a namespace is anonymous, whether the linkage is "C", and whether a template encloses it."""
    names, in_class, anonymous, c_linkage, template = [], None, False, False, False
    p = node.parent
    while p is not None:
        t = p.type
        if t == "namespace_definition":
            name = p.child_by_field_name("name")
            if name is None:
                anonymous = True
            else:
                names.extend(reversed(re.sub(r"\s+", "", _text(name, src)).split("::")))
            in_class = False if in_class is None else in_class
        elif t in _CLASSES:
            name = p.child_by_field_name("name")
            names.append(_plain(name, src) if name is not None else "(anonymous)")
            in_class = True if in_class is None else in_class
        elif t == "linkage_specification":
            value = p.child_by_field_name("value")
            c_linkage = c_linkage or (value is not None and _text(value, src).strip('"') == "C")
        elif t == "template_declaration":
            template = True
        p = p.parent
    return names[::-1], bool(in_class), anonymous, c_linkage, template


def _type_name(node, src: bytes) -> str:
    """A declared type as a plain name: const, pointers and references dropped, and a smart
    pointer or optional read as what it holds. Primitive types and `auto` give ""."""
    if node is None:
        return ""
    t = node.type
    if t in ("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"):
        name = node.child_by_field_name("name")
        return _plain(name, src) if name is not None else ""
    if t in ("template_type", "qualified_identifier"):
        target = node
        while target.type == "qualified_identifier" and target.child_by_field_name("name") is not None:
            target = target.child_by_field_name("name")
        if target.type == "template_type" and _plain(target.child_by_field_name("name"), src) in _SMART:
            return _first_type_argument(target, src)
        return _plain(node, src)
    if t in ("type_identifier", "dependent_type"):
        return _plain(node, src)
    return ""                                            # primitive types, auto, decltype


def _first_type_argument(node, src: bytes) -> str:
    args = node.child_by_field_name("arguments")
    first = next((a for a in args.named_children if a.type == "type_descriptor"), None) if args is not None else None
    return _type_name(first.child_by_field_name("type"), src) if first is not None else ""


def _count(arguments) -> int:
    return sum(1 for a in arguments.named_children if a.type != "comment") if arguments is not None else 0


def _parameters(fdecl, src: bytes) -> tuple[list[str], int, int]:
    """Parameter texts, and the fewest and most arguments a call may give."""
    plist = fdecl.child_by_field_name("parameters")
    if plist is None and fdecl.type == "operator_cast":
        inner = fdecl.child_by_field_name("declarator")
        plist = inner.child_by_field_name("parameters") if inner is not None else None
    if plist is None:
        return [], 0, 0
    params, low, high = [], 0, 0
    for p in plist.named_children:
        if p.type == "comment":
            continue
        text = squash_ws(_text(p, src))
        if p.type == "parameter_declaration" and text == "void":
            continue
        params.append(text)
        if p.type.startswith("variadic") or text.endswith("..."):
            high = _ANY[1]
        elif p.type == "optional_parameter_declaration":
            high += 1
        else:
            low += 1
            high += 1
    if any(c.type == "..." for c in plist.children):
        high = _ANY[1]
    return params, low, high


def _is_virtual(node) -> bool:
    if any(c.type == "virtual" for c in node.children):
        return True
    fdecl, _ = _function_declarator(node.child_by_field_name("declarator"))
    return fdecl is not None and any(c.type == "virtual_specifier" for c in fdecl.children)


def _walk(node, skip=frozenset()):
    """Every node below `node` in source order, not entering the node types in `skip`."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed([c for c in n.children if c.type not in skip]))


# == the reader ==

class _Reader:
    def __init__(self, depth: int, c_defs: list[dict]):
        self.depth = depth
        self.parser = Parser(_LANGUAGE) if _LANGUAGE is not None else None
        self.defs: list[dict] = []
        self.nodes: list[tuple] = []                     # per definition: (node, src)
        self.classes: dict[str, dict] = {}               # qualified name -> {bases, fields, virtual, ns}
        self.namespaces: set[str] = set()
        self.aliases: dict[str, tuple[str, list[str]]] = {}
        self.using: dict[str, list[str]] = {}
        self.file_info: dict[str, dict] = {}
        self.prototypes: dict[str, list[str]] = defaultdict(list)
        self.macros: dict[str, str] = {}
        self.c_names: set[str] = set()                   # names declared with C linkage
        self.syntax_errors: list[str] = []
        self.c_defs = c_defs
        self.trees: list = []                            # the trees stay alive until every call is linked
        self._lineage: dict[str, list[str]] = {}

    # -- pass 1: definitions, classes, aliases --
    def read(self, full: str, rel: str) -> None:
        text = util.load_text(full)
        raw_lines = text.split("\n")
        clean = c_lang.blank_out(text)
        ext = os.path.splitext(rel)[1].lower()
        module, role = module_for(rel, self.depth), role_for(rel)
        info = {"module": module, "role": role, "lang": "C++", "ext": ext, "lines_count": clean.count("\n") + 1,
                "includes": [m.group(2) for m in c_lang._INCLUDE.finditer(clean)], "defs_count": 0}
        self.file_info[rel] = info
        self.macros.update(c_lang.macro_bodies(clean))
        if self.parser is None:
            info["not_read"] = PROBLEM
            return
        src = text.encode("utf-8")
        tree = self.parser.parse(src)
        self.trees.append(tree)
        if tree.root_node.has_error:
            info["syntax_errors"] = True
            self.syntax_errors.append(rel)
        using = []
        for node in _walk(tree.root_node, skip=frozenset({"compound_statement"})):
            t = node.type
            if t in _CLASSES and node.child_by_field_name("body") is not None:
                self._class(node, src, rel)
            elif t == "namespace_definition" and node.child_by_field_name("name") is not None:
                scope = _lexical(node, src)[0]
                for part in re.sub(r"\s+", "", _text(node.child_by_field_name("name"), src)).split("::"):
                    scope = scope + [part]
                    self.namespaces.add("::".join(scope))
            elif t in ("type_definition", "alias_declaration"):
                self._alias(node, src)
            elif t == "using_declaration" and any(c.type == "namespace" for c in node.children):
                target = next(iter(node.named_children), None)
                if target is not None:
                    using.append(_plain(target, src))
            elif t in ("declaration", "field_declaration"):
                self._declaration(node, src, rel, ext)
            elif t == "function_definition":
                if self._definition(node, src, rel, raw_lines, module, role):
                    info["defs_count"] += 1
        self.using[rel] = using

    def _class(self, node, src: bytes, rel: str) -> None:
        scope = _lexical(node, src)[0]
        qual = "::".join(scope + [_plain(node.child_by_field_name("name"), src) or "(anonymous)"])
        info = self.classes.setdefault(qual, {"bases": [], "fields": {}, "virtual": set(), "ns": scope, "file": rel})
        clause = next((c for c in node.children if c.type == "base_class_clause"), None)
        if clause is not None:
            info["bases"] += [_plain(c, src) for c in clause.named_children
                              if c.type in ("type_identifier", "qualified_identifier", "template_type")]
        for member in node.child_by_field_name("body").named_children:
            if member.type not in ("field_declaration", "function_definition", "declaration"):
                continue
            fdecl, _ = _function_declarator(member.child_by_field_name("declarator"))
            if fdecl is not None and not _points_to_function(fdecl):
                name = fdecl.child_by_field_name("declarator") if fdecl.type == "function_declarator" else fdecl
                if name is not None and _is_virtual(member):
                    info["virtual"].add(_parts(name, src)[-1])
                continue
            kind = _type_name(member.child_by_field_name("type"), src)
            for decl in member.children_by_field_name("declarator"):
                ident = _declared_name(decl)
                if ident is not None:
                    info["fields"][_text(ident, src)] = kind          # "" when the type is no class

    def _alias(self, node, src: bytes) -> None:
        scope = _lexical(node, src)[0]
        if node.type == "alias_declaration":
            name, target = node.child_by_field_name("name"), node.child_by_field_name("type")
            if target is not None and target.type == "type_descriptor":
                target = target.child_by_field_name("type")
            kind = _type_name(target, src)
            if name is not None and kind:
                self.aliases["::".join(scope + [_plain(name, src)])] = (kind, scope)
            return
        kind = _type_name(node.child_by_field_name("type"), src)
        for decl in node.children_by_field_name("declarator"):
            ident = decl
            while ident is not None and ident.type != "type_identifier":
                ident = _inner(ident) if ident.type not in _NAMES else None
            if ident is not None and kind:
                self.aliases["::".join(scope + [_plain(ident, src)])] = (kind, scope)

    def _declaration(self, node, src: bytes, rel: str, ext: str) -> None:
        """Prototypes (for declarations.json) and the names declared with C linkage."""
        fdecl, _ = _function_declarator(node.child_by_field_name("declarator"))
        if fdecl is None or fdecl.type != "function_declarator":
            return
        name = fdecl.child_by_field_name("declarator")
        if name is None:
            return
        scope, _in_class, _anon, c_linkage, _t = _lexical(node, src)
        parts = _parts(name, src)
        if c_linkage:
            self.c_names.add(parts[-1])
        if ext in HEADER_EXTENSIONS:
            self.prototypes["::".join(scope + parts)].append(rel)

    def _definition(self, node, src: bytes, rel: str, raw_lines: list[str], module: str, role: str) -> bool:
        fdecl, marks = _function_declarator(node.child_by_field_name("declarator"))
        if fdecl is None:
            return False
        name_node = fdecl.child_by_field_name("declarator") if fdecl.type == "function_declarator" else fdecl
        if name_node is None:
            return False
        scope, in_class, anonymous, c_linkage, template = _lexical(node, src)
        parts = _parts(name_node, src)
        start = node.parent if node.parent is not None and node.parent.type == "template_declaration" else node
        first, last = start.start_point[0] + 1, node.end_point[0] + 1
        type_node = node.child_by_field_name("type")
        ret = (squash_ws(_text(type_node, src)) if type_node is not None else "") + marks
        trailing = next((c for c in fdecl.children if c.type == "trailing_return_type"), None)
        if trailing is not None:
            ret = squash_ws(f"{ret} {_text(trailing, src)}")
        params, low, high = _parameters(fdecl, src)
        record = {
            "key": "", "name": parts[-1], "qualname": "", "lang": "C++", "kind": "", "module": module, "role": role,
            "file": rel, "ret": ret, "params": params, "first_line": first, "last_line": last,
            "lines_count": last - first + 1, "file_local": False, "doc": leading_comment(raw_lines, first),
            "call_keys": [], "via_macros": [], "external_calls": [], "ambiguous": [], "indirect_calls": [],
        }
        if template:
            record["template"] = True
        if c_linkage:
            record["c_linkage"] = True
            self.c_names.add(parts[-1])
        if _is_virtual(node):
            record["virtual"] = True
        is_static = any(c.type == "storage_class_specifier" and _text(c, src) == "static" for c in node.children)
        record["_arity"] = (low, high)
        record["_where"] = (scope, parts, "::".join(scope) if in_class else "", anonymous, is_static)
        self.nodes.append((node, src))
        self.defs.append(record)
        return True

    # -- what each definition belongs to, and the indexes pass 2 looks things up in --
    def index(self) -> None:
        self.class_by_short: dict[str, list[str]] = defaultdict(list)
        for q in sorted(self.classes):
            self.class_by_short[q.rsplit("::", 1)[-1]].append(q)
        for d in self.defs:
            scope, parts, lexical_owner, anonymous, is_static = d.pop("_where")
            short = parts[-1]
            owner = lexical_owner or (self._owner_of(parts[:-1], scope) if len(parts) > 1 else "")
            if owner:
                qual, ns = owner + "::" + short, self.classes[owner]["ns"] if owner in self.classes else owner.split("::")[:-1]
                kind = ("constructor" if short == owner.rsplit("::", 1)[-1] else "destructor" if short.startswith("~")
                        else "operator" if short.startswith("operator") else "method")
                d["class"] = owner
            else:
                qual, ns = "::".join(scope + parts), scope + parts[:-1]
                kind = "operator" if short.startswith("operator") else "function"
            d.update(key=f"{d['file']}#{qual}#{d['first_line']}", qualname=qual, kind=kind,
                     file_local=anonymous or (is_static and not owner))
            d["_ns"] = ns
        self.by_qual: dict[str, list[int]] = defaultdict(list)
        self.by_suffix: dict[str, list[int]] = defaultdict(list)
        self.free_by_short: dict[str, list[int]] = defaultdict(list)
        self.methods: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        self.methods_by_short: dict[str, list[int]] = defaultdict(list)
        for i, d in enumerate(self.defs):
            self.by_qual[d["qualname"]].append(i)
            pieces = d["qualname"].split("::")
            for k in range(1, len(pieces) - 1):
                self.by_suffix["::".join(pieces[k:])].append(i)
            if "class" in d:
                self.methods[d["class"]][d["name"]].append(i)
                self.methods_by_short[d["name"]].append(i)
            else:
                self.free_by_short[d["name"]].append(i)
        for q in sorted(self.methods):                   # a class known only from its methods' definitions
            if q not in self.classes and q not in self.class_by_short.get(q.rsplit("::", 1)[-1], []):
                self.class_by_short[q.rsplit("::", 1)[-1]].append(q)
        self.bases = {q: [b for b in (self.find_class(b, info["ns"]) for b in info["bases"]) if b and b != q]
                      for q, info in sorted(self.classes.items())}
        self.derived: dict[str, list[str]] = defaultdict(list)
        for q in sorted(self.bases):
            for b in self.bases[q]:
                self.derived[b].append(q)
        self.c_by_short: dict[str, list[dict]] = defaultdict(list)
        for d in self.c_defs:
            self.c_by_short[d["name"]].append(d)
        known = set(self.free_by_short) | set(self.c_by_short)
        self.macro_map = c_lang.macro_targets(self.macros, known)

    def _owner_of(self, written: list[str], scope: list[str]) -> str:
        """The class a qualified definition (`Controller::clamp`) belongs to; "" for a namespace."""
        name = "::".join(written)
        hit = self._scoped(name, scope, self.classes)
        if hit:
            return hit
        if self._scoped(name, scope, self.namespaces):
            return ""
        candidates = [q for q in self.class_by_short.get(written[-1], []) if q == name or q.endswith("::" + name)]
        if len(candidates) == 1:
            return candidates[0]
        return "::".join(scope + written)                # a class these folders do not define

    def find_class(self, name: str, ns: list[str]) -> str | None:
        """The class a type name means, seen from inside the namespaces `ns`; aliases followed."""
        for _ in range(8):                               # a chain of aliases, never a loop
            name = name.lstrip(":")
            if not name:
                return None
            hit = self._scoped(name, ns, self.classes) or self._scoped(name, ns, self.methods)
            if hit:
                return hit
            alias = self._scoped(name, ns, self.aliases)
            if not alias:
                break
            name, ns = self.aliases[alias]
        candidates = [q for q in self.class_by_short.get(name.rsplit("::", 1)[-1], []) if q == name or q.endswith("::" + name)]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _scoped(name: str, ns: list[str], table) -> str | None:
        for k in range(len(ns), -1, -1):
            q = "::".join(ns[:k] + [name])
            if q in table:
                return q
        return None

    def lineage(self, cls: str) -> list[str]:
        """A class and its base classes, nearest first."""
        if cls not in self._lineage:
            out, queue = [], [cls]
            while queue:
                c = queue.pop(0)
                if c not in out:
                    out.append(c)
                    queue += self.bases.get(c, [])
            self._lineage[cls] = out
        return self._lineage[cls]

    def field_type(self, cls: str, field: str) -> tuple[str | None, bool]:
        """(class of a field's type, whether `cls` or a base has a field of that name)."""
        for c in self.lineage(cls):
            info = self.classes.get(c)
            if info and field in info["fields"]:
                return self.find_class(info["fields"][field], info["ns"]), True
        return None, False

    def is_virtual(self, cls: str, name: str) -> bool:
        return any(name in self.classes.get(c, {}).get("virtual", ()) for c in self.lineage(cls))

    def overrides(self, cls: str, name: str) -> list[dict]:
        out, queue, seen = [], list(self.derived.get(cls, [])), set()
        while queue:
            c = queue.pop(0)
            if c in seen:
                continue
            seen.add(c)
            out += [self.defs[i] for i in self.methods.get(c, {}).get(name, [])]
            queue += self.derived.get(c, [])
        return out

    # -- pass 2: the calls of every definition --
    def link_all(self) -> None:
        for d, (node, src) in zip(self.defs, self.nodes, strict=True):
            _Calls(self, d, node, src).link()
        for d in self.defs:
            if d.get("class") and d["kind"] in ("method", "operator") and self.is_virtual(d["class"], d["name"]):
                below = sorted({o["qualname"] for o in self.overrides(d["class"], d["name"])})
                if below:
                    d["overridden_by"] = below
        for d in self.defs:
            d.pop("_arity", None)
            d.pop("_ns", None)


def choose(options: list[dict], caller: dict, args: int | None) -> tuple[dict, list[dict]]:
    """The definition a call most likely means, and the alternatives when there is a doubt: the
    number of arguments first, then the same file, the same module, and not local to another file."""
    if args is not None and len(options) > 1:
        fitting = [o for o in options if o.get("_arity", _ANY)[0] <= args <= o.get("_arity", _ANY)[1]]
        if len(fitting) == 1:
            return fitting[0], []
        options = fitting or options
    if len(options) == 1:
        return options[0], []
    same_file = [o for o in options if o["file"] == caller["file"]]
    if len(same_file) == 1:
        return same_file[0], []
    for test in (lambda o: o["module"] == caller["module"], lambda o: not o["file_local"]):
        hit = next((o for o in options if test(o)), None)
        if hit is not None:
            return hit, options
    return options[0], options


class _Calls:
    """The calls inside one definition, linked to the definitions they mean."""

    def __init__(self, reader: _Reader, record: dict, node, src: bytes):
        self.r, self.record, self.node, self.src = reader, record, node, src
        self.ns = record["_ns"]
        self.owner = record.get("class")
        self.linked: set[str] = set()
        self.outside: list[str] = []
        self.indirect: list[dict] = []
        self.locals: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.declared: dict[str, list[int]] = defaultdict(list)     # every variable and parameter, any type

    def link(self) -> None:
        body = [c for c in self.node.children if c.type in ("compound_statement", "field_initializer_list", "try_statement")]
        fdecl, _ = _function_declarator(self.node.child_by_field_name("declarator"))
        params = fdecl.child_by_field_name("parameters") if fdecl is not None and fdecl.type == "function_declarator" else None
        for part in ([params] if params is not None else []) + body:
            for n in _walk(part, skip=frozenset({"function_definition"})):
                if n.type in _DECLARATIONS:
                    self._declares(n)
        for part in body:
            for n in _walk(part, skip=frozenset({"function_definition"})):
                t = n.type
                if t == "call_expression":
                    self._call(n)
                elif t == "new_expression":
                    self._construct(_type_name(n.child_by_field_name("type"), self.src),
                                    _count(n.child_by_field_name("arguments")))
                elif t == "declaration":
                    self._declared_objects(n)
                elif t == "field_initializer":
                    self._initializer(n)
        self.record["external_calls"] = self.outside
        self.record["indirect_calls"] = sorted(self.indirect, key=lambda x: (x["line"], x["expr"]))

    # -- what the names in this definition are --
    def _declares(self, n) -> None:
        kind = _type_name(n.child_by_field_name("type"), self.src)
        for decl in n.children_by_field_name("declarator"):
            ident = _declared_name(decl)
            if ident is None:
                continue
            self.declared[_text(ident, self.src)].append(decl.start_byte)
            found = kind or self._made(decl)
            if found:
                self.locals[_text(ident, self.src)].append((decl.start_byte, found))

    def _made(self, decl) -> str:
        """The class an `auto` variable is made from: `Motor(..)`, `Motor{..}`, `new Motor`, `make_unique<Motor>`."""
        value = decl.child_by_field_name("value") if decl.type == "init_declarator" else None
        if value is None:
            return ""
        if value.type in ("new_expression", "compound_literal_expression"):
            return _type_name(value.child_by_field_name("type"), self.src)
        if value.type == "call_expression":
            fn = value.child_by_field_name("function")
            if fn is None:
                return ""
            target = fn
            while target.type == "qualified_identifier" and target.child_by_field_name("name") is not None:
                target = target.child_by_field_name("name")
            if target.type == "template_function" and _plain(target.child_by_field_name("name"), self.src) in _MAKERS:
                return _first_type_argument(target, self.src)
            name = _plain(fn, self.src)
            return name if self.r.find_class(name, self.ns) else ""
        return ""

    def _local(self, ident) -> str:
        seen = [k for pos, k in self.locals.get(_text(ident, self.src), []) if pos < ident.start_byte]
        return seen[-1] if seen else ""

    def _type_of(self, expr) -> str | None:
        """The class of an expression's object, when the text states it."""
        t = expr.type
        if t == "this":
            return self.owner
        if t == "identifier":
            declared = self._local(expr)
            if declared:
                return self.r.find_class(declared, self.ns)
            return self.r.field_type(self.owner, _text(expr, self.src))[0] if self.owner else None
        if t == "field_expression":
            base = self._type_of(expr.child_by_field_name("argument"))
            field = expr.child_by_field_name("field")
            return self.r.field_type(base, _plain(field, self.src))[0] if base and field is not None else None
        if t in ("parenthesized_expression", "pointer_expression"):
            inner = expr.child_by_field_name("argument") or (expr.named_children[0] if expr.named_children else None)
            return self._type_of(inner) if inner is not None else None
        return None

    # -- linking --
    def _link(self, options: list[dict], args: int | None, label: str, via: str | None = None,
              dispatch: bool = True) -> None:
        chosen, alternatives = choose(options, self.record, args)
        if chosen["key"] in self.linked:
            return
        self.linked.add(chosen["key"])
        self.record["call_keys"].append(chosen["key"])
        if via:
            self.record["via_macros"].append([via, chosen["name"]])
        listed = [o["key"] for o in alternatives]
        if dispatch and chosen.get("class") and chosen["kind"] in ("method", "operator") and                 self.r.is_virtual(chosen["class"], chosen["name"]):
            overrides = [o["key"] for o in self.r.overrides(chosen["class"], chosen["name"])]
            if 0 < len(overrides) <= LISTED_AT_CALL:
                listed = (listed or [chosen["key"]]) + [k for k in overrides if k not in listed]
        if listed:
            self.record["ambiguous"].append([label, listed])

    def _outside(self, name: str) -> None:
        if name and name not in self.outside:
            self.outside.append(name)

    def _methods(self, cls: str, name: str) -> list[dict]:
        for c in self.r.lineage(cls):
            found = self.r.methods.get(c, {}).get(name)
            if found:
                return [self.r.defs[i] for i in found]
        return []

    def _call(self, n) -> None:
        fn = n.child_by_field_name("function")
        if fn is None:
            return
        args = _count(n.child_by_field_name("arguments"))
        if fn.type == "template_function" and fn.child_by_field_name("name") is not None:
            fn = fn.child_by_field_name("name")
        t = fn.type
        if t == "identifier":
            self._plain_call(fn, args)
        elif t == "qualified_identifier":
            self._qualified_call(fn, args)
        elif t == "field_expression":
            self._member_call(fn, args)
        elif t == "lambda_expression":
            return                                        # its body is read as part of this definition
        elif t == "parenthesized_expression" and self._is_cast(fn):
            return                                        # (HBRUSH)(x) is a cast written like a call
        else:
            self.indirect.append({"expr": re.sub(r"\s+", "", _text(fn, self.src))[:80], "line": fn.start_point[0] + 1})

    def _is_cast(self, paren) -> bool:
        """`(Name)(...)` where Name is no variable, parameter or field here: a C-style cast to a type,
        as the C reader reads it. `(*handler)(...)` and `(callback)(...)` stay calls through a pointer."""
        inner = paren.named_children
        if len(inner) != 1 or inner[0].type != "identifier":
            return False
        name = _text(inner[0], self.src)
        return not self.declared.get(name) and not (self.owner and self.r.field_type(self.owner, name)[1])

    def _plain_call(self, fn, args: int) -> None:
        name = _text(fn, self.src)
        if name in _NOT_CALLS:
            return
        r = self.r
        if any(pos < fn.start_byte for pos in self.declared.get(name, ())) or                 (self.owner and r.field_type(self.owner, name)[1]):
            # a variable or a field called like a function: a lambda, a std::function, a function pointer
            self.indirect.append({"expr": name, "line": fn.start_point[0] + 1})
            return
        if name not in r.free_by_short and name in r.macro_map and not (self.owner and self._methods(self.owner, name)):
            target = r.macro_map[name]
            options = [r.defs[i] for i in r.free_by_short.get(target, [])] or r.c_by_short.get(target, [])
            if options:
                self._link(options, None, target, via=name)
                return
        if self.owner:
            found = self._methods(self.owner, name)
            if found:
                self._link(found, args, name)
                return
        scopes = [self.ns[:k] for k in range(len(self.ns), -1, -1)] + [u.split("::") for u in r.using.get(self.record["file"], [])]
        for ns in scopes:
            free = [r.defs[i] for i in r.by_qual.get("::".join(ns + [name]), []) if "class" not in r.defs[i]]
            if free:
                self._link(free, args, name)
                return
        if name in r.free_by_short:
            self._link([r.defs[i] for i in r.free_by_short[name]], args, name)
            return
        cls = r.find_class(name, self.ns)
        if cls and self._construct(cls, args):
            return
        if name in r.c_by_short:
            self._link(r.c_by_short[name], args, name)
            return
        self._outside(name)

    def _qualified_call(self, fn, args: int) -> None:
        r = self.r
        parts = _parts(fn, self.src)
        written, name = "::".join(parts), parts[-1]
        absolute = _text(fn, self.src).lstrip().startswith("::")
        for ns in ([[]] if absolute else [self.ns[:k] for k in range(len(self.ns), -1, -1)]):
            found = r.by_qual.get("::".join(ns + parts))
            if found:
                self._link([r.defs[i] for i in found], args, written, dispatch=False)
                return
        owner = r.find_class("::".join(parts[:-1]), self.ns) if len(parts) > 1 else None
        if owner:
            found = self._methods(owner, name)
            if found:
                self._link(found, args, written, dispatch=False)       # Base::f() calls that very f
                return
        if written in r.by_suffix:
            self._link([r.defs[i] for i in r.by_suffix[written]], args, written, dispatch=False)
            return
        cls = r.find_class(written, self.ns)
        if cls and self._construct(cls, args):
            return
        self._outside(written)

    def _member_call(self, fn, args: int) -> None:
        r = self.r
        field = fn.child_by_field_name("field")
        name = _plain(field, self.src) if field is not None else ""
        receiver = fn.child_by_field_name("argument")
        cls = self._type_of(receiver) if receiver is not None else None
        line = fn.start_point[0] + 1
        expr = re.sub(r"\s+", "", _text(fn, self.src))[:80]
        if cls:
            found = self._methods(cls, name)
            if found:
                self._link(found, args, f"{cls}::{name}")
            elif r.field_type(cls, name)[1]:
                self.indirect.append({"expr": expr, "line": line})        # a function pointer kept in a field
            else:
                self._outside(f"{cls}::{name}")
            return
        declared = self._local(receiver) if receiver is not None and receiver.type == "identifier" else ""
        if declared:
            self._outside(f"{declared}::{name}")                           # an object of a type from outside
            return
        candidates = sorted({r.defs[i]["qualname"] for i in r.methods_by_short.get(name, [])})
        if candidates:
            found = {"expr": expr, "line": line, "method": name, "candidates_count": len(candidates)}
            if len(candidates) <= LISTED_AT_CALL:
                found["candidates"] = candidates
            self.indirect.append(found)
        else:
            self._outside(name)

    def _construct(self, cls_name: str, args: int | None) -> bool:
        """A call to a constructor of the class `cls_name`, when these folders define one."""
        if not cls_name:
            return False
        cls = self.r.find_class(cls_name, self.ns) or cls_name
        found = [self.r.defs[i] for i in self.r.methods.get(cls, {}).get(cls.rsplit("::", 1)[-1], [])]
        if found:
            self._link(found, args, cls)
            return True
        return False

    def _declared_objects(self, n) -> None:
        """`Motor m(2);`, `Motor m{2};` and `Motor m;` build an object: a call to its constructor."""
        kind = _type_name(n.child_by_field_name("type"), self.src)
        if not kind:
            return
        for decl in n.children_by_field_name("declarator"):
            if decl.type == "identifier":
                self._construct(kind, 0)
            elif decl.type == "init_declarator":
                inner, value = decl.child_by_field_name("declarator"), decl.child_by_field_name("value")
                if inner is not None and inner.type == "identifier" and value is not None and \
                        value.type in ("argument_list", "initializer_list"):
                    self._construct(kind, _count(value))

    def _initializer(self, n) -> None:
        """`: Base(1), motor_(2)` in a constructor: the base class's, or the field's, constructor."""
        target = next((c for c in n.named_children if c.type in ("field_identifier", "type_identifier",
                                                                "qualified_identifier", "template_type")), None)
        value = next((c for c in n.named_children if c.type in ("argument_list", "initializer_list")), None)
        if target is None or not self.owner:
            return
        name = _plain(target, self.src)
        field_cls, is_field = self.r.field_type(self.owner, name)
        if is_field:
            if field_cls:
                self._construct(field_cls, _count(value))
            return
        self._construct(name, _count(value))


def analyze(root: str, files: list[tuple[str, str]], depth: int, c_defs: list[dict] | None = None):
    """Read every C++ file of one code base. Returns (defs, file_info, extras). `c_defs` are the
    C functions of the same code base, which C++ code may call."""
    reader = _Reader(depth, c_defs or [])
    for full, rel in files:
        reader.read(full, rel)
    reader.index()
    reader.link_all()
    extras = {
        "prototypes": {n: sorted(set(v)) for n, v in reader.prototypes.items()},
        "macro_map": reader.macro_map,
        "c_linkage": sorted(reader.c_names),
        "cpp": {
            "parser": "" if PROBLEM else parser_name(),
            "problem": PROBLEM,
            "files_count": len(files),
            "headers_read_as_cpp_count": sum(1 for _, rel in files if rel.lower().endswith(".h")),
            "classes_count": len(reader.classes),
            "files_with_syntax_errors_count": len(reader.syntax_errors),
            "files_with_syntax_errors": sorted(reader.syntax_errors)[:50],
        },
    }
    return reader.defs, reader.file_info, extras


def link_c_callers(c_defs: list[dict], cpp_defs: list[dict], c_names: list[str]) -> None:
    """Calls from C into C++ functions with C linkage (`extern "C"`), which C code can call by name."""
    by_name: dict[str, list[dict]] = defaultdict(list)
    wanted = set(c_names)
    for d in cpp_defs:
        if "class" not in d and (d.get("c_linkage") or d["name"] in wanted):
            by_name[d["name"]].append(d)
    for record in c_defs:
        kept = []
        for name in record["external_calls"]:
            options = by_name.get(name)
            if not options:
                kept.append(name)
                continue
            chosen, alternatives = choose(options, record, None)
            if chosen["key"] not in record["call_keys"]:
                record["call_keys"].append(chosen["key"])
            if alternatives:
                record["ambiguous"].append([name, [o["key"] for o in alternatives]])
        record["external_calls"] = kept
