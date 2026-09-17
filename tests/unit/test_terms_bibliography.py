# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Phase 3 session 4: terms and concepts, bibliography parsing and citation resolution."""

from __future__ import annotations

from contextmax.docs import bibliography, terms
from contextmax.docs import structure as structure_module
from contextmax.docs.adapters.markdown import MarkdownAdapter

THESIS = """# Sensing for Quad-rotors

## 1 Introduction

The Extended Kalman Filter (EKF) fuses sensors [1]. A gain-scheduled Kalman filter is used.
The gain-scheduled Kalman filter runs at 50 Hz. Attitude is defined as the orientation of the body frame.
GPS (Global Positioning System) drift is large [2, 4-5]; see also (Kalman, 1960) and (Smith et al., 2011).

## 2 Glossary

| Term | Meaning |
|---|---|
| IMU | Inertial Measurement Unit |
| drift | slow change of a sensor bias |

## References

[1] V. I. Kiriouchine ” Attitude estimation for Quad-copters .” CST, Eindhoven, June 2016
[2] R. E. Kalman ” A New Approach to Linear Filtering .” J. Basic Eng., DOI: 10.1115/1.3662552, 1960
[3] Some Author ” GPS tutorial .” Web, https://example.org/gps, 2012
[4] J. Smith and A. Doe ” Sensor Fusion Basics .” Somewhere, 2011
[5] Another ” Unrelated Work .” Nowhere, 2001
"""


def build(key: str, text: str):
    tree = MarkdownAdapter().extract(key, text.encode())
    return tree, structure_module.build(tree, key)


def test_acronyms_definitions_glossary_headings_and_keyphrases():
    tree, structure = build("docs/thesis.md", THESIS)
    cites = {s.id: f"docs/thesis.md:{s.line}" for s in structure.sections}
    rows, per_doc, top = terms.build_terms([("docs/thesis.md", tree, structure)], cites)
    by_id = {r["id"]: r for r in rows}
    ekf = by_id["term:ekf"]
    assert ekf["expansion"] == "Extended Kalman Filter" and "acronym" in ekf["methods"]
    assert ekf["defined_in"] == ["doc:docs/thesis.md#sensing-for-quad-rotors/1-introduction"]
    assert by_id["term:extended-kalman-filter"]["acronym"] == "EKF"
    gps = by_id["term:gps"]
    assert gps["expansion"] == "Global Positioning System"  # reverse form "GPS (Global Positioning System)"
    attitude = by_id["term:attitude"]
    assert attitude["method"] == "defined" and attitude["definition"].startswith("the orientation of the body frame")
    imu = by_id["term:imu"]
    assert imu["methods"] == ["glossary"] and imu["expansion"] == "Inertial Measurement Unit"
    assert by_id["term:drift"]["definition"] == "slow change of a sensor bias"
    assert "heading" in by_id["term:sensing-for-quad-rotors"]["methods"]
    assert "term:introduction" not in by_id  # generic headings are not topics
    key = by_id["term:gain-scheduled-kalman-filter"]
    assert key["method"] == "keyphrase" and key["tf"] == 2 and key["score"] > 0
    assert per_doc["doc:docs/thesis.md"] == len({r["id"] for r in rows if "doc:docs/thesis.md" in r["documents"]})
    assert ekf["n_occurrences"] >= 1 and ekf["cite"] == "docs/thesis.md:3"
    ordered = [r["id"] for r in top["doc:docs/thesis.md"]]
    assert ordered.index("term:imu") < ordered.index("term:gain-scheduled-kalman-filter")  # defined before keyphrases


def test_keyphrase_cap_is_announced_and_ranking_is_stable():
    text = "# T\n\n" + " ".join(f"alpha{i} beta{i} alpha{i} beta{i}." for i in range(60))
    tree, structure = build("docs/big.md", text)
    rows, _, top = terms.build_terms([("docs/big.md", tree, structure)], {}, cap=5)
    keyphrases = [r for r in rows if r["method"] == "keyphrase"]
    assert len(keyphrases) == 5
    assert any("terms cap" in n for entry in top["__notes__"] for n in entry["notes"])
    rows2, _, _ = terms.build_terms([("docs/big.md", tree, structure)], {}, cap=5)
    assert [r["id"] for r in rows2] == [r["id"] for r in rows]


