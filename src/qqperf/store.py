"""Where perf records live, behind a `backend` (plan: cloud agnostic).

v0 has one backend, `files`: a directory of JSON Lines, one file per repo and metric,
`<root>/<repo>/<metric>.jsonl`, one record per line in the order they were written. Lines are
never edited. A commit gets at most one `ok` record; a failed measurement may be retried by
appending another record, up to MAX_ATTEMPTS failures, so a flaky build does not leave a
permanent gap and a broken one is not rebuilt forever.

On GitHub the directory is the `perf-data` branch of this repo, which the perf workflow checks
out, appends to and pushes. It is the ledger of what is measured; the system of record for the
numbers is test-pipelines' results store, which gets each record as a results bundle built from
this ledger by the perf-publish workflow (results.py).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

SCHEMA = "qq-perf-record/1"
# Failed records per commit before it stops being retried. Runs every 30 minutes spend them in
# about an hour and a half, so a longer outage gives up on its commits. TODO(expert): space retries out over time.
MAX_ATTEMPTS = 3
STATUSES = ("ok", "failed")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
_COMMIT = re.compile(r"[0-9a-f]{40}")
DETAIL_KEYS = {"measure": str, "unit": str, "paths": list, "samples": list}
MAX_SAMPLES = 10_000
MAX_VALUES = 64
MAX_TEXT = 2_000      # characters of any one string a record holds (an error message is cut there)
MAX_FIELDS = 32       # keys of runner, toolchains and run
MAX_NUMBER = 1e18     # far above any size, count or duration
MAX_LINE = 256 << 10  # bytes of one stored record; the largest legitimate one is about 240 KB
KEYS = {"schema", "repo", "commit", "committed_at", "metric", "target", "status", "values", "runner",
        "toolchains", "run", "recorded_at", "error", "detail"}


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


def _number(v) -> bool:
    """A measured number: finite and not negative (sizes, counts and durations all are)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v) and 0 <= v <= MAX_NUMBER
    except OverflowError:  # an int too large for a float
        return False


def _reject_constant(name: str):
    raise StoreError(f"{name} is not a number a record may hold")


def loads(line: str):
    """Strict JSON: NaN and Infinity are refused, as strict readers of perf-data would."""
    return json.loads(line, parse_constant=_reject_constant)


def dumps(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _check_detail(detail) -> None:
    if not isinstance(detail, dict) or set(detail) - set(DETAIL_KEYS):
        raise StoreError(f"record detail must be an object with only {', '.join(sorted(DETAIL_KEYS))}")
    for key, kind in DETAIL_KEYS.items():
        if key in detail and not isinstance(detail[key], kind):
            raise StoreError(f"record detail.{key} must be a {kind.__name__}")
    paths = detail.get("paths", [])
    if len(paths) > 100 or not all(isinstance(p, str) and len(p) <= 512 for p in paths):
        raise StoreError("record detail.paths must be at most 100 short strings")
    if any(len(detail.get(k, "")) > 32 for k in ("measure", "unit")):
        raise StoreError("record detail.measure and unit must be short strings")
    samples = detail.get("samples", [])
    if len(samples) > MAX_SAMPLES or not all(_number(v) for v in samples):
        raise StoreError(f"record detail.samples must be at most {MAX_SAMPLES} finite numbers >= 0")


def validate(record) -> dict:
    """Refuse anything that is not a well-formed record, before any of it is written."""
    if not isinstance(record, dict):
        raise StoreError(f"a record is a JSON object, got {type(record).__name__}")
    if unknown := set(record) - KEYS:
        raise StoreError(f"record has unknown keys: {', '.join(sorted(map(repr, unknown)))[:200]}")
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
            and isinstance(v["unit"], str) and _number(v["value"]) for v in values):
        raise StoreError("record values must be a list of {name, value, unit} with finite values >= 0")
    if (record["status"] == "ok") != bool(values):
        raise StoreError("an ok record has values and a failed record has none")
    if not isinstance(record["runner"], dict):
        raise StoreError("record runner must be an object")
    if not isinstance(record.get("run", {}), dict):
        raise StoreError("record run must be an object")
    if len(values) > MAX_VALUES or any(len(v["name"]) > 128 or len(v["unit"]) > 32 for v in values):
        raise StoreError(f"record holds more than {MAX_VALUES} values or an over-long name or unit")
    for key in ("runner", "toolchains", "run"):
        obj = record.get(key, {})
        if not isinstance(obj, dict) or len(obj) > MAX_FIELDS or not all(
                isinstance(k, str) and isinstance(v, str) and len(k) <= 128 and len(v) <= MAX_TEXT
                for k, v in obj.items()):
            raise StoreError(f"record {key} must be an object of at most {MAX_FIELDS} short strings")
    for key in ("target", "error", "committed_at", "recorded_at"):
        if record.get(key) is not None and (not isinstance(record[key], str) or len(record[key]) > MAX_TEXT):
            raise StoreError(f"record {key} must be a string of at most {MAX_TEXT} characters")
    if "detail" in record:
        _check_detail(record["detail"])
    if len(dumps(record).encode()) > MAX_LINE:
        raise StoreError(f"record is larger than {MAX_LINE} bytes")
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
                out.append(validate(loads(line)))
            # ValueError: JSON errors, and integers past Python's digit limit; RecursionError: deep nesting.
            except (ValueError, RecursionError, StoreError) as e:
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
                    f.write(dumps(r) + "\n")
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
