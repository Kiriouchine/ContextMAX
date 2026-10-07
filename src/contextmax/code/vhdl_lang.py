"""VHDL: entities, ports, architectures, and the instantiation tree that takes the place of calls.

VHDL ignores case, so names are compared case-folded while the spelling in the source is kept
for display. `--` comments are blanked first, newlines kept. The design is everything below
the RTL entity that reaches the most others and that no RTL entity places; every other
entity is a testbench, simulation-only, or unplaced.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from contextmax import util
from contextmax.code.common import line_at, line_offsets, squash_ws

EXTENSIONS = {".vhd", ".vhdl"}

_NAME = r"[a-z]\w*"
_ENTITY = re.compile(rf"\b entity \s+ ({_NAME}) \s+ is \b", re.IGNORECASE | re.VERBOSE)
_ARCHITECTURE = re.compile(rf"\b architecture \s+ ({_NAME}) \s+ of \s+ ({_NAME}) \s+ is \b", re.IGNORECASE | re.VERBOSE)
_USE = re.compile(rf"\b use \s+ (?P<library> {_NAME}) \. (?P<unit> {_NAME}) (?: \. \w+ )? \s* ;", re.IGNORECASE | re.VERBOSE)
_SUBPROGRAM = re.compile(rf"\b (?P<kind> function | procedure) \s+ (?P<name> {_NAME})", re.IGNORECASE | re.VERBOSE)
_PROCESS = re.compile(r"(?<! [.\w] ) process \b", re.IGNORECASE | re.VERBOSE)
_COMPONENT = re.compile(rf"\b component \s+ ({_NAME})", re.IGNORECASE | re.VERBOSE)
_INSTANCE = re.compile(rf"""
    ^ [\t ]* (?P<label> {_NAME}) [\t ]* : [\t ]*
    (?: entity [\t ]+ (?: {_NAME} \. )? (?P<entity> {_NAME})            # entity work.name
      | (?: component [\t ]+ )? (?P<component> {_NAME}) )               # or a component
    [\r\n\t ]+ (?: generic | port ) [\t ]+ map
""", re.IGNORECASE | re.MULTILINE | re.VERBOSE)
# One line of a port or generic clause. The mode is a whole word followed by the type, so
# `inout` is not read as `in`, and a type such as `integer` keeps its first letters.
_PORT_LINE = re.compile(rf"""
    ^ [\t ]* (?P<names> {_NAME} (?: [\t ]* , [\t ]* {_NAME} )* ) [\t ]* : [\t ]*
    (?: (?P<mode> inout | in | out | buffer ) [\t ]+ )?
    (?P<type> [^\n;]+ )
""", re.IGNORECASE | re.MULTILINE | re.VERBOSE)
_NEXT_UNIT = re.compile(r"\b (entity | architecture | package | configuration) \s", re.IGNORECASE | re.VERBOSE)
_PORT_OPEN = re.compile(r"\b port \s* \(", re.IGNORECASE | re.VERBOSE)
_GENERIC_OPEN = re.compile(r"\b generic \s* \(", re.IGNORECASE | re.VERBOSE)
# Words that can stand before a colon without labelling an instance.
NOT_INSTANCE_LABELS = frozenset("begin case elsif end for generate if process when while with".split())
# Folders that sort a block's files; the folder above them names the block.
SORTING_DIRS = frozenset("behavior behaviour hdl interface rtl sim src struct tb".split())
_TESTBENCH_HINTS = ("_tb", "/tb/", "testbench")
_MODES = ("in", "out", "inout", "buffer", "")


def erase_comments(text: str) -> str:
    """`--` comments become spaces up to the line end; string literals are skipped untouched."""
    return "\n".join(_erase_comment_of(line) for line in text.split("\n"))


def _erase_comment_of(line: str) -> str:
    """One line with its comment blanked. A string literal never runs past its line, and an
    unclosed one hides the rest of the line."""
    at = 0
    while True:
        dash, quote = line.find("--", at), line.find('"', at)
        if dash < 0:
            return line
        if 0 <= quote < dash:
            close = line.find('"', quote + 1)
            if close < 0:
                return line
            at = close + 1
            continue
        return line[:dash] + "".join(ch if ch == "\t" else " " for ch in line[dash:])


def block_name(rel: str) -> str:
    """The folder that holds a block's rtl/tb/interface folders names the block."""
    parts = rel.split("/")
    for k in range(1, len(parts)):
        if parts[k].lower() in SORTING_DIRS:
            return parts[k - 1]
    return parts[0] if len(parts) > 1 else "(top)"


