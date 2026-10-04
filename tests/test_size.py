import pytest

from qqperf import size


def test_next_build_values(next_dist):
    vals = {v["name"]: v for v in size.next_build(next_dist)}
    assert all(v["unit"] == "bytes" for k, v in vals.items() if k != "static_files")
    assert vals["static_files"]["unit"] == "files"
    assert vals["static_files"]["value"] == 6
    assert vals["static_js_bytes"]["value"] == 1000 + 100 + 300 + 10
    assert vals["static_css_bytes"]["value"] == 60
    assert vals["static_font_bytes"]["value"] == 64
    assert vals["static_bytes"]["value"] == 1000 + 100 + 300 + 10 + 60 + 64
    assert vals["server_bytes"]["value"] == 1000
    # The cache and traces are not build output.
    total = vals["total_bytes"]["value"]
    assert total == vals["static_bytes"]["value"] + 1000 + 3 + len((next_dist / "build-manifest.json").read_text())
    # Shared first-load JS: the root main files that exist; polyfills are counted apart.
    assert vals["shared_first_load_js_bytes"]["value"] == 1000
    assert 0 < vals["shared_first_load_js_gzip_bytes"]["value"] < 1000
    assert vals["polyfill_js_bytes"]["value"] == 100
    assert 0 < vals["static_js_gzip_bytes"]["value"] < vals["static_js_bytes"]["value"]


def test_next_build_is_deterministic(next_dist):
    assert size.next_build(next_dist) == size.next_build(next_dist)


def test_no_manifest_means_no_shared_value(next_dist):
    (next_dist / "build-manifest.json").unlink()
    names = [v["name"] for v in size.next_build(next_dist)]
    assert "shared_first_load_js_bytes" not in names and "polyfill_js_bytes" not in names


def test_unfinished_build_is_an_error(tmp_path):
    (tmp_path / "static").mkdir()
    with pytest.raises(size.SizeError, match="not a finished Next.js build"):
        size.next_build(tmp_path)
