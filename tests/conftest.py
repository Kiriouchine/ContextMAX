"""One built demo project shared by the tests. Office is switched off so no test starts Word or Excel."""
from __future__ import annotations

import os

import pytest

os.environ["CONTEXTMAX_NO_OFFICE"] = "1"


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    os.environ["CONTEXTMAX_HOME"] = str(home)
    from contextmax import demo, pipeline

    proj = demo.create_project(tmp_path_factory.mktemp("src") / "demo")
    pipeline.build(proj, depth="documents", ocr=False)
    return proj
