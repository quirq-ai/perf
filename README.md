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

## v0 status

| Item | What | PR | State |
|---|---|---|---|
| V0-PRF-02 | Build-size record for Next.js apps | | not started |
| V0-PRF-01 | `bench` capability and storage | | waits on V0-TST-02 (test-pipelines) |

## Working here

See [AGENTS.md](AGENTS.md). Run the checks with `python -m pytest`.
