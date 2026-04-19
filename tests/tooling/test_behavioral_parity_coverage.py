# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests that run_behavioral_parity.py executes every file counted by
check_fixture_coverage.py._LANGUAGE_FILES for each language."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_RUNNER_SCRIPT = _REPO_ROOT / "spec" / "run_behavioral_parity.py"
_COVERAGE_SCRIPT = _REPO_ROOT / "spec" / "check_fixture_coverage.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_runner_module() -> ModuleType:
    return _load_module(_RUNNER_SCRIPT, "run_behavioral_parity_cov_test_module")


def _load_coverage_module() -> ModuleType:
    return _load_module(_COVERAGE_SCRIPT, "check_fixture_coverage_cov_test_module")


def _flatten_run_cmds(runner: Any) -> list[str]:
    """Flatten all run_cmds tokens for a runner into a single list of strings."""
    tokens: list[str] = []
    for cmd in runner.run_cmds:
        tokens.extend(cmd)
    return tokens


class TestTypeScriptRunnerCoverage:
    """TypeScript runner must execute every TS file in _LANGUAGE_FILES."""

    def test_parity_test_ts_is_in_run_cmd(self) -> None:
        runner_mod = _load_runner_module()
        runners = runner_mod._runners(_REPO_ROOT)
        ts_runner = next(r for r in runners if r.name == "typescript")
        tokens = _flatten_run_cmds(ts_runner)
        assert "tests/parity.test.ts" in tokens, "TypeScript runner must explicitly list tests/parity.test.ts"

    def test_endpoint_test_ts_is_in_run_cmd(self) -> None:
        runner_mod = _load_runner_module()
        runners = runner_mod._runners(_REPO_ROOT)
        ts_runner = next(r for r in runners if r.name == "typescript")
        tokens = _flatten_run_cmds(ts_runner)
        assert "tests/endpoint.test.ts" in tokens, (
            "TypeScript runner must explicitly list tests/endpoint.test.ts "
            "(counted by check_fixture_coverage.py but previously un-run)"
        )

    def test_all_ts_parity_files_covered(self) -> None:
        """Every .ts file in _LANGUAGE_FILES['typescript'] must appear in run_cmds."""
        runner_mod = _load_runner_module()
        cov_mod = _load_coverage_module()
        runners = runner_mod._runners(_REPO_ROOT)
        ts_runner = next(r for r in runners if r.name == "typescript")
        tokens = _flatten_run_cmds(ts_runner)
        ts_files = cov_mod._LANGUAGE_FILES.get("typescript", [])
        # Only check .ts test files (probes live under spec/ and are not run by vitest)
        test_files = [p for p in ts_files if str(p).endswith(".test.ts")]
        for path in test_files:
            # Match by filename relative to the typescript/ directory
            rel = path.relative_to(_REPO_ROOT / "typescript")
            assert str(rel) in tokens, (
                f"TypeScript parity test file '{rel}' is counted by "
                "check_fixture_coverage.py but is not in the vitest run_cmds"
            )


class TestGoRunnerCoverage:
    """Go runner must pick up TestEndpointValidationParity which lacks TestParity prefix."""

    def test_go_run_filter_matches_testparity_prefix(self) -> None:
        runner_mod = _load_runner_module()
        runners = runner_mod._runners(_REPO_ROOT)
        go_runner = next(r for r in runners if r.name == "go")
        tokens = _flatten_run_cmds(go_runner)
        # The -run argument is the regex filter; locate it
        assert "-run" in tokens
        run_idx = tokens.index("-run")
        run_filter = tokens[run_idx + 1]
        assert "TestParity" in run_filter, "Go -run filter must match TestParity* functions"

    def test_go_run_filter_matches_endpoint_validation_parity(self) -> None:
        """parity_endpoint_test.go uses TestEndpointValidationParity — must be matched."""
        runner_mod = _load_runner_module()
        runners = runner_mod._runners(_REPO_ROOT)
        go_runner = next(r for r in runners if r.name == "go")
        tokens = _flatten_run_cmds(go_runner)
        assert "-run" in tokens
        run_idx = tokens.index("-run")
        run_filter = tokens[run_idx + 1]
        assert "TestEndpointValidationParity" in run_filter, (
            "Go -run filter must match TestEndpointValidationParity from "
            "parity_endpoint_test.go (this test does not carry the TestParity prefix)"
        )

    def test_parity_endpoint_test_go_exists(self) -> None:
        """Confirm parity_endpoint_test.go still exists (guard against file rename)."""
        assert (_REPO_ROOT / "go" / "parity_endpoint_test.go").exists()


