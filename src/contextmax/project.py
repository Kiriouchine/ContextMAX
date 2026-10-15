"""A project: the folders a person chose, the words that describe them, and where the index lives.

The project file (`project.json`) is the only thing a person edits. Everything else in
the working folder is generated from it and from the folders it names. The engine knows
no project's vocabulary: categories, priorities, product tags, document IDs and the
lifecycle stages all come from this file, with neutral defaults.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path

from contextmax import util

SCHEMA = 1
SKIP_MARKER = ".contextmax-skip"
HOLDS = ("documents", "code", "both")

def _words(*parts: str) -> str:
    """A rule as a regex: any of these words or word starts. Each rule only answers 'does it match?',
    so the order of the words does not matter; they are kept in alphabetical order."""
    return "|".join(parts)


# Topic rules are tried in order on the lower-cased relative path; the first rule that matches wins.
# They are deliberately plain words a person can read and change in project.json.
DEFAULT_TOPICS = [
    {"category": "Risk analysis", "path": _words(r"\brisk", "fmea", "hazard")},
    {"category": "Requirements", "path": _words(r"\bprd\b", r"\bspecs?\b", r"\bsrs\b", r"\bstandards?\b", "requirement",
                                                "specification")},
    {"category": "Testing", "path": _words(r"\btesting\b", r"\btests?\b", "qualification", "test ?plan", "test ?report",
                                           "validation", "verification")},
    {"category": "Manufacturing", "path": _words(r"\bbom\b", "assembly", "factory", "manufactur", "packaging",
                                                 "production", "supplier")},
    {"category": "EMC", "path": _words(r"\bemc\b", "precompliance")},
    {"category": "Design", "path": _words("architecture", "decomposition", "design", "interface", "schematic")},
    {"category": "Project management", "path": _words(r"\bplan\b", "budget", "deliverable", "milestone", "minutes",
                                                      "planning", "project", "roadmap", "status")},
    {"category": "Corrective action", "path": _words(r"\bcapa\b", "corrective")},
]

# Lifecycle stages are the columns of the document map, left to right.
DEFAULT_STAGES = ["Requirements", "Design", "Verification", "Risk", "Production", "Project", "Tools", "General"]

# Which stage a catalogue category belongs to. Others are decided by the name rules below.
DEFAULT_STAGE_OF_CATEGORY = {
    "Requirements": "Requirements",
    "Design": "Design",
    "CAD": "Design",
    "Testing": "Verification",
    "EMC": "Risk",
    "Risk analysis": "Risk",
    "Corrective action": "Risk",
    "Manufacturing": "Production",
    "Project management": "Project",
}

# For documents whose category says little ("Document"): the file name decides. First match wins.
DEFAULT_NAME_RULES = [
    {"stage": "Requirements", "pattern": _words(r"\b(?:crs|prd|srs|urs)\b", r"\bspecs?\b", "requirement",
                                                "specification")},
    {"stage": "Design", "pattern": _words(r"\bdesign\b", r"\bicd\b", r"\bsad\b", "architect", "concept",
                                          "detailed[ _-]?design", "interface")},
    {"stage": "Verification", "pattern": _words(r"\bprocedure\b", r"\bprotocol\b", "qualification",
                                                "test[ _-]?(?:case|plan|protocol|report|spec)", "validat", "verificat")},
    {"stage": "Risk", "pattern": _words(r"\bcapa\b", r"\bd?fmea\b", r"\bemc\b", r"\brisk\b", "hazard",
                                        "impact[ _-]?assessment")},
    {"stage": "Production", "pattern": _words(r"\bbom\b", r"\bqa\b", "assembly", "manufactur", "packaging",
                                              "production", "supplier")},
    {"stage": "Project", "pattern": _words(r"\bproject\b", r"\breview\b", "charter", "kick[ _-]?off", "meeting",
                                           "minutes", "planning", "presentation", "roadmap", "slides", "status")},
    {"stage": "Tools", "pattern": _words(r"\btools?\b", "install", "manual", "readme", "toolbox", "user[ _-]?guide")},
]

# Workbooks: the name states the purpose more reliably than the folder they were filed in.
DEFAULT_SHEET_RULES = [
    {"stage": "Production", "pattern": _words(r"\bcost\b", r"\bprice\b", r"\bquotation\b")},
    {"stage": "Design", "pattern": _words("accurac", "budget", "calculat", "compute", "damping", "dissipat", "inertia",
                                          "kinemat", "sizing", "stiffness", "toleran")},
    {"stage": "Risk", "pattern": _words(r"\brisk\b", "failure[ _-]?mode", "fmea", "hazard", "mtbf", "reliab")},
    {"stage": "Production", "pattern": _words(r"\bavl\b", r"\bbom\b", "assembl", "manufactur", "packag", "packing",
                                              "production", "supplier")},
    {"stage": "Verification", "pattern": _words("measure", "regression", "review[ _-]?form", "test", "traceab",
                                                "valid", "verif")},
    {"stage": "Requirements", "pattern": _words(r"\breq\b", r"\bsrs\b", r"\burs\b", "compliance", "requirement")},
    {"stage": "Tools", "pattern": _words("template", "toolbox")},
    {"stage": "Project", "pattern": _words("effort", "estimation", "gantt", "meeting", "milestone", "plan(?:ning)?",
                                           "roadmap", "schedule", "status")},
]

# Requirement identifiers recognised next to a "shall"; a project adds its own. These are read out
# of the text, so here the order of the prefixes is kept as it is (it decides "SWR" against "SWREQ").
_REQUIREMENT_PREFIXES = ("SWR", "SYS", "REQ", "HWR", "SRS", "SWREQ", "FR", "NFR", "UR", "SR")
DEFAULT_REQUIREMENT_IDS = [
    r"\b(?:" + "|".join(_REQUIREMENT_PREFIXES) + r")[-_ ]?\d{1,5}\b",
    r"\[[A-Z]{2,6}[-_]?\d{1,5}\]",
]

DEFAULT_VOCABULARY = {
    "topics": DEFAULT_TOPICS,
    "stages": DEFAULT_STAGES,
    "stage_of_category": DEFAULT_STAGE_OF_CATEGORY,
    "stage_name_rules": DEFAULT_NAME_RULES,
    "stage_sheet_rules": DEFAULT_SHEET_RULES,
    "requirement_id_patterns": DEFAULT_REQUIREMENT_IDS,
    # A naming convention for file names that carries a document type and a code module, for example
    # {"pattern": "([A-Z]{2,5})-([A-Z]{2,8})-\\d{3}", "types": {"SPEC": "Requirements"},
    #  "modules": {"MOTOR": "motor"}}. Off unless a project sets it.
    "convention": None,
    # Words in prose that place a document on a part of the code: {"step response": "control"}.
    # The code's own module names are added automatically.
    "topic_words": {},
    # [{"label": "1-source", "folder": "Firmware", "path": "^src/"},
    #  {"label": "2-key-design", "doc_number": "DOC-1001"}]
    "priorities": [],
    # [{"tag": "Gen2", "pattern": "gen[ _]?2"}]
    "products": [],
    # Regular expressions for document numbers that appear in file names and text.
    "doc_number_patterns": [],
    # Extra unit spellings: {"sekunden": "s"}
    "units": {},
    # Label words in another language, folded to one spelling: {"vitesse": "speed"}
    "label_aliases": {},
    # Documents whose name matches this are read even in the narrow "design" scope.
    "design_doc_pattern": _words("accuracy", "budget", "design", "interface", "requirement", "specification"),
}


@dataclass(frozen=True)
class Folder:
    name: str
    path: str
    holds: str = "both"

    @property
    def holds_documents(self) -> bool:
        return self.holds in ("documents", "both")

    @property
    def holds_code(self) -> bool:
        return self.holds in ("code", "both")


class Project:
    """A loaded project.json plus the working folder it belongs to."""

    def __init__(self, workspace: Path, data: dict):
        self.workspace = Path(workspace)
        self.data = data

    # == identity ==
    @property
    def name(self) -> str:
        return self.data.get("name") or self.workspace.name

    @property
    def slug(self) -> str:
        return self.data.get("slug") or util.slugify(self.name)

    @property
    def folders(self) -> list[Folder]:
        out = []
        for f in self.data.get("folders", []):
            out.append(Folder(name=f["name"], path=f["path"], holds=f.get("holds", "both")))
        return out

    @property
    def vocabulary(self) -> dict:
        voc = copy.deepcopy(DEFAULT_VOCABULARY)
        voc.update(self.data.get("vocabulary") or {})
        return voc

    @property
    def code_targets(self) -> list[dict]:
        """Each code base that gets its own map.

        By default every folder that holds code is one code base. A project may instead
        list targets explicitly: {"name": "main-app", "folder": "Firmware", "subpath": "app"}.
        """
        explicit = self.data.get("code_targets")
        by_name = {f.name: f for f in self.folders}
        targets = []
        if explicit:
            for t in explicit:
                folder = by_name.get(t["folder"])
                if not folder:
                    continue
                root = Path(folder.path) / t.get("subpath", "")
                targets.append({"name": util.slugify(t["name"]), "label": t["name"], "root": str(root),
                                "folder": folder.name})
        else:
            for f in self.folders:
                if f.holds_code:
                    targets.append({"name": util.slugify(f.name), "label": f.name, "root": f.path,
                                    "folder": f.name})
        targets.sort(key=lambda t: t["name"])
        return targets

    @property
    def download_cloud_files(self) -> bool:
        return bool(self.data.get("download_cloud_files", False))

    # == working folder layout ==
    def path(self, *parts: str) -> Path:
        return self.workspace.joinpath(*parts)

    @property
    def catalogue_dir(self) -> Path:
        return self.path("catalogue")

    @property
    def code_dir(self) -> Path:
        return self.path("code")

    @property
    def documents_dir(self) -> Path:
        return self.path("documents")

    @property
    def pages_dir(self) -> Path:
        return self.path("pages")

    def save(self) -> None:
        util.save_json(self.workspace / "project.json", self.data, indent=2)


def default_home() -> Path:
    """Where projects live unless told otherwise: outside any synced folder."""
    env = os.environ.get("CONTEXTMAX_HOME")
    if env:
        return Path(env)
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "ContextMAX"


def projects_file() -> Path:
    return default_home() / "projects.json"


def list_projects() -> dict:
    return util.load_json(projects_file(), default={}) or {}


def _register(slug: str, workspace: Path) -> None:
    reg = list_projects()
    reg[slug] = str(workspace)
    util.save_json(projects_file(), dict(sorted(reg.items())), indent=2)


# Folders setup.cmd uses inside the ContextMAX folder: a project never gets one of these names.
PROGRAM_FOLDERS = frozenset({"python", "bin"})


def create(name: str, folders: list[dict], workspace: str | None = None) -> Project:
    slug = util.slugify(name)
    ws = Path(workspace) if workspace else default_home() / (f"{slug}-project" if slug in PROGRAM_FOLDERS else slug)
    ws.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": SCHEMA,
        "name": name,
        "slug": slug,
        "folders": [],
        "vocabulary": {},
    }
    proj = Project(ws, data)
    for f in folders:
        add_folder(proj, f["path"], f.get("name"), f.get("holds", "both"), save=False)
    proj.save()
    (ws / SKIP_MARKER).write_text("This folder is a ContextMAX working folder; it is never indexed.\n",
                                  encoding="utf-8")
    notes = ws / "notes" / "project-notes.md"
    if not notes.exists():
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(f"# Notes on {name}\n\nWrite here what the maps cannot know: which folder holds the current "
                         "release, naming conventions, who owns what, known traps. The AI skill reads this file "
                         "before the maps, and it travels with the skill.\n", encoding="utf-8")
    _register(slug, ws)
    return proj


def add_folder(proj: Project, path: str, name: str | None = None, holds: str = "both", save: bool = True) -> Folder:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"not found: {p}")
    if holds not in HOLDS:
        raise ValueError(f"holds must be one of {', '.join(HOLDS)}")
    taken = {f.name for f in proj.folders}
    base = name or p.name or str(p)
    label, n = base, 2
    while label in taken:
        label, n = f"{base} {n}", n + 1
    entry = {"name": label, "path": str(p), "holds": holds}
    proj.data.setdefault("folders", []).append(entry)
    if save:
        proj.save()
    return Folder(**entry)


def remove_folder(proj: Project, name: str) -> bool:
    before = len(proj.data.get("folders", []))
    proj.data["folders"] = [f for f in proj.data.get("folders", []) if f["name"] != name]
    proj.save()
    return len(proj.data["folders"]) != before


def lookup(ref: str | os.PathLike) -> Project:
    """Find a project by its slug (from the registry) or by a working folder path."""
    ref = str(ref)
    candidate = Path(ref)
    if (candidate / "project.json").is_file():
        ws = candidate
    else:
        reg = list_projects()
        if ref in reg:
            ws = Path(reg[ref])
        elif util.slugify(ref) in reg:
            ws = Path(reg[util.slugify(ref)])
        else:
            raise SystemExit(f"no project called {ref!r}. Known: {', '.join(sorted(reg)) or 'none yet'}")
    data = util.load_json(ws / "project.json")
    if not isinstance(data, dict):
        raise SystemExit(f"cannot read {ws / 'project.json'}")
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{ws / 'project.json'}: schema {data.get('schema')} is not {SCHEMA}")
    return Project(ws, data)
