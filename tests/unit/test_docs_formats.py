# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Phase 3 session 1 adapters: BibTeX, notebooks, RST, AsciiDoc, Org, email, config files, PDF."""

from __future__ import annotations

import json

import pytest

from contextmax.docs import refs as refs_module
from contextmax.docs import structure as structure_module
from contextmax.docs.adapters.asciidoc import AsciidocAdapter
from contextmax.docs.adapters.bibtex import BibtexAdapter, parse_entries
from contextmax.docs.adapters.configfile import ConfigAdapter
from contextmax.docs.adapters.email import EmailAdapter
from contextmax.docs.adapters.latex import LatexAdapter
from contextmax.docs.adapters.notebook import NotebookAdapter
from contextmax.docs.adapters.org import OrgAdapter
from contextmax.docs.adapters.rst import RstAdapter
from contextmax.docs.base import ExtractionError


def kinds(tree, kind):
    return [b for b in tree.blocks if b.kind == kind]


# ----- BibTeX -------------------------------------------------------------------------------------
BIB = b"""@article{smith2020,
  title = {A {Great} Paper},
  author = {Smith, J. and Doe, A.},
  year = 2020, journal = {J. Things}, doi = {10.1000/xyz},
  file = {:papers/smith2020.pdf:pdf}
}
@book{knuth, title="TAOCP", author="Knuth, D.", year={1968}}
@comment{not an entry}
@article{smith2020, title={Duplicate key}}
"""


def test_bibtex_entries_and_reference_ids():
    entries = parse_entries(BIB.decode())
    assert [e["key"] for e in entries] == ["smith2020", "knuth", "smith2020"]
    assert entries[0]["title"] == "A Great Paper" and entries[0]["doi"] == "10.1000/xyz"
    tree = BibtexAdapter().extract("docs/refs.bib", BIB)
    assert tree.metadata["n_entries"] == 3
    ids = refs_module.bibentry_ids(tree, "docs/refs.bib")
    assert [ref for _, ref in ids] == ["smith2020", "knuth", "smith2020~2"]
    assert refs_module.collect_bibentries(tree, "docs/refs.bib")["knuth"] == ["ref:docs/refs.bib#knuth"]


def test_citation_resolves_to_bib_entry_and_file_field_to_project_pdf():
    bib_tree = BibtexAdapter().extract("docs/refs.bib", BIB)
    tex = b"\\section{Intro}\nAs shown by \\cite{knuth, missing} and \\citep{smith2020}.\n"
    tex_tree = LatexAdapter().extract("docs/guide.tex", tex)
    catalog = refs_module.Catalog(
        files={"docs/refs.bib", "docs/guide.tex", "papers/smith2020.pdf"},
        documents={"docs/refs.bib", "docs/guide.tex"},
        bibentries=refs_module.collect_bibentries(bib_tree, "docs/refs.bib"),
    )
    rows = refs_module.build_references(tex_tree, "docs/guide.tex", structure_module.build(tex_tree, "docs/guide.tex"), catalog)
    by_raw = {r["raw"]: r for r in rows if r["ref_kind"] == "citation"}
    assert by_raw["knuth"]["resolved"] == "ref:docs/refs.bib#knuth" and by_raw["knuth"]["confidence"] == "high"
    assert by_raw["missing"]["resolved"] is None and by_raw["missing"]["external"] is True
    bib_rows = refs_module.build_references(bib_tree, "docs/refs.bib", structure_module.build(bib_tree, "docs/refs.bib"), catalog)
    smith = next(r for r in bib_rows if r["id"] == "ref:docs/refs.bib#smith2020")
    assert smith["ref_kind"] == "bibentry" and smith["resolved"] == "file:papers/smith2020.pdf" and smith["evidence"] == "bibfile"
    assert smith["doi"] == "10.1000/xyz" and smith["year"] == "2020"
    knuth = next(r for r in bib_rows if r["id"] == "ref:docs/refs.bib#knuth")
    assert knuth["external"] is True and knuth["resolved"] is None