def vhdl_role(rel: str) -> str:
    low = rel.lower()
    if low.startswith("tb/") or any(hint in low for hint in _TESTBENCH_HINTS):
        return "testbench"
    return "sim" if low.startswith("sim/") or "/sim" in low else "rtl"


def _type_text(raw: str) -> str:
    """A port's type as written, without the clause's own closing parenthesis when the last
    port shares its line with it."""
    text = squash_ws(raw)
    if text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].rstrip()
    return text[:60]


def _port_list(segment: str) -> list[dict]:
    found = []
    for m in _PORT_LINE.finditer(segment):
        mode, kind = (m["mode"] or "").lower(), _type_text(m["type"])
        found.extend({"name": name.strip(), "dir": mode, "type": kind} for name in m["names"].split(","))
    return found


def _span(text: str, start: int, until: re.Pattern) -> tuple[str, int]:
    """The text from `start` to the next match of `until` (or the end), and where it stops."""
    m = until.search(text, start + 1)
    stop = m.start() if m else len(text)
    return text[start:stop], stop


def _entity(name: str, clean: str, at: int, starts: list[int], rel: str, block: str, role: str) -> dict:
    unit, _ = _span(clean, at, _NEXT_UNIT)
    ports, generics = [], []
    port_at = _PORT_OPEN.search(unit)
    if port_at:
        rest = unit[port_at.end():]
        cut = rest.lower().find("end ")
        ports = _port_list(rest if cut < 0 else rest[:cut])
    generic_at = _GENERIC_OPEN.search(unit)
    if generic_at:
        stop = port_at.start() if port_at else generic_at.end() + 400
        generics = [p["name"] for p in _port_list(unit[generic_at.end():stop])]
    return {"name": name, "module": block, "role": role, "file": rel, "line": line_at(starts, at),
            "ports_count": len(ports), "ports": ports, "generics": generics,
            "placed_by": [], "places": [], "_design_parents": []}


class _Reading:
    """Everything collected from the files of one code base."""

    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.architectures: list[dict] = []
        self.file_info: dict[str, dict] = {}
        self.instances: list[tuple] = []
        self.uses: Counter = Counter()
        self.subprograms: list[dict] = []

    def read(self, full: str, rel: str) -> None:
        clean = erase_comments(util.load_text(full))
        starts = line_offsets(clean)
        block, role = block_name(rel), vhdl_role(rel)
        entity_keys, arch_names = [], []
        for m in _ENTITY.finditer(clean):
            self.entities[m.group(1).lower()] = _entity(m.group(1), clean, m.start(), starts, rel, block, role)
            entity_keys.append(m.group(1).lower())
        for m in _ARCHITECTURE.finditer(clean):
            self.architectures.append(self._architecture(m, clean, starts, rel, block, role))
            arch_names.append(m.group(1))
        self.uses.update(f"{u['library']}.{u['unit']}" for u in _USE.finditer(clean))
        self.subprograms.extend(dict(kind=s["kind"].lower(), name=s["name"], file=rel, line=line_at(starts, s.start()),
                                     module=block) for s in _SUBPROGRAM.finditer(clean))
        self.file_info[rel] = {"module": block, "role": role, "lang": "VHDL", "lines_count": clean.count("\n") + 1,
                               "entities": entity_keys, "architectures": arch_names}

    def _architecture(self, m, clean: str, starts: list[int], rel: str, block: str, role: str) -> dict:
        name, owner = m.group(1, 2)
        body, stop = _span(clean, m.start(), _ARCHITECTURE)
        arch = {"name": name, "for_entity": owner, "module": block, "role": role, "file": rel,
                "first_line": line_at(starts, m.start()), "last_line": line_at(starts, stop),
                "processes_count": len(_PROCESS.findall(body)),
                "components_declared_count": len({c.lower() for c in _COMPONENT.findall(body)}),
                "instances": []}
        for inst in _INSTANCE.finditer(body):
            label, placed = inst["label"], inst["entity"] or inst["component"]
            if placed and label.lower() not in NOT_INSTANCE_LABELS:
                line = line_at(starts, m.start() + inst.start())
                arch["instances"].append(dict(label=label, component=placed, line=line))
                self.instances.append((owner.lower(), placed.lower(), label, rel, line))
        return arch


