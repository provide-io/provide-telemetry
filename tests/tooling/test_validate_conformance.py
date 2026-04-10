# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
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
    assert result.returncode == 0, f"Conformance check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def test_conformance_detects_missing_symbol(tmp_path: Path) -> None:
    """The validator should exit 1 when a required symbol is missing."""
    fake_spec = tmp_path / "fake-spec.yaml"
    fake_spec.write_text(
        "spec_version: '1'\n"
        "api:\n"
        "  test:\n"
        "    - name: nonexistent_function\n"
        "      kind: function\n"
        "      required: true\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--lang", "python", "--spec", str(fake_spec)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 1, (
        f"Expected exit 1 for missing symbol:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "MISSING" in result.stdout
