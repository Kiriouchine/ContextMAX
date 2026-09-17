# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Phase 3 session 3: units, spreadsheets (sheet-v1), prose quantities and `cmx q param`."""

from __future__ import annotations

import pytest

from contextmax.docs import params as params_module
from contextmax.docs import structure as structure_module
from contextmax.docs import units
from contextmax.docs.adapters.markdown import MarkdownAdapter
from contextmax.docs.adapters.sheet import SheetAdapter, col_letter, parse_number
from contextmax.query.api import open_index
from fixtures import office


def cells(tree):
    return [b for b in tree.blocks if b.kind == "cell"]


def params_of(tree, key):
    return params_module.cell_parameters(tree, key, structure_module.build(tree, key))


# ----- units --------------------------------------------------------------------------------------
def test_unit_normalisation_and_label_split():
    assert units.normalise_unit("degrees") == "deg" and units.normalise_unit("Hz") == "Hz"
    assert units.normalise_unit("hz") == "Hz" and units.normalise_unit("Nm") == "N·m" and units.normalise_unit("nm") == "nm"
    assert units.normalise_unit("furlong") == "furlong"  # unknown units are kept, never dropped
    assert units.normalise_unit("furlong", units.alias_table(["furlong=fur"])) == "fur"
    assert units.split_label_unit("sample rate [Hz]") == ("sample rate", "Hz")
    assert units.split_label_unit("mass (kg)") == ("mass", "kg")
    assert units.split_label_unit("count (2)") == ("count (2)", None)
    assert units.unit_like("[m/s]") and not units.unit_like("servo error")


def test_prose_quantities_take_the_preceding_phrase_as_label():
    md = (
        "# Spec\n\nThe servo shall hold position within 2.0 deg at a sample rate of 50 Hz.\n\n"
        "Mass is 0.42 kg. In 2019 we measured 5 a and 3 In samples.\n\n- torque limit: 1.5 Nm\n"
    )
    tree = MarkdownAdapter().extract("docs/spec.md", md.encode())
    rows = params_module.prose_quantities(tree, "docs/spec.md", structure_module.build(tree, "docs/spec.md"))
    got = {(r["label"], r["value"], r["unit_norm"]) for r in rows}
    assert ("servo shall hold position", 2.0, "deg") in got  # the preceding phrase, edge stop words trimmed
    assert ("sample rate", 50, "Hz") in got  # starts after the previous quantity, not at "deg at a"
    assert ("Mass", 0.42, "kg") in got
    assert ("torque limit", 1.5, "N·m") in got
    assert not any(r["display"] in ("5", "3", "2019") for r in rows)  # "5 a" and "3 In" are not quantities
    first = next(r for r in rows if r["value"] == 2.0)
    assert first["id"] == "param:docs/spec.md#spec~1" and first["cite"] == "docs/spec.md:3"
    assert first["section"] == "doc:docs/spec.md#spec" and first["source_kind"] == "prose"


# ----- sheets -------------------------------------------------------------------------------------
def test_csv_cells_labels_units_and_parameter_rows():
    assert col_letter(1) == "A" and col_letter(28) == "AB"
    assert parse_number("2.0") == 2.0 and parse_number("-3") == -3 and parse_number("1,5") == 1.5 and parse_number("x") is None
    csv = b"label,value,unit\nservo error,2.0,deg\nsample rate,50,Hz\nnote,free text,\n"
    tree = SheetAdapter().extract("data/table.csv", csv)
    assert tree.metadata["page_unit"] == "sheet" and tree.pages == 1 and tree.title == "table.csv"
    lines = [b.text for b in cells(tree)]
    assert "B2\tservo error\t2\tdeg" in lines and "B3\tsample rate\t50\tHz" in lines
    rows = params_of(tree, "data/table.csv")
    by_cell = {r["cell"]: r for r in rows}
    assert by_cell["B2"]["label"] == "servo error" and by_cell["B2"]["value"] == 2 and by_cell["B2"]["unit_norm"] == "deg"
    assert by_cell["B2"]["header"] == "value" and by_cell["B2"]["id"] == "param:data/table.csv#table.csv!B2"
    assert by_cell["B2"]["cite"] == "data/table.csv table.csv!B2"
    assert "B4" not in by_cell  # free text is searchable but not a parameter


