# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Bounded-growth stress test: run as subprocess and assert exit code 0."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.memray
@pytest.mark.slow
def test_bounded_growth_stress() -> None:
    """Verify module-level caches do not grow unboundedly."""
    script_path = Path(__file__).parent.parent.parent / "scripts" / "memray" / "memray_bounded_growth_stress.py"

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(Path(__file__).parent.parent.parent),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Bounded-growth stress test failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
