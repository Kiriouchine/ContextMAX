# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Render the per-project skill and install it into an AI host.

The body is identical for every host; only the destination and the layout differ, and both
come from `hosts.json`. Values are YAML-escaped, unfilled placeholders fail the render, files
are written UTF-8 without BOM, and merge-block hosts keep everything outside the marked block.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from contextmax import version
from contextmax.io.atomic import atomic_write_text
from contextmax.io.jsonl import read_json
from contextmax.registry import format_name, language_name

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
BLOCK_BEGIN = "<!-- contextmax:{slug} begin -->"
BLOCK_END = "<!-- contextmax:{slug} end -->"


class SkillError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def hosts() -> dict[str, dict[str, Any]]:
    with (
        resources.files("contextmax.skill").joinpath("hosts.json").open("r", encoding="utf-8") as h
    ):
        return json.load(h)["hosts"]


def _template(name: str) -> str:
    return (
        resources.files("contextmax.skill")
        .joinpath("templates")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def yaml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def skill_name(config) -> str:
    override = config.data.get("skill", {}).get("name")
    name = override or f"contextmax-{config.slug}"
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    name = re.sub(r"-{2,}", "-", name)[:64].rstrip("-")
    if not name:
        raise SkillError("skill name is empty after normalisation")
    return name


def render_files(config, layout, coverage: dict[str, Any] | None) -> dict[str, str]:
    """Return {relative path: text} for the skill folder."""
    cov = coverage or (read_json(layout.coverage) if layout.coverage.is_file() else {})
    name = skill_name(config)
    keywords = [k for k in config.data["project"].get("keywords", []) if k]
    languages = sorted(cov.get("by_language", {}), key=lambda k: -cov["by_language"][k])[:6]
    formats_ = sorted(cov.get("by_format", {}), key=lambda k: -cov["by_format"][k])[:6]
    description_bits = [
        f"Search, navigate and cite the {config.name} project through its ContextMAX index",
        "(files, code symbols and call graph, document outlines, references, links).",
        "Use when asked where something is, how code works, who calls what, what would break,",
        "or what a document says about this project.",
    ]
    if keywords:
        description_bits.append("Keywords: " + ", ".join(keywords) + ".")
    if languages:
        description_bits.append(
            "Languages: " + ", ".join(language_name(x) or x for x in languages) + "."
        )
    description = " ".join(description_bits)[:1000]
    tiers = cov.get("by_tier", {})
    code = cov.get("code", {})
    docs = cov.get("documents", {})
    summary = (
        f"{cov.get('n_files', 0)} files (tiers A {tiers.get('A', 0)}, B {tiers.get('B', 0)}, C {tiers.get('C', 0)}, D {tiers.get('D', 0)}); "
        f"{code.get('n_symbols', 0)} code symbols with {code.get('n_resolved', 0)} resolved call edges; "
        f"{docs.get('n_documents', 0)} documents with {docs.get('n_sections', 0)} sections and {docs.get('n_references', 0)} references; "
        f"{cov.get('n_skipped', 0)} files recorded as not fully indexed. "
        + (
            "Languages: " + ", ".join(language_name(x) or x for x in languages) + ". "
            if languages
            else ""
        )
        + ("Formats: " + ", ".join(format_name(x) or x for x in formats_) + "." if formats_ else "")
    )
    values = {
        "NAME": name,
        "SLUG": config.slug,
        "PROJECT_NAME": config.name,
        "DESCRIPTION_YAML": yaml_string(description),
        "ENGINE_VERSION": version.__version__,
        "INDEX_PATH": str(layout.index),
        "INDEX_PATH_YAML": yaml_string(str(layout.index)),
        "ROOT_PATH": str(layout.root),
        "CMX": "cmx",
        "SUMMARY": summary,
    }
    files = {
        "SKILL.md": _fill(_template("SKILL.md.tmpl"), values),
        "references/recipes.md": _fill(_template("references/recipes.md.tmpl"), values),
        "references/honesty.md": _template("references/honesty.md"),
        "references/schema.md": _template("references/schema.md"),
    }
    return files


def _fill(template: str, values: dict[str, str]) -> str:
    out = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)
    left = PLACEHOLDER.findall(out)
    if left:
        raise SkillError(f"unfilled placeholders: {', '.join(sorted(set(left)))}")
    return out


