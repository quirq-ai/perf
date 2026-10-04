# Agent guide

How an agent changes this repo safely. Read `README.md` first.

- Every change is a pull request against `main`, titled with its work item id (for example
  `V0-PRF-02: ...`). It lands only with the `presubmit` check green.
- Store raw values with units and the runner type. Never average away noise in v0.
- Kind-specific benchmark code (`bench`) belongs in `quirq-ai/recipes` adapters; open that PR there.
- Manifests are read only through `quirq-ai/sync` (`qqsync`). Config is read with infra-config's `qqcfg`.
- `.github/CODEOWNERS` names suraj (`@sharmasuraj0123`) as owner of the policy and trust paths,
  including the code privileged workflows run; owner names are his call, so never change them. Leave any other `owners` list empty.
- Mark a decision you cannot make with a one-line `TODO(suraj):` or `TODO(expert):`.
- This repo is public: no secrets, tokens or internal hostnames.
- GitHub-specific code stays behind a `backend` field (`github` now, `launchpad` later).
- Use other qq repos by pinned commit, never by copying their code.