# ----- Notebook -----------------------------------------------------------------------------------
def test_notebook_cells_become_sections_and_code_blocks():
    nb = {
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {"cell_type": "markdown", "source": ["# Analysis\n", "\n", "Intro para.\n"]},
            {"cell_type": "code", "source": ["def f(x):\n", "    return x\n"], "outputs": [{"output_type": "stream"}], "execution_count": 1},
            {"cell_type": "raw", "source": "raw text"},
        ],
    }
    tree = NotebookAdapter().extract("nb.ipynb", json.dumps(nb).encode())
    assert tree.title == "Analysis" and tree.metadata["kernel_language"] == "python" and tree.metadata["n_cells"] == 3
    code = kinds(tree, "code")[0]
    assert code.lang == "python" and code.line == 4 and code.end_line == 5 and code.extra["cell"] == 2
    assert [b.extra["cell_type"] for b in kinds(tree, "cell")] == ["markdown", "code", "raw"]
    assert structure_module.build(tree, "nb.ipynb").sections[0].id == "doc:nb.ipynb#analysis"
    with pytest.raises(ExtractionError):
        NotebookAdapter().extract("bad.ipynb", b"{not json")


# ----- RST ----------------------------------------------------------------------------------------
RST = b"""=====
Title
=====

Intro with `site <https://ex.org>`_ and :ref:`lbl`.

Section
-------

.. _lbl:

.. code-block:: python

   x = 1

.. image:: img/a.png
   :alt: Alt text

.. toctree::

   intro
   api/index

Literal::

   raw text

- item one
- item two

+---+---+
| a | b |
+---+---+
"""


def test_rst_headings_directives_links_and_literals():
    tree = RstAdapter().extract("doc.rst", RST)
    assert tree.title == "Title"
    assert [(h.level, h.text) for h in kinds(tree, "heading")] == [(1, "Title"), (2, "Section")]
    para = kinds(tree, "paragraph")[0]
    assert para.text == "Intro with site and lbl."  # markup reduced to labels
    assert {b.target for b in kinds(tree, "link")} == {"https://ex.org"}
    assert kinds(tree, "ref")[0].target == "lbl" and kinds(tree, "label")[0].target == "lbl"
    codes = kinds(tree, "code")
    assert (codes[0].lang, codes[0].text) == ("python", "x = 1") and codes[1].text == "raw text"
    assert kinds(tree, "figure")[0].text == "Alt text"
    assert [b.target for b in kinds(tree, "include")] == ["intro", "api/index"]
    assert [b.text for b in kinds(tree, "list_item")] == ["item one", "item two"]
    assert kinds(tree, "table")[0].rows == [["a", "b"]]


# ----- AsciiDoc -----------------------------------------------------------------------------------
ADOC = b"""= Doc Title
:author: Me

== First

Text with link:other.adoc[Other] and <<anchor,See>> and https://ex.org[site].

[[anchor]]
=== Sub

[source,python]
----
x = 1
----

.Figure caption
image::img/a.png[Alt]

include::part.adoc[]

* one
** two

|===
| a | b
| 1 | 2
|===
"""


def test_asciidoc_structure_and_references():
    tree = AsciidocAdapter().extract("doc.adoc", ADOC)
    assert tree.title == "Doc Title" and tree.metadata["author"] == "Me"
    assert [(h.level, h.text) for h in kinds(tree, "heading")] == [(2, "First"), (3, "Sub")]
    assert kinds(tree, "paragraph")[0].text == "Text with Other and See and site."
    assert {b.target: b.text for b in kinds(tree, "link")} == {"other.adoc": "Other", "https://ex.org": "site"}
    assert kinds(tree, "ref")[0].target == "anchor" and kinds(tree, "label")[0].target == "anchor"
    code = kinds(tree, "code")[0]
    assert code.lang == "python" and code.text == "x = 1"
    assert kinds(tree, "figure")[0].text == "Figure caption"
    assert kinds(tree, "include")[0].target == "part.adoc"
    assert [(b.level, b.text) for b in kinds(tree, "list_item")] == [(1, "one"), (2, "two")]
    assert kinds(tree, "table")[0].rows == [["a", "b"], ["1", "2"]]
    sections = structure_module.build(tree, "doc.adoc").sections
    assert [s.id for s in sections] == ["doc:doc.adoc#first", "doc:doc.adoc#first/sub"]


# ----- Org ----------------------------------------------------------------------------------------
ORG = b"""#+TITLE: Org Doc
#+AUTHOR: Me

* TODO First heading :tag:
Some text with [[https://ex.org][site]] and [[file:other.org][other]] and [[*First heading]].
** Sub
#+BEGIN_SRC python
x = 1
#+END_SRC
#+CAPTION: A table
| a | b |
|---+---|
| 1 | 2 |
- item
#+INCLUDE: "part.org"
"""


