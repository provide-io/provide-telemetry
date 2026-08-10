# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for backpressure queue and health snapshot."""

from __future__ import annotations

import subprocess  # nosec
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.mark.memray
@pytest.mark.slow
def test_backpressure_stress(
    memray_output_dir: Path,
    memray_baseline: dict[str, int],
    assert_allocation_within_threshold: Callable[..., None],
    project_root: Path,
    parse_total_allocations: Callable[[str], int],
) -> None:
    """Stress test backpressure queues with memray profiling."""
    script_path = project_root / "scripts" / "memray" / "memray_backpressure_stress.py"
    output_bin = memray_output_dir / "memray_backpressure_stress.bin"

    result = subprocess.run(
        ["python", "-m", "memray", "run", "--force", "-o", str(output_bin), str(script_path)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"memray run failed: {result.stderr}"

    stats_result = subprocess.run(
        ["python", "-m", "memray", "stats", str(output_bin)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert stats_result.returncode == 0, f"memray stats failed: {stats_result.stderr}"

    total_allocations = parse_total_allocations(stats_result.stdout)

    baseline = memray_baseline.get("backpressure_total_allocations")
    assert_allocation_within_threshold(baseline, total_allocations, "backpressure")
