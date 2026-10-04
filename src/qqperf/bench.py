"""Read what recipes' `bench` capability wrote (V0-PRF-01).

`qqrecipes execute bench` leaves `{out}/bench/<target>.bench.<action>.json` per bench action:
its raw samples and summary metrics, each `{value, unit}`. This turns one of them into perf
values. Kind-specific code stays in recipes; this file only reads its output.
"""
from __future__ import annotations

import json
from pathlib import Path


class BenchError(Exception):
    """No usable bench output. The message says what is missing."""


def read(bench_dir: Path, target: str) -> tuple[list[dict], dict]:
    """(values, the raw bench JSON) for `target`'s one bench action under `bench_dir`."""
    found = sorted(Path(bench_dir).glob(f"{target}.bench.*.json"))
    if len(found) != 1:
        raise BenchError(f"expected one bench result for target {target!r} in {bench_dir},"
                         f" found {len(found)}; did `qqrecipes execute bench` run?")
    try:
        data = json.loads(found[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BenchError(f"{found[0]}: not readable JSON: {e}") from None
    if not data.get("ok"):
        raise BenchError(f"benchmark failed: {data.get('detail') or 'no detail'}")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise BenchError(f"{found[0]}: no metrics")
    values = [{"name": name, "value": m["value"], "unit": m["unit"]} for name, m in sorted(metrics.items())]
    return values, data
