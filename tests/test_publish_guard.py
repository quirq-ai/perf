from pathlib import Path

PUBLISH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "perf-publish.yml"


def test_publish_runs_only_for_perf_runs_on_main():
    text = PUBLISH.read_text()
    for clause in ("workflow_run.head_branch == 'main'", "head_repository.full_name == github.repository",
                   "workflow_run.path == '.github/workflows/perf.yml'", "github.run_attempt == 1",
                   'git merge-base --is-ancestor "$HEAD_SHA" FETCH_HEAD'):
        assert clause in text
