# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Offline pages and generated skills on the built corpus."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from contextmax.cli import main
from contextmax.config import load_config
from contextmax.io.jsonl import read_json
from contextmax.paths import layout_for
from contextmax.skill.render import install, merge_into, render_files, skill_name, yaml_string
from contextmax.viz.render import json_for_script

EXTERNAL = re.compile(r'(src|href)="https?://|<link |@import|fetch\(|url\(http', re.IGNORECASE)


def _pages(built: Path) -> dict[str, str]:
    viz = built / ".contextmax" / "viz"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(viz.glob("*.html"))}


def test_pages_exist_offline_and_escaped(built: Path):
    pages = _pages(built)
    assert set(pages) == {"index.html", "code.html", "docs.html"}
    for name, html in pages.items():
        assert not EXTERNAL.search(html), f"{name} loads something external"
        assert html.count("<script") == 2, name
        assert "<!DOCTYPE html>" in html and 'data-page="' in html


def test_page_counts_equal_coverage(built: Path):
    coverage = read_json(built / ".contextmax" / "coverage.json")
    html = _pages(built)["index.html"]
    payload = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[
        0
    ]
    data = json.loads(payload.replace("<\\/", "</"))
    assert data["coverage"]["n_files"] == coverage["n_files"]
    assert data["coverage"]["by_tier"] == coverage["by_tier"]
    assert data["coverage"]["code"]["n_symbols"] == coverage["code"]["n_symbols"]


def test_code_page_data_is_consistent(built: Path):
    html = _pages(built)["code.html"]
    payload = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[
        0
    ]
    data = json.loads(payload.replace("<\\/", "</"))
    ids = {s["id"] for s in data["symbols"]}
    assert all(c["source"] in ids and c["target"] in ids for c in data["calls"])
    assert any(m for m in data["mentions"].values())


def test_json_for_script_escapes_script_close():
    text = json_for_script({"t": "</script><script>bad()</script>&<!--"})
    assert "</script" not in text and "<!--" not in text
    assert json.loads(text.replace("<\\/", "</").replace("<\\!--", "<!--"))["t"].startswith(
        "</script>"
    )


def test_yaml_string_and_skill_name():
    assert yaml_string('a "quoted" \\ name\nline') == '"a \\"quoted\\" \\\\ name line"'
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", "contextmax-sample")


def test_rendered_skill_follows_the_spec(built: Path):
    config = load_config(built / ".contextmax" / "config.json")
    layout = layout_for(built, None)
    files = render_files(config, layout, None)
    skill = files["SKILL.md"]
    front = skill.split("---\n")[1]
    name = re.search(r"^name: (.+)$", front, re.M).group(1)
    assert name == skill_name(config) == "contextmax-sample"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", name) and not name.startswith("-") and "--" not in name
    description = re.search(r'^description: "(.+)"$', front, re.M).group(1)
    assert 1 <= len(description) <= 1024
    assert skill.count("\n") < 500
    assert "{{" not in skill and "{{" not in files["references/recipes.md"]
    assert "Documentation: not checked" in skill and "q skipped" in skill
    assert (
        built / ".contextmax" / "skill" / "contextmax-sample" / "references" / "honesty.md"
    ).is_file()


def test_install_skill_folder_zip_and_merge(built: Path, tmp_path: Path):
    config = load_config(built / ".contextmax" / "config.json")
    layout = layout_for(built, None)
    dest = install(config, layout, "custom", str(tmp_path / "skills" / "x"))
    assert (dest / "SKILL.md").is_file() and (dest / "references" / "recipes.md").is_file()
    assert (dest / "index-path.txt").read_text(encoding="utf-8").strip() == str(layout.index)
    assert not (dest / "SKILL.md").read_bytes().startswith(b"\xef\xbb\xbf")
    zip_path = install(config, layout, "claude-desktop")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "contextmax-sample/SKILL.md" in names and "contextmax-sample/index-path.txt" in names
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Project notes\n\nKeep me.\n", encoding="utf-8")
    merge_into(agents, "sample", "block v1")
    merge_into(agents, "sample", "block v2")
    text = agents.read_text(encoding="utf-8")
    assert text.startswith("# Project notes") and "Keep me." in text
    assert (
        text.count("<!-- contextmax:sample begin -->") == 1
        and "block v2" in text
        and "block v1" not in text
    )


def test_skill_is_outside_identity_and_cli_installs(built: Path, capsys):
    manifest = read_json(built / ".contextmax" / "manifest.json")
    assert not any(k.startswith("skill/") for k in manifest["artifact_hashes"])
    assert main(["skill", "hosts"]) == 0
    assert "claude-code-project" in capsys.readouterr().out
    assert main(["skill", "render", "--root", str(built)]) == 0
    assert main(["viz", "code", "--root", str(built), "--no-open"]) == 0
    assert capsys.readouterr().out.strip().endswith("code.html")
