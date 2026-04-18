# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for spec/run_behavioral_parity.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "run_behavioral_parity.py"
_SUPPORT = _REPO_ROOT / "spec" / "parity_probe_support.py"
_HARNESS = _REPO_ROOT / "spec" / "contract_probe_harness.py"


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


def _load_harness_module() -> ModuleType:
    return _load_module(_HARNESS, "contract_probe_harness_test_module")


def test_normalize_log_record_renames_and_normalizes_fields() -> None:
    module = _load_support_module()

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
    module = _load_support_module()

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
    module = _load_support_module()

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
    module = _load_support_module()

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


def test_runtime_probe_case_env_disables_trace_and_metrics_for_non_provider_python_cases() -> None:
    module = _load_support_module()

    for case in ("strict_schema_rejection", "required_keys_rejection", "shutdown_re_setup"):
        env = module._runtime_probe_case_env(case)
        assert env["PROVIDE_TRACE_ENABLED"] == "false"
        assert env["PROVIDE_METRICS_ENABLED"] == "false"


def test_runtime_probe_python_signal_enablement_exits_promptly() -> None:
    support = _load_support_module()
    probe = _REPO_ROOT / "spec" / "probes" / "runtime_probe_python.py"
    env = {
        **os.environ,
        **support._probe_env({}),
        "PROVIDE_PARITY_PROBE_CASE": "signal_enablement",
        "PROVIDE_TRACE_ENABLED": "false",
        "PROVIDE_METRICS_ENABLED": "false",
    }

    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        timeout=5,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["case"] == "signal_enablement"
    assert payload["traces_enabled"] is False
    assert payload["metrics_enabled"] is False


def test_runtime_probe_python_lazy_init_logger_exits_promptly() -> None:
    support = _load_support_module()
    probe = _REPO_ROOT / "spec" / "probes" / "runtime_probe_python.py"
    env = {
        **os.environ,
        **support._probe_env({}),
        "PROVIDE_PARITY_PROBE_CASE": "lazy_init_logger",
    }

    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        timeout=5,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["case"] == "lazy_init_logger"
    assert payload["record"]["message"] == "log.output.parity"


def test_runtime_probe_python_strict_schema_rejection_exits_promptly() -> None:
    support = _load_support_module()
    probe = _REPO_ROOT / "spec" / "probes" / "runtime_probe_python.py"
    env = {
        **os.environ,
        **support._probe_env({}),
        **support._runtime_probe_case_env("strict_schema_rejection"),
        "PROVIDE_PARITY_PROBE_CASE": "strict_schema_rejection",
    }

    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        timeout=5,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["case"] == "strict_schema_rejection"
    assert payload["schema_error"] is True


def test_python_probe_runners_use_current_interpreter_instead_of_uv_wrapper() -> None:
    module = _load_support_module()

    output_python = next(runner for runner in module._probe_runners(_REPO_ROOT, "cargo", {}) if runner.name == "python")
    runtime_python = next(
        runner for runner in module._runtime_probe_runners(_REPO_ROOT, "cargo", {}) if runner.name == "python"
    )

    assert output_python.cmd[:2] == [sys.executable, str(_REPO_ROOT / "spec" / "probes" / "emit_log_python.py")]
    assert runtime_python.cmd[:2] == [
        sys.executable,
        str(_REPO_ROOT / "spec" / "probes" / "runtime_probe_python.py"),
    ]


@pytest.mark.tooling
def test_contract_fixtures_contain_all_expected_cases() -> None:
    """All 6 contract case IDs must be present."""
    import yaml

    fixtures_path = _REPO_ROOT / "spec" / "contract_fixtures.yaml"
    data = yaml.safe_load(fixtures_path.read_text())
    cases = list(data["contract_cases"].keys())
    expected = [
        "propagation_to_logger_correlation",
        "trace_field_precedence",
        "setup_invalid_overrides",
        "shutdown_re_setup",
        "baggage_auto_injection",
        "propagation_cleanup",
        "propagation_cleanup_preserves_bound_context",
    ]
    assert cases == expected


@pytest.mark.tooling
def test_resolve_path_dotted() -> None:
    """Dotted path a.b resolves nested dicts."""
    module = _load_harness_module()
    assert module._resolve_path({"a": {"b": 1}}, "a.b") == 1


@pytest.mark.tooling
def test_resolve_path_bracket_notation() -> None:
    """Bracket notation a["b.c"] resolves literal key."""
    module = _load_harness_module()
    assert module._resolve_path({"a": {"b.c": 2}}, 'a["b.c"]') == 2


@pytest.mark.tooling
def test_resolve_path_missing_returns_none() -> None:
    """Missing key returns None."""
    module = _load_harness_module()
    assert module._resolve_path({"a": {}}, "a.b") is None
