"""C++ code maps: names with their namespaces and classes, calls followed by declared types, and the
calls the text cannot settle counted instead of guessed. A small mixed C and C++ code base."""
from __future__ import annotations

from pathlib import Path

import pytest

from contextmax import util
from contextmax.code import cpp_lang, run
from contextmax.docs import corpus, symbols

FILES = {
    "drive/motor.hpp": """\
#pragma once
namespace drive {

using Level = int;

struct Ops {
    void (*start)(int);
};

// A motor driven by PWM.
class Motor {
public:
    explicit Motor(int pole_pairs);
    virtual ~Motor();
    virtual void spin(double rpm);
    double rpm() const;
    void dispatch(void (*handler)(int), void (*callback)(int));
protected:
    void apply_torque(double nm);
private:
    int pole_pairs_;
    double rpm_ = 0.0;
};

class StepperMotor : public Motor {
public:
    StepperMotor();
    void spin(double rpm) override;
    void step_once();
};

}  // namespace drive
""",
    "drive/motor.cpp": """\
#include "motor.hpp"
#include "hal.h"

namespace drive {

Motor::Motor(int pole_pairs) : pole_pairs_(pole_pairs)
{
    hal_init();
}

Motor::~Motor() {}

void Motor::spin(double rpm)
{
    rpm_ = rpm;
    apply_torque(rpm / 10.0);
}

void Motor::apply_torque(double nm)
{
    hal_write_pwm(static_cast<int>(nm));
    hal_write_pwm((Level)(nm));
}

void Motor::dispatch(void (*handler)(int), void (*callback)(int))
{
    (*handler)(1);
    (callback)(2);
}

double Motor::rpm() const { return rpm_; }

StepperMotor::StepperMotor() : Motor(50) {}

void StepperMotor::spin(double rpm)
{
    Motor::spin(rpm);
    step_once();
}

void StepperMotor::step_once()
{
    this->apply_torque(1.0);
}

}  // namespace drive
""",
    "control/loop.h": """\
#pragma once
#include <functional>
#include <memory>
#include "motor.hpp"

namespace control {

using MotorRef = drive::Motor&;

class Loop {
public:
    Loop();
    void tick();
    void tick(int n);
private:
    drive::Motor* motor_;
    std::unique_ptr<drive::StepperMotor> stepper_;
    std::function<void()> on_done_;
    drive::Ops* ops_;
};

double clamp_value(double v, double lo, double hi);

}  // namespace control
""",
    "control/loop.cpp": """\
#include <vector>
#include "loop.h"

namespace control {

namespace {
int local_counter() { return 1; }
}

Loop::Loop() : motor_(new drive::Motor(7)) {}

void Loop::tick()
{
    motor_->spin(1200.0);
    stepper_->step_once();
    tick(local_counter());
    auto made = std::make_unique<drive::StepperMotor>();
    made->spin(5.0);
    drive::Motor local(3);
    local.spin(clamp_value(1.0, 0.0, 2.0));
    std::vector<int> values;
    values.push_back(1);
    on_done_();
    ops_->start(1);
    auto twice = [](int x) { return clamp_value(x, 0.0, 9.0); };
    twice(4);
}

void Loop::tick(int n)
{
    for (int i = 0; i < n; ++i) {
        this->tick();
    }
}

double clamp_value(double v, double lo, double hi)
{
    return std::min(std::max(v, lo), hi);
}

void turn_with(MotorRef m)
{
    m.spin(1.0);
}

void spin_any(auto& thing)
{
    thing.spin(2.0);
}

}  // namespace control
""",
    "hal/hal.h": """\
#ifndef HAL_H
#define HAL_H
#ifdef __cplusplus
extern "C" {
#endif
void hal_init(void);
void hal_write_pwm(int duty);
int hal_read_adc(int ch);
void app_on_fault(int code);
#ifdef __cplusplus
}
#endif
#endif
""",
    "hal/hal.c": """\
#include "hal.h"

void hal_init(void)
{
    hal_write_pwm(0);
}

void hal_write_pwm(int duty)
{
    (void)duty;
}

int hal_read_adc(int ch)
{
    app_on_fault(ch);
    return ch;
}
""",
    "app/main.cpp": """\
#include "loop.h"
#include "hal.h"

extern "C" void app_on_fault(int code)
{
    control::Loop loop;
    loop.tick();
}

int main()
{
    control::Loop l;
    l.tick(3);
    return hal_read_adc(0);
}
""",
    "broken/odd.cpp": """\
void still_found()
{
}

class { int x  ;; ) half(;
""",
}