class TestRustRunnerCoverage:
    """Rust runner must invoke all three parity integration test binaries."""

    def _rust_runner(self) -> Any:
        runner_mod = _load_runner_module()
        runners = runner_mod._runners(_REPO_ROOT)
        return next(r for r in runners if r.name == "rust")

    def test_rust_has_multiple_run_cmds(self) -> None:
        runner = self._rust_runner()
        assert len(runner.run_cmds) >= 3, "Rust runner must have at least 3 run_cmds entries (one per parity binary)"

    def test_parity_test_binary_in_run_cmds(self) -> None:
        runner = self._rust_runner()
        binary_args = [token for cmd in runner.run_cmds for token in cmd]
        assert "parity_test" in binary_args, "Rust runner must invoke --test parity_test"

    def test_parity_extra_test_binary_in_run_cmds(self) -> None:
        runner = self._rust_runner()
        binary_args = [token for cmd in runner.run_cmds for token in cmd]
        assert "parity_extra_test" in binary_args, (
            "Rust runner must invoke --test parity_extra_test "
            "(counted by check_fixture_coverage.py but previously un-run)"
        )

    def test_parity_pii_fixes_test_binary_in_run_cmds(self) -> None:
        runner = self._rust_runner()
        binary_args = [token for cmd in runner.run_cmds for token in cmd]
        assert "parity_pii_fixes_test" in binary_args, "Rust runner must invoke --test parity_pii_fixes_test"

    def test_rust_min_stack_env_preserved(self) -> None:
        runner = self._rust_runner()
        assert runner.env_extra.get("RUST_MIN_STACK") == "8388608", (
            "RUST_MIN_STACK=8388608 must be present in env_extra for all Rust parity runs"
        )

    def test_test_threads_1_in_all_rust_cmds(self) -> None:
        """Every Rust parity invocation must serialise tests (--test-threads=1)."""
        runner = self._rust_runner()
        for cmd in runner.run_cmds:
            assert "--test-threads=1" in cmd, (
                f"Rust parity command {cmd!r} is missing --test-threads=1; "
                "Rust parity tests share global state and must not run in parallel"
            )


class TestPythonRunnerCoverage:
    """Python runner already uses the full parity directory — sanity-check only."""

    def test_python_runs_parity_directory(self) -> None:
        runner_mod = _load_runner_module()
        runners = runner_mod._runners(_REPO_ROOT)
        py_runner = next(r for r in runners if r.name == "python")
        tokens = _flatten_run_cmds(py_runner)
        assert "tests/parity/" in tokens, "Python runner must pass tests/parity/ to cover all parity test files"


class TestRunnerCompleteness:
    """Every _LANGUAGE_FILES entry must be provably covered or explicitly exempted."""

    # Probe files under spec/probes/ are NOT run by the parity test suite runners;
    # they are invoked by the output-format probe checks in parity_probe_support.py.
    # We exempt them from the runner-coverage assertion below.
    _PROBE_EXEMPT_SUFFIXES = (
        "emit_log_typescript.ts",
        "emit_log_go/main.go",
    )

    def test_all_languages_have_a_runner(self) -> None:
        runner_mod = _load_runner_module()
        cov_mod = _load_coverage_module()
        runners = runner_mod._runners(_REPO_ROOT)
        runner_names = {r.name for r in runners}
        for lang in cov_mod._LANGUAGE_FILES:
            assert lang in runner_names, f"Language '{lang}' is in _LANGUAGE_FILES but has no runner in _runners()"

    def test_rust_parity_source_files_exist(self) -> None:
        """Confirm all Rust parity test files referenced by _LANGUAGE_FILES exist."""
        cov_mod = _load_coverage_module()
        for path in cov_mod._LANGUAGE_FILES.get("rust", []):
            assert path.exists(), f"Rust parity file {path} listed in _LANGUAGE_FILES does not exist"
