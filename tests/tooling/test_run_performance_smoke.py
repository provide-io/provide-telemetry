# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/run_performance_smoke.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/run_performance_smoke.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_performance_smoke", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load run_performance_smoke script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_module = _load_script_module()
PerfResult = _module.PerfResult
evaluate_thresholds = _module.evaluate_thresholds
_bench_ns_per_op = _module._bench_ns_per_op


def test_bench_ns_per_op_reports_positive_value() -> None:
    value = _bench_ns_per_op(1000, lambda: 1 + 1)
    assert value > 0


def test_evaluate_thresholds_returns_no_failures_when_within_limits() -> None:
    result = PerfResult(event_name_ns=100.0, should_sample_ns=200.0, sanitize_ns=300.0)
    failures = evaluate_thresholds(result, 1000.0, 1000.0, 1000.0)
    assert failures == []


def test_evaluate_thresholds_reports_each_exceeded_limit() -> None:
    result = PerfResult(event_name_ns=1000.0, should_sample_ns=2000.0, sanitize_ns=3000.0)
    failures = evaluate_thresholds(result, 100.0, 200.0, 300.0)
    assert len(failures) == 3
    assert "event_name_ns" in failures[0]
    assert "should_sample_ns" in failures[1]
    assert "sanitize_ns" in failures[2]
