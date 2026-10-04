import os
import re
import subprocess
import sys
from pathlib import Path

from qqperf import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_tools_qqperf_runs_from_source(tmp_path):
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
    env.pop("PYTHONPATH", None)
    out = subprocess.run([str(ROOT / "tools" / "qqperf"), "--version"], cwd=tmp_path, env=env,
                         check=True, capture_output=True, text=True).stdout
    assert __version__ in out


def test_publish_uses_the_qqresults_pin():
    pin = re.search(r"test-pipelines@([0-9a-f]{40})", (ROOT / "pyproject.toml").read_text()).group(1)
    publish = (ROOT / ".github" / "workflows" / "perf-publish.yml").read_text()
    assert f"ref: {pin}" in publish


def test_trusted_jobs_install_nothing():
    publish = (ROOT / ".github" / "workflows" / "perf-publish.yml").read_text()
    store = (ROOT / ".github" / "workflows" / "perf.yml").read_text().split("\n  store:\n")[1]
    for text in (publish, store):
        assert "pip install" not in text and "setup-python" not in text
