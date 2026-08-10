# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for sampling decision path."""

from __future__ import annotations

import subprocess  # nosec
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.mark.memray
@pytest.mark.slow
def test_sampling_stress(
    memray_output_dir: Path,
    memray_baseline: dict[str, int],
    assert_allocation_within_threshold: Callable[..., None],
    project_root: Path,
    parse_total_allocations: Callable[[str], int],
) -> None:
    """Stress test sampling decisions with memray profiling.

    This bucket measures imports more than it measures sampling. The script runs
    500k decisions and the whole process still allocates under 10k times,
    because the sampling path allocates essentially nothing — so the total is
    dominated by module import: dataclasses._create_fn, importlib's bytecode
    compile and attrs class building account for most of it.

    That makes the 15% tolerance largely a dependency-drift detector. The
    baseline was reseeded from 7474 to 9524 when it failed at +27% with both
    sampling.py and the stress script byte-identical to main; the growth was in
    what the imports cost, not in the code under test. Read a future failure the
    same way — check whether the top allocating locations are in
    provide.telemetry before calling it a regression. It still earns its place
    as a canary: if sampling ever starts allocating per decision, 500k
    iterations will bury the import noise and this will fail loudly.
    """
    script_path = project_root / "scripts" / "memray" / "memray_sampling_stress.py"
    output_bin = memray_output_dir / "memray_sampling_stress.bin"

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

    baseline = memray_baseline.get("sampling_total_allocations")
    assert_allocation_within_threshold(baseline, total_allocations, "sampling")
