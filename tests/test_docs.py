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
    from contextmax.docs import ocr

    row = next(r for r in util.load_jsonl(built.documents_dir / "text-index.jsonl") if r["key"] == "Test_report_3")
    root = next(f.path for f in built.folders if f.name == row["folder"])
    ink, count = ocr.render(f"{root}/{row['relative_path']}", tmp_path)
    assert count == 1 and list(ink) == [1] and 0 < ink[1] < 0.5          # a page with text on it
    png = (tmp_path / "page-0001.png").read_bytes()
    assert png.startswith(b"\x89PNG") and png[25] == 0                  # grey, 8 bits
    width = int.from_bytes(png[16:20], "big")
    assert 2400 < width < 2600                                           # an A4 page at 300 dpi


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


# == values stated in several documents ==

def _row(doc: str, label: str, value: str, unit: str = "mm", cell: str | None = None) -> dict:
    return {"doc_ref": doc, "label": label, "label_norm": label, "origin": "cell_entry" if cell else "prose_value",
            "value_norm": value, "value_shown": value, "unit": unit, "unit_norm": unit,
            "sheet": "Budget" if cell else None, "cell": cell}


def test_a_value_many_documents_state_joins_them_and_marks_every_odd_one_out_in_red():
    """Fourteen documents state one name: more than MAX_VALUE_OWNERS, so no pairs. Each document links to the
    first document stating the same value, and the two that differ from the twelve get a red link with both values."""
    docs = [f"d{i:02d}" for i in range(1, 15)]
    rows = [_row(d, "battery clearance", "214" if d in ("d07", "d12") else "267.5", cell="C9" if d == "d12" else None)
            for d in docs]
    assert len(docs) > corpus.MAX_VALUE_OWNERS
    values = corpus.value_owners(rows)
    edges = corpus._value_links(values)
    assert not [e for e in edges if e["kind"] == "shares"]
    anchors = {e["from"]: e["to"] for e in edges if e["kind"] == "anchor"}
    assert anchors == {**{d: "d01" for d in docs if d not in ("d01", "d07", "d12")}, "d12": "d07"}
    assert all(e["differ_count"] == 0 for e in edges if e["kind"] == "anchor")
    differs = {e["from"]: e for e in edges if e["kind"] == "differs"}
    assert set(differs) == {"d07", "d12"} and differs["d12"]["to"] == "d01"
    assert differs["d12"]["values"] == [["battery clearance", "214 mm", "267.5 mm", "Budget!C9", ""]]
    [conflict] = corpus.value_conflicts(values)
    assert conflict["anchor"] == "d01" and conflict["differing"] == ["d07", "d12"] and conflict["value"] == "267.5 mm"
    assert [(v["value"], v["documents_count"]) for v in conflict["values"]] == [("267.5 mm", 12), ("214 mm", 2)]


def test_with_no_majority_no_value_is_the_odd_one_out():
    """A unit cost that every bill of materials states differently: listed, joined by value, never marked red."""
    rows = [_row(f"bom{i:02d}", "unit cost", str(i % 5), "") for i in range(15)]
    values = corpus.value_owners(rows)
    edges = corpus._value_links(values)
    assert not [e for e in edges if e["kind"] == "differs"]
    anchors = {(e["from"], e["to"]) for e in edges if e["kind"] == "anchor"}
    assert ("bom05", "bom00") in anchors and ("bom06", "bom01") in anchors and len(anchors) == 10
    [conflict] = corpus.value_conflicts(values)
    assert conflict["anchor"] is None and conflict["differing"] == [] and len(conflict["values"]) == 5


def test_shared_values_link_every_pair_with_no_cap_per_document():
    """A document that shares a specific value with twenty others links to all twenty (once eight at most)."""
    rows = []
    for i in range(20):
        rows += [_row("hub", f"pump {i} pressure", "2", "bar"), _row(f"p{i:02d}", f"pump {i} pressure", "2", "bar")]
    edges = corpus._value_links(corpus.value_owners(rows))
    assert len([e for e in edges if e["kind"] == "shares" and "hub" in (e["from"], e["to"])]) == 20
    assert not [e for e in edges if e["kind"] != "shares"]


def test_two_documents_that_disagree_share_a_red_link_and_neither_is_the_odd_one_out():
    rows = [_row("b_doc", "settle time", "15", "ms"), _row("a_doc", "settle time", "12", "ms")]
    values = corpus.value_owners(rows)
    [edge] = corpus._value_links(values)
    assert (edge["kind"], edge["from"], edge["to"], edge["differ_count"]) == ("shares", "a_doc", "b_doc", 1)
    [conflict] = corpus.value_conflicts(values)
    assert conflict["anchor"] is None and conflict["differing"] == [] and conflict["documents_count"] == 2


def test_values_that_differ_are_listed_and_the_gate_checks_the_list(built):
    path = built.documents_dir / "value-conflicts.jsonl"
    conflicts = {c["label_norm"]: c for c in util.load_jsonl(path)}
    assert "settle time" in conflicts
    differs = [e for e in util.load_jsonl(built.documents_dir / "links" / "between-docs.jsonl") if e["kind"] == "differs"]
    assert any(v[0] == "settle time" for e in differs for v in e["values"])
    assert "value-conflicts.jsonl" in util.load_json(built.workspace / "buildinfo.json")["corpus"]["bytes_sha256"]
    before = path.read_bytes()
    try:
        path.write_bytes(before.replace(b'"settle time"', b'"settle tim"', 1))
        errors, _ = corpus.validate(built)
        assert "value-conflicts.jsonl does not match the value list" in errors
    finally:
        path.write_bytes(before)


def test_names_that_differ_only_in_capitals_get_keys_of_their_own(built, tmp_path):
    """Windows takes ReadMe.txt and readme.txt for one file: as keys (text/<key>.txt) they must differ more."""
    from contextmax import pipeline, project
    from contextmax.docs import textcache

    rows = [{"Name": n, "Folder": "f", "RelativePath": f"{d}/{n}"} for d, n in (("a", "ReadMe.txt"), ("b", "readme.txt"),
                                                                                 ("c", "Notes.txt"))]
    keys = textcache.assign_keys(rows)
    assert keys[("f", "c/Notes.txt")] == "Notes"
    assert len({keys[("f", "a/ReadMe.txt")].casefold(), keys[("f", "b/readme.txt")].casefold()}) == 2
    src = tmp_path / "src"
    # of different sizes, as in the project where this was found: same name and size would be one document's copies
    for d, n, text in (("a", "ReadMe.txt", "the first read-me"), ("b", "readme.txt", "the second read-me" + " longer" * 60)):
        (src / d).mkdir(parents=True)
        (src / d / n).write_text(text, encoding="utf-8")
    proj = project.create("Two readmes", [{"path": str(src), "holds": "documents"}], str(tmp_path / "ws"))
    pipeline.build(proj, depth="documents", ocr=False)          # the gate passes: no text replaced another
    texts = sorted((proj.documents_dir / r["cached_text"]).read_text(encoding="utf-8")
                   for r in util.load_jsonl(proj.documents_dir / "text-index.jsonl"))
    assert texts == ["the first read-me", "the second read-me" + " longer" * 60]
