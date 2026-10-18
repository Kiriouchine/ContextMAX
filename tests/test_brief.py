"""The way in for an AI: one call (brief), constants with their uses, the documents' text searchable, plain
text out, and the index faults a paired agent test found."""
from __future__ import annotations

from types import SimpleNamespace

from contextmax import ask, brief, catalogue, plain, query, util
from contextmax.code import c_lang
from contextmax.docs import corpus, search, textcache, value_code


def test_an_include_is_read_from_the_file_not_from_the_blanked_text():
    text = '#include "laser_control_f7.h"\n#include <math.h>\n// #include "old.h"\n/* #include "gone.h" */\n'
    assert c_lang.includes_of(text, c_lang.blank_out(text)) == ["laser_control_f7.h", "math.h"]


def test_named_numbers_record_their_uses_and_their_header(built):
    rows = {v["name"]: v for v in util.load_jsonl(built.code_dir / "firmware" / "values.jsonl")}
    limit = rows["PID_OUTPUT_LIMIT"]
    assert limit["uses_count"] == 2 and {u["in"] for u in limit["used_in"]} == {"clamp_output"}
    assert all(u["file"].endswith("pid.c") for u in limit["used_in"])          # defined in pid.h, used in pid.c
    assert limit["included_by_count"] == 4 and rows["SENSOR_SAMPLE_HZ"]["uses_count"] == 0
    files = util.load_json(built.code_dir / "firmware" / "file-list.json")
    assert files["control/src/loop.c"]["includes"] == ["pid.h", "sensor.h", "log.h"]


def test_the_documents_text_is_searchable_without_reading_it_again(built):
    assert search.check(built) == []
    ix = ask._index(built)
    assert "store" in ix and "passages" not in ix                      # looked up, not loaded
    hits = query.text_hits(built, "settle time")
    plan = next(h for h in hits if h["key"] == "Test_plan")
    assert plan["line"] == 11 and "15 ms" in plan["says"] and "line 11" in plan["cite"]
    out = query.find(built, "doc", "settle time")
    assert out["text_hits"] and not out["hits"]                        # no title holds it; the text does
    assert "documents whose text says it: " in plain.find(out, "doc")


def test_symbol_callers_and_impact_cover_named_numbers(built):
    hit = next(h for h in query.find(built, "symbol", "PID_OUTPUT_LIMIT")["hits"] if h.get("value"))
    assert hit["value"] == "1000" and hit["uses_count"] == 2 and hit["cite"].endswith("pid.h:4")
    out = query.find(built, "impact", "PID_OUTPUT_LIMIT")
    imp = next(h for h in out["hits"] if h.get("value"))
    assert [f["name"] for f in imp["used_by"]] == ["clamp_output"]
    assert imp["impact"]["direct_callers"] == 1 and "run_loop" in imp["impact"]["entry_points_reached"]
    text = plain.find(out, "impact")
    assert "used 2 times: clamp_output (pid.c:18)" in text and "its header is included by 4 files" in text


def test_the_brief_gives_the_ways_in_with_their_lines_in_one_call(built):
    b = brief.brief(built, "What is the settle time, and do the documents agree?")
    texts = {w["text"] for w in b["ways_in"]}
    assert "#define PID_SETTLE_TIME_MS 12" in texts and "- settle time: 15 ms" in texts
    stated = next(x for x in b["lookups"] if x["window"]["cite"].startswith("settle time"))
    assert "with 2 different values (the documents differ)" in stated["says"]
    shown = brief.render(b)
    assert shown.startswith("ContextMAX brief · demo-project · built ") and "WAYS IN" in shown and "LOOKED UP" in shown
    assert "control/inc/pid.h:3" in shown and "NEXT:" in shown
    assert "Nothing in the index holds these words" in brief.render(brief.brief(built, "zzqx wvvy"))


def test_a_name_no_value_has_suggests_the_names_that_share_its_words(built):
    out = query.params(built, name="pid limit")
    assert out["n"] == 0 and out["near"][0]["name"] == "output limit"
    assert "names that share its words: output limit" in plain.params(out)
    compare = plain.params(query.params(built, name="settle time", compare=True))
    assert "settle time: 2 different values" in compare


