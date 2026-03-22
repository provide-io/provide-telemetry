#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Orchestrator for memray stress tests across all hot-path components."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent.parent / "memray-output"
SCRIPTS = [
    "memray_logging_stress.py",
    "memray_sampling_stress.py",
    "memray_pii_stress.py",
    "memray_backpressure_stress.py",
    "memray_tracing_stress.py",
    "memray_metrics_stress.py",
]


def main() -> int:
    """Run all memray stress tests and print ready-to-paste commands."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    for script in SCRIPTS:
        script_path = Path(__file__).parent / script
        output_bin = OUTPUT_DIR / f"{script.replace('.py', '')}.bin"

        print(f"\n>>> Running {script}...", file=sys.stderr)
        try:
            subprocess.run(
                ["uv", "run", "memray", "run", "--force", "-o", str(output_bin), str(script_path)],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"ERROR: {script} failed with exit code {e.returncode}", file=sys.stderr)
            return e.returncode

    # Print ready-to-paste commands
    print("\n" + "=" * 80)
    print("Memray stress tests complete. Ready-to-paste analysis commands:")
    print("=" * 80)
    for script in SCRIPTS:
        bin_file = OUTPUT_DIR / f"{script.replace('.py', '')}.bin"
        print(f"\n# {script}:")
        print(f"memray flamegraph {bin_file}")
        print(f"memray stats {bin_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