def test_org_headings_blocks_and_links():
    tree = OrgAdapter().extract("doc.org", ORG)
    assert tree.title == "Org Doc" and tree.metadata["author"] == "Me"
    assert [(h.level, h.text) for h in kinds(tree, "heading")] == [(1, "First heading"), (2, "Sub")]
    assert kinds(tree, "paragraph")[0].text == "Some text with site and other and *First heading."
    assert {b.target for b in kinds(tree, "link")} == {"https://ex.org", "other.org"}
    assert kinds(tree, "ref")[0].target == "First heading"
    assert kinds(tree, "code")[0].lang == "python"
    table = kinds(tree, "table")[0]
    assert table.text == "A table" and table.rows == [["a", "b"], ["1", "2"]]
    assert kinds(tree, "include")[0].target == "part.org"


# ----- Email --------------------------------------------------------------------------------------
EML = (
    b"From: a@x.org\r\nTo: b@y.org\r\nSubject: Meeting notes\r\nDate: Mon, 1 Jan 2024 10:00:00 +0000\r\n"
    b"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=\"B\"\r\n\r\n--B\r\n"
    b"Content-Type: text/plain\r\n\r\nFirst paragraph.\r\n\r\nSecond with https://ex.org/x.\r\n--B\r\n"
    b"Content-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"spec.pdf\"\r\n\r\n%PDF\r\n--B--\r\n"
)


def test_email_headers_body_and_attachments():
    tree = EmailAdapter().extract("mail/thread.eml", EML)
    assert tree.title == "Meeting notes" and tree.metadata["from"] == "a@x.org"
    paras = [b.text for b in kinds(tree, "paragraph")]
    assert paras[0].startswith("From: a@x.org; To: b@y.org") and "First paragraph." in paras
    attachment = kinds(tree, "link")[0]
    assert attachment.target == "spec.pdf" and attachment.extra["attachment"] is True


def test_mbox_messages_become_sections():
    mbox = b"From a@x.org Mon Jan  1 10:00:00 2024\nSubject: One\n\nBody one.\n\nFrom b@y.org Mon Jan  1 11:00:00 2024\nSubject: Two\n\nBody two.\n"
    tree = EmailAdapter().extract("mail/box.mbox", mbox)
    assert tree.metadata["n_messages"] == 2
    assert [h.text for h in kinds(tree, "heading")] == ["One", "Two"]
    assert [s.id for s in structure_module.build(tree, "mail/box.mbox").sections] == ["doc:mail/box.mbox#one", "doc:mail/box.mbox#two"]


# ----- Config files -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "data", "shape", "expect_items", "expect_links"),
    [
        ("data/config.json", b'{\n  "name": "demo",\n  "paths": {"docs": "docs/spec.md", "url": "https://ex.org"}\n}\n',
         "json", ["name = demo", "paths.docs = docs/spec.md", "paths.url = https://ex.org"], {"docs/spec.md", "https://ex.org"}),
        ("ci.yaml", b"name: demo\nsteps:\n  - run: make\nenv:\n  MAIN: src/app/main.py\n", "yaml-lite",
         ["name = demo", "steps.run = make", "env.MAIN = src/app/main.py"], {"src/app/main.py"}),
        ("tool.toml", b'[project]\nname = "x"\ndeps = ["a>=1", "b"]\n[tool.ruff]\nline = 100\n', "toml",
         ['project.name = x', 'project.deps = ["a>=1", "b"]', "tool.ruff.line = 100"], set()),
        ("build.xml", b'<?xml version="1.0"?>\n<root a="1">\n  <item href="docs/spec.md">Hello</item>\n</root>\n', "xml",
         ["root@a = 1", "root/item@href = docs/spec.md", "root/item = Hello"], {"docs/spec.md"}),
        ("app.ini", b"[main]\nname = x\npath = data/table.csv\n", "ini", ["main.name = x", "main.path = data/table.csv"], {"data/table.csv"}),
        ("requirements.txt", b"pypdf>=5.0  # pdf\nopenpyxl\n", "dependencies", ["pypdf >=5.0", "openpyxl"], set()),
        ("records.jsonl", b'{"a": 1, "b": "x"}\n{"a": 2}\n', "jsonl", ["[1].a = 1", "[1].b = x", "[2].a = 2"], set()),
    ],
)
def test_config_shapes(name, data, shape, expect_items, expect_links):
    tree = ConfigAdapter().extract(name, data)
    assert tree.metadata["shape"] == shape
    items = [b.text for b in kinds(tree, "list_item")]
    assert items == expect_items
    assert {b.target for b in kinds(tree, "link")} == expect_links
    assert all(b.line >= 1 for b in tree.blocks)


