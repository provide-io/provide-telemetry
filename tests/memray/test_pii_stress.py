# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for PII sanitization engine."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.mark.memray
@pytest.mark.slow
def test_pii_stress(
    memray_output_dir: Path,
    memray_baseline: dict[str, int],
    assert_allocation_within_threshold: Callable[..., None],
    project_root: Path,
) -> None:
    """Stress test PII sanitization with memray profiling."""
    script_path = project_root / "scripts" / "memray" / "memray_pii_stress.py"
    output_bin = memray_output_dir / "memray_pii_stress.bin"

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

    match = re.search(r"Total allocations:\s+([\d,]+)", stats_result.stdout)
    assert match, f"Could not parse allocations from memray stats:\n{stats_result.stdout}"
    total_allocations = int(match.group(1).replace(",", ""))

    baseline = memray_baseline.get("pii_total_allocations")
    assert_allocation_within_threshold(baseline, total_allocations, "pii")
