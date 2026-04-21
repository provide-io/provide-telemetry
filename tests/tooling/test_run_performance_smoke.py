# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
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
run_benchmarks_stable = _module.run_benchmarks_stable

_ALL_FIELDS = {
    "event_name_ns": 100.0,
    "should_sample_ns": 200.0,
    "sanitize_ns": 300.0,
    "trace_decorator_ns": 400.0,
    "counter_add_ns": 500.0,
    "histogram_record_ns": 600.0,
    "health_snapshot_ns": 700.0,
}


def test_bench_ns_per_op_reports_positive_value() -> None:
    value = _bench_ns_per_op(1000, lambda: 1 + 1)
    assert value > 0


def test_evaluate_thresholds_returns_no_failures_when_within_limits() -> None:
    result = PerfResult(**_ALL_FIELDS)
    failures = evaluate_thresholds(result, *([10_000.0] * 7))
    assert failures == []


def test_evaluate_thresholds_reports_each_exceeded_limit() -> None:
    result = PerfResult(**{k: 10_000.0 for k in _ALL_FIELDS})
    failures = evaluate_thresholds(result, *([100.0] * 7))
    assert len(failures) == 7
    assert "event_name_ns" in failures[0]
    assert "should_sample_ns" in failures[1]
    assert "sanitize_ns" in failures[2]


def test_run_benchmarks_stable_uses_median(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(
        [
            PerfResult(**dict(zip(_ALL_FIELDS, [100, 300, 500, 100, 100, 100, 100], strict=True))),
            PerfResult(**dict(zip(_ALL_FIELDS, [200, 100, 700, 200, 200, 200, 200], strict=True))),
            PerfResult(**dict(zip(_ALL_FIELDS, [900, 200, 600, 300, 300, 300, 300], strict=True))),
        ]
    )
    monkeypatch.setattr(_module, "run_benchmarks", lambda _iterations: next(values))
    result = run_benchmarks_stable(iterations=1000, runs=3)
    assert result.event_name_ns == 200.0
    assert result.should_sample_ns == 200.0
    assert result.sanitize_ns == 600.0