def test_a_sentence_value_takes_the_fuller_name_its_own_document_gives_it():
    rows = [{"label": "Laser control max current", "label_norm": "laser control max current", "label_source": "label"},
            {"label": "max current", "label_norm": "max current", "label_source": "sentence"},
            {"label": "settle time", "label_norm": "settle time", "label_source": "sentence"}]
    corpus._fuller_names(rows)
    assert rows[1]["label"] == "Laser control max current" and rows[1]["label_source"] == "sentence"
    assert rows[2]["label"] == "settle time"                           # no fuller name in this document
    two = [{"label": "Pump max current", "label_norm": "pump max current", "label_source": "label"},
           {"label": "Fan max current", "label_norm": "fan max current", "label_source": "label"},
           {"label": "max current", "label_norm": "max current", "label_source": "sentence"}]
    corpus._fuller_names(two)
    assert two[2]["label"] == "max current"                            # two could be meant: left as it is


def test_a_requirement_names_its_value_in_one_word_when_the_document_says_whose():
    assert corpus.name_and_symbol("REQ-74611: The pump control shall keep the timeout at ") == ("timeout", None)
    assert corpus.name_and_symbol("The unit shall keep the time at ") == (None, None)       # a word that names nothing
    assert corpus.name_and_symbol("the timeout is ") == (None, None)                       # not a requirement
    rows = [{"label": "Pump control timeout", "label_norm": "pump control timeout", "label_source": "label"},
            {"label": "timeout", "label_norm": "timeout", "label_source": "sentence", "symbol": None}]
    corpus._fuller_names(rows)
    assert rows[1]["label_norm"] == "pump control timeout"
    alone = [{"label": "timeout", "label_norm": "timeout", "label_source": "sentence", "symbol": None}]
    corpus._fuller_names(alone)
    assert alone[0]["label_norm"] == "" and alone[0]["label"] is None                      # whose timeout: not said


def test_a_numbered_name_meets_the_code_only_in_its_own_part():
    def stated(doc, sentence):
        return {"label": "control limit 10", "label_norm": "control limit 10", "origin": "cell_entry", "value_norm": "18",
                "value_shown": "18", "value_as_written": "18", "unit_norm": "", "unit": "", "doc_ref": doc, "file_key": doc,
                "stage": "Design", "line_no": 3, "page": None, "section": "sheet Budget", "sheet": "Budget", "cell": "B10",
                "sentence": sentence, "context": sentence}

    code = [{"name": "LASER_CONTROL_LIMIT_10", "value": "624", "value_norm": "624", "unit": "", "target": "fw",
             "target_label": "fw", "file": "laser/laser_f10.c", "line": 4, "module": "laser", "lang": "C"}]
    optics = value_code.links([stated("Optics_config_budget", "control limit 10 = 18")], code)
    laser = value_code.links([stated("Laser_control_budget", "control limit 10 = 18")], code)
    assert optics == [] and laser and laser[0]["matched_by"] == "name, with one more word in the code"


def test_another_tools_report_about_the_project_is_not_catalogued(tmp_path):
    (tmp_path / "graphify").mkdir()
    for name in ("GRAPH_REPORT.md", "graph.json"):
        (tmp_path / "graphify" / name).write_text("x", encoding="utf-8")
    (tmp_path / "spec.md").write_text("# Spec", encoding="utf-8")
    rows, stepped = catalogue.walk_folder(tmp_path)
    assert [rel for _, rel, _ in rows] == ["spec.md"]
    assert stepped["skip marker, working folder or another tool's output"] == 1


def test_an_older_index_names_its_text_hash_the_new_way(tmp_path):
    (tmp_path / "text-index.jsonl").write_text('{"key": "A", "sha256": "abc", "chars": 3}\n', encoding="utf-8")
    proj = SimpleNamespace(documents_dir=tmp_path)
    assert textcache.migrate(proj) and util.load_jsonl(tmp_path / "text-index.jsonl") == [
        {"key": "A", "text_sha256": "abc", "chars": 3}]
    assert not textcache.migrate(proj)                                  # once


def test_a_short_name_is_used_where_it_stands(tmp_path):
    from contextmax.code import values

    (tmp_path / "gps.c").write_text("#define r1 5\nint f(void) { return r1 + 1; }\n", encoding="utf-8")
    values.write(tmp_path, {"C": [(str(tmp_path / "gps.c"), "gps.c")]}, {"gps.c": {"module": "m", "includes": []}},
                 [{"file": "gps.c", "first_line": 2, "last_line": 2, "name": "f"}])
    r1 = util.load_jsonl(tmp_path / "values.jsonl")[0]
    assert r1["name"] == "r1" and r1["used_in"] == [{"file": "gps.c", "line": 2, "in": "f"}]


