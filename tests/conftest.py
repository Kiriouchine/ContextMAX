"""One built demo project shared by the tests. Office is switched off so no test starts Word or Excel."""
from __future__ import annotations

import os
import sys

import pytest

os.environ["CONTEXTMAX_NO_OFFICE"] = "1"


@pytest.fixture(autouse=True)
def test_registry_places(monkeypatch):
    """No test ever writes the real PATH, Apps entry or contextmax-open: link: their default places point
    under HKCU\\Software\\ContextMAX-tests, whatever a test passes or forgets to pass."""
    if sys.platform != "win32":
        yield                       # no Windows registry to keep away from
        return
    from contextmax import install

    root = r"Software\ContextMAX-tests"
    monkeypatch.setattr(install, "ENV_KEY", root + r"\Environment")
    monkeypatch.setattr(install, "UNINSTALL_KEY", root + r"\Uninstall\ContextMAX")
    monkeypatch.setattr(install, "LINK_KEY", root + r"\Classes\contextmax-open")
    yield
    _delete_tree(root)


def _delete_tree(name: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, name) as key:
            subs = []
            while True:
                try:
                    subs.append(winreg.EnumKey(key, len(subs)))
                except OSError:
                    break
    except FileNotFoundError:
        return
    for sub in subs:
        _delete_tree(name + "\\" + sub)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    os.environ["CONTEXTMAX_HOME"] = str(home)
    from contextmax import demo, pipeline

    proj = demo.create_project(tmp_path_factory.mktemp("src") / "demo")
    pipeline.build(proj, depth="documents", ocr=False)
    return proj