def _link(entities: dict, instances: list[tuple]) -> tuple[list[dict], Counter]:
    """Connect each instance to its entity; count the names no entity answers to."""
    placed, missing = [], Counter()
    for parent, child, label, rel, line in instances:
        if child not in entities:
            missing[child] += 1
            continue
        if parent in entities:
            entities[parent]["places"].append(child)
            entities[child]["placed_by"].append(parent)
            if entities[parent]["role"] == "rtl":
                entities[child]["_design_parents"].append(parent)
        placed.append(dict(parent=parent, child=child, label=label, file=rel, line=line))
    placed.sort(key=lambda r: (r["file"], r["line"], r["label"]))
    for e in entities.values():
        e["places"] = sorted(set(e["places"]))
        e["placed_by"] = sorted(set(e["placed_by"]))
        e["children_count"] = len(e["places"])
        e["parents_count"] = len(e["placed_by"])
        e["rtl_parents_count"] = len(set(e.pop("_design_parents")))
    return placed, missing


def _below(entities: dict, start: str) -> set:
    """`start` and every entity placed under it, directly or not."""
    seen, todo = set(), [start]
    while todo:
        key = todo.pop()
        if key in entities and key not in seen:
            seen.add(key)
            todo += entities[key]["places"]
    return seen


def _class_of(entity: dict, inside_design: bool) -> str:
    if entity["role"] != "rtl":
        return "testbench"
    if inside_design:
        return "design"
    return "sim-only" if entity["parents_count"] else "orphan"


def _classify(entities: dict) -> tuple[str | None, set]:
    roots = sorted(k for k, e in entities.items() if e["role"] == "rtl" and e["rtl_parents_count"] == 0)
    top = max(roots, key=lambda k: (len(_below(entities, k)), k), default=None)
    design = _below(entities, top) if top else set()
    for key, e in entities.items():
        e["classification"] = _class_of(e, key in design)
        e["in_hdl_design"] = e["classification"] == "design"
    return top, design


def _blocks(entities: dict, placed: list[dict]) -> dict:
    across: dict[str, Counter] = defaultdict(Counter)
    for r in placed:
        upper = entities[r["parent"]]["module"] if r["parent"] in entities else None
        lower = entities[r["child"]]["module"]
        if upper and upper != lower:
            across[upper][lower] += 1
    members: dict[str, list] = defaultdict(list)
    for e in entities.values():
        members[e["module"]].append(e)
    return {block: {"name": block, "entities_count": len(group),
                    "rtl_count": sum(1 for e in group if e["role"] == "rtl"),
                    "needs": dict(sorted(across.get(block, {}).items()))}
            for block, group in sorted(members.items())}


def _names_where(entities: dict, keep) -> list[str]:
    return sorted(e["name"] for e in entities.values() if keep(e))


def _by_count(counts: dict) -> list[tuple]:
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def map_vhdl(root: str, files: list[tuple[str, str]], out: Path, target: dict) -> dict:
    """Read the VHDL of one code base, write its hdl-* files and guide, return the overview."""
    reading = _Reading()
    for full, rel in files:
        reading.read(full, rel)
    entities = reading.entities
    placed, missing = _link(entities, reading.instances)
    top, design = _classify(entities)
    blocks = _blocks(entities, placed)
    by_key = [entities[k] for k in sorted(entities)]

    out.mkdir(parents=True, exist_ok=True)
    util.save_jsonl(out / "hdl-entities.jsonl", by_key)
    util.save_json(out / "hdl-architectures.json", sorted(reading.architectures, key=lambda a: (a["file"], a["first_line"])))
    util.save_json(out / "hdl-tree.json", placed)
    util.save_json(out / "hdl-name-lookup.json", {e["name"]: {k: e[k] for k in ("file", "line", "module", "role")}
                                                  for e in by_key})
    util.save_json(out / "hdl-uses.json", _by_count(reading.uses))
    util.save_json(out / "hdl-unmatched.json", _by_count(missing))
    util.save_json(out / "hdl-unplaced.json", [
        {k: e[k] for k in ("name", "classification", "file", "line", "ports_count", "module")}
        for e in by_key if e["classification"] in ("orphan", "sim-only")])
    util.save_json(out / "hdl-functions.json", sorted(reading.subprograms, key=lambda f: (f["file"], f["line"])))
    util.save_json(out / "hdl-modules.json", blocks)
    util.save_json(out / "hdl-files.json", dict(sorted(reading.file_info.items())))

    rtl_tops = _names_where(entities, lambda e: e["role"] == "rtl" and e["rtl_parents_count"] == 0)
    overview = {
        "target": target["name"],
        "files_count": len(files),
        "entities_count": len(entities),
        "architectures_count": len(reading.architectures),
        "instantiations_count": len(placed),
        "unresolved_instances_count": sum(missing.values()),
        "functions_count": len(reading.subprograms),
        "top_entities_count": len(rtl_tops),
        "leaf_entities_count": sum(1 for e in entities.values() if e["role"] == "rtl" and not e["children_count"]),
        "modules_count": len(blocks),
        "top_level_entities": rtl_tops,
        "hdl_top": entities[top]["name"] if top else None,
        "design_entities_count": len(design),
        "unplaced_entities": _names_where(entities, lambda e: e["classification"] == "orphan"),
        "test_entities": _names_where(entities, lambda e: e["classification"] == "sim-only"),
    }
    util.save_json(out / "hdl-overview.json", overview)
    util.save_text(out / "hdl-guide.md", _guide(target, overview, blocks, entities))
    return overview


