#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Coarse perf-budget gate: compare measured timings against a baseline file.

Generic — works for any language whose benchmark runner can emit a flat
``{operation_name: ns_per_op}`` JSON object on stdout. The runner is invoked
by the caller; this script just consumes its stdout and compares to the
matching OS bucket inside ``baselines/perf-<lang>.json``.

Baseline file shape (per language):

    {
      "linux-x86_64": {
        "event_name_ns": {"baseline_ns": 142.5, "tolerance_multiplier": 3.0}
      },
      "macos-arm64":  {...},
      "windows-x86_64": {...}
    }

Exit codes:
  0 — every measured op passed (measured <= baseline_ns * tolerance_multiplier)
      OR ``--report-only`` flag is set OR the OS bucket has no entries yet
  1 — at least one op exceeded its budget (only when not ``--report-only``)
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import TextIO


def detect_os_key() -> str:
    """Return ``<system>-<arch>`` (e.g. ``linux-x86_64``, ``macos-arm64``).

    The system part is normalised to lowercase short names matching common
    GitHub Actions runner labels: ``linux``, ``macos``, ``windows``.
    """
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    elif system not in {"linux", "windows"}:
        system = system  # leave anything exotic as-is so the mismatch is visible
    arch = platform.machine().lower()
    # Normalise common aarch64 / arm variants for stability across runners.
    if arch in {"aarch64", "arm64"}:
        arch = "arm64"
    elif arch in {"x86_64", "amd64"}:
        arch = "x86_64"
    return f"{system}-{arch}"


def load_baseline(path: Path) -> dict[str, dict[str, dict[str, float]]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"baseline {path} must contain a JSON object")
    return raw  # type: ignore[no-any-return]


def evaluate(
    measurements: dict[str, float],
    bucket: dict[str, dict[str, float]],
) -> tuple[list[str], list[str]]:
    """Return (failures, missing) — failures exceeded budget; missing are
    measured ops with no baseline entry yet."""
    failures: list[str] = []
    missing: list[str] = []
    for op_name, measured_ns in measurements.items():
        entry = bucket.get(op_name)
        if entry is None:
            missing.append(op_name)
            continue
        baseline_ns = float(entry["baseline_ns"])
        tolerance = float(entry.get("tolerance_multiplier", 3.0))
        budget = baseline_ns * tolerance
        if measured_ns > budget:
            failures.append(
                f"{op_name}: measured {measured_ns:.1f}ns > budget {budget:.1f}ns "
                f"(baseline {baseline_ns:.1f}ns x {tolerance:.2f})"
            )
    return failures, missing


def parse_measurements(stream: TextIO) -> dict[str, float]:
    """Read the runner's stdout — accepts either:

    * a single flat JSON object ``{op_name: ns_per_op, ...}`` (Python runner), or
    * a stream of ``{"operation": "...", "ns_per_op": ...}`` JSON objects, one
      per line or concatenated (Go/Rust runner-friendly format).

    Detection: if every decoded top-level object has exactly the
    ``{operation, ns_per_op}`` shape, treat as line-oriented. Otherwise the
    LAST decoded object is taken as the flat measurements blob (lets the
    runner print a trailing status line without breaking the parse).
    """
    text = stream.read().strip()
    if not text:
        raise ValueError("no input on stdin")

    objects: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx] != "{":
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                objects.append(obj)
            idx = end
        except json.JSONDecodeError:
            idx += 1

    if not objects:
        raise ValueError("no JSON object decodable from input")

    line_shaped = all("operation" in obj and "ns_per_op" in obj for obj in objects)
    if line_shaped:
        out: dict[str, float] = {}
        for obj in objects:
            op = obj["operation"]
            ns = obj["ns_per_op"]
            if isinstance(op, str) and isinstance(ns, int | float):
                out[op] = float(ns)
        if not out:
            raise ValueError("no `{operation, ns_per_op}` lines decodable from input")
        return out

    last = objects[-1]
    return {k: float(v) for k, v in last.items() if isinstance(v, int | float)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare benchmark output against a perf baseline.")
    parser.add_argument("--lang", required=True, help="Language tag (used for the baseline filename).")
    parser.add_argument(
        "--baseline-file",
        type=Path,
        help="Override path to the baseline file. Defaults to baselines/perf-<lang>.json.",
    )
    parser.add_argument(
        "--os-key",
        default=None,
        help="OS bucket key (e.g. linux-x86_64). Defaults to host detection.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print measurements + verdict, never exit nonzero. Useful for local runs.",
    )
    args = parser.parse_args()

    baseline_path = args.baseline_file or Path(__file__).parent.parent / "baselines" / f"perf-{args.lang}.json"
    os_key = args.os_key or detect_os_key()
    baseline = load_baseline(baseline_path)
    bucket = baseline.get(os_key, {})

    try:
        measurements = parse_measurements(sys.stdin)
    except ValueError as exc:
        print(f"perf_check: input parse error: {exc}", file=sys.stderr)
        return 2

    if not bucket:
        # No baseline yet for this OS — record measurements and exit clean.
        # The maintainer is expected to seed the bucket via `make perf-baseline`.
        print(
            json.dumps(
                {
                    "lang": args.lang,
                    "os_key": os_key,
                    "baseline_status": "missing",
                    "measurements": measurements,
                    "hint": (
                        f"seed baselines/{baseline_path.name} for {os_key} via "
                        "`make perf-baseline` or copy the measurements above."
                    ),
                },
                indent=2,
            )
        )
        return 0

    failures, missing = evaluate(measurements, bucket)
    print(
        json.dumps(
            {
                "lang": args.lang,
                "os_key": os_key,
                "baseline_status": "present",
                "measurements": measurements,
                "failures": failures,
                "missing_baseline_entries": missing,
            },
            indent=2,
        )
    )

    if failures and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
