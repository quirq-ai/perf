"""qqperf: the perf command line."""
from __future__ import annotations

import argparse

from qqperf import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qqperf", description=__doc__.split("\n")[0])
    ap.add_argument("--version", action="version", version=f"qqperf {__version__}")
    ap.parse_args(argv)
    ap.print_help()
    return 0
