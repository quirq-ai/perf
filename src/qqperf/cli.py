"""qqperf: record performance numbers per commit, raw and with units.

    qqperf pending --store DIR --repo NAME --checkout PATH [--metric M] [--ref REF] [--limit N]
    qqperf backlog --store DIR --repo NAME --checkout PATH [--metric M] [--ref REF]
    qqperf record build-size --store DIR --repo NAME --checkout PATH --dist DIR --runner LABEL
                  [--commit SHA] [--target T] [--toolchain NAME=VERSION]... [--run-url URL]
                  [--error TEXT]
    qqperf record bench --store DIR --repo NAME --checkout PATH --benchmark NAME --target T
                  --bench-dir DIR --runner LABEL [same options as build-size]
    qqperf manifest --base PATH --target T --params JSON --out PATH
    qqperf history --store DIR --repo NAME [--metric M] [--value NAME] [--json]
    qqperf merge --store DIR --from DIR --repo NAME... [--metric M]... [--commit SHA]... [--run-url URL]
                 [--run-url-prefix URL] [--max-records N]
    qqperf bundle --store DIR --repo NAME --metric M --run-url URL --results-out DIR

`pending` lists the commits of a branch (first parent, newest first) with no ok record that have
not yet failed MAX_ATTEMPTS times, down to the oldest commit the store has any record of (older
commits landed before perf measured the stream). `backlog` prints, as JSON, how many of those there are, the oldest
of them, and whether a shallow checkout hides owed commits. `record build-size` measures a finished Next.js build and stores
one record; with `--error` it stores a failed record instead, so the history shows the gap.
`record bench` stores what recipes' `bench` capability measured (a failed benchmark is a failed
record). `bundle` writes the record one run added as a test-pipelines results bundle: a Run with
one Result whose metrics hold the values (V0-PRF-01). It runs only on records a trusted job has
merged, never in a job that ran product code. `manifest` adds benchmark params to a
target through qqsync's editor, until the product repos' own manifests carry them.
`merge` adds the records of one store to another, so a job that builds untrusted code never holds
write access to the history: it records into a scratch store that a separate job merges, and the
merge validates every record, only for the repos, metrics, commits and run it is told to take,
before writing any.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qqperf import __version__, bench, record, size
from qqperf.store import StoreError, check_commit, open_store

BUILD_SIZE = "build-size"
SHOWN = ("gzip_bytes", "_p50")  # the values `record` prints; every value is stored


def _store(args):
    return open_store(args.backend, Path(args.store))


def _landed(args, store) -> list[str]:
    """The commits perf owes a record: first parent of the ref, down to the oldest one recorded."""
    seen = {r["commit"] for r in store.records(args.repo, args.metric)}
    return record.since_first(record.first_parent(Path(args.checkout), args.ref), seen)


def cmd_pending(args) -> int:
    store = _store(args)
    for c in record.pending(_landed(args, store), store.done(args.repo, args.metric), args.limit):
        print(c)
    return 0


def cmd_backlog(args) -> int:
    store = _store(args)
    print(json.dumps(record.backlog(_landed(args, store), store.done(args.repo, args.metric),
                                    record.is_shallow(Path(args.checkout)))))
    return 0


def _toolchains(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values:
        name, sep, version = v.partition("=")
        if not sep or not name or not version:
            raise record.RecordError(f"--toolchain wants NAME=VERSION, got {v!r}")
        out[name] = version
    return out


def _record(args, metric: str, values, error, detail: dict | None = None) -> int:
    """Store one record. `detail` keeps what the summary values lose (a benchmark's raw samples)."""
    checkout = Path(args.checkout)
    commit = check_commit(args.commit or record.first_parent(checkout, "HEAD")[0])
    rec = record.make(
        repo=args.repo, commit=commit, metric=metric, target=args.target, values=values,
        error=error, runner_info=record.runner(args.runner, args.runner_backend),
        toolchains=_toolchains(args.toolchain), committed_at=record.commit_time(checkout, commit),
        run={"url": args.run_url} if args.run_url else {}, detail=detail)
    path = _store(args).put(rec)
    if error is None:
        shown = ", ".join(f"{v['name']}={v['value']}{'' if v['unit'] in ('bytes', 'count') else v['unit']}"
                          for v in values if v["name"].endswith(SHOWN))
        print(f"recorded {args.repo} {commit[:12]} {metric}: {shown} -> {path}")
    else:
        print(f"recorded {args.repo} {commit[:12]} {metric}: failed -> {path}")
    return 0


def cmd_record_build_size(args) -> int:
    values = None if args.error is not None else size.next_build(Path(args.dist))
    return _record(args, BUILD_SIZE, values, args.error)


def cmd_record_bench(args) -> int:
    values, error, detail = None, args.error, None
    if error is None:
        try:
            values, data = bench.read(Path(args.bench_dir), args.target)
            detail = {k: data[k] for k in ("measure", "paths", "unit", "samples") if k in data}
        except bench.BenchError as e:
            error = str(e)  # a failed benchmark is recorded as failed, like a failed build
    return _record(args, args.benchmark, values, error, detail)


def merge_params(base: dict, extra: dict) -> dict:
    """extra over base, one level deep: an overlay `env` adds to the target's own env."""
    out = dict(base)
    for k, v in extra.items():
        out[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def cmd_manifest(args) -> int:
    """Write a copy of a manifest with extra params on one target, through qqsync's editor."""
    from qqsync.errors import ManifestError
    from qqsync.manifest import Manifest
    try:
        extra = json.loads(args.params)
    except json.JSONDecodeError as e:
        raise record.RecordError(f"--params is not JSON: {e}") from None
    if not isinstance(extra, dict):
        raise record.RecordError("--params must be a JSON object")
    try:
        m = Manifest.read(args.base)
        target = next((t for t in m.data.get("targets", []) if t.get("name") == args.target), None)
        if target is None:
            raise record.RecordError(f"{args.base} has no target {args.target!r}")
        m.set_target(args.target, "params", merge_params(target.get("params", {}), extra))
        m.write(args.out)
    except ManifestError as e:
        raise record.RecordError(str(e)) from None
    print(f"wrote {args.out}")
    return 0


def cmd_history(args) -> int:
    rows = _store(args).records(args.repo, args.metric)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        vals = {v["name"]: v for v in r.get("values", [])}
        if r["status"] != "ok":
            shown = "failed"
        elif args.value in vals:
            shown = f"{vals[args.value]['value']} {vals[args.value]['unit']}"
        else:
            shown = f"no {args.value}"
        print(f"{r.get('committed_at') or '-'}  {r['commit'][:12]}  {shown}  ({r['runner'].get('label', '?')})")
    return 0


def cmd_merge(args) -> int:
    dest, src = open_store(args.backend, Path(args.store)), open_store(args.backend, Path(args.source))
    records = []
    for repo, metric in src.streams():
        if repo not in args.repo:
            raise StoreError(f"{args.source} has records for repo {repo!r}; this merge takes only"
                             f" {', '.join(args.repo)}")
        if args.metric and metric not in args.metric:
            raise StoreError(f"{args.source} has records for metric {metric!r}; this merge takes only"
                             f" {', '.join(args.metric)}")
        stored = dest.records(repo, metric)
        for r in src.records(repo, metric):
            if r["repo"] != repo or r["metric"] != metric:
                raise StoreError(f"{args.source}/{repo}/{metric}.jsonl holds a record for"
                                 f" {r['repo']!r} {r['metric']!r}; refusing the merge")
            if r in stored:
                continue  # already merged, by an earlier attempt of the same run
            if args.commit and r["commit"] not in args.commit:
                raise StoreError(f"{repo} {metric} record for commit {r['commit']} was not pending in this"
                                 " run; refusing the merge")
            url = r.get("run", {}).get("url", "")
            if (args.run_url and url != args.run_url) or (
                    args.run_url_prefix and not url.startswith(args.run_url_prefix)):
                raise StoreError(f"{repo} {metric} record for {r['commit'][:12]} names run"
                                 f" {url!r}, not this run; refusing the merge")
            records.append(r)
    if args.max_records is not None and len(records) > args.max_records:
        raise StoreError(f"{args.source} holds {len(records)} records; this merge takes at most"
                         f" {args.max_records}")
    n = dest.put_many(records)
    print(f"merged {n} record(s) into {args.store}")
    return 0


def cmd_bundle(args) -> int:
    """Write the record a run added for one repo and metric as a test-pipelines results bundle."""
    from qqresults.errors import Error as ResultsError  # only this command needs qqresults
    from qqperf import results
    found = [r for r in _store(args).records(args.repo, args.metric)
             if r.get("run", {}).get("url") == args.run_url]
    if not found:
        print(f"no {args.repo} {args.metric} record from {args.run_url}")
        return 0
    if len(found) > 1:
        raise StoreError(f"{len(found)} {args.repo} {args.metric} records from {args.run_url}; expected one")
    try:
        out = results.write_bundle(found[0], Path(args.results_out), backend=args.results_backend, org=args.org)
    except ResultsError as e:
        raise StoreError(f"results bundle not written: {e}") from None
    print(f"results bundle: {out}")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"bundle={out}\nname={out.name}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qqperf", description=__doc__.split("\n")[0])
    ap.add_argument("--version", action="version", version=f"qqperf {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_store(p):
        p.add_argument("--store", required=True, help="the store's root directory")
        p.add_argument("--backend", default="files", help="store backend (v0: files)")
        p.add_argument("--repo", required=True, help="the repo's name, as in infra-config repos.toml")
        return p

    p = with_store(sub.add_parser("pending", help="commits with no record yet"))
    p.add_argument("--checkout", required=True)
    p.add_argument("--metric", default=BUILD_SIZE)
    p.add_argument("--ref", default="HEAD")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_pending)

    p = with_store(sub.add_parser("backlog", help="how many landed commits have no record yet"))
    p.add_argument("--checkout", required=True)
    p.add_argument("--metric", default=BUILD_SIZE)
    p.add_argument("--ref", default="HEAD")
    p.set_defaults(func=cmd_backlog)

    rec = sub.add_parser("record", help="measure and store one record")
    rsub = rec.add_subparsers(dest="metric", required=True)

    def with_record(p, target):
        with_store(p)
        p.add_argument("--checkout", required=True, help="the repo checkout the build ran in")
        p.add_argument("--commit", help="default: HEAD of --checkout")
        p.add_argument("--target", default=target, help="the manifest target that was measured")
        p.add_argument("--runner", required=True, help="the runner type, such as ubuntu-24.04")
        p.add_argument("--runner-backend", default="github", help="where it ran (github; launchpad later)")
        p.add_argument("--toolchain", action="append", default=[], metavar="NAME=VERSION")
        p.add_argument("--run-url")
        p.add_argument("--error", help="record a failure with this message instead of values")
        return p

    p = with_record(rsub.add_parser(BUILD_SIZE, help="size of a finished Next.js build"), "app")
    p.add_argument("--dist", help="the build output directory (.next)")
    p.set_defaults(func=cmd_record_build_size)

    p = with_record(rsub.add_parser("bench", help="a benchmark recipes' bench capability ran"), "")
    p.add_argument("--benchmark", required=True, help="its name in infra-config perf.toml")
    p.add_argument("--bench-dir", help="the bench/ directory under qqrecipes' --out")
    p.set_defaults(func=cmd_record_bench)

    p = sub.add_parser("manifest", help="copy a manifest with extra params on one target")
    p.add_argument("--base", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--params", required=True, help="a JSON object merged into the target's params")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_manifest)

    p = with_store(sub.add_parser("history", help="print the records of a repo"))
    p.add_argument("--metric", default=BUILD_SIZE)
    p.add_argument("--value", default="static_js_gzip_bytes", help="the value to show per commit")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("merge", help="add every record of one store to another")
    p.add_argument("--store", required=True, help="the store to add to")
    p.add_argument("--from", dest="source", required=True, help="the store to read")
    p.add_argument("--repo", action="append", required=True, help="a repo whose records may be merged")
    p.add_argument("--metric", action="append", help="a metric whose records may be merged (default: any)")
    p.add_argument("--commit", action="append", help="a commit whose records may be merged (default: any)")
    p.add_argument("--run-url", help="merge only records that name this run")
    p.add_argument("--run-url-prefix", help="merge only records whose run starts with this")
    p.add_argument("--max-records", type=int, help="refuse a source with more records than this")
    p.add_argument("--backend", default="files")
    p.set_defaults(func=cmd_merge)

    p = with_store(sub.add_parser("bundle", help="write a run's record as a results bundle"))
    p.add_argument("--metric", required=True)
    p.add_argument("--run-url", required=True, help="the run that added the record")
    p.add_argument("--results-out", required=True, help="the directory to write the bundle in")
    p.add_argument("--results-backend", default="github", choices=("github", "local"),
                   help="who describes the bundle's run (github: this Actions job)")
    p.add_argument("--org", default="quirq-ai", help="owner of --repo, for the bundle's run")
    p.add_argument("--github-output", help="append bundle=PATH and name=NAME here")
    p.set_defaults(func=cmd_bundle)

    args = ap.parse_args(argv)
    if args.cmd == "record" and args.metric == BUILD_SIZE and args.error is None and not args.dist:
        ap.error("record build-size needs --dist, or --error for a failed build")
    if args.cmd == "record" and args.metric == "bench":
        if not args.target:
            ap.error("record bench needs --target")
        if args.error is None and not args.bench_dir:
            ap.error("record bench needs --bench-dir, or --error for a failed run")
    try:
        return args.func(args)
    except (size.SizeError, StoreError, record.RecordError, bench.BenchError) as e:
        print(f"qqperf: {e}", file=sys.stderr)
        return 1