def _map(tmp_path: Path, name: str = "code") -> Path:
    root = tmp_path / "src"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    out = tmp_path / name
    run.map_target({"root": str(root), "name": name, "label": name}, out)
    return out


@pytest.fixture(scope="module")
def cmap(tmp_path_factory):
    return _map(tmp_path_factory.mktemp("cpp"))


def _fns(out: Path) -> list[dict]:
    return util.load_jsonl(out / "function-list.jsonl")


def _q(fns: list[dict], qualname: str, line: int | None = None) -> dict:
    found = [f for f in fns if f.get("qualname", f["name"]) == qualname and (line is None or f["first_line"] == line)]
    assert len(found) == 1, (qualname, [f.get("qualname") for f in fns])
    return found[0]


def _overload(fns: list[dict], qualname: str, params: list[str]) -> dict:
    found = [f for f in fns if f.get("qualname") == qualname and f["params"] == params]
    assert len(found) == 1, (qualname, params)
    return found[0]


def _calls(fns: list[dict], f: dict) -> set[str]:
    return {fns[i].get("qualname", fns[i]["name"]) for i in f["callee_ids"]}


def test_definitions_get_their_namespace_class_kind_and_lines(cmap):
    fns = _fns(cmap)
    spin = _q(fns, "drive::Motor::spin")
    assert (spin["file"], spin["first_line"], spin["last_line"], spin["kind"]) == ("drive/motor.cpp", 13, 17, "method")
    assert spin["class"] == "drive::Motor" and spin["lang"] == "C++"
    assert _q(fns, "drive::Motor::Motor")["kind"] == "constructor"
    assert _q(fns, "drive::Motor::~Motor")["kind"] == "destructor"
    assert _q(fns, "control::clamp_value")["kind"] == "function"
    local = _q(fns, "control::local_counter")
    assert local["file_local"] is True
    assert len([f for f in fns if f.get("qualname") == "control::Loop::tick"]) == 2       # two overloads


def test_a_header_is_cpp_by_its_text_and_c_headers_stay_c(cmap):
    files = util.load_json(cmap / "file-list.json")
    assert files["control/loop.h"]["lang"] == "C++"
    assert files["hal/hal.h"]["lang"] == "C"
    assert files["hal/hal.c"]["lang"] == "C"


def test_member_calls_follow_the_declared_type(cmap):
    fns = _fns(cmap)
    tick = _overload(fns, "control::Loop::tick", [])
    assert {"drive::Motor::spin",                 # motor_ is a drive::Motor*
            "drive::StepperMotor::step_once",     # stepper_ is a unique_ptr<StepperMotor>
            "drive::StepperMotor::spin",          # auto made = make_unique<StepperMotor>()
            "drive::Motor::Motor",                # drive::Motor local(3)
            "control::clamp_value",
            } <= _calls(fns, tick)


def test_overloads_are_told_apart_by_the_number_of_arguments(cmap):
    fns = _fns(cmap)
    no_args, one_arg = _overload(fns, "control::Loop::tick", []), _overload(fns, "control::Loop::tick", ["int n"])
    assert one_arg["id"] in no_args["callee_ids"]          # tick(local_counter())
    assert no_args["id"] in one_arg["callee_ids"]          # this->tick()
    main = _q(fns, "main")
    assert one_arg["id"] in main["callee_ids"] and no_args["id"] not in main["callee_ids"]


def test_a_virtual_call_lists_the_overrides(cmap):
    fns = _fns(cmap)
    tick = _overload(fns, "control::Loop::tick", [])
    listed = dict((name, ids) for name, ids in tick["ambiguous"])
    override = _q(fns, "drive::StepperMotor::spin")["id"]
    assert any(override in ids for ids in listed.values())