def write_rendered(config, layout, coverage: dict[str, Any] | None) -> Path:
    files = render_files(config, layout, coverage)
    target = layout.skill_dir / skill_name(config)
    if target.exists():
        shutil.rmtree(target)
    for rel, text in files.items():
        atomic_write_text(target / rel, text)
    return target


def run_skill_stage(ctx) -> dict[str, Any]:
    # Not registered as an artifact: the skill names this machine's paths, and identity
    # hashes must stay comparable between machines.
    target = write_rendered(ctx.config, ctx.layout, ctx.coverage)
    ctx.log(f"  rendered skill '{target.name}' into {target}")
    return {
        "name": target.name,
        "path": str(target),
        "n_files": sum(1 for p in target.rglob("*") if p.is_file()),
    }


def install(config, layout, host_id: str, custom_path: str | None = None) -> Path:
    """Install the rendered skill into a host. Returns the destination path."""
    spec = hosts().get(host_id)
    if spec is None:
        raise SkillError(f"unknown host '{host_id}'; run `contextmax skill hosts`")
    name = skill_name(config)
    source = layout.skill_dir / name
    if not (source / "SKILL.md").is_file():
        write_rendered(config, layout, None)
    values = {
        "project": str(layout.root),
        "home": str(Path.home()),
        "index": str(layout.index),
        "name": name,
    }
    if spec["path"] is None:
        if not custom_path:
            raise SkillError("host 'custom' needs --path")
        dest = Path(custom_path).expanduser().resolve()
    else:
        dest = Path(spec["path"].format(**values))
    layout_kind = spec["layout"]
    if layout_kind == "skill-folder":
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        if spec.get("sidecar"):
            atomic_write_text(dest / "index-path.txt", str(layout.index) + "\n")
        return dest
    if layout_kind == "zip":
        dest.parent.mkdir(parents=True, exist_ok=True)
        if spec.get("sidecar"):
            atomic_write_text(source / "index-path.txt", str(layout.index) + "\n")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    zf.write(path, f"{name}/{path.relative_to(source).as_posix()}")
        return dest
    if layout_kind == "merge-block":
        block = _merge_block(config, layout, name, source)
        merge_into(dest, config.slug, block)
        return dest
    raise SkillError(f"unsupported layout {layout_kind}")


def _merge_block(config, layout, name: str, source: Path) -> str:
    return (
        f"## ContextMAX index for {config.name}\n\n"
        f"A deterministic index of this project lives at `{layout.index}` (skill: `{source}`).\n"
        f"Query it with `cmx q <verb>` (search, find, symbol, callers, impact, file, doc, outline, section, source);\n"
        f"run `cmx status --json` first and check `completeness.verdict`. Cite `path:line` or `path §section`\n"
        f"for every claim; tier C findings are lexical leads (confidence low), verify them with `cmx q source`.\n"
        f"Absence from the index is not absence from the project: run `cmx q skipped` before saying so.\n"
        f"Full instructions: `{source / 'SKILL.md'}`.\n"
    )


def merge_into(path: Path, slug: str, block: str) -> None:
    begin = BLOCK_BEGIN.format(slug=slug)
    end = BLOCK_END.format(slug=slug)
    existing = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    marked = f"{begin}\n{block.rstrip()}\n{end}\n"
    if begin in existing and end in existing:
        start = existing.index(begin)
        stop = existing.index(end) + len(end)
        rest = existing[stop:].lstrip("\n")
        new = existing[:start] + marked + ("\n" + rest if rest else "")
    else:
        sep = "" if not existing or existing.endswith("\n") else "\n"
        new = existing + sep + ("\n" if existing else "") + marked
    atomic_write_text(path, new)


def list_hosts() -> list[dict[str, Any]]:
    return [{"id": hid, **spec} for hid, spec in hosts().items()]
