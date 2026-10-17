"""The build's log: its steps, how far a long loop is, and the summary at the end. The log only: the index
is the same with or without it."""
from __future__ import annotations

import re

from contextmax import catalogue, pipeline, util

# what the ContextMAX window reads from the log (panel.html, STEP_RX)
STEP_RX = re.compile(r"^=== Step (\d+) of (\d+) · (.+?)\s+\(([\d:]+)\)$")


def test_a_long_loop_says_how_far_it_is(capsys, monkeypatch):
    p = util.Progress("docs", "reading documents", 4, every=0)
    p.tick("DOC-1")
    assert capsys.readouterr().out == "[docs]   reading documents: 1 of 4 (25%) · DOC-1\n"
    p.t0 -= 60                                    # a minute spent on one document: three to go
    p.tick("DOC-2")
    assert capsys.readouterr().out.endswith("2 of 4 (50%) · DOC-2 · about 1 min left\n")
    quiet = util.Progress("docs", "reading documents", 4)
    quiet.tick("DOC-1")
    assert capsys.readouterr().out == ""          # at most one line every PROGRESS_EVERY seconds
    with util.progress("code", "reading C", 2) as inner:
        inner.every = 0
        util.tick("a.c")                          # code that does not know the loop still counts in it
    util.tick("outside")                          # and outside any loop, nothing happens
    assert capsys.readouterr().out == "[code]   reading C: 1 of 2 (50%) · a.c\n"
    assert util.count(1, "file") == "1 file" and util.count(2400, "entity", "entities") == "2,400 entities"
    assert util.clock(65) == "1:05" and util.clock(3725) == "1:02:05"
    long = util.Progress("docs", "reading documents", 0).line("x" * 100)
    assert "…" + "x" * 69 in long and "x" * 71 not in long


def test_the_build_names_its_steps_and_ends_with_a_summary(built, capsys):
    pipeline.build(built, depth="quick", ocr=False)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "=== Steps: Code map · Document map · Validation gate · Pages"
    steps = [STEP_RX.match(line) for line in out if line.startswith("=== Step ")]
    assert [(m.group(1), m.group(2), m.group(3)) for m in steps] == [
        ("1", "4", "Code map"), ("2", "4", "Document map"), ("3", "4", "Validation gate"), ("4", "4", "Pages")]
    assert sum(1 for line in out if re.fullmatch(r"    done in \d+\.\d s", line)) == 4
    summary = out[out.index(next(line for line in out if line.startswith("=== Summary · "))):]
    labels = [line[4:14].strip() for line in summary[1:] if line.startswith("    ")]
    assert labels[:2] == ["files", "documents"] and "code" in labels
    assert labels[-5:] == ["links", "values", "in code", "gate", "pages"]
    values = next(line for line in summary if line.startswith("    values"))
    assert "each with its line" in values and "with a name" in values
    assert "named number" in next(line for line in summary if line.startswith("    in code"))
    assert any(line.startswith("    pages      ") and "confidence" in line for line in summary)


def test_the_steps_follow_the_depth(built):
    assert pipeline._plan(built, "documents") == ["catalogue", "read", "code", "docmap", "gate", "pages"]
    assert pipeline._plan(built, "quick") == ["code", "docmap", "gate", "pages"]
    assert pipeline._plan(built, "catalogue") == ["catalogue", "gate", "pages"]


def test_the_catalogue_says_what_changed_since_the_last_one(tmp_path):
    before = tmp_path / "all-files.csv"
    row = lambda folder, rel, kb, day: [folder, "", "", "", "", "", rel, ".txt", kb, day, "False", rel]  # noqa: E731
    util.save_csv(before, catalogue.HEADER, [row("a", "x.txt", "1.0", "2026-10-01"), row("a", "y.txt", "1.0", "2026-10-01"),
                                              row("a", "gone.txt", "1.0", "2026-10-01")])
    now = [row("a", "x.txt", "1.0", "2026-10-01"), row("a", "y.txt", "2.0", "2026-10-01"), row("a", "new.txt", "1.0", "2026-10-02")]
    assert catalogue._changes(before, now) == "1 new, 1 changed, 1 removed"
    assert catalogue._changes(before, [row("a", n, "1.0", "2026-10-01") for n in ("x.txt", "y.txt", "gone.txt")]) == \
        "no file added, changed or removed"
    assert catalogue._changes(tmp_path / "none.csv", now) == ""


def test_every_build_leaves_its_log_in_the_working_folder(built, capsys, monkeypatch):
    from contextmax import cli

    logs = built.path("logs")
    monkeypatch.setenv("CONTEXTMAX_LIVE", "1")          # as in the window: the drawing's events stay out of the log
    assert cli.run(["build", built.slug]) == 0
    printed = capsys.readouterr().out
    [log] = sorted(logs.glob("build-*.txt"))[-1:]
    text = log.read_text(encoding="utf-8")
    assert f"[log] this build's log is saved in {log}" in printed
    assert text.startswith("ContextMAX ") and "=== Steps: Code map" in text and "=== Summary" in text
    assert util.LIVE_MARK not in text and util.LIVE_MARK in printed
    assert text.rstrip("\n").splitlines()[-1].endswith("with exit code 0")
    for n in range(40):                                  # only the newest are kept
        (logs / f"build-2000-01-01_0000{n:02d}.txt").write_text("old", encoding="utf-8")
    monkeypatch.delenv("CONTEXTMAX_LIVE")
    assert cli.run(["build", built.slug]) == 0
    kept = sorted(logs.glob("build-*.txt"))
    assert len(kept) == cli.KEEP_BUILD_LOGS and log in kept and kept[-1].read_text(encoding="utf-8").startswith("ContextMAX ")
