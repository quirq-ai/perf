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
- Every record is written as a `quirq-ai/test-pipelines` results bundle: a Run for the measured
  repo and commit with one Result (`perf::<metric>`) whose `metrics` hold the values as
  `{value, unit}`, and a `raw` JSON with the runner type, toolchains and any raw samples. Its
  scorecard workflow collects them into the results store (V0-TST-02).
- v0 numbers are a record, not a regression signal: one measurement per commit on shared runners,
  few samples, no baseline run beside it. Do not gate or alert on them; that needs v1's repeated,
  A/B runs.

Plan and every v0 item: [quirq-ai/infra-config](https://github.com/quirq-ai/infra-config),
`docs/plan.md` and `docs/v0.md`.

## The perf workflow

`.github/workflows/perf.yml` runs every 30 minutes (or on dispatch). For each measurement it takes
the newest commit on the product repo's `main` (first parent) that has no record yet, so a backlog
drains one commit per run:

| Metric | Item | Repo | What |
|---|---|---|---|
| `build-size` | V0-PRF-02 | innernet | the `.next` output: client static bytes and files, JS and CSS raw and gzipped, fonts, server bytes, total without cache, traces and build-time chunks, the JS every route loads first, legacy polyfills apart |
| `xo-space-server-start` | V0-PRF-01 | xo-space | seconds from starting the server until it answers, over 5 starts (p50, p90, min, max) |
| `innernet-search` | V0-PRF-01 | innernet | milliseconds per search request on the demo build (fixed committed index), 30 requests over 3 queries |

Builds and benchmarks go through recipes' adapters (`build`, and `bench` with `params.bench`), on
the pinned Python, Node and pnpm. A failed build or benchmark is recorded as failed and retried by
later runs, up to three failed records per commit. GitHub turns off a scheduled workflow after 60
days without repo activity; re-enable it in the Actions tab.

Each record goes two places. This repo's [`perf-data`](../../tree/perf-data) branch keeps the
records as JSON Lines, one file per repo and metric (schema `qq-perf-record/1`); it is also how a
run knows what is already measured. Lines are never edited, and a commit gets at most one `ok`
record. The results store is the system of record: `.github/workflows/perf-publish.yml` turns the
records each perf run stored into results bundles (`qq-results-*` artifacts) for the scorecard to
collect.

Trust: the `measure` jobs run product code and its dependencies, so they get read access only and
their records are claims. They upload only a ledger. The `store` job, which runs no product code,
accepts a ledger only for its own leg's repo and metric, only for commits still pending on that
repo's `main`, only for records naming this run, and only finite values of at least 0, then pushes
`perf-data`. perf-publish runs after perf completes, from the default branch, reads only
`perf-data`, and is the only workflow that uploads results bundles; test-pipelines collects perf
bundles from it alone.

```sh
qqperf pending --store DIR --repo innernet --checkout PATH        # landed commits with no record
qqperf record build-size --store DIR --repo innernet --checkout PATH --dist PATH/.next --runner LABEL
qqperf history --store DIR --repo innernet [--value static_js_gzip_bytes] [--json]
qqperf merge --store DIR --from DIR --repo innernet [--metric M] [--commit SHA]... [--run-url URL]
qqperf record bench --store DIR --repo xo-space --checkout PATH --benchmark xo-space-server-start \
  --target server --bench-dir OUT/bench --runner LABEL
qqperf bundle --store DIR --repo innernet --metric build-size --run-url URL --results-out DIR
qqperf manifest --base repo.toml --target app --params '{"bench": {...}}' --out bench.toml
```

## v0 status

| Item | What | PR | State |
|---|---|---|---|
| V0-PRF-02 | Build-size record for Next.js apps | #2 | merged; innernet history on [`perf-data`](../../blob/perf-data/innernet/build-size.jsonl) since run [37202550498](../../actions/runs/37202550498) |
| V0-PRF-01 | `bench` capability and storage | recipes#10, #4, #5 | merged; first records from run [37204645471](../../actions/runs/37204645471), in test-pipelines' results store. Polls `main` until product post-submit exists (V0-GAR-01) |

## Working here

See [AGENTS.md](AGENTS.md). Run the checks with `python -m pytest`.

## Licence

[Apache-2.0](LICENSE).
