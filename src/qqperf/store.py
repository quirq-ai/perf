"""Where perf records live, behind a `backend` (plan: cloud agnostic).

v0 has one backend, `files`: a directory of JSON Lines, one file per repo and metric,
`<root>/<repo>/<metric>.jsonl`, one record per line in the order they were written. Lines are
never edited. A commit gets at most one `ok` record; a failed measurement may be retried by
appending another record, up to MAX_ATTEMPTS failures, so a flaky build does not leave a
permanent gap and a broken one is not rebuilt forever.

On GitHub the directory is the `perf-data` branch of this repo, which the build-size workflow
checks out, appends to and pushes. TODO(expert): move to test-pipelines' results store (V0-TST-02)
as part of V0-PRF-01, importing these files, and keep this backend for local runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "qq-perf-record/1"
# Failed records per commit before it stops being retried. Hourly runs spend them in about three
# hours, so a longer outage gives up on its commits. TODO(expert): space retries out over time.
MAX_ATTEMPTS = 3
STATUSES = ("ok", "failed")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
_COMMIT = re.compile(r"[0-9a-f]{40}")


class StoreError(Exception):
    """A record was refused. The message says why and what to do."""


def _check_name(kind: str, value) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise StoreError(f"{kind} {value!r} must be lower case letters, digits, '.', '_' or '-'")
    return value


def check_commit(value) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise StoreError(f"commit {value!r} must be a full 40-character lower-case hex sha")
    return value


def validate(record) -> dict:
    """Refuse anything that is not a well-formed record, before any of it is written."""
    if not isinstance(record, dict):
        raise StoreError(f"a record is a JSON object, got {type(record).__name__}")
    for key in ("schema", "repo", "commit", "metric", "status", "values", "runner"):
        if key not in record:
            raise StoreError(f"record has no {key!r}")
    if record["schema"] != SCHEMA:
        raise StoreError(f"record schema {record['schema']!r}; this store writes {SCHEMA!r}")
    _check_name("repo", record["repo"])
    _check_name("metric", record["metric"])
    check_commit(record["commit"])
    if record["status"] not in STATUSES:
        raise StoreError(f"record status {record['status']!r}; one of {', '.join(STATUSES)}")
    values = record["values"]
    if not isinstance(values, list) or not all(
            isinstance(v, dict) and set(v) == {"name", "value", "unit"} and isinstance(v["name"], str)
            and isinstance(v["unit"], str) and isinstance(v["value"], (int, float))
            and not isinstance(v["value"], bool) for v in values):
        raise StoreError("record values must be a list of {name, value, unit} with numeric values")
    if (record["status"] == "ok") != bool(values):
        raise StoreError("an ok record has values and a failed record has none")
    if not isinstance(record["runner"], dict):
        raise StoreError("record runner must be an object")
    return record


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
                out.append(validate(json.loads(line)))
            except (json.JSONDecodeError, StoreError) as e:
                raise StoreError(f"{path}:{n} is not a valid record ({e}); fix or remove that line") from None
        return out

    def done(self, repo: str, metric: str) -> set[str]:
        """Commits that need no more measuring: one ok record, or MAX_ATTEMPTS failed ones."""
        failed: dict[str, int] = {}
        out = set()
        for r in self.records(repo, metric):
            if r["status"] == "ok":
                out.add(r["commit"])
            else:
                failed[r["commit"]] = failed.get(r["commit"], 0) + 1
        return out | {c for c, n in failed.items() if n >= MAX_ATTEMPTS}

    def streams(self) -> list[tuple[str, str]]:
        """Every (repo, metric) this store holds records for, sorted."""
        if not self.root.is_dir():
            return []
        return sorted((p.parent.name, p.stem) for p in self.root.glob("*/*.jsonl"))

    def put_many(self, records: list[dict]) -> int:
        """Validate every record first, then append them all; nothing is written if one is refused."""
        for r in records:
            validate(r)
        pending: dict[tuple[str, str], list[dict]] = {}
        for r in records:
            pending.setdefault((r["repo"], r["metric"]), []).append(r)
        for (repo, metric), new in pending.items():
            existing = self.records(repo, metric)
            for r in new:
                same = [e for e in existing if e["commit"] == r["commit"]]
                if any(e["status"] == "ok" for e in same):
                    raise StoreError(f"{repo} {metric} already has an ok record for commit {r['commit']};"
                                     " records are never replaced")
                if len(same) >= MAX_ATTEMPTS:
                    raise StoreError(f"{repo} {metric} commit {r['commit']} already failed {len(same)}"
                                     " times; it is not measured again")
                existing.append(r)
        for (repo, metric), new in pending.items():
            path = self._path(repo, metric)
            path.parent.mkdir(parents=True, exist_ok=True)
            # A hand-edited file may lack its last newline; never join two records on one line.
            lead = path.is_file() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
            with path.open("a", encoding="utf-8") as f:
                if lead:
                    f.write("\n")
                for r in new:
                    f.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
        return len(records)

    def put(self, record: dict) -> Path:
        self.put_many([record])
        return self._path(record["repo"], record["metric"])


BACKENDS = {"files": FileStore}


def open_store(backend: str, root: Path):
    try:
        return BACKENDS[backend](root)
    except KeyError:
        raise StoreError(f"unknown store backend {backend!r}; known: {', '.join(BACKENDS)}") from None
