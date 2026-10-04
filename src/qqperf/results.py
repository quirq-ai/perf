"""Perf records as test-pipelines Results, the store every qq signal lands in (V0-PRF-01).

One perf record (one metric of one commit) becomes one run bundle, written with test-pipelines'
own `qqresults` (pinned by commit): a Run for the measured repo and commit, one Result whose
`metrics` hold every value as `{value, unit}`, and the Verdict computed from it. Bundles are built
only from records already merged into perf-data, by the perf-publish workflow, which runs no
product code; it keeps each as a `qq-results-*` artifact, and test-pipelines' scorecard workflow
collects it into the results store.

The Run's kind is `other`: product repos have no post-submit of their own yet (V0-GAR-01), so perf
polls their main branches. TODO(expert): run `bench` inside the generated post-submit once it
exists, so these become `postsubmit` runs.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from qqresults import backends, bundle, verdict
from qqresults.model import Result, Run, Status

KIND = "other"
TEST_PREFIX = "perf::"


def make_run(*, backend: str, repo: str, commit: str, name: str, branch: str = "main",
             env: Mapping[str, str] | None = None) -> Run:
    """The run of one measurement of `repo` (owner/name) at `commit`, described by `backend`."""
    b = backends.load(backend)
    if backend == "github":
        run = b.run_from_env(os.environ if env is None else env, kind=KIND, name=name)
        # The job runs in this repo; the run is about the measured repo's commit.
        return Run.from_dict({**run.to_dict(), "repo": repo, "commit": commit, "branch": branch,
                              "base_commit": "", "change": None})
    return b.run_from_args(repo, commit, kind="local", name=name)


def raw(record: Mapping) -> str:
    """What the metrics alone lose, as canonical JSON: the runner type, toolchains, target and
    any detail the measurement kept (a bench's raw samples, unit and paths)."""
    data = {"runner": record["runner"], "toolchains": record.get("toolchains", {}),
            "target": record.get("target", ""), "measured_in": record.get("run", {}).get("url", ""),
            **record.get("detail", {})}
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def to_result(run: Run, record: Mapping) -> Result:
    """One Result from one perf record: PASS with metrics, or CRASH with the error."""
    ok = record["status"] == "ok"
    return Result(
        run_id=run.id,
        test_id=TEST_PREFIX + record["metric"],
        status=Status.PASS.value if ok else Status.CRASH.value,
        expected=ok,
        message=record.get("error", ""),
        metrics={v["name"]: {"value": v["value"], "unit": v["unit"]} for v in record["values"]},
        raw=raw(record),
    )


def write_bundle(record: Mapping, out: Path, *, backend: str, org: str) -> Path:
    repo = f"{org}/{record['repo']}"
    run = make_run(backend=backend, repo=repo, commit=record["commit"],
                   name=f"{record['metric']}-{record['commit'][:12]}")
    results = [to_result(run, record)]
    return bundle.write(bundle.Bundle(run, results, verdict.compute(run, results)), Path(out))