def _mode_summary(ports: list[dict]) -> str:
    counts = Counter(p["dir"] for p in ports)
    named = [f"{mode or 'mode not written'} {counts[mode]}" for mode in _MODES if counts[mode]]
    return f"{len(ports)}" + (f" ({', '.join(named)})" if named else "")


def _guide(target: dict, overview: dict, blocks: dict, entities: dict) -> str:
    """The VHDL map as one page a person or an AI agent can read from top to bottom."""
    top = overview["hdl_top"]
    top_text = f"`{top}`, with {overview['design_entities_count']} entities in the design" if top else "none found"
    out = [f"# VHDL guide: {target.get('label', target['name'])}", "",
           "Built by ContextMAX from the VHDL files alone. In VHDL the call graph is the instantiation "
           "hierarchy: which entity places which. Every entity below has its file and line.", "",
           "| | |", "|---|---|",
           f"| Entities | {overview['entities_count']} |",
           f"| Architectures | {overview['architectures_count']} |",
           f"| Instances | {overview['instantiations_count']} placed; {overview['unresolved_instances_count']} of a "
           "name with no entity in these files |",
           f"| Design top | {top_text} |",
           "", "## Top entities", "", "Nothing in the RTL places these.", "",
           "| Entity | File | Line | Places | Ports |", "|---|---|--:|--:|--:|"]
    for name in overview["top_level_entities"]:
        e = entities[name.lower()]
        out.append(f"| {e['name']} | `{e['file']}` | {e['line']} | {e['children_count']} | {e['ports_count']} |")
    node = {key: f"E{n}" for n, key in enumerate(sorted(entities))}
    out += ["", "## How the entities place each other", "", "```mermaid", "flowchart TD"]
    out += [f'  {node[key]}["{entities[key]["name"]}"]' for key in sorted(entities)]
    out += [f"  {node[key]} --> {node[child]}" for key in sorted(entities) for child in entities[key]["places"]]
    out += ["```", "", "## Blocks", "", "| Block | Entities | of which RTL | Places entities of |", "|---|--:|--:|---|"]
    for name, b in sorted(blocks.items()):
        needs = ", ".join(f"{other} ({n})" for other, n in _by_count(b["needs"]))
        out.append(f"| {name} | {b['entities_count']} | {b['rtl_count']} | {needs} |")
    out += ["", "## Entities", ""]
    for key in sorted(entities):
        e = entities[key]
        out += [f"### {e['name']}", "", f"`{e['file']}` line {e['line']} · {e['role']} · {e['classification']}", ""]
        if e["generics"]:
            out.append("- generics: " + ", ".join(e["generics"]))
        out.append("- ports: " + _mode_summary(e["ports"]))
        if e["places"]:
            out.append("- places: " + ", ".join(entities[c]["name"] for c in e["places"]))
        if e["placed_by"]:
            out.append("- placed by: " + ", ".join(entities[p]["name"] for p in e["placed_by"]))
        out.append("")
    out += ["## Reading the other files (for an AI agent)", "",
            "| File | Holds |", "|---|---|",
            "| `hdl-name-lookup.json` | entity name to `{file, line, module, role}` |",
            "| `hdl-entities.jsonl` | one entity per line: ports with `dir` and `type`, generics, `places`, "
            "`placed_by`, `classification` |",
            "| `hdl-tree.json` | `{parent, child, label, file, line}` for every instance |",
            "| `hdl-architectures.json` | per architecture: process count, declared components, instances with lines |",
            "| `hdl-unplaced.json` | RTL entities outside the design: unplaced ones, and those only a testbench places |",
            "| `hdl-unmatched.json` | instantiated names with no entity in these files, with counts |",
            "| `hdl-functions.json`, `hdl-uses.json` | functions and procedures with their lines; `use` clauses with counts |",
            "", "Open an entity with its `file` and `line`, under the code base's folder."]
    return "\n".join(out)
