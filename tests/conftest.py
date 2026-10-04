import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def next_dist(tmp_path) -> Path:
    """A small stand-in for a finished `next build` output directory."""
    dist = tmp_path / ".next"
    files = {
        "BUILD_ID": "abc",
        "static/chunks/main.js": "console.log('main');" * 50,
        "static/chunks/poly.js": "p" * 100,
        "static/chunks/page.js": "x" * 300,
        "static/css/app.css": "body{}" * 10,
        "static/media/font.woff2": "f" * 64,
        "static/abc/_buildManifest.js": "m" * 10,
        "server/app/page.js": "s" * 1000,
        "cache/big.bin": "c" * 5000,
        "trace": "t" * 700,
        "build/chunks/x.js": "b" * 400,
        "types/routes.d.ts": "t" * 30,
        "build-manifest.json": json.dumps({"polyfillFiles": ["static/chunks/poly.js"],
                                           "rootMainFiles": ["static/chunks/main.js", "static/chunks/missing.js"]}),
    }
    for rel, text in files.items():
        p = dist / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return dist


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def product_repo(tmp_path) -> Path:
    """A repo with three commits on main, the middle one a merge, as GitHub lands PRs."""
    repo = tmp_path / "product"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a").write_text("1")
    git(repo, "add", "a")
    git(repo, "commit", "-q", "-m", "one")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "b").write_text("2")
    git(repo, "add", "b")
    git(repo, "commit", "-q", "-m", "feature work")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    (repo / "a").write_text("3")
    git(repo, "commit", "-q", "-am", "three")
    return repo
