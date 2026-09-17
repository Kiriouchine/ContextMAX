# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
from __future__ import annotations

from contextmax.gitignore import IgnoreStack, compile_rule, compile_rules


def ignored(lines: list[str], key: str, is_dir: bool = False, base: str = "") -> bool:
    stack = IgnoreStack()
    stack.push(base, compile_rules(lines, base))
    return stack.is_ignored(key, is_dir) is not None


def test_comments_and_blank_lines_are_skipped():
    assert compile_rule("# comment") is None
    assert compile_rule("   ") is None
    assert compile_rule("\\#literal").regex.match("#literal")


def test_unanchored_pattern_matches_at_any_depth():
    assert ignored(["*.log"], "a/b/c.log")
    assert ignored(["*.log"], "c.log")
    assert not ignored(["*.log"], "c.log.txt")


def test_anchored_pattern_matches_only_at_base():
    assert ignored(["/top.txt"], "top.txt")
    assert not ignored(["/top.txt"], "sub/top.txt")
    assert ignored(["docs/*.md"], "docs/a.md")
    assert not ignored(["docs/*.md"], "other/docs/a.md")


def test_directory_only_pattern():
    assert ignored(["build/"], "build", is_dir=True)
    assert ignored(["build/"], "x/build", is_dir=True)
    assert not ignored(["build/"], "build", is_dir=False)


def test_negation_last_match_wins():
    lines = ["*.log", "!keep.log"]
    assert ignored(lines, "logs/run.log")
    assert not ignored(lines, "logs/keep.log")


def test_double_star_forms():
    assert ignored(["**/foo"], "foo")
    assert ignored(["**/foo"], "a/b/foo")
    assert ignored(["a/**/b"], "a/b")
    assert ignored(["a/**/b"], "a/x/y/b")
    assert ignored(["a/**"], "a/x/y")
    assert not ignored(["a/**"], "b/x")


def test_question_mark_and_class():
    assert ignored(["file?.txt"], "file1.txt")
    assert not ignored(["file?.txt"], "file12.txt")
    assert ignored(["file[0-9].txt"], "file7.txt")
    assert not ignored(["file[!0-9].txt"], "file7.txt")


def test_nested_ignore_file_is_relative_to_its_folder():
    assert ignored(["*.tmp"], "sub/x.tmp", base="sub")
    assert not ignored(["*.tmp"], "x.tmp", base="sub")
    assert ignored(["/only.txt"], "sub/only.txt", base="sub")


def test_trailing_spaces_ignored_unless_escaped():
    assert compile_rule("name   ").regex.match("name")
    assert compile_rule("name\\ ").regex.match("name ")
