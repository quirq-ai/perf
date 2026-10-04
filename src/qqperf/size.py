"""Build-output size of a Next.js app (V0-PRF-02).

Reads the `.next` directory a `next build` leaves behind. Every value is raw bytes; comparing them
is v1's job (bundle-size budget). Only files are counted, never the build cache or traces, which
depend on the machine rather than on the code.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

# Not build output: the incremental cache, traces and diagnostics vary from run to run.
SKIP_TOP = frozenset({"cache", "trace", "trace-build", "diagnostics"})
GROUPS = {"js": {".js", ".mjs"}, "css": {".css"}, "font": {".woff", ".woff2", ".ttf", ".otf"}}


class SizeError(Exception):
    """The directory is not a finished Next.js build. The message says what is missing."""


def _files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            yield p


def _gzip_size(path: Path) -> int:
    # mtime=0 keeps the compressed bytes the same on every machine.
    return len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))


def next_build(dist: Path) -> list[dict]:
    """Size values of one Next.js build, each `{"name", "value", "unit"}`, in a fixed order."""
    dist = Path(dist)
    static = dist / "static"
    if not (dist / "BUILD_ID").is_file() or not static.is_dir():
        raise SizeError(f"{dist} is not a finished Next.js build (no BUILD_ID or static/); run the"
                        " build first")
    values: dict[str, int] = {
        "static_bytes": 0, "static_files": 0, "static_js_bytes": 0, "static_js_gzip_bytes": 0,
        "static_css_bytes": 0, "static_css_gzip_bytes": 0, "static_font_bytes": 0,
    }
    for p in _files(static):
        size = p.stat().st_size
        values["static_bytes"] += size
        values["static_files"] += 1
        suffix = p.suffix.lower()
        for group, suffixes in GROUPS.items():
            if suffix in suffixes:
                values[f"static_{group}_bytes"] += size
                if group != "font":
                    values[f"static_{group}_gzip_bytes"] += _gzip_size(p)
    server = dist / "server"
    values["server_bytes"] = sum(p.stat().st_size for p in _files(server)) if server.is_dir() else 0
    values["total_bytes"] = sum(
        p.stat().st_size for p in _files(dist) if p.relative_to(dist).parts[0] not in SKIP_TOP)
    shared = _shared_first_load(dist)
    if shared is not None:
        values["shared_first_load_js_bytes"], values["shared_first_load_js_gzip_bytes"] = shared
    return [{"name": k, "value": v, "unit": "files" if k.endswith("_files") else "bytes"}
            for k, v in values.items()]


def _shared_first_load(dist: Path) -> tuple[int, int] | None:
    """JS every route loads first: build-manifest's root main and polyfill files.

    TODO(expert): per-route first-load JS; the manifests that list it change between Next majors.
    """
    try:
        manifest = json.loads((dist / "build-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    names = list(dict.fromkeys([*manifest.get("polyfillFiles", []), *manifest.get("rootMainFiles", [])]))
    paths = [dist / n for n in names if (dist / n).is_file()]
    if not paths:
        return None
    return sum(p.stat().st_size for p in paths), sum(_gzip_size(p) for p in paths)
