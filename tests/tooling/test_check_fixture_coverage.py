# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for spec/check_fixture_coverage.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "check_fixture_coverage.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_fixture_coverage", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_fixture_coverage_exits_zero() -> None:
    """Script should run and exit 0 (report mode, not a hard gate)."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"check_fixture_coverage.py exited {result.returncode}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_check_fixture_coverage_outputs_all_yaml_categories() -> None:
    """Every YAML category should appear in the output table."""
    import yaml

    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0

    fixtures_path = _REPO_ROOT / "spec" / "behavioral_fixtures.yaml"
    categories = list(yaml.safe_load(fixtures_path.read_text()).keys())
    for cat in categories:
        assert cat in result.stdout, f"Category '{cat}' missing from coverage report output"


def test_check_fixture_coverage_python_all_covered() -> None:
    """All YAML categories should show OK for Python in the coverage matrix."""
    module = _load_module()
    fixtures_path = _REPO_ROOT / "spec" / "behavioral_fixtures.yaml"

    coverage = module.run_report(fixtures_path, module._LANGUAGE_FILES)

    assert "python" in coverage, "Python should be in the coverage matrix"
    uncovered = [cat for cat, ok in coverage["python"].items() if not ok]
    assert not uncovered, f"Python parity tests missing for categories: {uncovered}"


def test_category_variants_snake_case() -> None:
    """_category_variants should produce camelCase and PascalCase variants."""
    module = _load_module()
    variants = module._category_variants("pii_hash")
    assert "pii_hash" in variants
    assert "piiHash" in variants
    assert "PiiHash" in variants
    assert "pii-hash" in variants


def test_category_mentioned_finds_variant(tmp_path: Path) -> None:
    """_category_mentioned should match camelCase variant in corpus."""
    module = _load_module()
    corpus = "describe('piiHash', () => { ... })"
    assert module._category_mentioned("pii_hash", corpus)


def test_category_mentioned_returns_false_when_absent() -> None:
    """_category_mentioned should return False when no variant is found."""
    module = _load_module()
    corpus = "describe('sampling', () => { ... })"
    assert not module._category_mentioned("cardinality_clamping", corpus)


def test_run_report_missing_file_treated_as_empty(tmp_path: Path) -> None:
    """A language whose test file doesn't exist should show all categories as uncovered."""
    module = _load_module()
    import yaml

    fixtures_path = _REPO_ROOT / "spec" / "behavioral_fixtures.yaml"
    lang_files = {"phantom": [tmp_path / "nonexistent_parity_test.go"]}
    coverage = module.run_report(fixtures_path, lang_files)

    assert "phantom" in coverage
    categories = list(yaml.safe_load(fixtures_path.read_text()).keys())
    for cat in categories:
        assert coverage["phantom"][cat] is False, f"Expected {cat} to be uncovered for phantom language"
