"""Code maps: what the readers must find, and what they must refuse to invent."""
from __future__ import annotations

from contextmax import util


def _fns(proj, target):
    return util.load_jsonl(proj.code_dir / target / "function-list.jsonl")


def _by_name(fns, name):
    return [f for f in fns if f["name"] == name]


def test_a_call_edge_needs_a_definition_in_the_folders(built):
    fns = _fns(built, "firmware")
    names = {f["name"] for f in fns}
    for f in fns:
        assert set(f["calls"]) <= names


def test_pid_step_has_its_real_callers(built):
    fns = _fns(built, "firmware")
    pid = _by_name(fns, "pid_step")[0]
    callers = {fns[i]["name"] for i in pid["caller_ids"]}
    assert {"run_loop", "tune_gains", "test_pid_step"} <= callers
    assert pid["file"] == "control/src/pid.c" and pid["first_line"] == 4


def test_a_macro_that_stands_for_a_function_becomes_a_call(built):
    run = _by_name(_fns(built, "firmware"), "run_loop")[0]
    assert "write_log" in run["calls"]
    assert ["LOG", "write_log"] in run["via_macros"]


def test_calls_through_pointers_are_counted_never_guessed(built):
    fns = _fns(built, "firmware")
    run = _by_name(fns, "run_loop")[0]
    assert any("ops->start" in c["expr"] for c in run["indirect_calls"])
    recv = _by_name(fns, "can_receive")[0]
    assert any(c["expr"].startswith("handlers[") for c in recv["indirect_calls"])


def test_a_name_defined_twice_records_its_alternatives(built):
    fns = _fns(built, "firmware")
    read = _by_name(fns, "read_sensor")[0]
    amb = dict((name, ids) for name, ids in read["ambiguous"])
    assert "hal_read_adc" in amb and len(amb["hal_read_adc"]) == 2


def test_roles_come_from_the_path(built):
    fns = _fns(built, "firmware")
    assert _by_name(fns, "test_pid_step")[0]["role"] == "test"
    assert {f["role"] for f in _by_name(fns, "hal_read_adc")} == {"product", "stub"}


def test_the_comment_above_a_function_is_its_description(built):
    pid = _by_name(_fns(built, "firmware"), "pid_step")[0]
    assert pid["doc"].startswith("One step of the PI controller")


def test_vhdl_hierarchy_design_top_orphan_and_testbench(built):
    s = util.load_json(built.code_dir / "logic" / "hdl-overview.json")
    assert s["hdl_top"] == "motion_top"
    assert s["unplaced_entities"] == ["old_filter"]
    ents = {e["name"]: e for e in util.load_jsonl(built.code_dir / "logic" / "hdl-entities.jsonl")}
    assert ents["motion_top_tb"]["classification"] == "testbench"
    assert ents["sys_timer"]["placed_by"] == ["motion_top", "pwm_gen"]
    edges = util.load_json(built.code_dir / "logic" / "hdl-tree.json")
    assert sum(1 for e in edges if e["child"] == "quad_decoder") == 2


def test_python_calls_resolve_through_the_file(built):
    fns = _fns(built, "tools")
    main = _by_name(fns, "main")[0]
    assert set(main["calls"]) == {"offset_of", "load_capture"}


def test_matlab_indexing_is_not_a_call(built):
    fns = _fns(built, "models")
    step = _by_name(fns, "step_response")[0]
    assert "y" not in step["calls"] and "y" not in step["external_calls"]
    model = _by_name(fns, "pid_model")[0]
    assert set(model["calls"]) == {"plant_tf", "step_response"}
    assert model["doc"].startswith("Closed-loop step response")


def test_every_map_writes_the_same_files(built):
    for t in ("firmware", "tools", "models"):
        for name in ("function-list.jsonl", "call-pairs.json", "name-lookup.json", "module-list.json", "overview.json",
                     "code-guide.md", "unmatched-calls.json", "indirect-calls.json"):
            assert (built.code_dir / t / name).exists(), (t, name)
