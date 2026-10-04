import datetime as dt

import pytest

from qqperf import record
from conftest import git


def test_make_ok_and_failed():
    now = dt.datetime(2026, 10, 4, tzinfo=dt.UTC)
    r = record.make(repo="innernet", commit="c", metric="build-size", target="app",
                    values=[{"name": "x", "value": 2, "unit": "bytes"}],
                    runner_info=record.runner("ubuntu-24.04", "github"),
                    toolchains={"pnpm": "11", "node": "24"}, now=now)
    assert r["status"] == "ok" and r["recorded_at"] == "2026-10-04T00:00:00+00:00"
    assert list(r["toolchains"]) == ["node", "pnpm"]
    assert r["runner"]["label"] == "ubuntu-24.04" and r["runner"]["backend"] == "github"
    f = record.make(repo="innernet", commit="c", metric="build-size", target="app", values=None,
                    error="build failed", runner_info={})
    assert f["status"] == "failed" and f["values"] == [] and f["error"] == "build failed"


@pytest.mark.parametrize("values, error", [(None, None), ([], "boom"),
                                           ([{"name": "x", "value": "1", "unit": "b"}], None)])
def test_make_rejects(values, error):
    with pytest.raises(record.RecordError):
        record.make(repo="r", commit="c", metric="m", target="t", values=values, error=error, runner_info={})


def test_first_parent_and_pending(product_repo):
    landed = record.first_parent(product_repo)
    assert len(landed) == 3  # the feature commit is not on main's first-parent line
    assert record.pending(landed, {landed[0]}, 10) == landed[1:]
    assert record.pending(landed, set(), 1) == landed[:1]
    assert dt.datetime.fromisoformat(record.commit_time(product_repo, landed[0])).tzinfo is not None


def test_git_error_is_actionable(tmp_path):
    with pytest.raises(record.RecordError, match="rev-list"):
        record.first_parent(tmp_path)
