from qqresults import bundle

from qqperf import record, results

C = "a" * 40
ENV = {"GITHUB_REPOSITORY": "quirq-ai/perf", "GITHUB_RUN_ID": "77", "GITHUB_SHA": "f" * 40,
       "GITHUB_JOB": "bench", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKFLOW": "bench",
       "GITHUB_EVENT_NAME": "schedule", "GITHUB_REF_NAME": "main"}


def rec(error=None):
    return record.make(repo="innernet", commit=C, metric="innernet-search", target="app",
                       values=None if error else [{"name": "latency_p50", "value": 12.5, "unit": "ms"},
                                                  {"name": "latency_samples", "value": 30, "unit": "count"}],
                       error=error, runner_info=record.runner("ubuntu-24.04", "github"))


def test_github_run_is_about_the_measured_repo(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    run = results.make_run(backend="github", repo="quirq-ai/innernet", commit=C, name="innernet-search-aaaa")
    assert run.repo == "quirq-ai/innernet" and run.commit == C and run.kind == "other"
    assert run.id == "github/quirq-ai/perf/77/1/bench/innernet-search-aaaa"
    assert run.url.startswith("https://github.com/quirq-ai/perf/actions/runs/77")
    assert run.branch == "main" and run.change is None


def test_bundle_round_trips_with_metrics(tmp_path):
    path = results.write_bundle(rec(), tmp_path, backend="local", org="quirq-ai")
    b = bundle.read(path)
    assert b.run.repo == "quirq-ai/innernet" and b.run.commit == C and b.run.kind == "local"
    [r] = b.results
    assert r.test_id == "perf::innernet-search" and r.status == "PASS" and r.expected
    assert r.metrics == {"latency_p50": {"value": 12.5, "unit": "ms"},
                         "latency_samples": {"value": 30, "unit": "count"}}
    assert b.verdict.passed


def test_failed_record_is_an_unexpected_crash(tmp_path):
    b = bundle.read(results.write_bundle(rec(error="benchmark failed: GET /search answered 500"), tmp_path,
                                         backend="local", org="quirq-ai"))
    [r] = b.results
    assert r.status == "CRASH" and not r.expected and "500" in r.message and r.metrics == {}
    assert not b.verdict.passed
