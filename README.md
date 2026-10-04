# perf

Part of **quirq infra** ("qq"), quirq-ai's CI/CD system for repos in any language. This repo records
performance on every post-submit commit, so v1 can alert on regressions and v2 can bisect them.

**Chromium counterpart:** the chrome.perf waterfall, the perf dashboard and Pinpoint. v0 only
records numbers; it does not alert or bisect.

## How it works (v0)

- Every number is stored raw, with its unit and the runner type it was measured on, because shared
  CI runners are noisy. Comparing numbers is v1's job.
- The benchmarks are declared in `quirq-ai/infra-config` (`config/perf.toml`): `xo-space-server-start`
  and `innernet-search`. Kind-specific `bench` code belongs in `quirq-ai/recipes` adapters, not here.
- Results go to the results store of `quirq-ai/test-pipelines` (V0-TST-02) once it exists.

Plan and every v0 item: [quirq-ai/infra-config](https://github.com/quirq-ai/infra-config),
`docs/plan.md` and `docs/v0.md`.

## Build-size history (V0-PRF-02)

The `build-size` workflow polls innernet's `main` every hour (or on dispatch) and builds each
landed commit (first parent, newest first, five per run by default) that has no record yet,
through recipes' `node-app` adapter on the pinned Node and pnpm. It records the size of the
`.next` output: client static bytes and file count, JS and CSS bytes raw and gzipped, font
bytes, server bytes, the total without the build cache, traces and build-time chunks, the JS
every route loads first and the legacy polyfills apart. A build that fails is recorded as failed
and retried by later runs, up to three failed records per commit. GitHub turns off a scheduled
workflow after 60 days without repo activity; re-enable it in the Actions tab.

History lives on this repo's [`perf-data`](../../tree/perf-data) branch as JSON Lines, one file
per repo and metric (`innernet/build-size.jsonl`), schema `qq-perf-record/1`. Lines are never
edited, and a commit gets at most one `ok` record. The job that builds innernet has read access
only; a second job validates its records, takes only innernet's, and pushes.

```sh
qqperf pending --store DIR --repo innernet --checkout PATH        # landed commits with no record
qqperf record build-size --store DIR --repo innernet --checkout PATH --dist PATH/.next --runner LABEL
qqperf history --store DIR --repo innernet [--value static_js_gzip_bytes] [--json]
qqperf merge --store DIR --from DIR --repo innernet
```

## v0 status

| Item | What | PR | State |
|---|---|---|---|
| V0-PRF-02 | Build-size record for Next.js apps | #2 | in review |
| V0-PRF-01 | `bench` capability and storage | | waits on V0-TST-02 (test-pipelines) |

## Working here

See [AGENTS.md](AGENTS.md). Run the checks with `python -m pytest`.
