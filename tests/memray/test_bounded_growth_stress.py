# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Bounded-growth stress test: run as subprocess and assert exit code 0."""

from __future__ import annotations

import subprocess  # nosec
import sys
from pathlib import Path

import pytest


@pytest.mark.memray
@pytest.mark.slow
def test_bounded_growth_stress(project_root: Path) -> None:
    """Verify module-level caches do not grow unboundedly."""
    script_path = project_root / "scripts" / "memray" / "memray_bounded_growth_stress.py"

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Bounded-growth stress test failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
