import json

import pytest

from qqperf import record, store

C1, C2 = "1" * 40, "2" * 40


def rec(commit=C1, repo="innernet", error=None):
    return record.make(repo=repo, commit=commit, metric="build-size", target="app",
                       values=None if error else [{"name": "static_bytes", "value": 1, "unit": "bytes"}],
                       error=error, runner_info=record.runner("ubuntu-24.04", "github"))


def test_put_and_read(tmp_path):
    s = store.open_store("files", tmp_path)
    path = s.put(rec(C1))
    s.put(rec(C2))
    assert path == tmp_path / "innernet" / "build-size.jsonl"
    assert [r["commit"] for r in s.records("innernet", "build-size")] == [C1, C2]
    assert s.done("innernet", "build-size") == {C1, C2}
    assert s.records("innernet", "other") == []
    assert s.streams() == [("innernet", "build-size")]


def test_ok_is_never_replaced(tmp_path):
    s = store.FileStore(tmp_path)
    s.put(rec(C1))
    with pytest.raises(store.StoreError, match="never replaced"):
        s.put(rec(C1))
    with pytest.raises(store.StoreError, match="never replaced"):
        s.put(rec(C1, error="late failure"))


def test_failed_is_retried_up_to_the_limit(tmp_path):
    s = store.FileStore(tmp_path)
    for _ in range(store.MAX_ATTEMPTS - 1):
        s.put(rec(C1, error="flaky"))
    assert C1 not in s.done("innernet", "build-size")
    s.put(rec(C1, error="flaky"))
    assert C1 in s.done("innernet", "build-size")
    with pytest.raises(store.StoreError, match="not measured again"):
        s.put(rec(C1, error="again"))
    # A retry that succeeds ends the retries.
    s.put(rec(C2, error="flaky"))
    s.put(rec(C2))
    assert C2 in s.done("innernet", "build-size")


@pytest.mark.parametrize("field, value, match", [
    ("repo", "../escape", "repo"), ("repo", "innernet\n", "repo"), ("commit", "abc", "commit"),
    ("commit", "--output=x" + "0" * 30, "commit"), ("status", "maybe", "status"),
    ("values", [{"name": "x", "value": "1", "unit": "b"}], "values"), ("values", [], "ok record"),
    ("schema", "other/1", "schema"),
    ("values", [{"name": "x", "value": -1, "unit": "b"}], "values"),
    ("values", [{"name": "x", "value": float("nan"), "unit": "b"}], "values"),
    ("values", [{"name": "x", "value": float("inf"), "unit": "b"}], "values"),
    ("run", "url", "run"), ("detail", {"samples": [1, -2]}, "samples"),
    ("detail", {"samples": [float("nan")]}, "samples"), ("detail", {"logs": []}, "detail"),
    ("detail", {"paths": [1]}, "paths"), ("target", "x" * 3000, "target"),
    ("runner", {"label": "x" * 3000}, "runner"), ("toolchains", {"node": 24}, "toolchains"),
    ("values", [{"name": f"v{i}", "value": 1, "unit": "b"} for i in range(65)], "values")])
def test_bad_records_are_refused(tmp_path, field, value, match):
    r = rec()
    r[field] = value
    with pytest.raises(store.StoreError, match=match):
        store.FileStore(tmp_path).put(r)
    assert not (tmp_path / "innernet").exists()


def test_put_many_is_all_or_nothing(tmp_path):
    s = store.FileStore(tmp_path)
    bad = rec(C2)
    bad["status"] = "maybe"
    with pytest.raises(store.StoreError):
        s.put_many([rec(C1), bad])
    assert s.records("innernet", "build-size") == []
    with pytest.raises(store.StoreError, match="never replaced"):
        s.put_many([rec(C1), rec(C1)])
    assert s.records("innernet", "build-size") == []


def test_unknown_backend(tmp_path):
    with pytest.raises(store.StoreError, match="unknown store backend"):
        store.open_store("cloud", tmp_path)


@pytest.mark.parametrize("line", ["{not json", "[1]", json.dumps({"schema": store.SCHEMA})])
def test_bad_line_is_reported(tmp_path, line):
    p = tmp_path / "innernet" / "build-size.jsonl"
    p.parent.mkdir()
    p.write_text(line + "\n")
    with pytest.raises(store.StoreError, match="build-size.jsonl:1"):
        store.FileStore(tmp_path).done("innernet", "build-size")


def test_append_after_a_missing_final_newline(tmp_path):
    s = store.FileStore(tmp_path)
    s.put(rec(C1, error="flaky"))
    p = tmp_path / "innernet" / "build-size.jsonl"
    p.write_text(p.read_text().rstrip("\n"))
    s.put(rec(C2))
    assert [r["commit"] for r in s.records("innernet", "build-size")] == [C1, C2]
