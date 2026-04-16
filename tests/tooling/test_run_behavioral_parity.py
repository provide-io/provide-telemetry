# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for spec/run_behavioral_parity.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "run_behavioral_parity.py"
_SUPPORT = _REPO_ROOT / "spec" / "parity_probe_support.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_runner_module() -> ModuleType:
    return _load_module(_SCRIPT, "run_behavioral_parity_test_module")


def _load_support_module() -> ModuleType:
    return _load_module(_SUPPORT, "parity_probe_support_test_module")


def test_normalize_log_record_renames_and_normalizes_fields() -> None:
    module = _load_runner_module()

    record = module._normalize_log_record(
        {
            "msg": "hello",
            "level": 30,
            "service.name": "svc",
            "service.env": "prod",
            "service.version": "1.2.3",
            "trace.id": "0" * 32,
            "span.id": "1" * 16,
            "name": "probe.logger",
            "pid": 123,
        }
    )

    assert record == {
        "message": "hello",
        "level": "INFO",
        "service": "svc",
        "env": "prod",
        "version": "1.2.3",
        "trace_id": "0" * 32,
        "span_id": "1" * 16,
        "logger_name": "probe.logger",
    }


def test_compare_outputs_flags_optional_field_mismatches() -> None:
    module = _load_runner_module()

    mismatches = module._compare_outputs(
        {
            "python": {
                "message": "log.output.parity",
                "level": "INFO",
                "service": "probe",
                "env": "prod",
                "version": "1.2.3",
                "logger_name": "probe",
            },
            "go": {
                "message": "log.output.parity",
                "level": "INFO",
                "service": "probe",
                "env": "dev",
                "version": "9.9.9",
                "logger_name": "worker",
            },
        }
    )

    joined = "\n".join(mismatches)
    assert "field 'env' differs" in joined
    assert "field 'version' differs" in joined
    assert "field 'logger_name' differs" in joined


def test_compare_outputs_flags_timestamp_policy_violation() -> None:
    module = _load_runner_module()

    mismatches = module._compare_outputs(
        {
            "python": {"message": "log.output.parity", "level": "INFO"},
            "go": {
                "message": "log.output.parity",
                "level": "INFO",
                "timestamp": "2026-04-15T12:00:00.123Z",
            },
        }
    )

    assert any("timestamp presence differs" in mismatch for mismatch in mismatches)


def test_compare_outputs_flags_trace_context_presence_violation() -> None:
    module = _load_runner_module()

    mismatches = module._compare_outputs(
        {
            "python": {
                "message": "log.output.parity",
                "level": "INFO",
                "trace_id": "0" * 32,
                "span_id": "1" * 16,
            },
            "rust": {"message": "log.output.parity", "level": "INFO"},
        }
    )

    joined = "\n".join(mismatches)
    assert "field 'trace_id' presence differs" in joined
    assert "field 'span_id' presence differs" in joined


def test_runtime_probe_case_env_disables_trace_and_metrics_for_signal_enablement() -> None:
    module = _load_support_module()

    assert module._runtime_probe_case_env("signal_enablement") == {
        "PROVIDE_TRACE_ENABLED": "false",
        "PROVIDE_METRICS_ENABLED": "false",
    }
