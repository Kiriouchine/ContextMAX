# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from contextmax.docs import refs as refs_module
from contextmax.docs import structure as structure_module
from contextmax.docs.adapters.html import HtmlAdapter
from contextmax.docs.adapters.latex import LatexAdapter, clean_text, strip_comments
from contextmax.docs.adapters.markdown import MarkdownAdapter
from contextmax.docs.adapters.plain import PlainAdapter


def kinds(tree, kind):
    return [b for b in tree.blocks if b.kind == kind]


def test_markdown_structure_and_inline_artifacts():
    text = (
        "---\ntitle: Front Title\n---\n# Guide\n\nIntro with [spec](docs/spec.md#scope) and `helper()`.\n\n"
        "## 1.2 Setup\n\n- step one\n- step two [^n1]\n\n```python\nx = 1\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\nSecond\n------\n\n![diagram](img/d.png)\n\n[^n1]: a footnote\n\n[ref]: https://example.org\nSee [site][ref].\n"
    )
    tree = MarkdownAdapter().extract("docs/guide.md", text.encode("utf-8"))
    assert tree.title == "Front Title"
    heads = kinds(tree, "heading")
    assert [(h.level, h.number, h.text) for h in heads] == [
        (1, None, "Guide"),
        (2, "1.2", "Setup"),
        (2, None, "Second"),
    ]
    assert [b.text for b in kinds(tree, "list_item")] == ["step one", "step two [^n1]"]
    code = kinds(tree, "code")[0]
    assert code.lang == "python" and code.text == "x = 1"
    assert kinds(tree, "table")[0].rows == [["a", "b"], ["1", "2"]]
    links = {b.target: b.kind for b in tree.blocks if b.kind in ("link", "figure")}
    assert links == {
        "docs/spec.md#scope": "link",
        "img/d.png": "figure",
        "https://example.org": "link",
    }
    assert kinds(tree, "footnote")[0].target == "n1"
    assert any(b.kind == "ref" and b.target == "n1" for b in tree.blocks)
    para = kinds(tree, "paragraph")[0]
    assert "`helper()`" in para.text and para.line == 6


def test_plain_headings_are_conservative():
    text = "Report Title\n============\n\nBody text here.\n\n2.1 Numbered Heading\n\nMore body.\nnot a heading 3.\n"
    tree = PlainAdapter().extract("notes.txt", text.encode("utf-8"))
    assert tree.title == "Report Title"
    heads = [(h.level, h.number, h.text) for h in kinds(tree, "heading")]
    assert heads == [(1, None, "Report Title"), (2, "2.1", "Numbered Heading")]
    assert len(kinds(tree, "paragraph")) == 2


def test_html_drops_scripts_and_keeps_structure():
    html = (
        "<html><head><title>Page Title</title><script>var x = 'no';</script><style>p{}</style></head>"
        "<body><h1>Main</h1><p>Hello <a href='other.html#part'>link</a> world.</p><ul><li>one</li><li>two</li></ul>"
        "<h2>3 Data</h2><table><tr><th>k</th><th>v</th></tr><tr><td>a</td><td>1</td></tr></table>"
        "<pre>code here</pre><img src='pic.png' alt='A picture'></body></html>"
    )
    tree = HtmlAdapter().extract("page.html", html.encode("utf-8"))
    assert tree.title == "Page Title"
    assert [(h.level, h.number, h.text) for h in kinds(tree, "heading")] == [
        (1, None, "Main"),
        (2, "3", "Data"),
    ]
    assert "no" not in "".join(b.text for b in tree.blocks)
    assert kinds(tree, "link")[0].target == "other.html#part"
    assert [b.text for b in kinds(tree, "list_item")] == ["one", "two"]
    assert kinds(tree, "table")[0].rows == [["k", "v"], ["a", "1"]]
    assert kinds(tree, "code")[0].text == "code here"
    assert kinds(tree, "figure")[0].target == "pic.png"


def test_latex_sections_labels_refs_cites_floats_and_comments():
    tex = (
        "\\documentclass{article}\n\\title{GPS Guide}\n\\begin{document}\n\\section{Introduction}\\label{sec:intro}\n"
        "Text with \\cite{smith2020, doe19} and \\ref{fig:setup} and \\textbf{bold} words. % \\cite{ignored}\n"
        "\\subsection{Method}\n\\begin{figure}\n\\includegraphics{setup.png}\n\\caption{The bench setup}\\label{fig:setup}\n\\end{figure}\n"
        "\\begin{itemize}\n\\item first\n\\item second\n\\end{itemize}\n\\begin{equation}\nE = mc^2\n\\end{equation}\n"
        "\\input{intro}\n\\end{document}\n"
    )
    tree = LatexAdapter().extract("docs/guide.tex", tex.encode("utf-8"))
    assert tree.title == "GPS Guide"
    assert [(h.level, h.text) for h in kinds(tree, "heading")] == [
        (3, "Introduction"),
        (4, "Method"),
    ]
    assert [b.target for b in kinds(tree, "citation")] == ["smith2020", "doe19"]
    assert [b.target for b in kinds(tree, "ref")] == ["fig:setup"]
    assert sorted(b.target for b in kinds(tree, "label")) == ["fig:setup", "sec:intro"]
    fig = kinds(tree, "figure")
    assert any(f.text == "The bench setup" for f in fig) and any(
        f.target == "setup.png" for f in fig
    )
    assert [b.text for b in kinds(tree, "list_item")] == ["first", "second"]
    assert kinds(tree, "math")[0].text.startswith("E = mc")
    assert kinds(tree, "include")[0].target == "intro"
    para = next(b for b in kinds(tree, "paragraph") if "bold" in b.text)
    assert "[smith2020, doe19]" in para.text and "\\textbf" not in para.text
    assert strip_comments("a % comment\n\\% not\n") == "a \n\\% not\n"
    assert clean_text("\\emph{x} and $y$") == "x and $y$"


