#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Analyze memray binary outputs: generate flamegraphs, stats report, regression detection."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent.parent / "memray-output"


def parse_memray_stats(bin_path: Path) -> dict[str, str | int]:
    """Run memray stats on a binary and extract key metrics."""
    result = subprocess.run(
        ["uv", "run", "memray", "stats", str(bin_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    info: dict[str, str | int] = {"file": bin_path.name}
    if result.returncode != 0:
        info["error"] = result.stderr.strip()
        return info

    alloc_match = re.search(r"Total allocations:\s+([\d,]+)", result.stdout)
    if alloc_match:
        info["total_allocations"] = int(alloc_match.group(1).replace(",", ""))

    mem_match = re.search(r"Total memory allocated:\s+([\d.]+\w+)", result.stdout)
    if mem_match:
        info["total_memory"] = mem_match.group(1)

    peak_match = re.search(r"Peak memory usage:\s+([\d.]+\w+)", result.stdout)
    if peak_match:
        info["peak_memory"] = peak_match.group(1)

    # Extract top allocator
    top_match = re.search(r"Top 5 largest allocating locations \(by number of allocations\):\s*\n\s*- (.+)", result.stdout)
    if top_match:
        info["top_allocator"] = top_match.group(1).strip()

    return info


def generate_flamegraph(bin_path: Path) -> Path | None:
    """Generate an HTML flamegraph from a memray binary."""
    html_path = bin_path.with_name(bin_path.stem + "_flamegraph.html")
    result = subprocess.run(
        ["uv", "run", "memray", "flamegraph", str(bin_path), "-o", str(html_path), "--force"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        return html_path
    return None


def detect_regression(current_size: int, baseline_size: int) -> tuple[bool, float]:
    """Detect if allocation count regressed by >10%."""
    if baseline_size == 0:
        return (False, 0.0)
    increase_pct = ((current_size - baseline_size) / baseline_size) * 100
    return (increase_pct > 10, increase_pct)


def main() -> int:
    """Analyze all memray binaries and generate report."""
    if not OUTPUT_DIR.exists():
        print("No memray-output/ directory found. Run: make memray", file=sys.stderr)
        return 1

    bin_files = sorted(OUTPUT_DIR.glob("memray_*.bin"))
    if not bin_files:
        print("No .bin files found in memray-output/. Run: make memray", file=sys.stderr)
        return 1

    print(f"Analyzing {len(bin_files)} memray binary files...\n")

    results: list[dict[str, str | int]] = []
    flamegraphs: list[str] = []

    for bin_path in bin_files:
        info = parse_memray_stats(bin_path)
        results.append(info)

        html = generate_flamegraph(bin_path)
        if html:
            flamegraphs.append(html.name)

    # Generate ANALYSIS.md
    report_path = OUTPUT_DIR / "ANALYSIS.md"
    lines = [
        "# Memray Analysis Report\n",
        "",
        "| Test | Allocations | Total Memory | Peak Memory |",
        "|------|------------|-------------|-------------|",
    ]
    for r in results:
        name = str(r.get("file", "?")).replace("memray_", "").replace("_stress.bin", "")
        allocs = f'{r.get("total_allocations", "?"):,}' if isinstance(r.get("total_allocations"), int) else "?"
        total = r.get("total_memory", "?")
        peak = r.get("peak_memory", "?")
        lines.append(f"| {name} | {allocs} | {total} | {peak} |")

    lines.append("")
    lines.append("## Flamegraphs")
    lines.append("")
    for fg in flamegraphs:
        lines.append(f"- [{fg}]({fg})")

    lines.append("")
    lines.append("## Top Allocators")
    lines.append("")
    for r in results:
        name = str(r.get("file", "?")).replace("memray_", "").replace("_stress.bin", "")
        top = r.get("top_allocator", "n/a")
        lines.append(f"- **{name}**: {top}")

    lines.append("")

    report_path.write_text("\n".join(lines))
    print(f"Report written to {report_path}")
    print(f"Flamegraphs generated: {len(flamegraphs)}")

    for r in results:
        allocs = r.get("total_allocations")
        if isinstance(allocs, int):
            print(f"  {r['file']}: {allocs:,} allocations, {r.get('total_memory', '?')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
