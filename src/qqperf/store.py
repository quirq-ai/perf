"""Where perf records live, behind a `backend` (plan: cloud agnostic).

v0 has one backend, `files`: a directory of JSON Lines, one file per repo and metric,
`<root>/<repo>/<metric>.jsonl`, one record per line in the order they were written. Records are
write-once: a second record for the same repo, commit and metric is refused.

On GitHub the directory is the `perf-data` branch of this repo, which the build-size workflow
checks out, appends to and pushes. TODO(expert): move to test-pipelines' results store (V0-TST-02)
as part of V0-PRF-01, importing these files, and keep this backend for local runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "qq-perf-record/1"
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class StoreError(Exception):
    """A record was refused. The message says why and what to do."""


def _check_name(kind: str, value: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        raise StoreError(f"{kind} {value!r} must be lower case letters, digits, '.', '_' or '-'")
    return value


class FileStore:
    backend = "files"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, repo: str, metric: str) -> Path:
        return self.root / _check_name("repo", repo) / f"{_check_name('metric', metric)}.jsonl"

    def records(self, repo: str, metric: str) -> list[dict]:
        path = self._path(repo, metric)
        if not path.is_file():
            return []
        out = []
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise StoreError(f"{path}:{n} is not JSON ({e}); fix or remove that line") from None
        return out

    def commits(self, repo: str, metric: str) -> set[str]:
        return {r["commit"] for r in self.records(repo, metric)}

    def streams(self) -> list[tuple[str, str]]:
        """Every (repo, metric) this store holds records for, sorted."""
        if not self.root.is_dir():
            return []
        return sorted((p.parent.name, p.stem) for p in self.root.glob("*/*.jsonl"))

    def put(self, record: dict) -> Path:
        for key in ("schema", "repo", "commit", "metric", "status"):
            if key not in record:
                raise StoreError(f"record has no {key!r}")
        if record["schema"] != SCHEMA:
            raise StoreError(f"record schema {record['schema']!r}; this store writes {SCHEMA!r}")
        if record["commit"] in self.commits(record["repo"], record["metric"]):
            raise StoreError(f"{record['repo']} {record['metric']} already has a record for commit"
                             f" {record['commit']}; records are write-once")
        path = self._path(record["repo"], record["metric"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return path


BACKENDS = {"files": FileStore}


def open_store(backend: str, root: Path):
    try:
        return BACKENDS[backend](root)
    except KeyError:
        raise StoreError(f"unknown store backend {backend!r}; known: {', '.join(BACKENDS)}") from None
