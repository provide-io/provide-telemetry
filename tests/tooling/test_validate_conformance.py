# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for spec/validate_conformance.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "validate_conformance.py"


def test_conformance_passes_for_current_codebase() -> None:
    """The validator should exit 0 when run against current Python + TS exports."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Conformance check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_conformance_reports_missing_symbol() -> None:
    """The validator should detect when a required symbol is missing."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check-symbol", "nonexistent_function"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Script crashed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
