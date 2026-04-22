#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for the runtime-probe shutdown/re-setup case."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_RUNNER_SCRIPT = _REPO_ROOT / "spec" / "run_behavioral_parity.py"
_SUPPORT_SCRIPT = _REPO_ROOT / "spec" / "parity_probe_support.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_runner_module() -> ModuleType:
    return _load_module(_RUNNER_SCRIPT, "run_behavioral_parity_restart_probe_test")


def _load_support_module() -> ModuleType:
    return _load_module(_SUPPORT_SCRIPT, "parity_probe_support_restart_probe_test")


def _runtime_available(lang: str, runner_module: ModuleType) -> bool:
    if lang == "python":
        return True
    if lang == "typescript":
        return shutil.which("node") is not None and (_REPO_ROOT / "typescript" / "node_modules").exists()
    if lang == "go":
        return shutil.which("go") is not None
    if lang == "rust":
        cargo_bin = str(getattr(runner_module, "_CARGO_BIN", "cargo"))
        return Path(cargo_bin).exists() or shutil.which(cargo_bin) is not None
    raise AssertionError(f"unexpected runtime {lang}")


@pytest.mark.parametrize("lang", ["python", "go", "typescript", "rust"])
def test_runtime_probe_restart_case_reports_fresh_config(lang: str) -> None:
    runner_module = _load_runner_module()
    support = _load_support_module()

    if not _runtime_available(lang, runner_module):
        pytest.skip(f"{lang} runtime is not installed")

    runners = support._runtime_probe_runners(_REPO_ROOT, runner_module._CARGO_BIN, runner_module._CARGO_ENV)
    runner = next(r for r in runners if r.name == lang)
    timeout = 240 if lang == "rust" and sys.platform == "win32" else 60

    output, err = support._run_runtime_probe(
        runner,
        "lazy_logger_shutdown_re_setup",
        support._probe_env({}),
        timeout=timeout,
    )

    assert not err, err
    payload = support._extract_json_line(output)
    assert payload is not None, output
    assert payload["case"] == "lazy_logger_shutdown_re_setup"
    assert payload["first_logger_emitted"] is True
    assert payload["shutdown_cleared_setup"] is True
    assert payload["shutdown_cleared_providers"] is True
    assert payload["shutdown_fallback_all"] is True
    assert payload["re_setup_done"] is True
    assert payload["second_logger_uses_fresh_config"] is True
