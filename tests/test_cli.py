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
