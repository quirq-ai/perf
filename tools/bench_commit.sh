#!/usr/bin/env bash
# Run one benchmark on each given commit through recipes' bench capability and record it (V0-PRF-01).
#
#   tools/bench_commit.sh CHECKOUT FIXTURE_MANIFEST TARGET PARAMS_JSON SCRATCH_STORE REPO BENCHMARK
#                         RUNNER_LABEL COMMIT...
#
# The manifest is the repo's own infra/repo.toml at that commit, or the onboarding fixture until it
# has one (V0-ONB-01/02), with PARAMS_JSON merged into TARGET's params through qqsync's editor.
# A run that fails is recorded as failed, so the history shows the gap and a later run retries it.
#   QQ_RECIPES_ARGS   extra arguments for `qqrecipes execute`, such as --toolchain python=ROOT
#   QQ_TOOLCHAINS     the toolchain versions to record, such as "python=3.14.8"
# TODO(expert): move the benchmark params into infra-config perf.toml or the product manifests.
set -euo pipefail
checkout=$1 fixture=$2 target=$3 params=$4 store=$5 repo=$6 benchmark=$7 label=$8
shift 8
work=${RUNNER_TEMP:-$(mktemp -d)}/qq-bench
mkdir -p "$work"
read -r -a recipes_args <<< "${QQ_RECIPES_ARGS:-}"
extra=()
for tc in ${QQ_TOOLCHAINS:-}; do extra+=(--toolchain "$tc"); done
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  extra+=(--run-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT")
fi
for commit in "$@"; do
  echo "::group::${repo} ${benchmark} ${commit}"
  git -C "$checkout" checkout --quiet --force "$commit"
  git -C "$checkout" clean -qfdx
  base="$checkout/infra/repo.toml"
  [ -f "$base" ] || base=$fixture
  manifest="$work/$commit.repo.toml"
  out="$work/out-$commit"
  common=(--store "$store" --repo "$repo" --checkout "$checkout" --commit "$commit" --runner "$label"
          --benchmark "$benchmark" --target "$target" "${extra[@]}")
  if qqperf manifest --base "$base" --target "$target" --params "$params" --out "$manifest" &&
     qqrecipes execute bench --repo "$checkout" --manifest "$manifest" --target "$target" --out "$out" \
       "${recipes_args[@]}"; then
    qqperf record bench "${common[@]}" --bench-dir "$out/bench"
  elif [ -d "$out/bench" ]; then
    qqperf record bench "${common[@]}" --bench-dir "$out/bench"  # records the bench's own failure detail
  else
    qqperf record bench "${common[@]}" --error "qqrecipes execute bench failed before measuring; see the run's log"
  fi
  echo "::endgroup::"
done
