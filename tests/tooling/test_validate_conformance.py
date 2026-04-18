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


def test_conformance_governance_gaps_reported() -> None:
    """Governance-gated symbols missing from Python/TypeScript/Go are flagged by the checker.

    register_classification_rule (singular) and classify_key are not yet exported
    by Python, TypeScript, or Go — these are real governance gaps exposed by the
    new capability-gate check.  Sibling PRs must add these exports to close the
    gaps and allow this test to be updated to assert exit code 0.

    Until those PRs land, this test documents the known failures rather than
    masking them.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    # Known governance gaps — conformance currently exits 1.
    # Once sibling PRs add register_classification_rule + classify_key to
    # Python/TypeScript/Go, this assertion changes to returncode == 0.
    assert result.returncode == 1, (
        "Expected conformance to fail on governance gaps; got exit 0.\n"
        "If all governance symbols are now present, update this test to assert exit 0."
    )
    assert "MISSING [governance]" in result.stdout, "Expected governance gap messages in output"
    assert "register_classification_rule" in result.stdout
    assert "classify_key" in result.stdout


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


def test_parse_language_overrides_fallback_parses_go_entries() -> None:
    """_parse_language_overrides_fallback should extract go and rust override entries."""
    module = _load_validate_conformance_module()
    sample_yaml = (
        "spec_version: '1'\n"
        "language_overrides:\n"
        "  go:\n"
        "    - spec_name: tracer\n"
        "      accepted_kinds: [type]\n"
        '      note: "Go exports Tracer as interface type"\n'
        "    - spec_name: trace\n"
        "      accepted_kinds: [function]\n"
        '      note: "Go uses Trace() function"\n'
        "  rust:\n"
        "    - spec_name: trace\n"
        "      accepted_kinds: [function]\n"
        '      note: "Rust pub fn"\n'
        "other_key: value\n"
    )
    result = module._parse_language_overrides_fallback(sample_yaml)

    assert "go" in result, f"go not in result: {list(result.keys())}"
    assert len(result["go"]) == 2
    assert result["go"][0]["spec_name"] == "tracer"
    assert result["go"][0]["accepted_kinds"] == ["type"]
    assert result["go"][1]["spec_name"] == "trace"
    assert result["go"][1]["accepted_kinds"] == ["function"]

    assert "rust" in result
    assert len(result["rust"]) == 1
    assert result["rust"][0]["spec_name"] == "trace"
    assert result["rust"][0]["accepted_kinds"] == ["function"]

    # other_key should not appear
    assert "other_key" not in result


def test_load_spec_no_yaml_includes_language_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PyYAML is unavailable, _load_spec() should still parse language_overrides."""
    module = _load_validate_conformance_module()
    typed_module = cast(Any, module)

    # Patch _YAML_AVAILABLE to False to exercise the regex fallback path
    monkeypatch.setattr(typed_module, "_YAML_AVAILABLE", False)

    spec_data = typed_module._load_spec()
    lo = spec_data.get("language_overrides", {})

    assert isinstance(lo, dict), f"language_overrides is not a dict: {type(lo)}"
    assert "go" in lo, f"go not in overrides: {list(lo.keys())}"
    assert len(lo["go"]) > 0, "go overrides should be non-empty"

    # Confirm at least tracer and trace overrides are present for go
    go_spec_names = [e["spec_name"] for e in lo["go"]]
    assert "tracer" in go_spec_names
    assert "trace" in go_spec_names


def test_conformance_go_kind_deviations_are_notes_not_errors_no_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without PyYAML, Go kind deviations must be notes (not errors) and exit 0."""
    module = _load_validate_conformance_module()
    typed_module = cast(Any, module)

    monkeypatch.setattr(typed_module, "_YAML_AVAILABLE", False)

    spec_data = typed_module._load_spec()
    symbols = typed_module._collect_spec_symbols(spec_data)
    errors, kind_notes = typed_module._check_language("go", symbols, spec_data)

    assert errors == [], f"Expected no errors for go; got: {errors}"
    # Go has documented deviations that should appear as kind notes
    assert len(kind_notes) > 0, "Expected at least one kind note for go"
