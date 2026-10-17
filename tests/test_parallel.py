"""Work spread over several processes gives what one piece at a time gives; a stopped build keeps what it
finished."""
from __future__ import annotations

from pathlib import Path

import pytest

from contextmax import parallel, util


def test_work_spread_over_processes_gives_what_one_at_a_time_gives():
    items = ["6*7", "int('x')", "sum(range(10))"]
    for n in (1, 2):
        with parallel.Spread(eval, items, n) as spread:
            got = dict(spread.results())
        assert spread.n == n and got[0] == 42 and got[2] == 45 and isinstance(got[1], ValueError)


def test_a_worker_that_dies_is_named_and_the_others_still_finish():
    items = ["1+1", "__import__('os')._exit(3)", "2+2"]
    with parallel.Spread(eval, items, 2) as spread:
        got = dict(spread.results())
    assert got[0] == 2 and got[2] == 4 and isinstance(got[1], parallel.Crashed)


def test_the_number_of_workers_follows_the_setting(monkeypatch):
    monkeypatch.setenv("CONTEXTMAX_WORKERS", "3")
    assert parallel.workers() == 3
    monkeypatch.setenv("CONTEXTMAX_WORKERS", "")
    assert 1 <= parallel.workers() <= parallel.MAX_WORKERS
    assert parallel.Spread(eval, ["1"]).n == 1               # never more workers than pieces of work


def _demo(tmp_path, name: str, folder: str | None = None):
    from contextmax import demo, project

    root = demo.write(tmp_path / (folder or name) / "src")
    folders = [{"path": str(root / f), "holds": "documents" if f == "docs" else "code"}
               for f in ("docs", "firmware", "logic", "tools", "models")]
    proj = project.create(name, folders, str(tmp_path / (folder or name) / "ws"))
    proj.data["vocabulary"] = dict(demo.VOCABULARY)
    proj.save()
    return proj


def test_the_index_is_the_same_with_one_worker_or_several(built, tmp_path, monkeypatch):
    from contextmax import pipeline

    hashes = {}
    for n in ("1", "4"):          # the same project (its name is in the index) in two folders
        monkeypatch.setenv("CONTEXTMAX_WORKERS", n)
        proj = _demo(tmp_path, "Workers", f"workers-{n}")
        pipeline.build(proj, depth="documents", ocr=False)
        hashes[n] = util.load_json(proj.workspace / "buildinfo.json")["outputs_hash"]
    assert hashes["1"] == hashes["4"]


def test_a_stopped_build_keeps_what_it_finished(built, tmp_path, monkeypatch, capsys):
    from contextmax import cli

    proj = _demo(tmp_path, "Stopped")
    stop = tmp_path / "stop-now"
    stop.write_text("", encoding="utf-8")
    monkeypatch.setenv("CONTEXTMAX_STOP_FILE", str(stop))
    monkeypatch.setattr(util, "_STOP_LOOKED", [0.0])
    assert cli.run(["build", proj.slug, "--documents"]) == cli.STOPPED
    assert "[stop] stopped from the ContextMAX window" in capsys.readouterr().out
    [log] = proj.path("logs").glob("build-*.txt")
    assert log.read_text(encoding="utf-8").rstrip().endswith("stopped: stopped from the ContextMAX window")
    assert not (proj.workspace / "buildinfo.json").exists()           # no page was written from half a build
    monkeypatch.delenv("CONTEXTMAX_STOP_FILE")
    assert cli.run(["build", proj.slug, "--documents"]) == 0           # the next build goes on and finishes


def test_the_reading_step_keeps_what_it_read_when_stopped(built, tmp_path, monkeypatch):
    from contextmax import catalogue
    from contextmax.docs import textcache

    proj = _demo(tmp_path, "Halfway")
    catalogue.build(proj)
    monkeypatch.setenv("CONTEXTMAX_WORKERS", "1")
    calls = []
    real = textcache._read_one

    def read_then_stop(job):
        if len(calls) == 3:
            raise util.Stopped("asked")
        calls.append(job["p"]["key"])
        return real(job)

    monkeypatch.setattr(textcache, "_read_one", read_then_stop)
    with pytest.raises(util.Stopped):
        textcache.build(proj, ocr=False)
    kept = {r["key"] for r in util.load_jsonl(proj.documents_dir / "text-index.jsonl")}
    assert set(calls) <= kept                     # the three read are kept (and any Word or Excel read before)
    monkeypatch.setattr(textcache, "_read_one", real)
    report = textcache.build(proj, ocr=False)
    assert len(kept) < report["cached_count"] and report["read_now"] == report["cached_count"] - len(kept)


def test_the_window_says_what_the_last_build_missed_and_what_to_press(built, tmp_path):
    from contextmax import cli, panel

    proj = _demo(tmp_path, "Fresh")
    assert cli.run(["build", proj.slug, "--documents"]) == 0
    f = panel._freshness(proj)
    assert f["advice"] is None and f["last"]["state"] == "finished" and f["changes"]["new"] == 0
    docs = next(Path(x.path) for x in proj.folders if x.name == "docs")
    (docs / "Added later.txt").write_text("a note written after the build", encoding="utf-8")
    f = panel._freshness(proj)
    assert f["advice"] == "documents" and f["changes"]["new"] == 1 and f["changes"]["examples"]["new"] == ["Added later.txt"]
    assert cli.run(["build", proj.slug, "--documents"]) == 0
    assert panel._freshness(proj)["advice"] is None
    log = sorted(proj.path("logs").glob("build-*.txt"))[-1]
    log.write_text(log.read_text(encoding="utf-8").rsplit("ended ", 1)[0] + "ended now stopped: stopped from the "
                   "ContextMAX window\n", encoding="utf-8")
    f = panel._freshness(proj)
    assert f["advice"] == "documents" and f["last"]["state"] == "stopped" and "stopped" in f["why"]
    log.write_text(log.read_text(encoding="utf-8").rsplit("ended ", 1)[0], encoding="utf-8")     # no end: cut off
    assert panel._freshness(proj)["last"]["state"] == "cut off"
    (docs / "Broken.pdf").write_bytes(b"%PDF-1.4 not really")
    assert cli.run(["build", proj.slug, "--documents"]) == 0
    f = panel._freshness(proj)
    assert f["advice"] == "full" and [u["name"] for u in f["missed"]["unread"]] == ["Broken.pdf"]
