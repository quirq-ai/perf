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


def test_store_downloads_each_leg_by_name():
    perf = (ROOT / ".github" / "workflows" / "perf.yml").read_text()
    measure, store = perf.split("\n  store:\n")
    legs = set(re.findall(r"- metric: (\S+)\n\s+repo: (\S+)", measure))
    names = {f"ledger--{repo}--{metric}" for metric, repo in legs}
    assert len(legs) == 3
    # Each leg's exact name, into its own directory: a pattern download that matches one artifact
    # extracts it with no directory naming its leg, and a wildcard would let one leg's artifact
    # land in another's directory.
    downloads = re.findall(r"pattern: (\S+)\n\s+path: \.qq/new/(\S+)", store)
    assert {name for name, _ in downloads} == names
    assert all(name == path for name, path in downloads)
    assert store.count("pattern:") == len(names) and "name: ledger--" not in store
    # A real download failure must fail the job; an absent ledger already matches nothing.
    assert "continue-on-error" not in store.split("- name: append to the history branch")[0]
    allowlist = re.search(r'case "\$repo/\$metric" in\n\s+(\S+)\)', store).group(1)
    assert set(allowlist.split("|")) == {f"{repo}/{metric}" for metric, repo in legs}