def test_a_nominal_or_typical_value_keeps_its_name_and_a_capitalised_code_name_counts():
    assert corpus.name_and_symbol("REQ-22701: The encoder drive shall keep the nominal voltage at ") == ("nominal voltage", None)
    assert corpus.name_and_symbol("the supply is a nominal ") == (None, None)
    exact = {"pid_step": {("fw", "control", "function")}, "update": {("fw", "control", "function")}}
    rows = corpus._name_rows("Pid_step() runs first. Update it later. Then pid_step() again.", exact, {})
    assert rows[0]["symbols"][0]["sym"] == "pid_step" and rows[0]["symbols"][0]["n"] == 2   # "Update" is a word


def test_the_part_a_question_names_is_its_module_of_two_words_or_more():
    t = {"name": "fw"}
    ix = {"functions": [(t, {"module": "laser_control", "file": "a.c"}), (t, {"module": "laser_config", "file": "b.c"}),
                        (t, {"module": "control", "file": "c.c"})], "code_values": []}
    assert ask.part_of(ix, ["laser", "control", "limit"]) == "laser_control"
    assert ask.part_of(ix, ["control", "limit"]) is None                 # a one-word module names no part
    assert ask.part_of(ix, ["laser", "control", "config"]) is None       # two parts fit as well: neither


def test_the_brief_starts_with_what_the_question_names(built):
    b = brief.brief(built, "Who calls clamp_output, and where is PID_OUTPUT_LIMIT used?")
    named = {n["name"]: n for n in b["named"]}
    clamp = named["clamp_output"]
    assert {c["name"] for c in clamp["callers"]} == {"pid_step", "test_pid_step"}
    assert all(":" in c["cite"] for c in clamp["callers"]) and clamp["reach"]["product_functions"] >= 1
    limit = named["PID_OUTPUT_LIMIT"]
    assert limit["value"] == "1000" and {u["in"] for u in limit["uses"]} == {"clamp_output"}
    assert b["ways_in"][0]["why"].startswith("named in the question")
    shown = brief.render(b)
    assert "NAMED IN THE QUESTION: clamp_output (function)" in shown and "called by 2: " in shown
    assert "NAMED IN THE QUESTION: PID_OUTPUT_LIMIT (named number)" in shown


def test_a_code_name_holds_the_words_its_initials_spell():
    asked = ask.Asked({"passages_count": 10, "df": {}}, ask.words("How does the extended Kalman filter work?"))
    assert asked.held(ask._code_words("ekf_attitude_step")) == {"extended", "kalman", "filter"}
    assert asked.initials("f_ekf1") == "EKF: extended kalman filter" and asked.initials("pid_step") == ""


def test_in_a_question_about_one_part_its_own_words_say_where_not_what():
    asked = ask.Asked({"passages_count": 10, "df": {}}, ["encoder", "drive", "nominal", "voltage"])
    asked.part = {"encoder", "drive"}
    stated = asked.score({"encoder", "drive", "nominal", "voltage"})
    assert asked.score({"encoder", "drive"}) == 0.0 < asked.score({"encoder", "drive", "voltage"}) < stated
    alone = ask.Asked({"passages_count": 10, "df": {}}, ["encoder", "drive"])
    alone.part = {"encoder", "drive"}
    assert alone.score({"encoder", "drive"}) > 0                    # a question about the part itself


def test_a_value_compared_is_counted_in_documents_not_lines():
    out = {"query": {"name": "x"}, "compare": [{"name": "x", "verdict": "match", "documents": 1, "values": [
        {"value": "5 V", "stated_in": [{"document": "A", "cite": "A · line 3"}, {"document": "A", "cite": "A · line 9"}]}]}]}
    assert "5 V in 1 document (2 places)" in plain.params(out)


def test_the_part_summary_lists_its_numbers_and_every_text_line_is_found(built):
    ix = ask._index(built)
    part = brief._part(built, ix, "control")
    assert {n["name"] for n in part["named_numbers"]} >= {"PID_OUTPUT_LIMIT", "PID_SETTLE_TIME_MS"}
    hit = next(h for h in query.text_hits(built, "settle time") if h["key"] == "Test_plan")
    assert hit["lines"] and all("settle" in ln["says"].lower() for ln in hit["lines"])
    from contextmax import agentskill

    text = agentskill.compose(built)
    assert "**Named in the question**" in text and "**The part the question names**" in text
