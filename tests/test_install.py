"""ContextMAX as a Windows program: launchers, shortcuts, the PATH entry and the Apps entry, all undone.

Every test works in temporary folders and under HKCU\\Software\\ContextMAX-tests, never in the real
Start menu, PATH or Apps & features. uninstall.cmd itself (which also deletes the program folders and
keeps the projects) is exercised end to end outside the test suite, with setup.cmd.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
TEST_ROOT = r"Software\ContextMAX-tests"
LINK_KEY = TEST_ROOT + r"\Classes\contextmax-open"


@pytest.fixture
def keys():
    import winreg

    env_key, apps_key = TEST_ROOT + r"\Environment", TEST_ROOT + r"\Uninstall\ContextMAX"
    yield env_key, apps_key
    link = TEST_ROOT + r"\Classes\contextmax-open"
    for key in (link + r"\shell\open\command", link + r"\shell\open", link + r"\shell", link + r"\DefaultIcon", link,
                TEST_ROOT + r"\Classes", apps_key, TEST_ROOT + r"\Uninstall", env_key, TEST_ROOT):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def _set_path(env_key, value):
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, env_key, 0, winreg.KEY_SET_VALUE) as key:
        if value is None:
            try:
                winreg.DeleteValue(key, "Path")
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)


def test_a_shortcut_reads_back_as_written(tmp_path):
    from contextmax import winshell

    lnk = tmp_path / "ContextMAX.lnk"
    winshell.make_shortcut(lnk, tmp_path / "go.cmd", arguments='--x "a b"', minimized=True)
    back = winshell.read_shortcut(lnk)
    assert back["target"].lower() == str(tmp_path / "go.cmd").lower()
    assert back["arguments"] == '--x "a b"' and back["minimized"] and back["workdir"] == str(tmp_path)


@pytest.mark.parametrize("before", [r"%USERPROFILE%\tools;C:\other", "C:\\a;;C:\\b;", "", None])
def test_the_path_comes_back_exactly_as_it_was(keys, before):
    import winreg

    from contextmax import install

    env_key, _ = keys
    _set_path(env_key, before)
    folder = Path(r"C:\Users\someone\ContextMAX\bin")
    assert install.add_to_path(folder, env_key) is True
    assert install.add_to_path(Path(str(folder).upper() + "\\"), env_key) is False      # same folder, other spelling
    value, kind = install._read_path(env_key)
    assert value.split(";")[-1] == str(folder) and kind == winreg.REG_EXPAND_SZ
    assert install.remove_from_path(folder, env_key) is True
    assert install._read_path(env_key)[0] == (before or None)       # an emptied value is deleted
    assert install.remove_from_path(folder, env_key) is False


def test_a_quoted_entry_is_the_same_folder(keys):
    from contextmax import install

    env_key, _ = keys
    _set_path(env_key, r'C:\x;"C:\Users\someone\ContextMAX\bin"')
    assert install.add_to_path(Path(r"C:\Users\someone\ContextMAX\bin"), env_key) is False


def test_install_then_uninstall_undoes_shortcuts_path_and_apps_entry(tmp_path, monkeypatch, keys):
    import winreg

    from contextmax import install, winshell

    env_key, apps_key = keys
    home = tmp_path / "Context MAX (1) & é"
    monkeypatch.setenv("CONTEXTMAX_HOME", str(home))
    places = {"start_menu": tmp_path / "start", "desktop": tmp_path / "desktop", "env_key": env_key,
              "uninstall_key": apps_key, "link_key": LINK_KEY}
    install.install(**places)

    launchers = [home / "ContextMAX.cmd", home / "bin" / "contextmax.cmd", home / "bin" / "cmx.cmd", home / "uninstall.cmd"]
    for launcher in launchers:       # cmd reads them in the console's code page: no folder names, ASCII only
        launcher.read_bytes().decode("ascii")
    assert '"%~dp0.venv\\Scripts\\python.exe" -m contextmax panel %*' in launchers[0].read_text()
    assert '"%~dp0..\\.venv\\Scripts\\python.exe" -m contextmax %*' in launchers[1].read_text()
    assert (home / install.MARKER).exists()
    assert sorted(p.name for p in (home / "bin").iterdir()) == ["cmx.cmd", "contextmax.cmd"]   # no python.exe on the PATH
    for lnk in (tmp_path / "start" / "ContextMAX.lnk", tmp_path / "desktop" / "ContextMAX.lnk"):
        info = winshell.read_shortcut(lnk)
        assert info["target"].lower() == str(home / "ContextMAX.cmd").lower() and info["minimized"]
    assert str(home / "bin") in install._read_path(env_key)[0]
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, apps_key) as key:
        assert winreg.QueryValueEx(key, "DisplayName")[0] == "ContextMAX"
        assert winreg.QueryValueEx(key, "UninstallString")[0] == f'"{home / "uninstall.cmd"}"'
        assert Path(winreg.QueryValueEx(key, "DisplayIcon")[0]).is_file()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LINK_KEY) as key:
        assert winreg.QueryValueEx(key, "URL Protocol")[0] == ""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LINK_KEY + r"\shell\open\command") as key:
        command = winreg.QueryValueEx(key, "")[0]
    assert command == f'"{home.resolve() / ".venv" / "Scripts" / "pythonw.exe"}" -m contextmax link "%1"'

    install.uninstall(**places)
    assert not (tmp_path / "start" / "ContextMAX.lnk").exists() and not (tmp_path / "desktop" / "ContextMAX.lnk").exists()
    assert install._read_path(env_key)[0] is None
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, apps_key)
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, LINK_KEY)


def test_uninstall_leaves_what_is_not_its_own(tmp_path, monkeypatch, keys):
    """A shortcut named ContextMAX that points elsewhere, and the Apps entry of another ContextMAX folder."""
    import winreg

    from contextmax import install, winshell

    env_key, apps_key = keys
    monkeypatch.setenv("CONTEXTMAX_HOME", str(tmp_path / "home"))
    other = tmp_path / "start" / "ContextMAX.lnk"
    winshell.make_shortcut(other, tmp_path / "my own ContextMAX checkout" / "ContextMAX.cmd")
    install.register(tmp_path / "another home", apps_key)
    install.register_links(tmp_path / "another home", LINK_KEY)
    done = install.uninstall(start_menu=tmp_path / "start", desktop=tmp_path / "desktop", env_key=env_key,
                             uninstall_key=apps_key, link_key=LINK_KEY)
    assert other.exists() and done == []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LINK_KEY + r"\shell\open\command") as key:
        assert str(tmp_path / "another home") in winreg.QueryValueEx(key, "")[0]
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, apps_key) as key:
        assert winreg.QueryValueEx(key, "InstallLocation")[0] == str(tmp_path / "another home")


def test_a_project_folder_named_bin_is_never_used_for_the_program(tmp_path, monkeypatch, keys):
    from contextmax import install

    env_key, apps_key = keys
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "project.json").write_text("{}")
    monkeypatch.setenv("CONTEXTMAX_HOME", str(home))
    done = install.install(shortcuts=False, apps_entry=False, env_key=env_key, uninstall_key=apps_key)
    assert sorted(p.name for p in (home / "bin").iterdir()) == ["project.json"]
    assert install._read_path(env_key)[0] is None and any("project's folder" in line for line in done)