def test_base_classes_qualified_calls_initialisers_and_new(cmap):
    fns = _fns(cmap)
    assert _calls(fns, _q(fns, "drive::StepperMotor::spin")) == {"drive::Motor::spin", "drive::StepperMotor::step_once"}
    assert _q(fns, "drive::StepperMotor::spin")["ambiguous"] == []    # Motor::spin(rpm) is no virtual call
    assert _calls(fns, _q(fns, "drive::StepperMotor::step_once")) == {"drive::Motor::apply_torque"}
    assert "drive::Motor::Motor" in _calls(fns, _q(fns, "drive::StepperMotor::StepperMotor"))
    assert "drive::Motor::Motor" in _calls(fns, _q(fns, "control::Loop::Loop"))
    assert _calls(fns, _q(fns, "control::turn_with")) == {"drive::Motor::spin"}          # through a type alias


def test_c_and_cpp_call_each_other(cmap):
    fns = _fns(cmap)
    assert "hal_init" in _calls(fns, _q(fns, "drive::Motor::Motor"))
    assert "hal_write_pwm" in _calls(fns, _q(fns, "drive::Motor::apply_torque"))
    read = [f for f in fns if f["name"] == "hal_read_adc"][0]
    assert "app_on_fault" in _calls(fns, read)                # C calls a C++ function with C linkage
    assert "app_on_fault" not in read["external_calls"]


def test_what_the_text_cannot_settle_is_counted_not_guessed(cmap):
    fns = _fns(cmap)
    tick = _overload(fns, "control::Loop::tick", [])
    assert "std::vector::push_back" in tick["external_calls"]
    exprs = {c["expr"] for c in tick["indirect_calls"]}
    assert {"on_done_", "twice", "ops_->start"} <= exprs     # a field, a lambda, a function pointer in a struct
    assert not any("start" in name for name in tick["external_calls"])
    assert _q(fns, "drive::Motor::apply_torque")["indirect_calls"] == []     # (Level)(nm) is a cast
    assert [c["expr"] for c in _q(fns, "drive::Motor::dispatch")["indirect_calls"]] == ["(*handler)", "(callback)"]
    unknown = _q(fns, "control::spin_any")
    assert unknown["callee_ids"] == []
    assert unknown["indirect_calls"][0]["candidates"] == ["drive::Motor::spin", "drive::StepperMotor::spin"]
    assert unknown["indirect_calls"][0]["method"] == "spin" and unknown["indirect_calls"][0]["candidates_count"] == 2
    assert _q(fns, "drive::Motor::spin")["overridden_by"] == ["drive::StepperMotor::spin"]


def test_text_the_parser_cannot_read_is_reported(cmap):
    ov = util.load_json(cmap / "overview.json")
    assert ov["cpp"]["files_with_syntax_errors"] == ["broken/odd.cpp"]
    assert ov["cpp"]["parser"].startswith("tree-sitter-cpp")
    assert _q(_fns(cmap), "still_found")["file"] == "broken/odd.cpp"
    assert "C++" in (cmap / "code-guide.md").read_text(encoding="utf-8")


def test_the_same_code_gives_the_same_bytes(tmp_path, cmap):
    again = _map(tmp_path)
    names = sorted(p.name for p in cmap.iterdir())
    assert names == sorted(p.name for p in again.iterdir())
    for n in names:
        assert (cmap / n).read_bytes() == (again / n).read_bytes(), n


def test_documents_can_name_cpp_code_with_its_scope(cmap):
    exact, _ = symbols.collect_names(cmap.parent, [{"name": cmap.name, "root": str(cmap.parent / "src")}])
    assert {"Motor::spin", "drive::Motor::spin", "Loop::tick", "control::clamp_value"} <= set(exact)
    rows = corpus._name_rows("See Motor::spin and control::clamp_value() before changing the loop.", exact, {}, True)
    names = {s["sym"] for r in rows for s in r["symbols"]}
    assert {"Motor::spin", "control::clamp_value"} <= names


def test_c_headers_with_a_cplusplus_guard_are_not_cpp():
    assert not cpp_lang.is_cpp_header('#ifdef __cplusplus\nextern "C" {\n#endif\nint pid_step(int e); // a::b\n')
    assert cpp_lang.is_cpp_header("namespace hw {\nint read();\n}\n")
    assert cpp_lang.is_cpp_header("template <typename T> T twice(T v);\n")
