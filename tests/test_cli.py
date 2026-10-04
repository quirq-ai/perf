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
    assert capsys.readouterr().out.split() == [landed[2]]

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
    assert "write-once" in capsys.readouterr().err


def test_record_needs_dist_or_error(tmp_path, product_repo):
    with pytest.raises(SystemExit):
        cli.main(["record", "build-size", "--store", str(tmp_path), "--repo", "innernet",
                  "--checkout", str(product_repo), "--runner", "x"])


def test_merge(tmp_path, product_repo, next_dist, capsys):
    scratch, history = tmp_path / "scratch", tmp_path / "history"
    base = ["record", "build-size", "--repo", "innernet", "--checkout", str(product_repo), "--dist",
            str(next_dist), "--runner", "x"]
    assert cli.main([*base, "--store", str(scratch)]) == 0
    assert cli.main(["merge", "--store", str(history), "--from", str(scratch)]) == 0
    assert "merged 1 record" in capsys.readouterr().out
    assert (history / "innernet" / "build-size.jsonl").read_text() == (scratch / "innernet" / "build-size.jsonl").read_text()
    # Merging the same records again is refused: history is write-once.
    assert cli.main(["merge", "--store", str(history), "--from", str(scratch)]) == 1
    assert cli.main(["merge", "--store", str(history), "--from", str(tmp_path / "none")]) == 0
