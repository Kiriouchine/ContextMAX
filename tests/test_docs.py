"""Text cache and document map: what must be read, folded, linked and refused."""
from __future__ import annotations

from contextmax import util
from contextmax.docs import corpus


def _core(proj):
    return {d["key"]: d for d in util.load_jsonl(proj.documents_dir / "doc-list.jsonl")}


def test_word_headings_are_kept_as_headings(built):
    text = (built.documents_dir / "text" / "Detailed_design_v2.1.txt").read_text(encoding="utf-8")
    assert "# 1 Introduction" in text and "## 3.1 PID step" in text


def test_pdf_text_and_title_are_read(built):
    row = next(r for r in util.load_jsonl(built.documents_dir / "text-index.jsonl") if r["key"] == "Test_report_3")
    assert row["doc_title"] == "Test report 3: control loop"
    assert "settle time" in (built.documents_dir / row["cached_text"]).read_text(encoding="utf-8")


def test_an_old_xls_workbook_is_read_through_xlrd(monkeypatch):
    """No .xls can be written without Excel, so a stand-in uses xlrd's own names, checked against xlrd."""
    import xlrd
    import xlrd.sheet

    from contextmax.docs import sheets

    used = ("cell_value", "cell_type", "cell_xf_index", "nrows", "ncols", "merged_cells", "rowinfo_map",
            "colinfo_map", "visibility", "name")
    assert all(hasattr(xlrd.sheet.Sheet, m) for m in used)
    cells = {(0, 0): ("settle time", xlrd.XL_CELL_TEXT), (0, 1): (12.0, xlrd.XL_CELL_NUMBER),
             (1, 0): ("merged", xlrd.XL_CELL_TEXT), (1, 1): ("", xlrd.XL_CELL_EMPTY)}

    class Sheet:
        name, nrows, ncols, visibility = "Budget", 2, 2, 0
        merged_cells = [(1, 2, 0, 2)]
        rowinfo_map, colinfo_map = {}, {}

        def cell_value(self, r, c):
            return cells[(r, c)][0]

        def cell_type(self, r, c):
            return cells[(r, c)][1]

        def cell_xf_index(self, r, c):
            raise IndexError

    class Book:
        datemode = 0

        def sheets(self):
            return [Sheet()]

    monkeypatch.setattr(xlrd, "open_workbook", lambda *a, **k: Book())
    found, _, _, engine = sheets.open_xls("budget.xls")
    name, grid = found[0][0], found[0][1]
    assert name == "Budget" and engine.startswith("xlrd")
    assert grid[(1, 1)].value == "settle time" and grid[(1, 2)].value == 12.0
    assert grid[(2, 2)].value == "merged"           # a merged cell carries its anchor's value


def test_pdf_pages_render_for_text_recognition(built, tmp_path):
    from contextmax.docs.readers import render_pdf_pages

    row = next(r for r in util.load_jsonl(built.documents_dir / "text-index.jsonl") if r["key"] == "Test_report_3")
    root = next(f.path for f in built.folders if f.name == row["folder"])
    assert render_pdf_pages(f"{root}/{row['relative_path']}", tmp_path, dpi=50) == 1
    png = next(tmp_path.glob("*.png")).read_bytes()
    assert png.startswith(b"\x89PNG") and len(png) > 100


def test_words_own_marks_become_plain_text():
    from contextmax.office import clean_word_text

    # as word_text.ps1 hands it over: CR already LF; a 2x2 table, a manual break, a page break, hyphens
    raw = "gain\n\x072.5\n\x07\n\x07limit\n\x07900 counts\n\x07\n\x07line\x0bbreak\x0cpage re\x1eentry opti\x1fmal\n"
    assert clean_word_text(raw) == ("gain\t2.5\t\nlimit\t900 counts\t\nline\nbreak\npage re\N{NON-BREAKING HYPHEN}entry "
                                    "optimal\n")


def test_every_spreadsheet_value_keeps_its_cell_and_unit(built):
    recs = util.load_jsonl(built.documents_dir / "sheets" / "Error_budget.jsonl")
    filt = next(r for r in recs if r["cell"] == "B5")
    assert filt["label"] == "filter delay" and filt["unit"] == "ms" and filt["sheet"] == "Budget"


def test_revisions_and_review_copies_fold_into_one_document(built):
    core = _core(built)
    assert core["System_requirements_v1.2"]["copies"] == 2
    design = core["Detailed_design_v2.1"]
    assert design["copies"] == 2 and "review" not in design["relative_path"]
    sources = util.load_jsonl(built.documents_dir / "doc-sources.jsonl")
    assert {s["file_key"] for s in sources if s["node_ref"] == "Detailed_design_v2.1"} == {
        "Detailed_design_v2.1", "Detailed_design_v2.1_review"}


def test_stage_comes_with_its_reason(built):
    core = _core(built)
    assert core["System_requirements_v1.2"]["stage"] == "Requirements"
    assert core["Error_budget"]["stage"] == "Design" and core["Error_budget"]["reason"].startswith("sheet-name")
    assert all(d["reason"] for d in core.values())


def test_a_document_names_code_only_through_distinctive_names(built):
    edges = [e for e in util.load_jsonl(built.documents_dir / "links" / "doc-to-code.jsonl") if e["document_key"] == "Detailed_design_v2.1"]
    names = {s["sym"] for e in edges for s in e["symbols"]}
    assert {"pid_step", "run_loop", "clamp_output", "PID_OUTPUT_LIMIT"} <= names
    assert "Control" not in names and "loop" not in names


def test_a_link_between_documents_says_why(built):
    edges = util.load_jsonl(built.documents_dir / "links" / "between-docs.jsonl")
    kinds = {(e["kind"], e["from"], e["to"]) for e in edges}
    assert ("quotes", "Detailed_design_v2.1", "System_requirements_v1.2") in kinds
    assert ("cites", "Detailed_design_v2.1", "System_requirements_v1.2") in kinds
    differ = [e for e in edges if e["kind"] == "shares" and e["differ_count"]]
    assert any("settle time" in e["differ"] for e in differ)


def test_a_document_never_links_to_itself_and_the_gate_passes(built):
    errors, counts = corpus.validate(built)
    assert errors == []
    assert counts["map documents"] == 7


def test_requirements_keep_their_ids(built):
    s = {r["key"]: r for r in util.load_jsonl(built.documents_dir / "doc-outlines.jsonl")}
    reqs = s["System_requirements_v1.2"]["requirements"]
    assert any(r["ids"] == ["REQ-012"] for r in reqs)


def test_the_gate_catches_a_changed_text(built, tmp_path):
    p = built.documents_dir / "text" / "Project_notes.txt"
    before = p.read_bytes()
    try:
        p.write_bytes(before + b"tampered\n")
        errors, _ = corpus.validate(built)
        assert any("Project_notes" in e for e in errors)
    finally:
        p.write_bytes(before)
