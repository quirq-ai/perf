import json

import pytest

from qqperf import __version__, cli


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_pending_record_history(tmp_path, product_repo, next_dist, capsys):
    store = str(tmp_path / "store")
    base = ["--store", store, "--repo", "innernet"]
    assert cli.main(["pending", *base, "--checkout", str(product_repo)]) == 0
    landed = capsys.readouterr().out.split()
    assert len(landed) == 3

    assert cli.main(["record", "build-size", *base, "--checkout", str(product_repo), "--dist", str(next_dist),
                     "--runner", "ubuntu-24.04", "--toolchain", "node=24.21.0"]) == 0
    assert "recorded innernet" in capsys.readouterr().out
    assert cli.main(["record", "build-size", *base, "--checkout", str(product_repo), "--commit", landed[1],
                     "--runner", "ubuntu-24.04", "--error", "build failed"]) == 0
    capsys.readouterr()

    assert cli.main(["pending", *base, "--checkout", str(product_repo)]) == 0
    # The failed commit is retried until it has failed MAX_ATTEMPTS times.
    assert capsys.readouterr().out.split() == [landed[1], landed[2]]

    assert cli.main(["history", *base]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "bytes" in lines[0] and "failed" in lines[1]
    assert cli.main(["history", *base, "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["commit"] == landed[0] and rows[0]["toolchains"] == {"node": "24.21.0"}


def test_record_twice_is_refused(tmp_path, product_repo, next_dist, capsys):
    args = ["record", "build-size", "--store", str(tmp_path), "--repo", "innernet", "--checkout",
            str(product_repo), "--dist", str(next_dist), "--runner", "x"]
    assert cli.main(args) == 0
    assert cli.main(args) == 1
    assert "never replaced" in capsys.readouterr().err


def test_record_needs_dist_or_error(tmp_path, product_repo):
    with pytest.raises(SystemExit):
        cli.main(["record", "build-size", "--store", str(tmp_path), "--repo", "innernet",
                  "--checkout", str(product_repo), "--runner", "x"])


def test_merge(tmp_path, product_repo, next_dist, capsys):
    scratch, history = tmp_path / "scratch", tmp_path / "history"
    base = ["record", "build-size", "--repo", "innernet", "--checkout", str(product_repo), "--dist",
            str(next_dist), "--runner", "x"]
    assert cli.main([*base, "--store", str(scratch)]) == 0
    merge = ["merge", "--store", str(history), "--repo", "innernet"]
    assert cli.main([*merge, "--from", str(scratch)]) == 0
    assert "merged 1 record" in capsys.readouterr().out
    assert (history / "innernet" / "build-size.jsonl").read_text() == (scratch / "innernet" / "build-size.jsonl").read_text()
    # Merging the same records again is refused: an ok record is never replaced.
    assert cli.main([*merge, "--from", str(scratch)]) == 1
    assert cli.main([*merge, "--from", str(tmp_path / "none")]) == 0


def test_merge_refuses_other_repos_and_mislabelled_records(tmp_path, product_repo, next_dist, capsys):
    scratch, history = tmp_path / "scratch", tmp_path / "history"
    assert cli.main(["record", "build-size", "--store", str(scratch), "--repo", "innernet", "--checkout",
                     str(product_repo), "--dist", str(next_dist), "--runner", "x"]) == 0
    merge = ["merge", "--store", str(history), "--from", str(scratch)]
    assert cli.main([*merge, "--repo", "xo-space"]) == 1
    assert "takes only xo-space" in capsys.readouterr().err
    # A record whose own repo differs from the file it sits in is refused, not redirected.
    f = scratch / "innernet" / "build-size.jsonl"
    f.write_text(f.read_text().replace('"repo":"innernet"', '"repo":"xo-space"'))
    assert cli.main([*merge, "--repo", "innernet"]) == 1
    assert "refusing the merge" in capsys.readouterr().err
    assert not history.exists()


def test_record_bench_and_results_bundle(tmp_path, product_repo, capsys):
    from qqresults import bundle
    bench_dir = tmp_path / "out" / "bench"
    bench_dir.mkdir(parents=True)
    (bench_dir / "server.bench.serve.json").write_text(json.dumps(
        {"ok": True, "metrics": {"startup_p50": {"value": 1.25, "unit": "s"}}, "measure": "startup",
         "paths": ["/"], "unit": "s", "samples": [1.2, 1.25, 1.3]}))
    base = ["record", "bench", "--store", str(tmp_path / "store"), "--repo", "xo-space", "--checkout",
            str(product_repo), "--benchmark", "xo-space-server-start", "--target", "server", "--runner", "x",
            "--results-out", str(tmp_path / "results"), "--results-backend", "local",
            "--github-output", str(tmp_path / "gh-out")]
    assert cli.main([*base, "--bench-dir", str(bench_dir)]) == 0
    out = capsys.readouterr().out
    assert "startup_p50=1.25s" in out and "results bundle:" in out
    [path] = (tmp_path / "results").iterdir()
    b = bundle.read(path)
    assert b.run.repo == "quirq-ai/xo-space" and b.results[0].metrics["startup_p50"]["unit"] == "s"
    raw = json.loads(b.results[0].raw)
    assert raw["samples"] == [1.2, 1.25, 1.3] and raw["runner"]["label"] == "x" and raw["target"] == "server"
    assert f"name={path.name}" in (tmp_path / "gh-out").read_text()

    # A failed benchmark is a failed record, retried later.
    (bench_dir / "server.bench.serve.json").write_text(json.dumps({"ok": False, "detail": "never ready"}))
    landed = cli.record.first_parent(product_repo)
    assert cli.main([*base, "--bench-dir", str(bench_dir), "--commit", landed[1]]) == 0
    rows = cli.open_store("files", tmp_path / "store").records("xo-space", "xo-space-server-start")
    assert [r["status"] for r in rows] == ["ok", "failed"] and "never ready" in rows[1]["error"]


def test_no_ledger_record_without_its_bundle(tmp_path, product_repo, capsys, monkeypatch):
    from qqresults.errors import Error
    from qqperf import results

    def broken(*a, **kw):
        raise Error("GITHUB_RUN_ID is not set")
    monkeypatch.setattr(results, "write_bundle", broken)
    assert cli.main(["record", "bench", "--store", str(tmp_path / "store"), "--repo", "xo-space", "--checkout",
                     str(product_repo), "--benchmark", "b", "--target", "server", "--runner", "x",
                     "--error", "boom", "--results-out", str(tmp_path / "results")]) == 1
    assert "nothing was recorded" in capsys.readouterr().err
    assert cli.open_store("files", tmp_path / "store").records("xo-space", "b") == []


def test_record_bench_needs_a_target(tmp_path, product_repo):
    with pytest.raises(SystemExit):
        cli.main(["record", "bench", "--store", str(tmp_path), "--repo", "xo-space", "--checkout",
                  str(product_repo), "--benchmark", "b", "--runner", "x", "--bench-dir", str(tmp_path)])


def test_manifest_adds_params(tmp_path, capsys):
    base = tmp_path / "repo.toml"
    base.write_text('schema = "quirq-repo/1"\n[qq]\nversion = "0.1.0"\n\n[[targets]]\nname = "app"\n'
                    'kind = "node-app"\nsrcs = ["app/**"]\nparams = { ready_path = "/", env = { A = "1" } }\n')
    out = tmp_path / "bench.toml"
    params = json.dumps({"env": {"INNERNET_DEMO": "1"}, "bench": {"paths": ["/search?q=qq"], "samples": 10}})
    assert cli.main(["manifest", "--base", str(base), "--target", "app", "--params", params, "--out", str(out)]) == 0
    from qqsync.manifest import load
    [t] = load(out)["targets"]
    assert t["params"] == {"ready_path": "/", "env": {"A": "1", "INNERNET_DEMO": "1"},
                           "bench": {"paths": ["/search?q=qq"], "samples": 10}}
    assert cli.main(["manifest", "--base", str(base), "--target", "nope", "--params", "{}", "--out", str(out)]) == 1
    assert cli.main(["manifest", "--base", str(base), "--target", "app", "--params", "[1]", "--out", str(out)]) == 1
