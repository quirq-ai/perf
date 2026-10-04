"""qqperf: record performance numbers per commit, raw and with units.

    qqperf pending --store DIR --repo NAME --checkout PATH [--metric M] [--ref REF] [--limit N]
    qqperf record build-size --store DIR --repo NAME --checkout PATH --dist DIR --runner LABEL
                  [--commit SHA] [--target T] [--toolchain NAME=VERSION]... [--run-url URL]
                  [--error TEXT]
    qqperf history --store DIR --repo NAME [--metric M] [--value NAME] [--json]
    qqperf merge --store DIR --from DIR

`pending` lists the commits of a branch (first parent, newest first) that have no record yet.
`record build-size` measures a finished Next.js build and stores one write-once record; with
`--error` it stores a failed record instead, so the history shows the gap. `merge` adds every
record of one store to another, so a job that builds untrusted code never holds write access to
the history: it records into a scratch store that a separate job merges.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qqperf import __version__, record, size
from qqperf.store import StoreError, open_store

BUILD_SIZE = "build-size"


def _store(args):
    return open_store(args.backend, Path(args.store))


def cmd_pending(args) -> int:
    recorded = _store(args).commits(args.repo, args.metric)
    for c in record.pending(record.first_parent(Path(args.checkout), args.ref), recorded, args.limit):
        print(c)
    return 0


def _toolchains(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values:
        name, sep, version = v.partition("=")
        if not sep or not name or not version:
            raise record.RecordError(f"--toolchain wants NAME=VERSION, got {v!r}")
        out[name] = version
    return out


def cmd_record_build_size(args) -> int:
    checkout = Path(args.checkout)
    commit = args.commit or record.first_parent(checkout, "HEAD")[0]
    values, error = None, args.error
    if error is None:
        values = size.next_build(Path(args.dist))
    rec = record.make(
        repo=args.repo, commit=commit, metric=BUILD_SIZE, target=args.target, values=values,
        error=error, runner_info=record.runner(args.runner, args.runner_backend),
        toolchains=_toolchains(args.toolchain), committed_at=record.commit_time(checkout, commit),
        run={"url": args.run_url} if args.run_url else {})
    path = _store(args).put(rec)
    if error is None:
        shown = ", ".join(f"{v['name']}={v['value']}" for v in values if v["name"].endswith("gzip_bytes"))
        print(f"recorded {args.repo} {commit[:12]} {BUILD_SIZE}: {shown} -> {path}")
    else:
        print(f"recorded {args.repo} {commit[:12]} {BUILD_SIZE}: failed -> {path}")
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
    n = 0
    for repo, metric in src.streams():
        for r in src.records(repo, metric):
            dest.put(r)
            n += 1
    print(f"merged {n} record(s) into {args.store}")
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

    rec = sub.add_parser("record", help="measure and store one record")
    rsub = rec.add_subparsers(dest="metric", required=True)
    p = with_store(rsub.add_parser(BUILD_SIZE, help="size of a finished Next.js build"))
    p.add_argument("--checkout", required=True, help="the repo checkout the build ran in")
    p.add_argument("--dist", help="the build output directory (.next)")
    p.add_argument("--commit", help="default: HEAD of --checkout")
    p.add_argument("--target", default="app", help="the manifest target that was built")
    p.add_argument("--runner", required=True, help="the runner type, such as ubuntu-24.04")
    p.add_argument("--runner-backend", default="github", help="where it ran (github; launchpad later)")
    p.add_argument("--toolchain", action="append", default=[], metavar="NAME=VERSION")
    p.add_argument("--run-url")
    p.add_argument("--error", help="record a failed build with this message instead of sizes")
    p.set_defaults(func=cmd_record_build_size)

    p = with_store(sub.add_parser("history", help="print the records of a repo"))
    p.add_argument("--metric", default=BUILD_SIZE)
    p.add_argument("--value", default="static_js_gzip_bytes", help="the value to show per commit")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("merge", help="add every record of one store to another")
    p.add_argument("--store", required=True, help="the store to add to")
    p.add_argument("--from", dest="source", required=True, help="the store to read")
    p.add_argument("--backend", default="files")
    p.set_defaults(func=cmd_merge)

    args = ap.parse_args(argv)
    if args.cmd == "record" and args.error is None and not args.dist:
        ap.error("record build-size needs --dist, or --error for a failed build")
    try:
        return args.func(args)
    except (size.SizeError, StoreError, record.RecordError) as e:
        print(f"qqperf: {e}", file=sys.stderr)
        return 1