def test_bibliography_entries_and_citations_resolve():
    tree, structure = build("docs/thesis.md", THESIS)
    rows = bibliography.parse_bibliography(
        tree,
        "docs/thesis.md",
        structure,
        doc_titles={bibliography.norm_title("GPS tutorial"): ["docs/page.html"]},
        doc_stems={"papers/Attitude_estimation_for_Quad-copters.pdf": bibliography.norm_stem("papers/Attitude_estimation_for_Quad-copters.pdf")},
        bib_dois={"10.1115/1.3662552": "ref:docs/refs.bib#kalman1960"},
        bib_titles={},
    )
    entries = {r["entry_key"]: r for r in rows if r["ref_kind"] == "bibentry"}
    assert set(entries) == {"1", "2", "3", "4", "5"}
    assert entries["2"]["doi"] == "10.1115/1.3662552" and entries["2"]["resolved"] == "ref:docs/refs.bib#kalman1960" and entries["2"]["evidence"] == "doi-bibtex"
    assert entries["2"]["title"] == "A New Approach to Linear Filtering" and entries["2"]["year"] == "1960"
    assert entries["3"]["resolved"] == "doc:docs/page.html" and entries["3"]["confidence"] == "medium" and entries["3"]["url"] == "https://example.org/gps"
    assert entries["1"]["resolved"] == "doc:papers/Attitude_estimation_for_Quad-copters.pdf" and entries["1"]["confidence"] == "low"
    assert entries["5"]["resolved"] is None and entries["5"]["external"] is True
    assert entries["1"]["id"] == "ref:docs/thesis.md#b1" and entries["1"]["section"] == "doc:docs/thesis.md#sensing-for-quad-rotors/references"
    citations = [r for r in rows if r["ref_kind"] == "citation"]
    numbered = {r["raw"]: r for r in citations if r["evidence"].startswith("numbered")}
    assert set(numbered) == {"[1]", "[2]", "[4]", "[5]"}  # 4-5 expanded
    assert numbered["[1]"]["resolved"] == "ref:docs/thesis.md#b1" and numbered["[1]"]["confidence"] == "high"
    assert numbered["[1]"]["section"] == "doc:docs/thesis.md#sensing-for-quad-rotors/1-introduction"
    author_year = {r["raw"]: r for r in citations if r["evidence"].startswith("author-year")}
    assert author_year["(Kalman, 1960)"]["resolved"] == "ref:docs/thesis.md#b2"
    assert author_year["(Smith et al., 2011)"]["resolved"] == "ref:docs/thesis.md#b4"


def test_configuration_files_contribute_no_topics_or_keyphrases():
    from contextmax.docs.adapters.configfile import ConfigAdapter

    tree = ConfigAdapter().extract("data/app.ini", b"[main]\nname = bench\npath = data/table.csv\n")
    structure = structure_module.build(tree, "data/app.ini")
    rows, per_doc, _ = terms.build_terms([("data/app.ini", tree, structure)], {})
    assert rows == [] and per_doc == {}  # keys and values are searchable, but they are not concepts


def test_query_term_finds_definitions_with_citations(built):
    from contextmax.query.api import open_index

    index = open_index(str(built))
    try:
        result = index.term("EKF")
        assert result["n"] >= 1
        top = result["hits"][0]
        assert top["acronym"] == "EKF" and top["expansion"] == "Extended Kalman Filter"
        assert top["defined_in"] and top["defined_in"][0]["cite"].startswith("docs/thesis.md")
        assert top["n_occurrences"] >= 1
        gps = index.term("Global Positioning System")["hits"][0]
        assert gps["acronym"] == "GPS" and "macro" in gps["methods"]  # from \newacronym in guide.tex
        assert gps["n_documents"] >= 2
        assert all(h["cite"] for h in index.term("")["hits"])
    finally:
        index.con.close()


def test_split_entries_fallbacks():
    dotted = "1. Alpha, A. Title one. 2001\n2. Beta, B. Title two. 2002\n"
    assert [n for n, _ in bibliography.split_entries(dotted)] == ["1", "2"]
    blank = "Alpha, A. (2001). Title one.\n\nBeta, B. (2002). Title two.\n\nnot an entry\n"
    assert [t[:8] for _, t in bibliography.split_entries(blank)] == ["Alpha, A", "Beta, B."]
    entry = bibliography.parse_entry("Alpha, A. and Beta, B. Deterministic indexing. Journal of Things, 2001.")
    assert entry["authors"] == "Alpha, A. and Beta, B" and entry["title"] == "Deterministic indexing" and entry["year"] == "2001"
