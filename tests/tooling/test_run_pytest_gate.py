# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/run_pytest_gate.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/run_pytest_gate.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_pytest_gate", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load run_pytest_gate script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_script_module()


def test_half_cpu_count_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: None)
    assert gate._half_cpu_count() == 1


def test_build_pytest_cmd_caps_to_half_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    cmd = gate._build_pytest_cmd(24, ["tests/property", "--no-cov"])
    assert cmd == ["uv", "run", "pytest", "-n", "12", "tests/property", "--no-cov"]


def test_build_pytest_cmd_defaults_to_single_worker_with_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    cmd = gate._build_pytest_cmd(None, [])
    assert cmd == ["uv", "run", "pytest", "-n", "1"]


def test_build_pytest_cmd_defaults_to_half_cpu_without_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    cmd = gate._build_pytest_cmd(None, ["--no-cov"])
    assert cmd == ["uv", "run", "pytest", "-n", "12", "--no-cov"]