def test_structure_ids_ranges_and_nesting():
    text = "# Top\n\nintro\n\n## 1 First\n\nbody one\n\n### 1.1 Sub\n\nsub body\n\n## 2 First\n\ntwo\n\n## 2 First\n\ndup\n"
    tree = MarkdownAdapter().extract("d.md", text.encode("utf-8"))
    st = structure_module.build(tree, "d.md")
    ids = [s.id for s in st.sections]
    assert ids[0] == "doc:d.md#top"
    assert ids[1] == "doc:d.md#top/1-first" and ids[2] == "doc:d.md#top/1-first/1-1-sub"
    assert ids[3] == "doc:d.md#top/2-first" and ids[4] == "doc:d.md#top/2-first~2"
    first = st.sections[1]
    assert st.text[first.text_start : first.text_end].startswith("## 1 First")
    assert "sub body" in st.text[first.text_start : first.text_end]
    assert "two" not in st.text[first.text_start : first.text_end]
    assert st.sections[2].parent == first.id and st.sections[2].depth == 3
    assert st.toc == ids and st.n_words > 0


def test_structure_all_numbered_uses_numbers_as_ids():
    tex = "\\section{3 Scope}\n\\subsection{3.1 Goals}\n\\subsection{3.2 Limits}\n"
    tree = LatexAdapter().extract("s.tex", tex.encode("utf-8"))
    st = structure_module.build(tree, "s.tex")
    assert [s.id for s in st.sections] == ["doc:s.tex#3", "doc:s.tex#3.1", "doc:s.tex#3.2"]
    assert [s.depth for s in st.sections] == [1, 2, 2]


def test_reference_resolution_rules():
    files = {
        "docs/guide.md",
        "docs/spec.md",
        "docs/intro.tex",
        "docs/guide.tex",
        "src/app/util.py",
        "img/d.png",
    }
    md = MarkdownAdapter().extract(
        "docs/guide.md",
        (
            b"# G\n\nSee [spec](spec.md#scope), [ext](https://x.org), [missing](nope.md), [code](../src/app/util.py) "
            b"and the file util.py plus ![d](../img/d.png).\n"
        ),
    )
    st = structure_module.build(md, "docs/guide.md")
    spec = MarkdownAdapter().extract("docs/spec.md", b"# Spec\n\n## Scope\n\nx\n")
    spec_st = structure_module.build(spec, "docs/spec.md")
    tex = LatexAdapter().extract(
        "docs/guide.tex",
        b"\\section{A}\\label{sec:a}\nSee \\ref{sec:a}, \\ref{sec:zzz} and \\cite{k1}.\n\\input{intro}\n",
    )
    tex_st = structure_module.build(tex, "docs/guide.tex")
    labels = refs_module.collect_labels(tex, "docs/guide.tex", tex_st)
    catalog = refs_module.Catalog(
        files=files,
        documents={"docs/guide.md", "docs/spec.md", "docs/guide.tex", "docs/intro.tex"},
        labels=labels,
    )
    rows = {r["raw"]: r for r in refs_module.build_references(md, "docs/guide.md", st, catalog)}
    assert (
        rows["spec.md#scope"]["resolved"] == "doc:docs/spec.md#scope"
        and rows["spec.md#scope"]["confidence"] == "high"
    )
    assert rows["https://x.org"]["external"] is True and rows["https://x.org"]["resolved"] is None
    assert rows["nope.md"]["resolved"] is None and rows["nope.md"]["external"] is False
    assert rows["../src/app/util.py"]["resolved"] == "file:src/app/util.py"
    assert (
        rows["util.py"]["ref_kind"] == "path"
        and rows["util.py"]["resolved"] == "file:src/app/util.py"
    )
    assert (
        rows["../img/d.png"]["ref_kind"] == "figure"
        and rows["../img/d.png"]["resolved"] == "file:img/d.png"
    )
    trows = {
        r["raw"]: r for r in refs_module.build_references(tex, "docs/guide.tex", tex_st, catalog)
    }
    assert (
        trows["sec:a"]["resolved"] == "doc:docs/guide.tex#a"
        and trows["sec:a"]["ref_kind"] == "crossref"
    )
    assert (
        trows["sec:zzz"]["resolved"] is None and trows["sec:zzz"]["evidence"] == "label-unresolved"
    )
    assert trows["k1"]["ref_kind"] == "citation" and trows["k1"]["external"] is True
    assert trows["intro"]["resolved"] == "doc:docs/intro.tex"
    assert spec_st.sections[1].id == "doc:docs/spec.md#spec/scope"
