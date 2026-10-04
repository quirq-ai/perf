import json

import pytest

from qqperf import bench


def write(d, name, data):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data))


def test_read_values_sorted(tmp_path):
    write(tmp_path, "server.bench.serve.json", {"ok": True, "metrics": {
        "startup_p50": {"value": 1.2, "unit": "s"}, "startup_max": {"value": 1.5, "unit": "s"}}})
    values, data = bench.read(tmp_path, "server")
    assert [v["name"] for v in values] == ["startup_max", "startup_p50"]
    assert values[1] == {"name": "startup_p50", "value": 1.2, "unit": "s"} and data["ok"]


@pytest.mark.parametrize("files, match", [
    ({}, "found 0"),
    ({"server.bench.a.json": {"ok": True, "metrics": {}}, "server.bench.b.json": {"ok": True}}, "found 2"),
    ({"server.bench.a.json": {"ok": False, "detail": "GET / answered 500"}}, "answered 500"),
    ({"server.bench.a.json": {"ok": True, "metrics": {}}}, "no metrics")])
def test_read_errors(tmp_path, files, match):
    tmp_path.mkdir(exist_ok=True)
    for name, data in files.items():
        write(tmp_path, name, data)
    with pytest.raises(bench.BenchError, match=match):
        bench.read(tmp_path, "server")
