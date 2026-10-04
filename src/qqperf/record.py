"""Turn measured values into a perf record, and find the commits that still need one.

A record (schema `qq-perf-record/1`) holds the raw values with their units, the runner they were
measured on and the toolchains used, so v1 can compare like with like on noisy shared runners.
Core file: names no language or build tool; the measurement modules (`size`) may.
"""
from __future__ import annotations

import datetime as _dt
import platform as _platform
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from qqperf.store import SCHEMA


class RecordError(Exception):
    """The record cannot be made. The message says what to fix."""


def runner(label: str, backend: str) -> dict:
    """The machine a number was measured on. `label` is the runner type, such as ubuntu-24.04."""
    return {"backend": backend, "label": label, "os": sys.platform, "arch": _platform.machine().lower()}


def make(*, repo: str, commit: str, metric: str, target: str, values: list[dict] | None,
         runner_info: Mapping, toolchains: Mapping[str, str] | None = None,
         committed_at: str | None = None, run: Mapping | None = None, error: str | None = None,
         now: _dt.datetime | None = None) -> dict:
    """A record. With `error` it records a failed measurement, so history shows the gap."""
    if (values is None) == (error is None):
        raise RecordError("a record has either values or an error, not both or neither")
    for v in values or []:
        if set(v) != {"name", "value", "unit"} or not isinstance(v["value"], (int, float)):
            raise RecordError(f"value {v!r} needs exactly name, a numeric value and a unit")
    record = {
        "schema": SCHEMA,
        "repo": repo,
        "commit": commit,
        "committed_at": committed_at,
        "metric": metric,
        "target": target,
        "status": "ok" if error is None else "failed",
        "values": list(values or []),
        "runner": dict(runner_info),
        "toolchains": dict(sorted((toolchains or {}).items())),
        "run": dict(run or {}),
        "recorded_at": (now or _dt.datetime.now(_dt.UTC)).isoformat(timespec="seconds"),
    }
    if error is not None:
        record["error"] = error[:2000]
    return record


def _git(checkout: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True,
                              text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        raise RecordError(f"git {' '.join(args)} in {checkout} failed: {detail.strip()}") from None


def first_parent(checkout: Path, ref: str = "HEAD") -> list[str]:
    """The commits that landed on a branch, newest first: one per merge, as post-submit sees them."""
    return _git(checkout, "rev-list", "--first-parent", ref).split()


def commit_time(checkout: Path, commit: str) -> str:
    return _git(checkout, "show", "-s", "--format=%cI", "--end-of-options", commit).strip()


def pending(landed: Iterable[str], recorded: set[str], limit: int) -> list[str]:
    """Landed commits with no record yet, newest first, at most `limit`."""
    return [c for c in landed if c not in recorded][: max(limit, 0)]