def test_config_json_top_level_keys_have_lines_and_broken_json_falls_back_to_lines():
    tree = ConfigAdapter().extract("c.json", b'{\n  "alpha": 1,\n  "beta": {"x": 2}\n}\n')
    assert [(h.text, h.line) for h in kinds(tree, "heading")] == [("alpha", 2), ("beta", 3)]
    broken = ConfigAdapter().extract("c.json", b'{"alpha": 1,\n')
    assert broken.metadata["shape"] == "lines" and any("parse failed" in n for n in broken.notes)


def test_config_xml_with_entities_is_refused():
    with pytest.raises(ExtractionError):
        ConfigAdapter().extract("evil.xml", b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')


def test_config_caps_are_announced():
    from contextmax.docs.adapters import configfile

    big = {f"k{i:05d}": i for i in range(configfile.MAX_SECTIONS + 5)}
    tree = ConfigAdapter().extract("big.json", json.dumps(big, indent=1).encode())
    assert len(kinds(tree, "heading")) == configfile.MAX_SECTIONS
    assert any("TRUNCATED" in n for n in tree.notes)


# ----- PDF ----------------------------------------------------------------------------------------
def minimal_pdf(pages: list[list[str]]) -> bytes:
    """A hand-assembled PDF with Helvetica text lines per page (deterministic bytes)."""
    objects: list[bytes] = []
    n_pages = len(pages)
    page_ids = [4 + 2 * i for i in range(n_pages)]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        content = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({ln}) Tj 0 -16 Td" for ln in lines) + " ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_ids[i] + 1} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream".encode())
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf_derived_headings_pages_and_scan_detection(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.delenv("CONTEXTMAX_NO_OPTIONAL_READERS", raising=False)
    from contextmax.docs.adapters.pdf import PdfAdapter, looks_like_heading, sane_title

    assert looks_like_heading("3.1 Gain scheduling") == (True, 2)
    assert looks_like_heading("2020 was a year.") == (False, 0)
    assert looks_like_heading("REFERENCES") == (True, 1)
    assert sane_title("Microsoft Word - thesis.docx") == "" and sane_title("D:\\Books\\x") == ""
    pdf = minimal_pdf([
        ["A Study of Things", "1 Introduction", "This is the first sentence of the body text which is long enough.", "It ends here."],
        ["2 Method", "Second page body."],
    ])
    tree = PdfAdapter().extract("docs/study.pdf", pdf)
    assert tree.pages == 2 and tree.metadata["toc_source"] == "derived"
    assert tree.title == "A Study of Things" and tree.metadata["title_source"] == "first-line"
    heads = kinds(tree, "heading")
    assert [(h.number, h.text, h.page) for h in heads] == [("1", "Introduction", 1), ("2", "Method", 2)]
    structure = structure_module.build(tree, "docs/study.pdf")
    assert [(s.id, s.page, s.end_page) for s in structure.sections] == [("doc:docs/study.pdf#1", 1, 2), ("doc:docs/study.pdf#2", 2, 2)]
    from contextmax.docs.run import section_cite

    assert section_cite("docs/study.pdf", structure.sections[0]) == "docs/study.pdf p.1-2 §1"
    scan = PdfAdapter().extract("docs/scan.pdf", minimal_pdf([[""], [""]]))
    assert scan.metadata.get("scan_detected") is True and any("no OCR" in n for n in scan.notes)
    with pytest.raises(ExtractionError):
        PdfAdapter().extract("docs/bad.pdf", b"%PDF-1.4 garbage")


def test_pdf_outline_becomes_toc(monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    monkeypatch.delenv("CONTEXTMAX_NO_OPTIONAL_READERS", raising=False)
    import io

    from contextmax.docs.adapters.pdf import PdfAdapter

    reader = pypdf.PdfReader(io.BytesIO(minimal_pdf([["Cover"], ["Chapter text"], ["More"]])))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    top = writer.add_outline_item("1 Background", 1)
    writer.add_outline_item("1.1 Detail", 2, parent=top)
    writer.add_metadata({"/Title": "Outlined"})
    buf = io.BytesIO()
    writer.write(buf)
    tree = PdfAdapter().extract("docs/outlined.pdf", buf.getvalue())
    assert tree.metadata["toc_source"] == "outline" and tree.title == "Outlined"
    assert [(h.level, h.number, h.text, h.page) for h in kinds(tree, "heading")] == [(1, "1", "Background", 2), (2, "1.1", "Detail", 3)]
