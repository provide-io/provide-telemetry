# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for spec/validate_conformance.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "validate_conformance.py"


def _load_validate_conformance_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_conformance_test_module", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_conformance_supports_rust_language() -> None:
    """Rust should be a supported conformance target in the current codebase."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--lang", "rust"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        "Expected rust conformance check to run successfully for the current codebase:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "Checking rust..." in result.stdout
    assert "OK" in result.stdout


def test_get_rust_exports_supports_async_const_and_reexports(tmp_path: Path) -> None:
    """Rust export detection should support common public export forms in lib.rs."""
    module = _load_validate_conformance_module()
    rust_src = tmp_path / "rust" / "src"
    rust_src.mkdir(parents=True)
    (rust_src / "lib.rs").write_text(
        """
pub async fn setup_telemetry() {}
pub const logger: usize = 0;
pub use crate::api::{bind_context, TelemetryError as ExportedTelemetryError};
pub use crate::trace;
""".strip(),
        encoding="utf-8",
    )

    typed_module = cast(Any, module)
    typed_module._REPO_ROOT = tmp_path
    exports = module._get_rust_exports()

    assert "setup_telemetry" in exports
    assert "logger" in exports
    assert "bind_context" in exports
    assert "ExportedTelemetryError" in exports
    assert "trace" in exports
