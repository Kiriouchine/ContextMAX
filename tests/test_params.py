"""A parameter is a name, not a number."""
from __future__ import annotations

from contextmax import query
from contextmax.docs import params as P
from contextmax.docs.sheets import Units, number_text


def test_equivalent_number_spellings_share_a_key():
    assert P.canon_number("1") == P.canon_number("1.0") == P.canon_number("1,0") == "1"


def test_torque_and_length_never_merge():
    assert P.canon_unit("Nm") == "Nm" and P.canon_unit("nm") == "nm"


def test_a_constant_inside_a_formula_excludes_cell_references():
    assert P.formula_constants("=ROUND(D5*2.54/12, 3)") == ["2.54", "12", "3"]
    assert P.formula_constants("=C3-5") == ["5"]


def test_a_percent_cell_reads_as_a_percent():
    assert number_text(0.25, "0%") == ("25", "[exact 0.25]")


def test_units_in_brackets_are_normalized():
    u = Units({"sekunden": "s"})
    assert u.read("[ms]") == ("ms", True) and u.read("[sekunden]") == ("s", True)


def test_compare_reports_the_disagreement(built):
    out = query.params(built, name="settle time", compare=True)
    row = next(r for r in out["compare"] if r["name"] == "settle time")
    assert row["verdict"] == "2 different values"
    values = {v["value"] for v in row["values"]}
    assert values == {"12 ms", "15 ms"}


def test_a_formula_literal_never_gets_a_unit(built):
    out = query.params(built, origin="formula_constant", limit=500)
    assert out["rows"] and all(r["unit_norm"] == "" for r in out["rows"])
