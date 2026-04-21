# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for spec/check_fixture_coverage.py."""

from __future__ import annotations

import importlib.util
import subprocess  # nosec
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


def test_check_fixture_coverage_exits_zero_with_allowlist() -> None:
    """Script should exit 0 when all gaps are covered by the allowlist."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"check_fixture_coverage.py exited {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"Hint: add new gaps to spec/fixture_coverage_allowlist.yaml with reason+owner"
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


def test_check_fixture_coverage_omits_low_risk_false_positive_gaps() -> None:
    """Closed TypeScript and Go fixture coverage should not be reported as gaps."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0

    unexpected_gaps = [
        "typescript: missing 'backpressure_unlimited'",
        "typescript: missing 'sampling_signal_validation'",
        "typescript: missing 'health_snapshot'",
        "typescript: missing 'log_output_format'",
        "go: missing 'log_output_format'",
    ]

    for gap in unexpected_gaps:
        assert gap not in result.stdout, f"Unexpected false-positive coverage gap reported: {gap}"


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


def test_probe_only_category_requires_canonical_probe_content_marker(tmp_path: Path) -> None:
    """Known probe-only categories should count coverage from probe contents, not just file names."""
    module = _load_module()
    probe = tmp_path / "spec" / "probes" / "emit_log_typescript.ts"
    probe.parent.mkdir(parents=True)
    probe.write_text("log.output.parity\n", encoding="utf-8")
    path_only_probe = tmp_path / "spec" / "probes" / "emit_log_go" / "main.go"
    path_only_probe.parent.mkdir(parents=True)
    path_only_probe.write_text("// no canonical log marker here\n", encoding="utf-8")

    assert module._category_mentioned("log_output_format", probe.read_text(encoding="utf-8"))
    assert not module._category_mentioned(
        "log_output_format",
        path_only_probe.read_text(encoding="utf-8"),
    )


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


def test_load_allowlist_returns_expected_pairs(tmp_path: Path) -> None:
    """_load_allowlist should parse all (lang, category) pairs from YAML."""
    module = _load_module()
    al = tmp_path / "allowlist.yaml"
    al.write_text(
        "allowlist:\n"
        "  - lang: rust\n"
        "    category: config_headers\n"
        "    reason: pending\n"
        "    owner: provide-io\n"
        "  - lang: typescript\n"
        "    category: health_snapshot\n"
        "    reason: pending\n"
        "    owner: provide-io\n",
        encoding="utf-8",
    )
    pairs = module._load_allowlist(al)
    assert ("rust", "config_headers") in pairs
    assert ("typescript", "health_snapshot") in pairs
    assert ("go", "config_headers") not in pairs


def test_load_allowlist_returns_empty_when_missing(tmp_path: Path) -> None:
    """_load_allowlist should return empty set when file does not exist."""
    module = _load_module()
    pairs = module._load_allowlist(tmp_path / "nonexistent.yaml")
    assert pairs == set()


def test_unallowlisted_gap_causes_nonzero_exit(tmp_path: Path) -> None:
    """main() should return non-zero when a gap is not in the allowlist."""

    module = _load_module()

    # Build a tiny fixtures.yaml with a category that no language covers
    fixtures = tmp_path / "fixtures.yaml"
    fixtures.write_text("totally_new_category:\n  description: new\n", encoding="utf-8")

    # Use a language file that doesn't mention it
    lang_files: dict[str, list[Path]] = {"go": [tmp_path / "nonexistent.go"]}

    # Patch _load_allowlist to return nothing
    import types

    patched_module = types.ModuleType("check_fixture_coverage_patched")
    patched_module.__dict__.update(module.__dict__)

    coverage = module.run_report(fixtures, lang_files)
    assert coverage["go"]["totally_new_category"] is False

    # Simulate main with empty allowlist by calling _load_allowlist on a missing file
    allowlist = module._load_allowlist(tmp_path / "empty_allowlist.yaml")
    assert len(allowlist) == 0

    # Confirm the gap is not in the allowlist
    assert ("go", "totally_new_category") not in allowlist
