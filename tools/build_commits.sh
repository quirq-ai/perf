#!/usr/bin/env bash
# Build each given commit of a Next.js repo through recipes' node-app adapter and record its size.
#
#   tools/build_commits.sh CHECKOUT FIXTURE_MANIFEST SCRATCH_STORE REPO RUNNER_LABEL COMMIT...
#
# The manifest is the repo's own infra/repo.toml at that commit, or the onboarding fixture until it
# has one (V0-ONB-02). A failed build is recorded as failed, so the history shows the gap.
# TODO(expert): read the build output dir from the manifest target instead of assuming .next.
set -euo pipefail
checkout=$1 fixture=$2 store=$3 repo=$4 label=$5
shift 5
node_version=$(node --version | sed 's/^v//')
pnpm_version=$(pnpm --version)
run_url="${GITHUB_SERVER_URL:-}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
for commit in "$@"; do
  echo "::group::${repo} ${commit}"
  git -C "$checkout" checkout --quiet --force "$commit"
  git -C "$checkout" clean -qfdx
  manifest="$checkout/infra/repo.toml"
  [ -f "$manifest" ] || manifest=$fixture
  common=(--store "$store" --repo "$repo" --checkout "$checkout" --commit "$commit" --runner "$label"
          --toolchain "node=$node_version" --toolchain "pnpm=$pnpm_version" --run-url "$run_url")
  if qqrecipes execute build --repo "$checkout" --manifest "$manifest" --out "$RUNNER_TEMP/qq-out/$commit"; then
    qqperf record build-size "${common[@]}" --dist "$checkout/.next"
  else
    qqperf record build-size "${common[@]}" --error "qqrecipes execute build failed; see the run's log"
  fi
  echo "::endgroup::"
done
