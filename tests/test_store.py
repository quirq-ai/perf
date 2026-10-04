import pytest

from qqperf import record, store


def rec(commit="c1", **kw):
    return record.make(repo="innernet", commit=commit, metric="build-size", target="app",
                       values=[{"name": "static_bytes", "value": 1, "unit": "bytes"}],
                       runner_info=record.runner("ubuntu-24.04", "github"), **kw)


def test_put_and_read(tmp_path):
    s = store.open_store("files", tmp_path)
    path = s.put(rec("c1"))
    s.put(rec("c2"))
    assert path == tmp_path / "innernet" / "build-size.jsonl"
    assert [r["commit"] for r in s.records("innernet", "build-size")] == ["c1", "c2"]
    assert s.commits("innernet", "build-size") == {"c1", "c2"}
    assert s.records("innernet", "other") == []


def test_write_once(tmp_path):
    s = store.FileStore(tmp_path)
    s.put(rec("c1"))
    with pytest.raises(store.StoreError, match="write-once"):
        s.put(rec("c1"))


def test_names_are_checked(tmp_path):
    s = store.FileStore(tmp_path)
    r = rec()
    r["repo"] = "../escape"
    with pytest.raises(store.StoreError, match="repo"):
        s.put(r)


def test_unknown_backend(tmp_path):
    with pytest.raises(store.StoreError, match="unknown store backend"):
        store.open_store("cloud", tmp_path)


def test_corrupt_line_is_reported(tmp_path):
    p = tmp_path / "innernet" / "build-size.jsonl"
    p.parent.mkdir()
    p.write_text("{not json\n")
    with pytest.raises(store.StoreError, match="build-size.jsonl:1"):
        store.FileStore(tmp_path).records("innernet", "build-size")
