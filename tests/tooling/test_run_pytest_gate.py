# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
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


def test_build_pytest_args_caps_to_half_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    args = gate._build_pytest_args(24, ["tests/property", "--no-cov"])
    assert args == ["-n", "12", "tests/property", "--no-cov"]


def test_build_pytest_args_defaults_to_single_worker_with_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    args = gate._build_pytest_args(None, [])
    assert args == ["-n", "1"]


def test_build_pytest_args_defaults_to_half_cpu_without_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.os, "cpu_count", lambda: 24)
    args = gate._build_pytest_args(None, ["--no-cov"])
    assert args == ["-n", "12", "--no-cov"]
