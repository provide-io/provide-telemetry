#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
"""Merge the C# cobertura reports and enforce the coverage floors.

Both test projects instrument the core assembly, so each emits its own
report and neither is complete alone — the merge takes the union: a line
is covered if any suite reached it. On failure, every missed line and
partial branch is listed, because a floor breach whose location is only
visible in a runner's temp directory is undiagnosable from the log.
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


def merge(results_dir: str) -> dict[str, dict[int, tuple[int, int, int]]]:
    reports = glob.glob(f"{results_dir}/**/coverage.cobertura.xml", recursive=True)
    if not reports:
        sys.exit("FAIL: no coverage.cobertura.xml produced")
    lines: dict[str, dict[int, tuple[int, int, int]]] = defaultdict(dict)
    for report in reports:
        # The reports are our own build artifacts, not untrusted input.
        for cls in ET.parse(report).getroot().iter("class"):  # noqa: S314
            filename = cls.get("filename") or ""
            if "Provide.Telemetry" not in filename:
                continue
            for line in cls.iter("line"):
                number = int(line.get("number") or 0)
                hits = int(line.get("hits") or 0)
                fraction = re.search(r"\((\d+)/(\d+)\)", line.get("condition-coverage") or "")
                covered, total = (int(fraction[1]), int(fraction[2])) if fraction else (0, 0)
                previous = lines[filename].get(number, (0, 0, 0))
                lines[filename][number] = (
                    max(previous[0], hits),
                    max(previous[1], covered),
                    max(previous[2], total),
                )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce merged C# coverage floors.")
    parser.add_argument("results_dir")
    parser.add_argument("--line-floor", type=float, required=True)
    parser.add_argument("--branch-floor", type=float, required=True)
    args = parser.parse_args()

    lines = merge(args.results_dir)
    measured = [entry for file_lines in lines.values() for entry in file_lines.values()]
    if not measured:
        sys.exit("FAIL: no Provide.Telemetry classes found in the coverage reports")

    line_rate = sum(1 for hits, _, _ in measured if hits) / len(measured) * 100
    branch_total = sum(total for _, _, total in measured)
    branch_rate = sum(covered for _, covered, _ in measured) / branch_total * 100

    print(f"{len(lines)} files, {len(measured)} lines, {branch_total} branches")
    print(
        f"line: {line_rate:.2f}% (floor {args.line_floor:g}), branch: {branch_rate:.2f}% (floor {args.branch_floor:g})"
    )
    if line_rate >= args.line_floor and branch_rate >= args.branch_floor:
        return 0

    for filename, file_lines in sorted(lines.items()):
        missed = [n for n, (hits, _, _) in sorted(file_lines.items()) if not hits]
        partial = [n for n, (hits, covered, total) in sorted(file_lines.items()) if hits and total and covered < total]
        if missed or partial:
            print(f"  {filename}: missed={missed} partial-branch={partial}")
    print("FAIL: coverage fell below the recorded baseline")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