def test_ods_formulas_and_literals():
    tree = SheetAdapter().extract("data/params.ods", office.ODS)
    rows = params_of(tree, "data/params.ods")
    by_id = {r["id"]: r for r in rows}
    assert by_id["param:data/params.ods#Params!B2"]["value"] == 2 and by_id["param:data/params.ods#Params!B2"]["unit_norm"] == "deg"
    doubled = by_id["param:data/params.ods#Params!B3"]
    assert doubled["formula"] == "=B2*2" and doubled["value"] == 4 and doubled["label"] == "doubled"
    literal = by_id["param:data/params.ods#Params!B3~lit1"]
    assert literal["value"] == 2 and literal["source_kind"] == "formula-literal" and literal["unit"] is None


def test_sheet_bounds_are_announced():
    adapter = SheetAdapter()
    adapter.max_rows = 2
    tree = adapter.extract("data/big.csv", b"a,b\n1,2\n3,4\n5,6\n")
    assert any("TRUNCATED" in n for n in tree.notes)
    assert {b.line for b in cells(tree)} == {1, 2}


def test_xlsx_formulas_hidden_rows_and_units(monkeypatch):
    pytest.importorskip("openpyxl")
    monkeypatch.delenv("CONTEXTMAX_NO_OPTIONAL_READERS", raising=False)
    tree = SheetAdapter().extract("data/gains.xlsx", office.gains_xlsx())
    assert tree.pages == 2 and "openpyxl" in tree.adapter_version and tree.determinism == "version-bound"
    rows = params_of(tree, "data/gains.xlsx")
    by_cell = {(r["sheet"], r["cell"]): r for r in rows if r["source_kind"] == "cell"}
    servo = by_cell[("Gains", "B2")]
    assert servo["label"] == "servo error" and servo["value"] == 2 and servo["unit_norm"] == "deg"  # unit from the cell to the right
    assert by_cell[("Gains", "B3")]["unit_norm"] == "Hz" and by_cell[("Gains", "B3")]["label"] == "sample rate"  # unit from [Hz]
    ki = by_cell[("Gains", "B5")]
    assert ki["formula"] == "=B4*2" and ki["label"] == "Ki"
    assert by_cell[("Gains", "B7")]["hidden"] is True and by_cell[("Gains", "B2")]["hidden"] is False
    assert by_cell[("Notes", "B2")]["value"] == 2.5 and by_cell[("Notes", "B2")]["unit_norm"] == "deg"
    literal = next(r for r in rows if r["id"].endswith("Gains!B5~lit1"))
    assert literal["value"] == 2 and literal["source_kind"] == "formula-literal"


def test_xls_values(monkeypatch):
    pytest.importorskip("xlrd")
    monkeypatch.delenv("CONTEXTMAX_NO_OPTIONAL_READERS", raising=False)
    tree = SheetAdapter().extract("data/book.xls", office.book_xls())
    rows = params_of(tree, "data/book.xls")
    labels = {(r["label"], r["value"], r["unit_norm"]) for r in rows}
    assert ("servo error", 2, "deg") in labels and ("sample rate", 50, "Hz") in labels


# ----- query --------------------------------------------------------------------------------------
def test_query_param_compare_across_documents(built):
    index = open_index(str(built))
    try:
        result = index.parameter("servo error", compare=True)
        assert result["n"] >= 3
        sources = {h["source_kind"] for h in result["hits"]}
        assert {"cell", "prose"} <= sources
        group = next(g for g in result["comparison"] if g["label_norm"] == "servo error")
        assert group["n_documents"] == 2 and group["verdict"] == "agree"  # csv and ods both say 2 deg
        assert any(g["label_norm"] == "servo error stayed" for g in result["comparison"])  # prose label kept as written
        cites = {h["cite"] for h in result["hits"]}
        assert "data/table.csv table.csv!B2" in cites and "data/params.ods Params!B2" in cites
        by_value = index.parameter("", value=2, unit="degrees")  # alias normalised to deg
        assert by_value["n"] >= 2 and all(h["unit_norm"] == "deg" and h["value"] == 2 for h in by_value["hits"])
    finally:
        index.con.close()
